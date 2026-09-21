"""Export and import the whole archive as plain files.

Roadmap M3, "everything exportable as plain files, for longevity". There are two
different jobs here and they are deliberately not the same thing:

* ``scripts/backup.sh`` makes an **operational** backup: ``pg_dump`` plus a tar of
  the managed files. It restores exactly, fast, onto the same software.
* this module makes a **format-independent** export: one ZIP holding
  ``export.json`` — every table as ordinary JSON, ISO dates, no SQL dialect, no
  pickles — and the managed files beside it. If NegArchive is abandoned in 2031,
  a person with a text editor can still read what was in the archive, and any
  other program can import it.

The export streams: a 300 GB archive must not be built in memory or staged on
disk first, so the ZIP is produced chunk by chunk straight into the response.

**Linked files are listed but not copied.** Their bytes belong to a folder the
user manages (a NegPy library root, an Immich external library); duplicating them
into every export is exactly what link mode exists to avoid. The record keeps its
``source_path`` and ``content_hash``, which is what an import needs to find them
again.
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import paths
from ..models import (
    Camera,
    FilmRoll,
    FilmStock,
    ImageAsset,
    ImageType,
    Lens,
    LibraryRoot,
    Location,
    LocationMove,
    Setting,
    SleeveLayout,
)

#: Bumped when the shape of ``export.json`` changes incompatibly.
EXPORT_FORMAT = 1

#: Where managed files sit inside the ZIP.
FILES_PREFIX = "files/"

#: Export order is also import order: a table only ever references earlier ones.
TABLES = ("cameras", "lenses", "film_stocks", "film_rolls", "image_assets", "library_roots", "settings")


def _plain(value: Any) -> Any:
    """JSON-safe version of a column value."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, ImageType):
        return value.value
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value  # any other Enum column
    return value


def _rows(db: Session, model) -> List[Dict[str, Any]]:
    columns = [c.name for c in model.__table__.columns]
    return [
        {column: _plain(getattr(row, column)) for column in columns}
        for row in db.query(model).all()
    ]


def table_payload(db: Session) -> Dict[str, Any]:
    """Every table as JSON. This *is* the archive, minus the pixels."""
    return {
        "negarchive_export": EXPORT_FORMAT,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "tables": {
            "cameras": _rows(db, Camera),
            "lenses": _rows(db, Lens),
            "film_stocks": _rows(db, FilmStock),
            "film_rolls": _rows(db, FilmRoll),
            "image_assets": _rows(db, ImageAsset),
            "library_roots": _rows(db, LibraryRoot),
            "settings": _rows(db, Setting),
            # M4
            "sleeve_layouts": _rows(db, SleeveLayout),
            "locations": _rows(db, Location),
            "location_moves": _rows(db, LocationMove),
        },
    }


# ---------------------------------------------------------------------------
# Streaming ZIP
# ---------------------------------------------------------------------------


