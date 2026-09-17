import glob
import io
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from math import ceil
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image as PILImage
from PIL import ImageFile as PILImageFile
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import paths, schemas
from ..db import get_db
from ..errors import (
    ApiError,
    error_response,
    from_exc,
    not_found,
    parse_choice,
    parse_date,
    parse_int,
)
from ..models import (
    FILM_FORMATS,
    Camera,
    FilmKind,
    FilmRoll,
    FilmStock,
    ImageAsset,
    ImageType,
    Lens,
    Location,
)
from ..seed import seed_catalog
from ..services import lifecycle, serials
from ..services import locations as loc_svc
from ..services import strips as strips_svc
from ..services.hashing import safe_content_hash
from ..services.negpy import metadata as negpy_metadata
from ..services.negpy import naming as negpy_naming
from ..services.negpy import sidecar as negpy_sidecar

router = APIRouter(prefix="/api", tags=["api"])

# Disk thumbnail cache for /preview (pulled forward from roadmap M3 because the new
# roll list and frame grid request a preview per frame). Git-ignored, and safe to
# delete at any time.
#
# M3 moved all of this under DATA_DIR (see app/paths.py). The *stored* paths are
# unchanged — `static/uploads/scans/ab12.jpg` is still both the /static URL and the
# value in the database — only the directory behind them left the source tree, so
# `_abs()` below is now the single place that maps one to the other.


def cache_dir() -> str:
    return str(paths.cache_dir())


def uploads_root() -> str:
    """Everything NegArchive itself stores lives under here. The sweep walks it and
    the delete path refuses to touch a file outside it."""
    return str(paths.uploads_dir())

COVER_STRIP = 4  # thumbnails shown per row in the roll list

# --- upload allowlist (R#18) --------------------------------------------------

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".dng"}

#: Leading bytes we accept, checked *in addition* to the extension. DNG is a TIFF
#: dialect, so it shares the TIFF magic.
MAGIC_PREFIXES: Tuple[bytes, ...] = (
    b"\xff\xd8\xff",  # JPEG
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"II*\x00",  # TIFF little endian (also DNG)
    b"MM\x00*",  # TIFF big endian
    b"II+\x00",  # BigTIFF little endian
    b"MM\x00+",  # BigTIFF big endian
)


def max_upload_bytes() -> int:
    """``MAX_UPLOAD_MB`` (default 512) as bytes; read per call so tests can change it."""
    try:
        megabytes = int(os.getenv("MAX_UPLOAD_MB", "512"))
    except ValueError:
        megabytes = 512
    return max(1, megabytes) * 1024 * 1024


def _looks_like_image(head: bytes) -> bool:
    if head.startswith(MAGIC_PREFIXES):
        return True
    # WEBP is "RIFF" + 4 size bytes + "WEBP"
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


# --- frame numbers from filenames (R#7, R#24) ---------------------------------

_EXPLICIT_FRAME = re.compile(r"frame[\s_-]?(\d{1,4})", re.IGNORECASE)
_NUMERIC_TOKEN = re.compile(r"^\d{1,4}$")


def frame_number_from_filename(filename: Optional[str]) -> Optional[int]:
    """Best guess at the frame number in a scanner filename.

    Handles the shapes this archive actually sees::

        Roll12_007.tif                        -> 7   (NegPy's {roll}_{frame})
        NEG-2024-011_007.jpg                  -> 7
        NEG-2026-0007_013_Kodak Gold 200.jpg  -> 13  (M5: the export preset)
        scan_Frame007.tif                     -> 7
        007.jpg                               -> 7
        img_0007.png                          -> 7

    Three rules, in order: an explicit ``frame<n>`` wins; then the **whole name**
    read as NegPy's recommended export preset ``{{roll}}_{{frame}}_{{film}}``
    (:mod:`app.services.negpy.naming`); then the **last** purely numeric group of
    one to four digits. ``Roll12.tif`` deliberately yields nothing — a number glued
    to a word is part of the word, not a frame number.

    The preset has to come before the last-number rule, and M5 learned that the
    hard way: ``NEG-2026-0007_013_Kodak Gold 200.jpg`` ends in the film's ISO, so
    the loose rule filed every frame of the roll as frame 200.
    """
    if not filename:
        return None
    stem = os.path.splitext(os.path.basename(filename))[0]
    explicit = _EXPLICIT_FRAME.search(stem)
    if explicit:
        return int(explicit.group(1))
    preset = negpy_naming.parse(stem)
    if preset.frame_number is not None:
        return preset.frame_number
    tokens = [token for token in re.split(r"[^0-9A-Za-z]+", stem) if token]
    for token in reversed(tokens):
        if _NUMERIC_TOKEN.match(token):
            return int(token)
    return None


# --- serialisation -------------------------------------------------------------


def film_to_dict(
    f: FilmRoll, image_count: Optional[int] = None, cover_image_ids: Optional[List[int]] = None
) -> dict:
    return {
        "id": f.id,
        "title": f.title,
        # R#14: the ids are authoritative; the names answer with the catalog entry's
        # current name so a rename in Gear shows up on every roll that points at it.
        "camera_id": f.camera_id,
        "lens_id": f.lens_id,
        "film_stock_id": f.film_stock_id,
        "camera": f.camera_name,
        "lens": f.lens_name,
        "film_type": f.film_type_name,
        "format": f.format,
        "notes": f.notes,
        "building": f.building,
        "folder": f.folder,
        "archive_serial": f.archive_serial,
        "start_date": f.start_date.isoformat() if f.start_date else None,
        "end_date": f.end_date.isoformat() if f.end_date else None,
        "created_at": f.created_at.isoformat(),
        # M1: the roll list shows a frame count and a thumbnail strip per row without
        # fetching every roll's images (no N+1).
        "image_count": int(image_count or 0),
        "cover_image_id": (cover_image_ids or [None])[0],
        "cover_image_ids": list(cover_image_ids or []),
        # M4: the physical side. `effective_strips` is the roll's own list or the
        # sleeve layout's default, so the UI can place frame 14 on strip 3 without a
        # second request.
        "location_id": f.location_id,
        "location_path": loc_svc.path_string(f.location_ref),
        "location_kind": f.location_ref.kind if f.location_ref else None,
        "strips": list(f.strips) if f.strips else None,
        "effective_strips": _effective_strips(f),
        "status": f.status or "back",
        "status_label": lifecycle.STATUS_LABELS.get(f.status or "back"),
        "loaded_at": f.loaded_at.isoformat() if f.loaded_at else None,
        "shot_at": f.shot_at.isoformat() if f.shot_at else None,
        "lab_sent_at": f.lab_sent_at.isoformat() if f.lab_sent_at else None,
        "lab_back_at": f.lab_back_at.isoformat() if f.lab_back_at else None,
        "scanned_at": f.scanned_at.isoformat() if f.scanned_at else None,
        "sleeved_at": f.sleeved_at.isoformat() if f.sleeved_at else None,
        "loaded_camera_id": f.loaded_camera_id,
        "label_printed_at": f.label_printed_at.isoformat() if f.label_printed_at else None,
        "needs_label": f.label_printed_at is None,
    }


def _effective_strips(f: FilmRoll) -> List[int]:
    """The roll's strips, its sleeve's layout, an ancestor's layout, or PrintFile."""
    if f.strips:
        return [int(n) for n in f.strips]
    node = f.location_ref
    rows = per_row = None
    guard = 0
    while node is not None and guard < 64:
        if node.sleeve_layout is not None:
            rows, per_row = node.sleeve_layout.rows, node.sleeve_layout.frames_per_row
            break
        node = node.parent
        guard += 1
    return strips_svc.effective_strips(None, rows, per_row)


def roll_summaries(
    db: Session, film_ids: Optional[Iterable[int]] = None
) -> Dict[int, Tuple[int, List[int]]]:
    """``{film_roll_id: (scan count, first few image ids)}`` in two cheap queries."""
    ids = list(film_ids) if film_ids is not None else None
    if ids is not None and not ids:
        return {}

    counts = db.query(ImageAsset.film_roll_id, func.count(ImageAsset.id)).filter(
        ImageAsset.type == ImageType.scan, ImageAsset.film_roll_id.isnot(None)
    )
    covers = db.query(ImageAsset.film_roll_id, ImageAsset.id).filter(
        ImageAsset.type == ImageType.scan, ImageAsset.film_roll_id.isnot(None)
    )
    if ids is not None:
        counts = counts.filter(ImageAsset.film_roll_id.in_(ids))
        covers = covers.filter(ImageAsset.film_roll_id.in_(ids))

    summary: Dict[int, Tuple[int, List[int]]] = {
        roll_id: (count, []) for roll_id, count in counts.group_by(ImageAsset.film_roll_id).all()
    }
    # First frames of each roll in display order: lowest frame number, then oldest row.
    for roll_id, image_id in covers.order_by(
        ImageAsset.film_roll_id.asc(),
        ImageAsset.frame_number.asc().nulls_last(),
        ImageAsset.id.asc(),
    ).all():
        count, strip = summary.setdefault(roll_id, (0, []))
        if len(strip) < COVER_STRIP:
            strip.append(image_id)
    return summary


