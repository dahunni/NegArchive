"""The NegPy integration, as an API (roadmap M5).

    GET  /api/negpy/status                 where the files go, what is on, last sync
    POST /api/negpy/gear/sync              write cameras/lenses/film_stocks.json
    POST /api/negpy/rolls/{id}/handoff     prepare a roll folder plus a preset
    GET  /api/negpy/rolls/{id}/scan        what to type into NegPy's scan mode (M6.1)
    POST /api/negpy/ingest                 re-read metadata for frames already here
    POST /api/negpy/edits/match            match frames against NegPy's edits.db
    GET  /api/negpy/lookup                 find a frame by NegPy content hash or path

Every one of these is file-based and local: nothing here talks to NegPy, because
NegPy has nothing to talk to (docs/NEGPY_INTEGRATION.md). The endpoints write
files NegPy reads, and read files NegPy wrote.

The two write endpoints can only write inside the directories
:mod:`app.services.negpy.dirs` allows — by default a folder inside NegArchive's own
``DATA_DIR``, so the feature needs no configuration and cannot be aimed at
somebody's home directory by a stranger on the LAN.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError, error_response, from_exc, not_found, parse_int, read_json
from ..models import FilmRoll, ImageAsset, ImageType
from ..services import livemode, settings_store
from ..services import locations as loc_svc
from ..services.negpy import dirs, edits, gear, handoff, naming
from ..services.negpy import metadata as negpy_metadata

router = APIRouter(prefix="/api/negpy", tags=["negpy"])


def _paths(db: Session) -> dict:
    """The effective directories, or the reason there are none."""
    try:
        user = dirs.user_dir(db)
        return {
            "user_dir": str(user),
            "gear_dir": str(dirs.gear_dir(db)),
            "presets_dir": str(dirs.presets_dir(db)),
            "handoff_dir": str(dirs.handoff_dir(db)),
            "error": None,
        }
    except ApiError as exc:
        return {"user_dir": None, "gear_dir": None, "presets_dir": None, "handoff_dir": None, "error": exc.message}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Everything the Settings page needs to explain this integration."""
    settings = settings_store.get_all(db)
    edited = (
        db.query(ImageAsset).filter(ImageAsset.sidecar_path.isnot(None)).count()
    )
    ingested = (
        db.query(ImageAsset).filter(ImageAsset.capture_metadata.isnot(None)).count()
    )
    return {
        "ingest_enabled": bool(settings.get("negpy_ingest")),
        "create_gear": bool(settings.get("negpy_create_gear")),
        "handoff_mode": settings.get("negpy_handoff_mode") or "link",
        "gear_synced_at": settings.get("negpy_gear_synced_at") or None,
        "paths": _paths(db),
        # M5 ("left for later"): NegPy's own edits database, read-only. Absent is
        # normal and not an error — it only ever adds information.
        "edits_db": edits.describe(db),
        "allowed_bases": [str(base) for base in dirs.allowed_bases()],
        "filename_pattern": naming.FILENAME_PATTERN,
        "frames_with_metadata": ingested,
        "frames_edited_in_negpy": edited,
        "xmp_namespace": "https://negpy.app/ns/1.0/",
    }


@router.post("/gear/sync")
def sync_gear(dry_run: bool = False, db: Session = Depends(get_db)):
    """Write NegArchive's catalog into NegPy's ``gear/*.json``.

    Merge-safe: entries NegPy or the user wrote are kept exactly as they are, and
    only ids beginning ``na-`` are ours to add, update or remove.
    """
    try:
        directory = dirs.gear_dir(db)
        if not dry_run:
            dirs.ensure(directory)
        result = gear.sync(db, directory, dry_run=dry_run)
    except ApiError as exc:
        return from_exc(exc)
    except OSError as exc:
        return error_response("write_failed", f"Could not write the gear files: {exc}", 500)

    if not dry_run and result.synced_at:
        settings_store.set_value(db, "negpy_gear_synced_at", result.synced_at)
        db.commit()
    return {"ok": True, "result": result.to_dict()}


