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
    Setting,
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
    for row in payload["tables"]["image_assets"]:
        if (row.get("storage_mode") or "managed") != "managed":
            continue
        resolved = paths.resolve(row.get("path"))
        if resolved and resolved.is_file():
            managed.append((FILES_PREFIX + paths.relative_part(row["path"]), resolved))
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
                with archive.open(zipfile.ZipInfo(arcname), "w") as target:
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
             the archive's data directory (data/uploads/...).

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
]


def rolls_csv(db: Session) -> str:
    """One line per roll, the columns you would actually put in a binder index."""
    from sqlalchemy import func

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
            ("film_stocks", FilmStock, ("name", "iso", "kind", "expired", "expiration_date", "image_path")),
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

        # --- rolls, matched by archive serial, then by title + creation time ---
        roll_map: Dict[int, int] = {}
        for row in tables.get("film_rolls", []):
            serial = (row.get("archive_serial") or "").strip()
            existing = None
            if serial:
                existing = db.query(FilmRoll).filter(FilmRoll.archive_serial == serial).first()
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
            roll = FilmRoll(
                created_at=_parse_datetime(row.get("created_at")) or datetime.utcnow(),
                title=row.get("title") or "Untitled roll",
                camera=row.get("camera"),
                lens=row.get("lens"),
                film_type=row.get("film_type"),
                notes=row.get("notes"),
                start_date=_parse_date(row.get("start_date")),
                end_date=_parse_date(row.get("end_date")),
                building=row.get("building"),
                folder=row.get("folder"),
                archive_serial=row.get("archive_serial"),
                # source_dir is a path on the exporting machine; it is unique, so
                # importing it would break the next import from the same source.
                source_dir=None,
            )
            db.add(roll)
            db.flush()
            roll_map[row["id"]] = roll.id

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

            if storage_mode == "managed":
                if member in names:
                    subdir = "contact_sheets" if row.get("type") == "contact_sheet" else "scans"
                    target_dir = paths.uploads_dir() / subdir
                    target_dir.mkdir(parents=True, exist_ok=True)
                    suffix = Path(stored_path).suffix or ".jpg"
                    filename = f"{uuid4().hex}{suffix}"
                    with archive.open(member) as source, open(target_dir / filename, "wb") as target:
                        while True:
                            data = source.read(1024 * 1024)
                            if not data:
                                break
                            target.write(data)
                    new_path = paths.public_path("uploads", subdir, filename)
                    report.bump("files_copied")
                else:
                    report.bump("files_missing")

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
                )
            )

        report["library_roots_ignored"] = len(tables.get("library_roots", []))

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return report


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