def frames_in_order(query):
    """The one frame order in the archive: frame number first, nulls last, then id."""
    return query.order_by(ImageAsset.frame_number.asc().nulls_last(), ImageAsset.id.asc())


def image_to_dict(i: ImageAsset) -> dict:
    storage_mode = i.storage_mode or "managed"
    if storage_mode == "linked":
        # M3: a linked file lives outside /static on purpose, so the API serves it.
        public_url = f"/api/images/{i.id}/download"
    else:
        # R#13: the public URL follows the file, not the record's current type —
        # changing a scan into a contact sheet does not move the file.
        public_url = "/" + i.path.replace(os.sep, "/").lstrip("/")
    return {
        "id": i.id,
        "film_roll_id": i.film_roll_id,
        "type": i.type.value,
        "path": i.path,
        "url": public_url,
        "original_filename": i.original_filename,
        "storage_mode": storage_mode,
        # M3, import by reference: where a linked original really is, and the
        # sampled hash that identifies it across a move or a copy.
        "source_path": i.source_path,
        "content_hash": i.content_hash,
        "frame_number": i.frame_number,
        "notes": i.notes,
        "capture_date": i.capture_date.isoformat() if i.capture_date else None,
        # M5, NegPy: what the file itself said on ingest, and whether it has been
        # edited in NegPy. `negpy_recipe` carries the parsed sidecar; the viewer
        # only shows its summary, because NegArchive does not interpret a recipe.
        "capture_metadata": i.capture_metadata or None,
        "sidecar_path": i.sidecar_path,
        "negpy_edited_at": i.negpy_edited_at.isoformat() if i.negpy_edited_at else None,
        "negpy_recipe": i.negpy_recipe or None,
        "negpy_summary": (i.negpy_recipe or {}).get("summary") if i.negpy_recipe else None,
        "created_at": i.created_at.isoformat(),
    }


def catalog_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    # Ensure leading slash for valid URL resolution in Next/Image
    return path if path.startswith("/") else f"/{path}"


def camera_to_dict(c: Camera) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "mount": c.mount,
        "image_path": c.image_path,
        "url": catalog_url(c.image_path),
        "notes": c.notes,
    }


def lens_to_dict(l: Lens) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "mount": l.mount,
        "image_path": l.image_path,
        "url": catalog_url(l.image_path),
        "notes": l.notes,
    }


def filmstock_to_dict(s: FilmStock) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "manufacturer": s.manufacturer,
        "format": s.format,
        "iso": s.iso,
        "kind": s.kind.value if isinstance(s.kind, FilmKind) else str(s.kind),
        # R#1/R#22: always a real boolean, never 0/1 or None
        "expired": bool(s.expired),
        "expiration_date": s.expiration_date.isoformat() if s.expiration_date else None,
        "image_path": s.image_path,
        "url": catalog_url(s.image_path),
    }


def to_bool(value) -> Optional[bool]:
    """Coerce whatever the client sent into a bool the Boolean column accepts."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "expired"}
    return bool(value)


def clean_name(value) -> Optional[str]:
    """Map the UI's "None" placeholder and empty strings to NULL (R#8)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "" or value == "None":
            return None
    return value


def require_name(value, field: str = "name", label: Optional[str] = None) -> str:
    label = label or field.replace("_", " ")
    if value is None or not str(value).strip():
        raise ApiError("invalid_" + field, f"{label.capitalize()} is required.", 400, field)
    return str(value).strip()


# --- gear references (R#14) ----------------------------------------------------

GEAR = {
    "camera": (Camera, "camera_id", "camera", "camera"),
    "lens": (Lens, "lens_id", "lens", "lens"),
    "film_stock": (FilmStock, "film_stock_id", "film_type", "film stock"),
}


def _resolve_gear(db: Session, body: schemas.FilmRollWrite, roll: FilmRoll, creating: bool) -> None:
    """Apply the gear part of a roll body, by id or (for older clients) by name.

    * ``camera_id`` given → the roll points at that catalog entry, and the legacy
      ``camera`` string is written from it so a pre-M2 client still reads a name.
    * only ``camera`` given → the name is looked up; a hit sets the id too, a miss
      keeps the free text and clears the id.
    * either one explicitly ``null`` clears both.
    """
    for prefix, (model, id_field, name_field, label) in GEAR.items():
        given_id = creating or _given(body, id_field)
        given_name = creating or _given(body, name_field)
        raw_id = getattr(body, id_field)
        raw_name = clean_name(getattr(body, name_field))

        if given_id and raw_id is not None:
            entry = db.get(model, raw_id)
            if entry is None:
                raise ApiError(
                    f"unknown_{prefix}", f"That {label} does not exist.", 404, id_field
                )
            setattr(roll, id_field, entry.id)
            setattr(roll, name_field, entry.name)
            continue

        if given_name and raw_name is not None:
            match = db.query(model).filter(func.lower(model.name) == raw_name.lower()).first()
            setattr(roll, id_field, match.id if match else None)
            setattr(roll, name_field, match.name if match else raw_name)
            continue

        if (given_id and raw_id is None and (not given_name or raw_name is None)) or (
            given_name and raw_name is None and (not given_id or raw_id is None)
        ):
            setattr(roll, id_field, None)
            setattr(roll, name_field, None)


def _given(body, field: str) -> bool:
    return field in getattr(body, "model_fields_set", set())


def _rolls_using(db: Session, prefix: str, entry) -> int:
    """How many rolls still refer to a catalog entry, by id or by the legacy name."""
    _, id_field, name_field, _ = GEAR[prefix]
    return (
        db.query(func.count(FilmRoll.id))
        .filter(
            or_(
                getattr(FilmRoll, id_field) == entry.id,
                func.lower(getattr(FilmRoll, name_field)) == entry.name.lower(),
            )
        )
        .scalar()
        or 0
    )


# --- files ---------------------------------------------------------------------


def _abs(path: str) -> str:
    """Absolute location of a stored path.

    M3: `static/...` resolves under DATA_DIR, an absolute path (a linked original,
    import-by-reference) is returned untouched, and a file still sitting in the
    pre-M3 in-tree location is found there — so an archive from M0/M1 keeps
    rendering without a migration step. See app/paths.py.
    """
    return str(paths.resolve(path))


def _inside_uploads(abs_path: str) -> bool:
    root = os.path.abspath(uploads_root())
    try:
        return os.path.commonpath([os.path.abspath(abs_path), root]) == root
    except ValueError:
        # Different drives on Windows, or a relative/absolute mix: not ours.
        return False


def delete_asset_file(image: ImageAsset) -> bool:
    """Delete the file behind an image, unless somebody else owns it.

    Two guards, both deliberate: a ``linked`` row points at a file that belongs to
    the user's own library (M3's import-by-reference), and a managed file must live
    under ``static/uploads``. Returns whether a file was actually removed.
    """
    if not image.path:
        return False
    if (image.storage_mode or "managed") != "managed":
        return False
    target = _abs(image.path)
    if not _inside_uploads(target):
        return False
    # M5: the `.negpy` sidecar we stored beside the file goes with it. It describes
    # this file and nothing else, so leaving it behind would only produce an orphan.
    _remove_quietly(target + negpy_sidecar.SUFFIX)
    try:
        os.remove(target)
        return True
    except OSError:
        return False


def _wants_file_deletion(keep_files: bool, legacy_delete_file: Optional[bool]) -> bool:
    """M2 deletes managed files with the record; ``keep_files=true`` opts out (R#9).

    ``delete_file`` is the M1 spelling and still wins when it is sent explicitly, so
    a client written against the old default keeps behaving the way it expects.
    """
    if legacy_delete_file is not None:
        return bool(legacy_delete_file)
    return not keep_files