class _ChunkSink:
    """A write-only, unseekable file object `zipfile` can write into.

    Everything written is handed straight to the response generator, so the ZIP
    is never held in memory or staged on disk. `zipfile` copes with an unseekable
    stream by writing data descriptors after each entry.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._position = 0

    def write(self, data: bytes) -> int:
        self._buffer.extend(data)
        self._position += len(data)
        return len(data)

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:  # pragma: no cover - required by the file protocol
        return None

    def take(self) -> bytes:
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk


def export_filename() -> str:
    return f"negarchive-export-{datetime.utcnow():%Y%m%d-%H%M%S}.zip"


def iter_export_zip(db: Session, chunk_bytes: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield the export ZIP piece by piece."""
    payload = table_payload(db)
    managed: List[tuple[str, Path]] = []
    seen: set[str] = set()
    for row in payload["tables"]["image_assets"]:
        if (row.get("storage_mode") or "managed") != "managed":
            continue
        resolved = paths.resolve(row.get("path"))
        arcname = FILES_PREFIX + paths.relative_part(row.get("path") or "")
        # Two records can point at one file; the ZIP holds it once.
        if resolved and resolved.is_file() and arcname not in seen:
            seen.add(arcname)
            managed.append((arcname, resolved))

    # M5: a managed file's `.negpy` sidecar travels with it. It is the record of
    # an edit somebody made in NegPy, it is tiny, and an export that dropped it
    # would quietly lose work that is not in the database.
    for arcname, source in list(managed):
        sidecar = source.with_name(source.name + ".negpy")
        if sidecar.is_file():
            managed.append((arcname + ".negpy", sidecar))
    payload["file_count"] = len(managed)

    sink = _ChunkSink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("export.json", json.dumps(payload, indent=2, ensure_ascii=False))
        archive.writestr("README.txt", _README)
        chunk = sink.take()
        if chunk:
            yield chunk

        for arcname, source in managed:
            try:
                handle = source.open("rb")
            except OSError:
                continue  # a file that vanished mid-export must not abort it
            with handle:
                # Images are already compressed; storing them is much faster.
                # force_zip64: zipfile decides from `file_size`, which is 0 on a
                # streamed member, and would otherwise raise once a single scan
                # passes 2 GiB — mid-stream, after the client has half the ZIP.
                with archive.open(zipfile.ZipInfo(arcname), "w", force_zip64=True) as target:
                    while True:
                        data = handle.read(chunk_bytes)
                        if not data:
                            break
                        target.write(data)
                        piece = sink.take()
                        if piece:
                            yield piece
            piece = sink.take()
            if piece:
                yield piece

    tail = sink.take()
    if tail:
        yield tail


_README = """NegArchive export
=================

export.json  every database table as plain JSON. Dates are ISO-8601, enums are
             their string values, ids are the ones this archive used.
files/       the managed image files, under the same relative path they have in
             the archive's data directory (data/uploads/...). A file's `.negpy`
             sidecar, if it has one, sits next to it under the same name plus
             `.negpy` — that is where NegPy keeps what it did to the scan.

Files that were imported "by reference" (storage_mode = "linked") are NOT in
this ZIP: they live in a folder you manage. Their records carry source_path and
content_hash so they can be found again.

Import it with: POST /api/import  (multipart "file"), or through Settings in the
UI. Add ?dry_run=true first to see what it would do.
"""


# ---------------------------------------------------------------------------
# CSV of rolls, for spreadsheets
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "id",
    "archive_serial",
    "title",
    "camera",
    "lens",
    "film_type",
    "start_date",
    "end_date",
    "building",
    "folder",
    "frame_count",
    "notes",
    "created_at",
    # M4 (appended, so older column positions do not shift)
    "location",
    "status",
    # M5
    "developer",
    "development_dilution",
    "push_pull",
    "development_time",
]


def rolls_csv(db: Session) -> str:
    """One line per roll, the columns you would actually put in a binder index."""
    from . import locations as loc_svc

    counts = dict(
        db.query(ImageAsset.film_roll_id, func.count(ImageAsset.id))
        .filter(ImageAsset.film_roll_id.isnot(None))
        .group_by(ImageAsset.film_roll_id)
        .all()
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for roll in db.query(FilmRoll).order_by(FilmRoll.id.asc()).all():
        writer.writerow(
            {
                "id": roll.id,
                "archive_serial": roll.archive_serial or "",
                "title": roll.title,
                "camera": roll.camera or "",
                "lens": roll.lens or "",
                "film_type": roll.film_type or "",
                "start_date": roll.start_date.isoformat() if roll.start_date else "",
                "end_date": roll.end_date.isoformat() if roll.end_date else "",
                "building": roll.building or "",
                "folder": roll.folder or "",
                "location": loc_svc.path_string(roll.location_ref) or "",
                "status": roll.status or "",
                "developer": roll.developer or "",
                "development_dilution": roll.development_dilution or "",
                "push_pull": roll.push_pull or "",
                "development_time": roll.development_time or "",
                "frame_count": counts.get(roll.id, 0),
                "notes": (roll.notes or "").replace("\n", " "),
                "created_at": roll.created_at.isoformat() if roll.created_at else "",
            }
        )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).rstrip("Z"))
    except ValueError:
        return None


class ImportReport(dict):
    """A plain dict so it serialises straight into the response."""

    def bump(self, key: str, amount: int = 1) -> None:
        self[key] = self.get(key, 0) + amount