@router.post("/rolls/{film_id}/handoff")
async def prepare_handoff(film_id: int, request: Request, db: Session = Depends(get_db)):
    """“Open in NegPy”: the roll's scans in a folder, plus a metadata preset.

    Body (all optional): ``{"mode": "link" | "copy"}``. The default comes from the
    ``negpy_handoff_mode`` setting.
    """
    roll = db.get(FilmRoll, film_id)
    if not roll:
        return not_found("Roll")
    try:
        payload = await read_json(request, required=False)
    except ApiError as exc:
        return from_exc(exc)

    mode = str((payload or {}).get("mode") or settings_store.get(db, "negpy_handoff_mode") or "link").strip()
    try:
        root = dirs.ensure(dirs.handoff_dir(db))
        presets = dirs.ensure(dirs.presets_dir(db))
        result = handoff.prepare(db, roll, handoff_root=root, presets_root=presets, mode=mode)
    except ApiError as exc:
        return from_exc(exc)
    except OSError as exc:
        return error_response("write_failed", f"Could not prepare the folder: {exc}", 500)
    return {"ok": True, "handoff": result.to_dict()}


@router.get("/rolls/{film_id}/scan")
def scan_plan(film_id: int, db: Session = Depends(get_db)):
    """“Scan with NegPy”: the output folder and roll name to type into *Live View & Scan*.

    Read-only. NegPy names its files ``<roll name>_Frame001.ARW`` in a folder called
    ``<roll name>``; with the archive's serial as the roll name and the share's
    ``rolls/`` as the output, the watcher files the frames onto this very roll.
    """
    roll = db.get(FilmRoll, film_id)
    if not roll:
        return not_found("Roll")
    return {"ok": True, "scan": livemode.scan_plan(db, roll)}


@router.post("/ingest")
async def ingest(request: Request, db: Session = Depends(get_db)):
    """Re-read the files of frames that are already in the archive.

    For everything imported before M5, and for a roll whose files have been edited
    in NegPy since. Body (all optional):
    ``{"film_id": 3}``, ``{"image_ids": [1, 2]}``, or nothing at all for every
    frame that has never been read. It fills blanks only — a frame number or a
    date somebody typed is never overwritten — so it is safe to run twice.
    """
    try:
        payload = await read_json(request, required=False) or {}
    except ApiError as exc:
        return from_exc(exc)

    enabled, create_gear = negpy_metadata.ingest_settings(db)
    if not enabled:
        return error_response(
            "ingest_disabled",
            "Reading metadata from files is switched off in Settings (negpy_ingest).",
            409,
            "negpy_ingest",
        )

    try:
        film_id, image_ids, limit = _selection(payload, default_limit=500, max_limit=2000)
    except ApiError as exc:
        return from_exc(exc)
    query = db.query(ImageAsset).filter(ImageAsset.type == ImageType.scan)
    if film_id is not None:
        query = query.filter(ImageAsset.film_roll_id == film_id)
    if image_ids:
        query = query.filter(ImageAsset.id.in_(image_ids))
    if not payload.get("all") and film_id is None and not image_ids:
        # The default is the backlog: frames nothing has ever read.
        query = query.filter(ImageAsset.capture_metadata.is_(None))
    frames: List[ImageAsset] = query.order_by(ImageAsset.id.asc()).limit(limit).all()

    changed = 0
    sidecars = 0
    edits_matched = 0
    results = []
    index = edits.open_index(db)
    try:
        for frame in frames:
            result = negpy_metadata.ingest_image(
                db,
                frame,
                match_unassigned=True,
                enabled=enabled,
                create_gear=create_gear,
                edits_index=index,
            )
            if result:
                changed += 1
            if result.sidecar:
                sidecars += 1
            if result.edits_match:
                edits_matched += 1
            results.append(result.to_dict())
    finally:
        if index is not None:
            index.close()
    db.commit()
    return {
        "ok": True,
        "examined": len(frames),
        "changed": changed,
        "sidecars": sidecars,
        "edits_matched": edits_matched,
        "results": results,
    }