def store_upload(file: UploadFile, subdir: str) -> Tuple[str, str]:
    """Validate and save one uploaded file. Returns ``(relative path, original name)``.

    Raises :class:`ApiError` with 415 for a type that is not allowed and 413 for a
    file over ``MAX_UPLOAD_MB`` (R#18). The stored name is still a UUID — the name
    the scanner gave it is kept in ``image_assets.original_filename`` (R#7).
    """
    original = os.path.basename(file.filename or "").strip() or "upload"
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            "unsupported_file_type",
            f"“{original}” is not an accepted image "
            f"({', '.join(sorted(e.lstrip('.') for e in ALLOWED_EXTENSIONS))}).",
            415,
            "file",
        )

    file.file.seek(0)
    head = file.file.read(16)
    file.file.seek(0)
    if not _looks_like_image(head):
        raise ApiError(
            "unsupported_file_type",
            f"“{original}” does not look like an image file.",
            415,
            "file",
        )

    # The stored value keeps its `static/` prefix; the bytes go under DATA_DIR.
    os.makedirs(os.path.join(str(paths.data_dir()), subdir), exist_ok=True)
    rel_path = os.path.join("static", subdir, f"{uuid4().hex}{ext}")
    abs_path = _abs(rel_path)
    limit = max_upload_bytes()
    written = 0
    try:
        with open(abs_path, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise ApiError(
                        "file_too_large",
                        f"“{original}” is larger than the {limit // (1024 * 1024)} MB limit "
                        "(MAX_UPLOAD_MB).",
                        413,
                        "file",
                    )
                out.write(chunk)
    except ApiError:
        _remove_quietly(abs_path)
        raise
    except OSError as exc:
        _remove_quietly(abs_path)
        raise ApiError(
            "write_failed", f"“{original}” could not be stored: {exc}", 500, "file"
        ) from exc
    return rel_path, original


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --- NegPy sidecars on upload (M5) --------------------------------------------
#
# A `.negpy` file is not an image and never goes through `store_upload`: it is not
# in the allowlist, it has no magic bytes, and it belongs *next to* a scan rather
# than being one. The bulk and ZIP upload paths therefore pull sidecars out of the
# incoming files first, and hand each one to the frame whose name it shares — a
# managed file is stored under a UUID, so the sidecar is stored as
# `<uuid>.<ext>.negpy` beside it and the link is the record, not the name.


def store_sidecar_bytes(rel_path: str, payload: bytes) -> Optional[str]:
    """Write a ``.negpy`` sidecar next to an already-stored managed file."""
    if not payload or len(payload) > negpy_sidecar.MAX_SIDECAR_BYTES:
        return None
    target = _abs(rel_path) + negpy_sidecar.SUFFIX
    try:
        with open(target, "wb") as out:
            out.write(payload)
    except OSError:
        return None
    return target


def _pull_sidecars(files: List[UploadFile]) -> Tuple[List[UploadFile], Dict[str, bytes]]:
    """Split an upload into images and ``{stem: sidecar bytes}``."""
    images: List[UploadFile] = []
    sidecars: Dict[str, bytes] = {}
    for item in files:
        name = os.path.basename(item.filename or "")
        if negpy_sidecar.is_sidecar_name(name):
            item.file.seek(0)
            payload = item.file.read(negpy_sidecar.MAX_SIDECAR_BYTES + 1)
            if len(payload) <= negpy_sidecar.MAX_SIDECAR_BYTES:
                sidecars[negpy_sidecar.image_stem(name).lower()] = payload
            continue
        images.append(item)
    return images, sidecars


def _new_image(
    *,
    film_roll_id: Optional[int],
    image_type: ImageType,
    rel_path: str,
    original_filename: Optional[str],
    frame_number: Optional[int] = None,
    notes: Optional[str] = None,
    capture_date=None,
) -> ImageAsset:
    """One place builds an ImageAsset, so every path keeps the filename and the
    frame number parsed from it (R#7, R#24), and every file gets its content hash.

    The hash is M3's: it is what lets an import skip a file the archive already
    has, and what ties a NegArchive frame to a NegPy edit of the same scan. It
    samples ~6 MiB however large the file is (app/services/hashing.py)."""
    if frame_number is None and image_type == ImageType.scan:
        frame_number = frame_number_from_filename(original_filename)
    return ImageAsset(
        film_roll_id=film_roll_id,
        type=image_type,
        path=rel_path,
        original_filename=original_filename,
        storage_mode="managed",
        content_hash=safe_content_hash(_abs(rel_path)),
        frame_number=frame_number,
        notes=notes,
        capture_date=capture_date,
    )


# ---------------------------
# Film rolls
# ---------------------------


# ---------------------------------------------------------------------------
# Pagination and server-side search (roadmap M3, R#20)
#
# A 500-roll archive used to ship every roll and every frame to the browser and
# filter them in React. These endpoints do it in Postgres instead.
#
# The response shape is backwards compatible on purpose: **without** `limit` the
# endpoints still answer with a bare JSON array, so every existing caller (and
# the M0/M1/M2 tests) keeps working. **With** `limit` they answer an envelope
# carrying the total, which is what a "load more" button needs:
#
#     {"items": [...], "total": 412, "limit": 50, "offset": 100, "has_more": true}
#
# `X-Total-Count` carries the total in both shapes.
# ---------------------------------------------------------------------------

#: Refuse to serve more than this in one page, whatever the client asks for.
MAX_PAGE = 500


def _page_bounds(limit: Optional[int], offset: Optional[int]) -> Tuple[Optional[int], int]:
    if limit is None:
        return None, max(0, int(offset or 0))
    return max(1, min(int(limit), MAX_PAGE)), max(0, int(offset or 0))


def _respond_page(items: List[dict], total: int, limit: Optional[int], offset: int):
    headers = {"X-Total-Count": str(total)}
    if limit is None:
        return JSONResponse(items, headers=headers)
    return JSONResponse(
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total,
        },
        headers=headers,
    )