def import_archive(db: Session, archive_path: str, dry_run: bool = False) -> ImportReport:
    """Merge an export ZIP into this archive.

    Rules, in the order they matter:

    1. **Never overwrite.** Import only ever adds. Gear is matched by name, rolls
       by archive serial, frames by content hash; anything already here is left
       exactly as it is and counted as skipped.
    2. **Ids are remapped.** The ids in the export are meaningless here, so every
       row gets a new one and the references are rewritten.
    3. **Files are copied in** under fresh names in ``DATA_DIR/uploads``; a frame
       whose file is missing from the ZIP is still imported, so the metadata is
       not lost with it.
    4. ``library_roots`` are not imported: they are absolute paths on *another*
       machine, and silently pointing this one at them would be wrong.

    ``dry_run=True`` does all the counting and none of the writing.
    """
    report = ImportReport(dry_run=bool(dry_run))
    with zipfile.ZipFile(archive_path) as archive:
        try:
            raw = archive.read("export.json")
        except KeyError as exc:
            raise ValueError("This ZIP has no export.json — it is not a NegArchive export.") from exc
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or "tables" not in payload:
            raise ValueError("export.json does not look like a NegArchive export.")
        version = int(payload.get("negarchive_export") or 0)
        if version > EXPORT_FORMAT:
            raise ValueError(
                f"This export is format {version}; this NegArchive understands {EXPORT_FORMAT}."
            )
        tables = payload["tables"]
        report["format"] = version
        report["exported_at"] = payload.get("exported_at")

        names = set(archive.namelist())

        # --- gear, matched by name ------------------------------------------
        gear_maps: Dict[str, Dict[int, int]] = {}
        for table, model, fields in (
            ("cameras", Camera, ("name", "image_path", "mount", "notes")),
            ("lenses", Lens, ("name", "mount", "image_path", "notes")),
            (
                "film_stocks",
                FilmStock,
                ("name", "manufacturer", "format", "iso", "kind", "expired", "expiration_date", "image_path"),
            ),
        ):
            mapping: Dict[int, int] = {}
            for row in tables.get(table, []):
                name = row.get("name")
                existing = db.query(model).filter(model.name == name).first()
                if existing is not None:
                    mapping[row["id"]] = existing.id
                    report.bump(f"{table}_skipped")
                    continue
                report.bump(f"{table}_added")
                if dry_run:
                    continue
                values = {f: row.get(f) for f in fields}
                if "expiration_date" in values:
                    values["expiration_date"] = _parse_date(values["expiration_date"])
                obj = model(**values)
                db.add(obj)
                db.flush()
                mapping[row["id"]] = obj.id
            gear_maps[table] = mapping

        def gear_id(table: str, old: Any) -> Optional[int]:
            return gear_maps.get(table, {}).get(old) if old is not None else None

        # --- sleeve layouts, matched by name (M4) -----------------------------
        layout_map: Dict[int, int] = {}
        has_default = db.query(SleeveLayout).filter(SleeveLayout.is_default.is_(True)).first() is not None
        for row in tables.get("sleeve_layouts", []):
            existing = db.query(SleeveLayout).filter(SleeveLayout.name == row.get("name")).first()
            if existing is not None:
                layout_map[row["id"]] = existing.id
                report.bump("sleeve_layouts_skipped")
                continue
            report.bump("sleeve_layouts_added")
            if dry_run:
                continue
            layout = SleeveLayout(
                name=row.get("name") or f"Layout {row['id']}",
                rows=int(row.get("rows") or 1),
                frames_per_row=int(row.get("frames_per_row") or 1),
                film_format=row.get("film_format"),
                # This archive's default stays its default.
                is_default=bool(row.get("is_default")) and not has_default,
            )
            db.add(layout)
            db.flush()
            has_default = has_default or layout.is_default
            layout_map[row["id"]] = layout.id

        # --- locations, matched by parent + kind + name, parents first (M4) ----
        location_map: Dict[int, int] = {}
        pending = list(tables.get("locations", []))
        while pending:
            progressed = False
            for row in list(pending):
                parent_old = row.get("parent_id")
                if parent_old is not None and parent_old not in location_map:
                    if any(r["id"] == parent_old for r in pending):
                        continue  # its parent comes later in the list
                    parent_old = None  # parent missing from the export: becomes a root
                pending.remove(row)
                progressed = True
                parent_new = location_map.get(parent_old) if parent_old is not None else None
                existing = (
                    db.query(Location)
                    .filter(
                        Location.parent_id == parent_new if parent_new is not None else Location.parent_id.is_(None),
                        Location.kind == row.get("kind"),
                        Location.name == row.get("name"),
                    )
                    .first()
                )
                if existing is not None:
                    location_map[row["id"]] = existing.id
                    report.bump("locations_skipped")
                    continue
                report.bump("locations_added")
                if dry_run:
                    continue
                node = Location(
                    parent_id=parent_new,
                    kind=row.get("kind") or "other",
                    name=row.get("name") or "Untitled",
                    code=row.get("code"),
                    sort_order=int(row.get("sort_order") or 0),
                    notes=row.get("notes"),
                    capacity=row.get("capacity"),
                    sleeve_layout_id=layout_map.get(row.get("sleeve_layout_id")),
                    created_at=_parse_datetime(row.get("created_at")) or datetime.utcnow(),
                )
                db.add(node)
                db.flush()
                location_map[row["id"]] = node.id
            if not progressed:
                break  # a cycle in the export: whatever is left is not importable

        # --- rolls, matched by archive serial, then by title + creation time ---
        roll_map: Dict[int, int] = {}
        added_rolls: set[int] = set()
        for row in tables.get("film_rolls", []):
            serial = (row.get("archive_serial") or "").strip()
            existing = None
            if serial:
                # The unique index is on upper(): match the way it does.
                existing = db.query(FilmRoll).filter(func.upper(FilmRoll.archive_serial) == serial.upper()).first()
            else:
                # Not every roll has a serial yet (M4 introduces the scheme), and
                # re-importing must still not duplicate them. Title plus the exact
                # creation timestamp is as close to a natural key as we have.
                created = _parse_datetime(row.get("created_at"))
                if created is not None:
                    existing = (
                        db.query(FilmRoll)
                        .filter(FilmRoll.title == row.get("title"), FilmRoll.created_at == created)
                        .first()
                    )
            if existing is not None:
                roll_map[row["id"]] = existing.id
                report.bump("film_rolls_skipped")
                continue
            report.bump("film_rolls_added")
            if dry_run:
                continue
            strips = row.get("strips")
            roll = FilmRoll(
                created_at=_parse_datetime(row.get("created_at")) or datetime.utcnow(),
                title=row.get("title") or "Untitled roll",
                # Gear by id where the catalog entry came across, the legacy name either way.
                camera_id=gear_id("cameras", row.get("camera_id")),
                lens_id=gear_id("lenses", row.get("lens_id")),
                film_stock_id=gear_id("film_stocks", row.get("film_stock_id")),
                camera=row.get("camera"),
                lens=row.get("lens"),
                film_type=row.get("film_type"),
                format=row.get("format"),
                notes=row.get("notes"),
                developer=row.get("developer"),
                development_dilution=row.get("development_dilution"),
                push_pull=row.get("push_pull"),
                development_time=row.get("development_time"),
                start_date=_parse_date(row.get("start_date")),
                end_date=_parse_date(row.get("end_date")),
                building=row.get("building"),
                folder=row.get("folder"),
                archive_serial=row.get("archive_serial"),
                # M4: where it is and where it is in its life.
                location_id=location_map.get(row.get("location_id")),
                strips=[int(n) for n in strips] if isinstance(strips, list) else None,
                status=row.get("status") or "back",
                loaded_at=_parse_datetime(row.get("loaded_at")),
                shot_at=_parse_datetime(row.get("shot_at")),
                lab_sent_at=_parse_datetime(row.get("lab_sent_at")),
                lab_back_at=_parse_datetime(row.get("lab_back_at")),
                scanned_at=_parse_datetime(row.get("scanned_at")),
                sleeved_at=_parse_datetime(row.get("sleeved_at")),
                loaded_camera_id=gear_id("cameras", row.get("loaded_camera_id")),
                label_printed_at=_parse_datetime(row.get("label_printed_at")),
                # source_dir is a path on the exporting machine; it is unique, so
                # importing it would break the next import from the same source.
                source_dir=None,
            )
            db.add(roll)
            db.flush()
            roll_map[row["id"]] = roll.id
            added_rolls.add(row["id"])

        # --- the moves of the rolls that were just added (M4) ------------------
        for row in tables.get("location_moves", []):
            if row.get("roll_id") not in added_rolls:
                continue  # the roll was here already: its history is its own
            report.bump("location_moves_added")
            if dry_run:
                continue
            db.add(
                LocationMove(
                    roll_id=roll_map[row["roll_id"]],
                    from_location_id=location_map.get(row.get("from_location_id")),
                    to_location_id=location_map.get(row.get("to_location_id")),
                    moved_at=_parse_datetime(row.get("moved_at")) or datetime.utcnow(),
                    note=row.get("note"),
                )
            )

        # --- frames, matched by content hash ----------------------------------
        for row in tables.get("image_assets", []):
            digest = row.get("content_hash")
            existing = None
            if digest:
                existing = db.query(ImageAsset).filter(ImageAsset.content_hash == digest).first()
            elif row.get("path"):
                # A frame from before M3 has no hash; its stored path is the next
                # best thing, and it is what this archive would have used anyway.
                existing = db.query(ImageAsset).filter(ImageAsset.path == row["path"]).first()
            if existing is not None:
                report.bump("image_assets_skipped")
                continue
            report.bump("image_assets_added")
            if dry_run:
                continue

            storage_mode = row.get("storage_mode") or "managed"
            stored_path = row.get("path") or ""
            member = FILES_PREFIX + paths.relative_part(stored_path)
            new_path = stored_path
            sidecar_path = row.get("sidecar_path")

            if storage_mode == "managed":
                if member in names:
                    subdir = "contact_sheets" if row.get("type") == "contact_sheet" else "scans"
                    target_dir = paths.uploads_dir() / subdir
                    target_dir.mkdir(parents=True, exist_ok=True)
                    suffix = Path(stored_path).suffix or ".jpg"
                    filename = f"{uuid4().hex}{suffix}"
                    _extract(archive, member, target_dir / filename)
                    new_path = paths.public_path("uploads", subdir, filename)
                    report.bump("files_copied")
                    # M5: the `.negpy` the export put beside the file comes along.
                    sidecar_path = None
                    if member + ".negpy" in names:
                        _extract(archive, member + ".negpy", target_dir / (filename + ".negpy"))
                        sidecar_path = str(target_dir / (filename + ".negpy"))
                        report.bump("sidecars_copied")
                else:
                    report.bump("files_missing")
                    sidecar_path = None

            db.add(
                ImageAsset(
                    film_roll_id=roll_map.get(row.get("film_roll_id")),
                    type=ImageType(row.get("type") or "scan"),
                    path=new_path,
                    frame_number=row.get("frame_number"),
                    notes=row.get("notes"),
                    capture_date=_parse_date(row.get("capture_date")),
                    created_at=_parse_datetime(row.get("created_at")) or datetime.utcnow(),
                    original_filename=row.get("original_filename"),
                    storage_mode=storage_mode,
                    source_path=row.get("source_path"),
                    content_hash=digest,
                    # M5/M6: what the file said, what NegPy did to it, what it is.
                    capture_metadata=row.get("capture_metadata"),
                    sidecar_path=sidecar_path,
                    negpy_edited_at=_parse_datetime(row.get("negpy_edited_at")),
                    negpy_recipe=row.get("negpy_recipe"),
                    positive=row.get("positive"),
                )
            )

        report["library_roots_ignored"] = len(tables.get("library_roots", []))

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return report


def _extract(archive: zipfile.ZipFile, member: str, target: Path) -> None:
    """Copy one member out of the ZIP, a megabyte at a time."""
    with archive.open(member) as source, open(target, "wb") as sink:
        while True:
            data = source.read(1024 * 1024)
            if not data:
                break
            sink.write(data)


def newest_backup() -> Optional[str]:
    """Most recent file written by ``scripts/backup.sh``, for the settings page."""
    directory = paths.backups_dir()
    try:
        archives = sorted(
            (p for p in directory.glob("*.tar.gz") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    return os.fspath(archives[0]) if archives else None