@router.post("/edits/match")
async def match_edits(request: Request, db: Session = Depends(get_db)):
    """Match frames against NegPy's ``edits.db`` by content hash.

    For an archive whose owner never turned sidecars on: NegPy keys its edits by
    the same sampled hash NegArchive stores, so when both live on the same machine
    every scan that has been worked on can be found without touching a file. The
    database is opened **read-only and immutable** — nothing is written, locked or
    created (app/services/negpy/edits.py).

    Body (all optional): ``{"film_id": 3}``, ``{"image_ids": [...]}``, ``{"all": true}``
    to re-check frames that already carry a recipe. A ``.negpy`` sidecar always wins,
    so a frame that has one is skipped.
    """
    try:
        payload = await read_json(request, required=False) or {}
    except ApiError as exc:
        return from_exc(exc)

    index = edits.open_index(db)
    if index is None:
        report = edits.describe(db)
        return error_response(
            "no_edits_db",
            "No readable edits.db in NegPy's user directory"
            + (f" ({report['path']})" if report.get("path") else "")
            + ". Set NEGPY_USER_DIR, or point the NegPy folder in Settings at it.",
            404,
            "negpy_user_dir",
        )

    try:
        film_id, image_ids, limit = _selection(payload, default_limit=2000, max_limit=10000)
        query = db.query(ImageAsset).filter(
            ImageAsset.type == ImageType.scan, ImageAsset.content_hash.isnot(None)
        )
        if film_id is not None:
            query = query.filter(ImageAsset.film_roll_id == film_id)
        if image_ids:
            query = query.filter(ImageAsset.id.in_(image_ids))
        if not payload.get("all"):
            # The default is the gap: frames nothing has recorded a recipe for.
            query = query.filter(ImageAsset.negpy_recipe.is_(None))
        frames: List[ImageAsset] = query.order_by(ImageAsset.id.asc()).limit(limit).all()

        matched = 0
        by_hash = index.lookup_many([frame.content_hash for frame in frames])
        for frame in frames:
            if frame.sidecar_path:
                continue  # a sidecar beside the scan wins
            recipe = by_hash.get(str(frame.content_hash))
            if recipe is None:
                continue
            negpy_metadata.attach_recipe(frame, recipe, "edits.db")
            matched += 1
        db.commit()
        return {
            "ok": True,
            "database": str(index.path),
            "examined": len(frames),
            "matched": matched,
            "rows": index.row_count(),
        }
    except ApiError as exc:
        return from_exc(exc)
    finally:
        index.close()


def _selection(payload: dict, *, default_limit: int, max_limit: int) -> tuple[Optional[int], List[int], int]:
    """``film_id``, ``image_ids`` and ``limit`` from a body, as ints or as a 400."""
    film_id = parse_int(payload.get("film_id"), "film_id", minimum=1)
    raw_ids = payload.get("image_ids")
    image_ids: List[int] = []
    if raw_ids not in (None, "", []):
        if not isinstance(raw_ids, list):
            raise ApiError("invalid_ids", "image_ids must be a list of frame ids.", 400, "image_ids")
        for value in raw_ids:
            parsed = parse_int(value, "image_ids", minimum=1)
            if parsed is not None:
                image_ids.append(parsed)
    limit = parse_int(payload.get("limit"), "limit", minimum=1) or default_limit
    return film_id, image_ids, min(limit, max_limit)


@router.get("/lookup")
def lookup(
    hash: Optional[str] = Query(default=None, description="NegPy-compatible sampled SHA-256"),
    path: Optional[str] = Query(default=None, description="Absolute path of a linked original"),
    db: Session = Depends(get_db),
):
    """Which frame is this file?

    NegPy keys its edits by the sampled content hash
    (:mod:`app.services.hashing`), which NegArchive computes with the same
    documented algorithm. This is the other half of that: hand it a hash out of
    ``edits.db`` and it answers with the roll, the serial and the frame number —
    the physical negative the edit belongs to.
    """
    digest = (hash or "").strip().lower()
    wanted_path = (path or "").strip()
    if not digest and not wanted_path:
        return error_response("missing_query", "Pass ?hash= or ?path=.", 400, "hash")

    query = db.query(ImageAsset)
    if digest:
        query = query.filter(ImageAsset.content_hash == digest)
    if wanted_path:
        query = query.filter(ImageAsset.source_path == wanted_path)

    found = []
    for frame in query.order_by(ImageAsset.id.asc()).limit(50).all():
        roll = db.get(FilmRoll, frame.film_roll_id) if frame.film_roll_id else None
        found.append(
            {
                "image_id": frame.id,
                "frame_number": frame.frame_number,
                "original_filename": frame.original_filename,
                "content_hash": frame.content_hash,
                "storage_mode": frame.storage_mode,
                "source_path": frame.source_path,
                "roll_id": roll.id if roll else None,
                "archive_serial": roll.archive_serial if roll else None,
                "roll_title": roll.title if roll else None,
                "location_path": loc_svc.path_string(roll.location_ref) if roll else None,
                "sidecar_path": frame.sidecar_path,
            }
        )
    return {"ok": True, "count": len(found), "frames": found}