@router.get("/films", response_model=None)
def list_films(
    q: Optional[str] = None,
    camera_id: Optional[int] = None,
    film_stock_id: Optional[int] = None,
    camera: Optional[str] = None,
    film_type: Optional[str] = None,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = None,
    status: Optional[str] = None,
    location_id: Optional[int] = None,
    bucket: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """The roll list, filtered and paginated in the database.

    M4 adds ``status`` (one of the lifecycle steps), ``location_id`` (the node or
    anything under it) and ``bucket`` (``in_cameras`` / ``at_lab`` / ``to_scan`` /
    ``to_sleeve``, the home page work lists).

    * ``q``      — words that must all appear somewhere in the roll (title, notes,
                   serial, folder, building, camera, lens, film). Case-insensitive.
    * ``camera_id`` / ``film_stock_id`` — catalog ids (R#14). The deprecated
      ``camera`` / ``film_type`` name filters still work for older clients, and
      match a roll by either its id's catalog name or its legacy name column.
    * ``from`` / ``to`` — ISO dates. A roll matches when its shooting range
      *overlaps* the filter range, which is what "shot in August" means for a roll
      that ran from July to September.
    """
    try:
        start = parse_date(from_, "from")
        end = parse_date(to, "to")
    except ApiError as exc:
        return from_exc(exc)

    query = db.query(FilmRoll)

    for term in (q or "").split():
        pattern = f"%{term.lower()}%"
        query = query.filter(
            or_(
                func.lower(func.coalesce(FilmRoll.title, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.notes, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.archive_serial, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.folder, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.building, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.camera, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.lens, "")).like(pattern),
                func.lower(func.coalesce(FilmRoll.film_type, "")).like(pattern),
                FilmRoll.camera_id.in_(
                    db.query(Camera.id).filter(func.lower(Camera.name).like(pattern))
                ),
                FilmRoll.lens_id.in_(
                    db.query(Lens.id).filter(func.lower(Lens.name).like(pattern))
                ),
                FilmRoll.film_stock_id.in_(
                    db.query(FilmStock.id).filter(func.lower(FilmStock.name).like(pattern))
                ),
            )
        )

    if camera_id is not None:
        query = query.filter(FilmRoll.camera_id == camera_id)
    if film_stock_id is not None:
        query = query.filter(FilmRoll.film_stock_id == film_stock_id)
    # The by-name filters are the pre-M2 spelling: match the catalog entry the roll
    # points at, or the legacy name column for a roll that has no id yet.
    if camera:
        query = query.filter(
            or_(
                FilmRoll.camera == camera,
                FilmRoll.camera_id.in_(db.query(Camera.id).filter(Camera.name == camera)),
            )
        )
    if film_type:
        query = query.filter(
            or_(
                FilmRoll.film_type == film_type,
                FilmRoll.film_stock_id.in_(
                    db.query(FilmStock.id).filter(FilmStock.name == film_type)
                ),
            )
        )

    # Overlap: the roll ended on or after `from`, and started on or before `to`.
    if start is not None:
        query = query.filter(func.coalesce(FilmRoll.end_date, FilmRoll.start_date) >= start)
    if end is not None:
        query = query.filter(func.coalesce(FilmRoll.start_date, FilmRoll.end_date) <= end)

    # M4: lifecycle and location
    if status:
        try:
            query = query.filter(FilmRoll.status == lifecycle.parse_status(status))
        except ApiError as exc:
            return from_exc(exc)
    if bucket:
        statuses = {"in_cameras": ("loaded", "shot"), "at_lab": ("at_lab",), "to_scan": ("back",), "to_sleeve": ("scanned",)}.get(bucket)
        if statuses is None:
            return error_response("invalid_bucket", "Bucket must be in_cameras, at_lab, to_scan or to_sleeve.", 400, "bucket")
        query = query.filter(FilmRoll.status.in_(statuses))
    if location_id is not None:
        node = db.get(Location, location_id)
        if node is None:
            return not_found("Location", "location_id")
        under = [n.id for n in db.query(Location).all() if node.id in loc_svc.path_ids(n)]
        query = query.filter(FilmRoll.location_id.in_(under))

    page_limit, page_offset = _page_bounds(limit, offset)
    total = query.order_by(None).count()
    query = query.order_by(FilmRoll.created_at.desc(), FilmRoll.id.desc()).offset(page_offset)
    if page_limit is not None:
        query = query.limit(page_limit)
    films = query.all()

    summaries = roll_summaries(db, [f.id for f in films])
    items = [film_to_dict(f, *summaries.get(f.id, (0, []))) for f in films]
    return _respond_page(items, total, page_limit, page_offset)


@router.get("/films/{film_id}", response_model=schemas.FilmDetailOut, responses={404: {"model": schemas.ErrorOut}})
def get_film(film_id: int, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")
    scans = frames_in_order(
        db.query(ImageAsset).filter(
            ImageAsset.film_roll_id == f.id, ImageAsset.type == ImageType.scan
        )
    ).all()
    contact_sheets = (
        db.query(ImageAsset)
        .filter(ImageAsset.film_roll_id == f.id, ImageAsset.type == ImageType.contact_sheet)
        .order_by(ImageAsset.id.asc())
        .all()
    )
    return {
        "film": film_to_dict(f, len(scans), [i.id for i in scans[:COVER_STRIP]]),
        "images": [image_to_dict(i) for i in scans],
        "contact_sheets": [image_to_dict(i) for i in contact_sheets],
    }


def _check_date_order(start, end) -> None:
    if start and end and end < start:
        raise ApiError("invalid_date_range", "The end date is before the start date.", 400, "end_date")


@router.post("/films", response_model=schemas.FilmRollEnvelope, responses={400: {"model": schemas.ErrorOut}})
def create_film(body: schemas.FilmRollCreate, db: Session = Depends(get_db)):
    try:
        title = require_name(body.title, "title")
        start = parse_date(body.start_date, "start_date")
        end = parse_date(body.end_date, "end_date")
        _check_date_order(start, end)
        f = FilmRoll(
            title=title,
            notes=body.notes,
            format=body.format,
            building=body.building,
            folder=body.folder,
            start_date=start,
            end_date=end,
        )
        _resolve_gear(db, body, f, creating=True)
        # M4: a serial is allocated when none is given; the status defaults by whether
        # the roll is being created "loaded" (from a camera) or as an archived roll.
        serials.assign(db, f, body.archive_serial)
        f.strips = strips_svc.parse_strips(body.strips)
        if body.location_id not in (None, ""):
            target = db.get(Location, parse_int(body.location_id, "location_id", minimum=1))
            if target is None:
                raise ApiError("unknown_location", "That location does not exist.", 404, "location_id")
        else:
            target = None
        lifecycle.set_status(f, body.status or "back")
        db.add(f)
        db.flush()
        if target is not None:
            loc_svc.move_roll(db, f, target)
        if body.loaded_camera_id not in (None, ""):
            camera = db.get(Camera, parse_int(body.loaded_camera_id, "loaded_camera_id", minimum=1))
            if camera is None:
                raise ApiError("unknown_camera", "That camera does not exist.", 404, "loaded_camera_id")
            lifecycle.load_into_camera(db, camera, f)
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(f)
    return {"ok": True, "film": film_to_dict(f)}


@router.put(
    "/films/{film_id}",
    response_model=schemas.FilmRollEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def update_film(
    film_id: int,
    body: schemas.FilmRollUpdate,
    force: bool = Query(False, description="Allow changing a serial that is already printed (M4)."),
    db: Session = Depends(get_db),
):
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")
    try:
        if body.given("title"):
            f.title = require_name(body.title, "title")
        start = parse_date(body.start_date, "start_date") if body.given("start_date") else f.start_date
        end = parse_date(body.end_date, "end_date") if body.given("end_date") else f.end_date
        _check_date_order(start, end)
        _resolve_gear(db, body, f, creating=False)
        for key in ["notes", "format", "building", "folder"]:
            if body.given(key):
                setattr(f, key, clean_name(getattr(body, key)))
        f.start_date = start
        f.end_date = end
        # M4
        if body.given("archive_serial"):
            serials.assign(db, f, body.archive_serial, force=force)
        if body.given("strips"):
            f.strips = strips_svc.parse_strips(body.strips)
        if body.given("status") and body.status:
            lifecycle.set_status(f, body.status)
        if body.given("loaded_camera_id"):
            if body.loaded_camera_id in (None, ""):
                f.loaded_camera_id = None
            else:
                camera = db.get(Camera, parse_int(body.loaded_camera_id, "loaded_camera_id", minimum=1))
                if camera is None:
                    raise ApiError("unknown_camera", "That camera does not exist.", 404, "loaded_camera_id")
                lifecycle.load_into_camera(db, camera, f, force=force)
        if body.given("location_id"):
            target = None
            if body.location_id not in (None, "", "none"):
                target = db.get(Location, parse_int(body.location_id, "location_id", minimum=1))
                if target is None:
                    raise ApiError("unknown_location", "That location does not exist.", 404, "location_id")
            loc_svc.move_roll(db, f, target)
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(f)
    count, strip = roll_summaries(db, [f.id]).get(f.id, (0, []))
    return {"ok": True, "film": film_to_dict(f, count, strip)}


@router.post(
    "/films/{film_id}/status",
    response_model=schemas.FilmRollEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def set_roll_status(film_id: int, body: schemas.StatusChange, db: Session = Depends(get_db)):
    """Advance (or rewind) a roll in its lifecycle; ``at`` overrides the timestamp."""
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")
    try:
        when = None
        if body.at:
            parsed_date = parse_date(body.at, "at")
            when = datetime.combine(parsed_date, datetime.min.time()) if parsed_date else None
        lifecycle.set_status(f, body.status, when)
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(f)
    count, strip = roll_summaries(db, [f.id]).get(f.id, (0, []))
    return {"ok": True, "film": film_to_dict(f, count, strip)}


@router.get("/work")
def work_lists(db: Session = Depends(get_db)):
    """The home page's four work lists with counts (M4 lifecycle)."""
    buckets = {"in_cameras": ("loaded", "shot"), "at_lab": ("at_lab",), "to_scan": ("back",), "to_sleeve": ("scanned",)}
    out = {}
    for key, statuses in buckets.items():
        rolls = (
            db.query(FilmRoll)
            .filter(FilmRoll.status.in_(statuses))
            .order_by(FilmRoll.created_at.desc())
            .limit(50)
            .all()
        )
        total = db.query(func.count(FilmRoll.id)).filter(FilmRoll.status.in_(statuses)).scalar() or 0
        summaries = roll_summaries(db, [r.id for r in rolls])
        out[key] = {"total": int(total), "items": [film_to_dict(r, *summaries.get(r.id, (0, []))) for r in rolls]}
    unfiled = db.query(func.count(FilmRoll.id)).filter(FilmRoll.location_id.is_(None)).scalar() or 0
    needs_label = db.query(func.count(FilmRoll.id)).filter(FilmRoll.label_printed_at.is_(None)).scalar() or 0
    out["unfiled"] = int(unfiled)
    out["needs_label"] = int(needs_label)
    return out


@router.delete(
    "/films/{film_id}",
    response_model=schemas.DeleteResult,
    responses={404: {"model": schemas.ErrorOut}},
)
def delete_film(
    film_id: int,
    keep_files: bool = Query(False, description="Leave the scan files on disk (R#9)."),
    db: Session = Depends(get_db),
):
    """Delete a roll, its frame records and — unless ``keep_files`` — their files."""
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")
    images = db.query(ImageAsset).filter(ImageAsset.film_roll_id == f.id).all()
    files_deleted = 0
    for image in images:
        if not keep_files:
            files_deleted += int(delete_asset_file(image))
        drop_cached_previews(image.id)
        db.delete(image)
    db.delete(f)
    db.commit()
    return {"ok": True, "files_deleted": files_deleted}


# ---------------------------
# Images
# ---------------------------


@router.get("/images", response_model=None)
def list_images(
    film_id: Optional[int] = None,
    type: Optional[str] = None,
    q: Optional[str] = None,
    unassigned: Optional[bool] = None,
    storage_mode: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Every frame, filtered and paginated (roadmap M3, R#20).

    ``unassigned=true`` is the "not in a roll yet" pile the frames page shows;
    ``q`` searches the note and the original filename.
    """
    query = db.query(ImageAsset)
    if film_id:
        query = query.filter(ImageAsset.film_roll_id == film_id)
    if unassigned:
        query = query.filter(ImageAsset.film_roll_id.is_(None))
    if type:
        t = type.lower().strip()
        if t == "scan":
            query = query.filter(ImageAsset.type == ImageType.scan)
        elif t in {"contact", "contact_sheet", "contact-sheet"}:
            query = query.filter(ImageAsset.type == ImageType.contact_sheet)
        # else: ignore invalid type filter, return all
    if storage_mode in {"managed", "linked"}:
        query = query.filter(ImageAsset.storage_mode == storage_mode)
    for term in (q or "").split():
        pattern = f"%{term.lower()}%"
        query = query.filter(
            or_(
                func.lower(func.coalesce(ImageAsset.notes, "")).like(pattern),
                func.lower(func.coalesce(ImageAsset.original_filename, "")).like(pattern),
            )
        )

    page_limit, page_offset = _page_bounds(limit, offset)
    total = query.order_by(None).count()
    # R#24: frame order everywhere, not insertion order. Across rolls, group by
    # roll first so a page is not a shuffle of every roll's frame 1.
    ordered = frames_in_order(query.order_by(ImageAsset.film_roll_id.asc().nulls_first()))
    ordered = ordered.offset(page_offset)
    if page_limit is not None:
        ordered = ordered.limit(page_limit)
    return _respond_page([image_to_dict(i) for i in ordered.all()], total, page_limit, page_offset)


@router.get(
    "/images/{image_id}",
    response_model=schemas.ImageOut,
    responses={404: {"model": schemas.ErrorOut}},
)
def get_image(image_id: int, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return not_found("Frame")
    return image_to_dict(i)


def _cache_file(image_id: int, width: int, mtime_ns: int) -> str:
    """Cache file for one rendered preview, keyed by image id + width + source mtime."""
    return os.path.join(cache_dir(), f"{image_id}_{width}_{mtime_ns}.jpg")


def _write_cache(cache_path: str, payload: bytes) -> None:
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        tmp = f"{cache_path}.{uuid4().hex}.tmp"
        with open(tmp, "wb") as out:
            out.write(payload)
        os.replace(tmp, cache_path)  # atomic: readers never see a half-written file
        # Drop older renderings of the same image at the same width.
        stem = os.path.basename(cache_path).rsplit("_", 1)[0]
        for stale in glob.glob(os.path.join(cache_dir(), f"{stem}_*.jpg")):
            if os.path.abspath(stale) != os.path.abspath(cache_path):
                try:
                    os.remove(stale)
                except OSError:
                    pass
    except OSError:
        # A read-only or full disk must not break the preview itself.
        pass


def drop_cached_previews(image_id: int) -> None:
    for stale in glob.glob(os.path.join(cache_dir(), f"{image_id}_*.jpg")):
        try:
            os.remove(stale)
        except OSError:
            pass


def _cached_response(cache_path: str) -> FileResponse:
    return FileResponse(
        cache_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Preview-Cache": "hit"},
    )


@router.get("/images/{image_id}/preview", responses={404: {"model": schemas.ErrorOut}})
def get_image_preview(image_id: int, width: int = 1200, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return not_found("Frame")
    # Resolve absolute path
    abs_path = _abs(i.path)
    ext = os.path.splitext(abs_path)[1].lower()

    # Clamp the width so the cache cannot be filled with arbitrary sizes.
    width = max(16, min(int(width or 1200), 6000))
    cache_path = None
    try:
        mtime_ns = os.stat(abs_path).st_mtime_ns
        cache_path = _cache_file(image_id, width, mtime_ns)
        if os.path.exists(cache_path):
            return _cached_response(cache_path)
    except OSError:
        cache_path = None

    # Enable loading truncated images in Pillow
    PILImageFile.LOAD_TRUNCATED_IMAGES = True
    # Primary path: Pillow
    try:
        img = PILImage.open(abs_path)
        # Convert unusual modes to RGB safely
        if img.mode != "RGB":
            img = img.convert("RGB")
        if width and img.width > width:
            new_h = max(1, int(img.height * (width / img.width)))
            img = img.resize((width, new_h), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
        if cache_path:
            _write_cache(cache_path, data)
        return StreamingResponse(
            io.BytesIO(data),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Preview-Cache": "miss"},
        )
    except Exception:
        # Secondary fallback: OpenCV can read more TIFF variants (e.g., 16-bit)
        try:
            import cv2
            import numpy as np

            if not os.path.exists(abs_path):
                raise FileNotFoundError
            cv_img = cv2.imread(abs_path, cv2.IMREAD_UNCHANGED)
            if cv_img is None:
                raise ValueError("cv2 unreadable")
            # Convert 16-bit to 8-bit for JPEG encoding
            if cv_img.dtype == np.uint16:
                cv_img = cv2.convertScaleAbs(cv_img, alpha=(255.0 / 65535.0))
            elif cv_img.dtype in (np.float32, np.float64):
                min_val, max_val = float(cv_img.min()), float(cv_img.max())
                if max_val > min_val:
                    cv_img = ((cv_img - min_val) * (255.0 / (max_val - min_val))).astype(np.uint8)
                else:
                    cv_img = (cv_img * 255.0).astype(np.uint8)
            # Ensure 3-channel BGR
            if len(cv_img.shape) == 2:  # grayscale
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
            elif cv_img.shape[2] == 4:  # BGRA -> BGR
                cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGRA2BGR)
            elif cv_img.shape[2] != 3:
                cv_img = cv_img[:, :, :3]

            if width and cv_img.shape[1] > width:
                scale = width / float(cv_img.shape[1])
                new_h = int(cv_img.shape[0] * scale)
                cv_img = cv2.resize(cv_img, (width, new_h), interpolation=cv2.INTER_AREA)

            ok, enc = cv2.imencode(".jpg", cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                raise ValueError("encode failed")
            data = enc.tobytes()
            if cache_path:
                _write_cache(cache_path, data)
            return StreamingResponse(
                io.BytesIO(data),
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                    "X-Preview-Cache": "miss",
                },
            )
        except Exception:
            # Final fallback: serve original if browser-friendly
            if ext in {".jpg", ".jpeg", ".png"} and os.path.exists(abs_path):
                media_type = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
                return FileResponse(abs_path, media_type=media_type)
            if not os.path.exists(abs_path):
                return error_response(
                    "file_missing",
                    "The file behind this frame is missing from disk.",
                    404,
                )
            return error_response("unreadable_image", "This file could not be decoded.", 415)


@router.get("/images/{image_id}/download", responses={404: {"model": schemas.ErrorOut}})
def download_image(image_id: int, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return not_found("Frame")
    abs_path = _abs(i.path)
    if not os.path.exists(abs_path):
        return error_response("file_missing", "The file behind this frame is missing from disk.", 404)
    # R#7: the download gets the name the scanner gave it, not the UUID on disk.
    filename = i.original_filename or os.path.basename(abs_path)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return FileResponse(abs_path, media_type="application/octet-stream", headers=headers)


@router.post(
    "/images",
    response_model=schemas.ImageEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def create_image(body: schemas.ImageCreate, db: Session = Depends(get_db)):
    """Register an image whose file is already somewhere NegArchive can read."""
    try:
        path = require_name(body.path, "path")
        image_type = _parse_image_type(body.type or "scan")
        film_roll_id = _require_roll(db, body.film_roll_id)
        i = _new_image(
            film_roll_id=film_roll_id,
            image_type=image_type,
            rel_path=path,
            original_filename=body.original_filename or os.path.basename(path),
            frame_number=parse_int(body.frame_number, "frame_number", minimum=0),
            notes=body.notes,
            capture_date=parse_date(body.capture_date, "capture_date"),
        )
        if body.storage_mode:
            i.storage_mode = body.storage_mode
    except ApiError as exc:
        return from_exc(exc)
    db.add(i)
    db.commit()
    return {"ok": True, "image": image_to_dict(i)}


def _parse_image_type(value) -> ImageType:
    try:
        return ImageType(str(value))
    except ValueError as exc:
        raise ApiError(
            "invalid_type", "Type must be 'scan' or 'contact_sheet'.", 400, "type"
        ) from exc


@router.put(
    "/images/{image_id}",
    response_model=schemas.ImageEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def update_image(image_id: int, body: schemas.ImageUpdate, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return not_found("Frame")
    try:
        if body.given("film_roll_id"):
            # R#12: an explicit null unassigns the image from its roll
            i.film_roll_id = _require_roll(db, body.film_roll_id)
        if body.given("type") and body.type:
            i.type = _parse_image_type(body.type)
        if body.given("frame_number"):
            i.frame_number = parse_int(body.frame_number, "frame_number", minimum=0)
        if body.given("notes"):
            i.notes = body.notes or None
        if body.given("capture_date"):
            i.capture_date = parse_date(body.capture_date, "capture_date")
        if body.given("original_filename"):
            i.original_filename = body.original_filename or None
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.commit()
    return {"ok": True, "image": image_to_dict(i)}


def _require_roll(db: Session, film_roll_id) -> Optional[int]:
    if film_roll_id in (None, "", "none"):
        return None
    parsed = parse_int(film_roll_id, "film_roll_id")
    if not db.get(FilmRoll, parsed):
        raise ApiError("unknown_roll", "That roll does not exist.", 404, "film_roll_id")
    return parsed


@router.delete(
    "/images/{image_id}",
    response_model=schemas.DeleteResult,
    responses={404: {"model": schemas.ErrorOut}},
)
def delete_image(
    image_id: int,
    keep_files: bool = Query(False, description="Leave the file on disk (R#9)."),
    delete_file: Optional[bool] = Query(None, description="The M1 spelling; wins when sent."),
    db: Session = Depends(get_db),
):
    i = db.get(ImageAsset, image_id)
    if not i:
        return not_found("Frame")
    files_deleted = 0
    if _wants_file_deletion(keep_files, delete_file):
        files_deleted += int(delete_asset_file(i))
    drop_cached_previews(i.id)
    db.delete(i)
    db.commit()
    return {"ok": True, "files_deleted": files_deleted}


# ---------------------------
# Bulk frame operations (M1: multi-select in the roll workspace)
# ---------------------------
def _require_ids(raw) -> List[int]:
    if not isinstance(raw, list) or not raw:
        raise ApiError("invalid_ids", "Select at least one frame.", 400, "ids")
    ids: List[int] = []
    for value in raw:
        try:
            parsed = parse_int(value, "id", minimum=1)
        except ApiError as exc:
            raise ApiError("invalid_ids", "Frame ids must be whole numbers.", 400, "ids") from exc
        if parsed is None:
            raise ApiError("invalid_ids", "Frame ids must be whole numbers.", 400, "ids")
        ids.append(parsed)
    return ids


@router.post(
    "/images/bulk_update",
    response_model=schemas.BulkUpdateResult,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def bulk_update_images(body: schemas.BulkImageUpdate, db: Session = Depends(get_db)):
    """Apply a partial patch to many frames at once.

    Body: ``{"ids": [1, 2], "film_roll_id": 3|null, "capture_date": "2024-07-01"|null,
    "frame_number": 7|null}``. Only the keys present are written.
    """
    try:
        ids = _require_ids(body.ids)
        fields = {}
        if body.given("film_roll_id"):
            fields["film_roll_id"] = _require_roll(db, body.film_roll_id)
        if body.given("capture_date"):
            fields["capture_date"] = parse_date(body.capture_date, "capture_date")
        if body.given("frame_number"):
            fields["frame_number"] = parse_int(body.frame_number, "frame_number", minimum=0)
        if not fields:
            raise ApiError("nothing_to_update", "No fields to update were supplied.")
    except ApiError as exc:
        return from_exc(exc)

    images = db.query(ImageAsset).filter(ImageAsset.id.in_(ids)).all()
    if not images:
        return error_response("not_found", "None of those frames exist.", 404, "ids")
    for image in images:
        for key, value in fields.items():
            setattr(image, key, value)
    if fields.get("film_roll_id"):
        lifecycle.touch_scanned(db.get(FilmRoll, fields["film_roll_id"]))
    db.commit()
    return {"ok": True, "updated": len(images), "images": [image_to_dict(i) for i in images]}


@router.post(
    "/images/bulk_delete",
    response_model=schemas.BulkDeleteResult,
    responses={400: {"model": schemas.ErrorOut}},
)
def bulk_delete_images(body: schemas.BulkImageDelete, db: Session = Depends(get_db)):
    """Body: ``{"ids": [1, 2], "keep_files": false}``.

    Files go with the records unless ``keep_files`` is true (R#9); the M1 key
    ``delete_file`` still works and wins when it is sent.
    """
    try:
        ids = _require_ids(body.ids)
    except ApiError as exc:
        return from_exc(exc)
    remove_files = _wants_file_deletion(bool(body.keep_files), body.delete_file)

    images = db.query(ImageAsset).filter(ImageAsset.id.in_(ids)).all()
    files_deleted = 0
    for image in images:
        if remove_files:
            files_deleted += int(delete_asset_file(image))
        drop_cached_previews(image.id)
        db.delete(image)
    db.commit()
    return {"ok": True, "deleted": len(images), "files_deleted": files_deleted}


@router.post(
    "/images/upload",
    response_model=schemas.ImageEnvelope,
    responses={
        400: {"model": schemas.ErrorOut},
        404: {"model": schemas.ErrorOut},
        413: {"model": schemas.ErrorOut},
        415: {"model": schemas.ErrorOut},
    },
)
def upload_image(
    file: UploadFile = File(...),
    type: str = Form(...),
    film_roll_id: Optional[str] = Form(None),
    frame_number: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    capture_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        image_type = _parse_image_type((type or "").lower())
        roll_id = _require_roll(db, film_roll_id)
        number = parse_int(frame_number, "frame_number", minimum=0)
        captured = parse_date(capture_date, "capture_date")
        subdir = "uploads/scans" if image_type == ImageType.scan else "uploads/contact_sheets"
        rel_path, original = store_upload(file, subdir)
    except ApiError as exc:
        return from_exc(exc)
    img = _new_image(
        film_roll_id=roll_id,
        image_type=image_type,
        rel_path=rel_path,
        original_filename=original,
        frame_number=number,
        notes=notes or None,
        capture_date=captured,
    )
    db.add(img)
    roll = db.get(FilmRoll, roll_id) if roll_id else None
    # M5: read the file's own EXIF/XMP and fill what the client did not send. It
    # can also file an unassigned upload into the roll its `negpy:CaptureRoll`
    # names, which is what makes "drop a NegPy export on the archive" work.
    negpy_metadata.ingest_image(db, img, roll=roll)
    if img.film_roll_id and image_type == ImageType.scan:
        lifecycle.touch_scanned(roll or db.get(FilmRoll, img.film_roll_id))
    db.commit()
    return {"ok": True, "image": image_to_dict(img)}


# ---------------------------
# Contact sheet creation
# ---------------------------
@router.post(
    "/films/{film_id}/contact_sheet",
    response_model=schemas.ImageEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def create_contact_sheet(
    film_id: int, columns: int = 6, thumb_size: int = 300, db: Session = Depends(get_db)
):
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")
    columns = max(1, min(int(columns or 6), 20))
    thumb_size = max(32, min(int(thumb_size or 300), 1000))
    # R#24: the sheet is laid out in frame order, like everything else.
    scans: List[ImageAsset] = frames_in_order(
        db.query(ImageAsset).filter(
            ImageAsset.film_roll_id == film_id, ImageAsset.type == ImageType.scan
        )
    ).all()
    if len(scans) < 2:
        return error_response(
            "not_enough_images", "A contact sheet needs at least two scans in this roll."
        )

    # Prepare thumbnails
    thumbs: List[PILImage.Image] = []
    for i in scans:
        try:
            img = PILImage.open(_abs(i.path)).convert("RGB")
            img.thumbnail((thumb_size, thumb_size))
            # Center on square canvas
            canvas = PILImage.new("RGB", (thumb_size, thumb_size), color=(255, 255, 255))
            x = (thumb_size - img.size[0]) // 2
            y = (thumb_size - img.size[1]) // 2
            canvas.paste(img, (x, y))
            thumbs.append(canvas)
        except Exception:
            # Skip unreadable files
            continue

    if len(thumbs) < 2:
        return error_response(
            "not_enough_images", "At least two scans in this roll must be readable images."
        )

    rows = ceil(len(thumbs) / columns)
    sheet = PILImage.new("RGB", (columns * thumb_size, rows * thumb_size), color=(255, 255, 255))
    for idx, t in enumerate(thumbs):
        sheet.paste(t, ((idx % columns) * thumb_size, (idx // columns) * thumb_size))

    os.makedirs(os.path.join(uploads_root(), "contact_sheets"), exist_ok=True)
    rel_path = os.path.join("static", "uploads", "contact_sheets", f"{uuid4().hex}.jpg")
    sheet.save(_abs(rel_path), format="JPEG", quality=90)

    cs = _new_image(
        film_roll_id=film_id,
        image_type=ImageType.contact_sheet,
        rel_path=rel_path,
        original_filename=f"contact-sheet-{film_id}.jpg",
        notes="Generated contact sheet",
    )
    db.add(cs)
    db.commit()
    return {"ok": True, "image": image_to_dict(cs)}


# ---------------------------
# Bulk upload (multiple files or ZIP)
# ---------------------------
@router.post(
    "/films/{film_id}/images/bulk",
    response_model=schemas.ImageListEnvelope,
    responses={
        404: {"model": schemas.ErrorOut},
        413: {"model": schemas.ErrorOut},
        415: {"model": schemas.ErrorOut},
    },
)
def bulk_upload_images(
    film_id: int, files: List[UploadFile] = File(...), db: Session = Depends(get_db)
):
    """Many scans into one roll. Each file keeps its name and, when the name says so,
    gets its frame number from it (R#7, R#24)."""
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")
    images, sidecars = _pull_sidecars(files)
    ingest_on, create_gear = negpy_metadata.ingest_settings(db)
    created: List[ImageAsset] = []
    try:
        for file in images:
            rel_path, original = store_upload(file, "uploads/scans")
            img = _new_image(
                film_roll_id=film_id,
                image_type=ImageType.scan,
                rel_path=rel_path,
                original_filename=original,
            )
            db.add(img)
            created.append(img)
            # M5: a `.negpy` uploaded alongside its scan is stored next to the
            # managed file, so "edited in NegPy" survives the upload.
            payload = sidecars.get(os.path.splitext(original)[0].lower())
            stored_sidecar = store_sidecar_bytes(rel_path, payload) if payload else None
            negpy_metadata.ingest_image(
                db,
                img,
                roll=f,
                match_unassigned=False,
                enabled=ingest_on,
                create_gear=create_gear,
                sidecar_path=stored_sidecar,
            )
    except ApiError as exc:
        # Everything or nothing: a rejected file must not leave half a roll behind.
        db.rollback()
        for image in created:
            _remove_quietly(_abs(image.path))
            _remove_quietly(_abs(image.path) + negpy_sidecar.SUFFIX)
        return from_exc(exc)

    if created:
        lifecycle.touch_scanned(f)
    db.commit()
    return {"ok": True, "images": [image_to_dict(i) for i in created]}


@router.post(
    "/films/{film_id}/images/bulk_zip",
    response_model=schemas.ImageListEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 404: {"model": schemas.ErrorOut}},
)
def bulk_upload_zip(film_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return not_found("Roll")

    # Write uploaded zip to temp then extract
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "roll.zip")
        with open(zip_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmpdir)
        except Exception:
            return error_response("invalid_zip", "That file is not a readable ZIP archive.", 400, "file")

        os.makedirs(os.path.join(uploads_root(), "scans"), exist_ok=True)
        created: List[ImageAsset] = []
        skipped: List[str] = []
        ingest_on, create_gear = negpy_metadata.ingest_settings(db)

        # M5: a ZIP straight out of NegPy carries the `.negpy` sidecars too. Collect
        # them first, by stem, so every scan can be matched with its own.
        sidecar_files: Dict[str, str] = {}
        for root, _, names in os.walk(tmpdir):
            for name in names:
                if negpy_sidecar.is_sidecar_name(name):
                    sidecar_files[negpy_sidecar.image_stem(name).lower()] = os.path.join(root, name)

        # Walk extracted files in name order, so a roll keeps its scanner order even
        # when the filenames carry no frame number.
        for root, _, names in os.walk(tmpdir):
            for name in sorted(names):
                src = os.path.join(root, name)
                if src == zip_path or name.startswith(".") or negpy_sidecar.is_sidecar_name(name):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    skipped.append(name)
                    continue
                try:
                    with open(src, "rb") as probe:
                        if not _looks_like_image(probe.read(16)):
                            skipped.append(name)
                            continue
                    if os.path.getsize(src) > max_upload_bytes():
                        skipped.append(name)
                        continue
                    rel_path = os.path.join("static", "uploads", "scans", f"{uuid4().hex}{ext}")
                    shutil.copy(src, _abs(rel_path))
                    img = _new_image(
                        film_roll_id=film_id,
                        image_type=ImageType.scan,
                        rel_path=rel_path,
                        original_filename=name,
                    )
                    db.add(img)
                    created.append(img)
                    sidecar_src = sidecar_files.get(os.path.splitext(name)[0].lower())
                    stored_sidecar = None
                    if sidecar_src:
                        try:
                            with open(sidecar_src, "rb") as handle:
                                stored_sidecar = store_sidecar_bytes(
                                    rel_path, handle.read(negpy_sidecar.MAX_SIDECAR_BYTES + 1)
                                )
                        except OSError:
                            stored_sidecar = None
                    negpy_metadata.ingest_image(
                        db,
                        img,
                        roll=f,
                        match_unassigned=False,
                        enabled=ingest_on,
                        create_gear=create_gear,
                        sidecar_path=stored_sidecar,
                    )
                except OSError:
                    skipped.append(name)
                    continue

        if created:
            lifecycle.touch_scanned(f)
        db.commit()
        return {"ok": True, "images": [image_to_dict(i) for i in created]}


# ---------------------------
# Catalog: cameras
# ---------------------------


@router.get("/cameras", response_model=List[schemas.CameraOut])
def list_cameras(db: Session = Depends(get_db)):
    items = db.query(Camera).order_by(Camera.name.asc()).all()
    return [camera_to_dict(c) for c in items]


@router.get(
    "/cameras/{camera_id}",
    response_model=schemas.CameraOut,
    responses={404: {"model": schemas.ErrorOut}},
)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return not_found("Camera")
    return camera_to_dict(c)


def commit_unique(db: Session, what: str, name: Optional[str]):
    """Commit, turning the UNIQUE violation on ``name`` into a 409 instead of a 500."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            "duplicate_name", f"A {what} named “{name}” already exists.", 409, "name"
        ) from exc


def _delete_catalog_entry(db: Session, prefix: str, entry, force: bool):
    """Delete a camera/lens/film stock, refusing while rolls still use it (R#14)."""
    in_use = _rolls_using(db, prefix, entry)
    if in_use and not force:
        return error_response(
            "gear_in_use",
            f"{in_use} roll{'' if in_use == 1 else 's'} still use “{entry.name}”. "
            f"Delete it anyway with ?force=true; those rolls keep the name as plain text.",
            409,
        )
    db.delete(entry)
    db.commit()
    return {"ok": True, "rolls_affected": in_use}


@router.post(
    "/cameras",
    response_model=schemas.CameraEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def create_camera(body: schemas.CameraCreate, db: Session = Depends(get_db)):
    try:
        name = require_name(body.name)
        c = Camera(name=name, mount=body.mount, image_path=body.image_path, notes=body.notes)
        db.add(c)
        commit_unique(db, "camera", name)
    except ApiError as exc:
        return from_exc(exc)
    return {"ok": True, "camera": camera_to_dict(c)}


@router.put(
    "/cameras/{camera_id}",
    response_model=schemas.CameraEnvelope,
    responses={
        400: {"model": schemas.ErrorOut},
        404: {"model": schemas.ErrorOut},
        409: {"model": schemas.ErrorOut},
    },
)
def update_camera(camera_id: int, body: schemas.CameraUpdate, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return not_found("Camera")
    try:
        if body.given("name"):
            c.name = require_name(body.name)
        for key in ["mount", "image_path", "notes"]:
            if body.given(key):
                setattr(c, key, getattr(body, key) or None)
        commit_unique(db, "camera", c.name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "camera": camera_to_dict(c)}


@router.delete("/cameras/{camera_id}", responses={404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}})
def delete_camera(camera_id: int, force: bool = False, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return not_found("Camera")
    return _delete_catalog_entry(db, "camera", c, force)


@router.post(
    "/cameras/{camera_id}/image",
    response_model=schemas.CameraEnvelope,
    responses={404: {"model": schemas.ErrorOut}, 415: {"model": schemas.ErrorOut}},
)
def upload_camera_image(camera_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return not_found("Camera")
    try:
        rel_path, _ = store_upload(file, "catalog/cameras")
    except ApiError as exc:
        return from_exc(exc)
    c.image_path = rel_path
    db.commit()
    return {"ok": True, "camera": camera_to_dict(c)}


@router.post(
    "/cameras/{camera_id}/load",
    response_model=schemas.FilmRollEnvelope,
    responses={404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def load_film(camera_id: int, body: schemas.LoadFilm, db: Session = Depends(get_db)):
    """Create a roll in status ``loaded`` for this camera (M4 lifecycle).

    Refuses with 409 ``camera_occupied`` while another roll is still loaded or shot
    in the camera, unless ``force`` is set.
    """
    c = db.get(Camera, camera_id)
    if not c:
        return not_found("Camera")
    try:
        stock = None
        if body.film_stock_id not in (None, ""):
            stock = db.get(FilmStock, parse_int(body.film_stock_id, "film_stock_id", minimum=1))
            if stock is None:
                raise ApiError("unknown_film_stock", "That film stock does not exist.", 404, "film_stock_id")
        lens = None
        if body.lens_id not in (None, ""):
            lens = db.get(Lens, parse_int(body.lens_id, "lens_id", minimum=1))
            if lens is None:
                raise ApiError("unknown_lens", "That lens does not exist.", 404, "lens_id")
        today = datetime.utcnow().date()
        title = (body.title or "").strip() or f"{stock.name if stock else 'Roll'} in {c.name}, {today.isoformat()}"
        f = FilmRoll(
            title=title,
            notes=body.notes,
            format=body.format or (stock.format if stock else None),
            start_date=today,
            camera_id=c.id,
            camera=c.name,
            lens_id=lens.id if lens else None,
            lens=lens.name if lens else None,
            film_stock_id=stock.id if stock else None,
            film_type=stock.name if stock else None,
        )
        serials.assign(db, f, None)
        db.add(f)
        db.flush()
        lifecycle.load_into_camera(db, c, f, force=bool(body.force))
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(f)
    return {"ok": True, "film": film_to_dict(f)}


@router.get("/cameras/{camera_id}/loaded")
def loaded_roll(camera_id: int, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return not_found("Camera")
    roll = (
        db.query(FilmRoll)
        .filter(FilmRoll.loaded_camera_id == c.id, FilmRoll.status.in_(("loaded", "shot")))
        .order_by(FilmRoll.loaded_at.desc().nulls_last())
        .first()
    )
    return {"roll": film_to_dict(roll) if roll else None}


# ---------------------------
# Catalog: film stocks
# ---------------------------


@router.get("/filmstocks", response_model=List[schemas.FilmStockOut])
def list_filmstocks(db: Session = Depends(get_db)):
    items = db.query(FilmStock).order_by(FilmStock.name.asc()).all()
    return [filmstock_to_dict(s) for s in items]


@router.get(
    "/filmstocks/{stock_id}",
    response_model=schemas.FilmStockOut,
    responses={404: {"model": schemas.ErrorOut}},
)
def get_filmstock(stock_id: int, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return not_found("Film stock")
    return filmstock_to_dict(s)


def parse_kind(value) -> FilmKind:
    try:
        return FilmKind(value)
    except (ValueError, KeyError) as exc:
        valid = ", ".join(k.value for k in FilmKind)
        raise ApiError("invalid_kind", f"Kind must be one of: {valid}.", 400, "kind") from exc


@router.post(
    "/filmstocks",
    response_model=schemas.FilmStockEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def create_filmstock(body: schemas.FilmStockCreate, db: Session = Depends(get_db)):
    try:
        name = require_name(body.name)
        s = FilmStock(
            name=name,
            manufacturer=clean_name(body.manufacturer),
            format=parse_choice(body.format, "format", FILM_FORMATS),
            iso=parse_int(body.iso, "iso", minimum=1),
            kind=parse_kind(body.kind),
            expired=to_bool(body.expired),
            expiration_date=parse_date(body.expiration_date, "expiration_date"),
            image_path=body.image_path,
        )
        db.add(s)
        commit_unique(db, "film stock", name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "filmstock": filmstock_to_dict(s)}


@router.put(
    "/filmstocks/{stock_id}",
    response_model=schemas.FilmStockEnvelope,
    responses={
        400: {"model": schemas.ErrorOut},
        404: {"model": schemas.ErrorOut},
        409: {"model": schemas.ErrorOut},
    },
)
def update_filmstock(stock_id: int, body: schemas.FilmStockUpdate, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return not_found("Film stock")
    try:
        if body.given("kind") and body.kind:
            s.kind = parse_kind(body.kind)
        if body.given("name"):
            s.name = require_name(body.name)
        if body.given("manufacturer"):
            s.manufacturer = clean_name(body.manufacturer)
        if body.given("format"):
            s.format = parse_choice(body.format, "format", FILM_FORMATS)
        if body.given("iso"):
            s.iso = parse_int(body.iso, "iso", minimum=1)
        if body.given("image_path"):
            s.image_path = body.image_path
        if body.given("expired"):
            s.expired = to_bool(body.expired)
        if body.given("expiration_date"):
            s.expiration_date = parse_date(body.expiration_date, "expiration_date")
        commit_unique(db, "film stock", s.name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    # R#6: return the full object so the UI can chain an image upload
    return {"ok": True, "filmstock": filmstock_to_dict(s)}


@router.delete(
    "/filmstocks/{stock_id}",
    responses={404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def delete_filmstock(stock_id: int, force: bool = False, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return not_found("Film stock")
    return _delete_catalog_entry(db, "film_stock", s, force)


@router.post(
    "/filmstocks/{stock_id}/image",
    response_model=schemas.FilmStockEnvelope,
    responses={404: {"model": schemas.ErrorOut}, 415: {"model": schemas.ErrorOut}},
)
def upload_filmstock_image(stock_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return not_found("Film stock")
    try:
        rel_path, _ = store_upload(file, "catalog/films")
    except ApiError as exc:
        return from_exc(exc)
    s.image_path = rel_path
    db.commit()
    return {"ok": True, "filmstock": filmstock_to_dict(s)}


# ---------------------------
# Catalog: lenses
# ---------------------------


@router.get("/lenses", response_model=List[schemas.LensOut])
def list_lenses(db: Session = Depends(get_db)):
    items = db.query(Lens).order_by(Lens.name.asc()).all()
    return [lens_to_dict(l) for l in items]


@router.get(
    "/lenses/{lens_id}", response_model=schemas.LensOut, responses={404: {"model": schemas.ErrorOut}}
)
def get_lens(lens_id: int, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return not_found("Lens")
    return lens_to_dict(l)


@router.post(
    "/lenses",
    response_model=schemas.LensEnvelope,
    responses={400: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}},
)
def create_lens(body: schemas.LensCreate, db: Session = Depends(get_db)):
    try:
        name = require_name(body.name)
        l = Lens(name=name, mount=body.mount, image_path=body.image_path, notes=body.notes)
        db.add(l)
        commit_unique(db, "lens", name)
    except ApiError as exc:
        return from_exc(exc)
    return {"ok": True, "lens": lens_to_dict(l)}


@router.put(
    "/lenses/{lens_id}",
    response_model=schemas.LensEnvelope,
    responses={
        400: {"model": schemas.ErrorOut},
        404: {"model": schemas.ErrorOut},
        409: {"model": schemas.ErrorOut},
    },
)
def update_lens(lens_id: int, body: schemas.LensUpdate, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return not_found("Lens")
    try:
        if body.given("name"):
            l.name = require_name(body.name)
        for key in ["mount", "image_path", "notes"]:
            if body.given(key):
                setattr(l, key, getattr(body, key) or None)
        commit_unique(db, "lens", l.name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    # R#6: return the full object so the UI can chain an image upload
    return {"ok": True, "lens": lens_to_dict(l)}


@router.delete(
    "/lenses/{lens_id}", responses={404: {"model": schemas.ErrorOut}, 409: {"model": schemas.ErrorOut}}
)
def delete_lens(lens_id: int, force: bool = False, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return not_found("Lens")
    return _delete_catalog_entry(db, "lens", l, force)


@router.post(
    "/lenses/{lens_id}/image",
    response_model=schemas.LensEnvelope,
    responses={404: {"model": schemas.ErrorOut}, 415: {"model": schemas.ErrorOut}},
)
def upload_lens_image(lens_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return not_found("Lens")
    try:
        rel_path, _ = store_upload(file, "catalog/lenses")
    except ApiError as exc:
        return from_exc(exc)
    l.image_path = rel_path
    db.commit()
    return {"ok": True, "lens": lens_to_dict(l)}


# ---------------------------
# Maintenance
# ---------------------------


@router.post("/seed", response_model=schemas.SeedResult)
def seed(db: Session = Depends(get_db)):
    """Put the starter cameras and film stocks back (R#11).

    Startup only seeds while a catalog table is empty, so this endpoint is the way
    to ask for them again. Rows that are already there are left alone.
    """
    return {"ok": True, "added": seed_catalog(db, force=True)}


@router.post("/maintenance/sweep_orphans", response_model=schemas.SweepResult)
def sweep_orphans(
    apply: bool = Query(False, description="Actually delete the orphan files. Default: dry run."),
    db: Session = Depends(get_db),
):
    """Find files with no record and records with no file (R#9).

    A dry run by default: it reports what it would delete. ``?apply=true`` deletes the
    orphan **files**; the records whose file is missing are only reported, because
    deleting them would throw away the metadata that is the point of the archive.
    """
    known = set()
    for (path,) in db.query(ImageAsset.path).all():
        if path:
            absolute = os.path.abspath(_abs(path))
            known.add(absolute)
            # M5: a `.negpy` sidecar belongs to the frame beside it, not to nobody.
            known.add(absolute + negpy_sidecar.SUFFIX)

    orphans: List[str] = []
    data_root = os.path.abspath(str(paths.data_dir()))
    for folder, _, names in os.walk(uploads_root()):
        for name in names:
            if name.startswith("."):
                continue
            absolute = os.path.abspath(os.path.join(folder, name))
            if absolute not in known:
                # Report the *stored* form (`static/uploads/...`), so an orphan
                # reads the same as the `path` of any frame beside it — DATA_DIR
                # may be anywhere, and a path relative to the process's working
                # directory would be meaningless to whoever reads the report.
                orphans.append(paths.public_path(os.path.relpath(absolute, data_root)))

    missing = [
        {
            "image_id": image.id,
            "path": image.path,
            "film_roll_id": image.film_roll_id,
            "original_filename": image.original_filename,
        }
        for image in db.query(ImageAsset).all()
        if (image.storage_mode or "managed") == "managed" and not os.path.exists(_abs(image.path))
    ]

    deleted = 0
    reclaimed = 0
    if apply:
        for relative in orphans:
            absolute = _abs(relative)
            try:
                size = os.path.getsize(absolute)
                os.remove(absolute)
            except OSError:
                continue  # gone or unreadable: nothing reclaimed, nothing to report
            deleted += 1
            reclaimed += size

    return {
        "ok": True,
        "applied": bool(apply),
        "orphan_files": sorted(orphans),
        "missing_files": missing,
        "deleted_files": deleted,
        "bytes_reclaimed": reclaimed,
    }
