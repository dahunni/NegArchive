import glob
import os
import shutil
import tempfile
import zipfile
from datetime import date
from typing import Optional, List, Dict, Iterable, Tuple
from uuid import uuid4
from math import ceil
from PIL import Image as PILImage
from PIL import ImageFile as PILImageFile

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
import io
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import (
    ApiError,
    error_response,
    from_exc,
    parse_date,
    parse_int,
    read_json,
    require_text,
)
from ..models import FilmRoll, ImageAsset, Camera, FilmStock, Lens, ImageType, FilmKind

router = APIRouter(prefix="/api", tags=["api"])

# Disk thumbnail cache for /preview (pulled forward from roadmap M3 because the new
# roll list and frame grid request a preview per frame). Git-ignored.
CACHE_DIR = os.path.join("static", "cache")


COVER_STRIP = 4  # thumbnails shown per row in the roll list


def film_to_dict(f: FilmRoll, image_count: Optional[int] = None, cover_image_ids: Optional[List[int]] = None):
    return {
        "id": f.id,
        "title": f.title,
        "camera": f.camera,
        "lens": f.lens,
        "film_type": f.film_type,
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
    }


def roll_summaries(db: Session, film_ids: Optional[Iterable[int]] = None) -> Dict[int, Tuple[int, List[int]]]:
    """``{film_roll_id: (scan count, first few image ids)}`` in two cheap queries.

    Two queries for the whole list, not two per roll: the roll list renders a frame
    count and a thumbnail strip without fetching anybody's images.
    """
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


def image_to_dict(i: ImageAsset):
    # Provide a simple public URL under /static for the frontend
    filename = i.path.split("/")[-1]
    base = "uploads/contact_sheets" if i.type == ImageType.contact_sheet else "uploads/scans"
    public_url = f"/static/{base}/{filename}"
    return {
        "id": i.id,
        "film_roll_id": i.film_roll_id,
        "type": i.type.value,
        "path": i.path,
        "url": public_url,
        "frame_number": i.frame_number,
        "notes": i.notes,
        "capture_date": i.capture_date.isoformat() if getattr(i, "capture_date", None) else None,
        "created_at": i.created_at.isoformat(),
    }


def catalog_url(path: Optional[str]):
    if not path:
        return None
    # Ensure leading slash for valid URL resolution in Next/Image
    return path if path.startswith("/") else f"/{path}"


def camera_to_dict(c: Camera):
    return {
        "id": c.id,
        "name": c.name,
        "mount": c.mount,
        "image_path": c.image_path,
        "url": catalog_url(c.image_path),
        "notes": c.notes,
    }


def lens_to_dict(l: Lens):
    return {
        "id": l.id,
        "name": l.name,
        "mount": l.mount,
        "image_path": l.image_path,
        "url": catalog_url(l.image_path),
        "notes": l.notes,
    }


def filmstock_to_dict(s: FilmStock):
    return {
        "id": s.id,
        "name": s.name,
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


@router.get("/films")
def list_films(db: Session = Depends(get_db)):
    films = db.query(FilmRoll).order_by(FilmRoll.created_at.desc()).all()
    summaries = roll_summaries(db)
    return [film_to_dict(f, *summaries.get(f.id, (0, []))) for f in films]


@router.get("/films/{film_id}")
def get_film(film_id: int, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        # Unchanged on purpose: turning every "not found" into a real 404 is R#17 (M2).
        return {"error": "not_found"}
    # Separate scans and contact sheets
    scans = (
        db.query(ImageAsset)
        .filter(ImageAsset.film_roll_id == f.id, ImageAsset.type == ImageType.scan)
        # The frame grid shows them in this order, and it matches cover_image_id.
        .order_by(ImageAsset.frame_number.asc().nulls_last(), ImageAsset.id.asc())
        .all()
    )
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


def _check_date_order(start: Optional[date], end: Optional[date]) -> None:
    if start and end and end < start:
        raise ApiError("invalid_date_range", "The end date is before the start date.")


@router.post("/films")
async def create_film(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await read_json(request)
        title = require_text(payload.get("title"), "title")
        start = parse_date(payload.get("start_date"), "start_date")
        end = parse_date(payload.get("end_date"), "end_date")
        _check_date_order(start, end)
    except ApiError as exc:
        return from_exc(exc)
    f = FilmRoll(
        title=title,
        camera=clean_name(payload.get("camera")),
        lens=clean_name(payload.get("lens")),
        film_type=clean_name(payload.get("film_type")),
        notes=payload.get("notes"),
        building=payload.get("building"),
        folder=payload.get("folder"),
        archive_serial=payload.get("archive_serial"),
        start_date=start,
        end_date=end,
    )
    db.add(f)
    db.commit()
    return {"ok": True, "film": film_to_dict(f)}


@router.put("/films/{film_id}")
async def update_film(film_id: int, request: Request, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}
    try:
        payload = await read_json(request)
        if "title" in payload:
            f.title = require_text(payload.get("title"), "title")
        start = parse_date(payload["start_date"], "start_date") if "start_date" in payload else f.start_date
        end = parse_date(payload["end_date"], "end_date") if "end_date" in payload else f.end_date
        _check_date_order(start, end)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    for key in ["camera", "lens", "film_type", "notes", "building", "folder", "archive_serial"]:
        if key in payload:
            setattr(f, key, clean_name(payload[key]))
    f.start_date = start
    f.end_date = end
    db.commit()
    count, strip = roll_summaries(db, [f.id]).get(f.id, (0, []))
    return {"ok": True, "film": film_to_dict(f, count, strip)}


@router.delete("/films/{film_id}")
def delete_film(film_id: int, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}
    # Optionally also delete associated images records (not files)
    db.query(ImageAsset).filter(ImageAsset.film_roll_id == f.id).delete()
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.get("/images")
def list_images(
    film_id: Optional[int] = None,
    type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(ImageAsset)
    if film_id:
        q = q.filter(ImageAsset.film_roll_id == film_id)
    if type:
        t = type.lower().strip()
        if t == "scan":
            q = q.filter(ImageAsset.type == ImageType.scan)
        elif t in {"contact", "contact_sheet", "contact-sheet"}:
            q = q.filter(ImageAsset.type == ImageType.contact_sheet)
        # else: ignore invalid type filter, return all
    items = q.order_by(ImageAsset.id.asc()).all()
    return [image_to_dict(i) for i in items]


@router.get("/images/{image_id}")
def get_image(image_id: int, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    return image_to_dict(i)


def _cache_file(image_id: int, width: int, mtime_ns: int) -> str:
    """Cache file for one rendered preview, keyed by image id + width + source mtime.

    A re-scan that replaces the file on disk changes the mtime and therefore the key,
    so a stale thumbnail can never be served.
    """
    return os.path.join(CACHE_DIR, f"{image_id}_{width}_{mtime_ns}.jpg")


def _write_cache(cache_path: str, payload: bytes) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{cache_path}.{uuid4().hex}.tmp"
        with open(tmp, "wb") as out:
            out.write(payload)
        os.replace(tmp, cache_path)  # atomic: readers never see a half-written file
        # Drop older renderings of the same image at the same width.
        stem = os.path.basename(cache_path).rsplit("_", 1)[0]
        for stale in glob.glob(os.path.join(CACHE_DIR, f"{stem}_*.jpg")):
            if os.path.abspath(stale) != os.path.abspath(cache_path):
                try:
                    os.remove(stale)
                except OSError:
                    pass
    except OSError:
        # A read-only or full disk must not break the preview itself.
        pass


def drop_cached_previews(image_id: int) -> None:
    for stale in glob.glob(os.path.join(CACHE_DIR, f"{image_id}_*.jpg")):
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


@router.get("/images/{image_id}/preview")
def get_image_preview(image_id: int, width: int = 1200, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    # Resolve absolute path
    path = i.path
    abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
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
        if img.mode not in ("RGB", "RGBA"):
            try:
                img = img.convert("RGB")
            except Exception:
                pass
        # If still not RGB/RGBA, try a generic conversion
        if img.mode != "RGB":
            try:
                img = img.convert("RGB")
            except Exception:
                raise
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
            # Handle bit depth and channels
            # Convert 16-bit to 8-bit for JPEG encoding
            if cv_img.dtype == np.uint16:
                cv_img = cv2.convertScaleAbs(cv_img, alpha=(255.0/65535.0))
            elif cv_img.dtype == np.float32 or cv_img.dtype == np.float64:
                # Normalize float images to 0-255
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
            elif cv_img.shape[2] == 3:
                pass  # already BGR
            else:
                # Unusual channel count: reduce to 3 via first three channels
                cv_img = cv_img[:, :, :3]

            # Resize preserving aspect
            if width and cv_img.shape[1] > width:
                scale = width / float(cv_img.shape[1])
                new_h = int(cv_img.shape[0] * scale)
                cv_img = cv2.resize(cv_img, (width, new_h), interpolation=cv2.INTER_AREA)

            # Encode JPEG
            ok, enc = cv2.imencode(".jpg", cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                raise ValueError("encode failed")
            data = enc.tobytes()
            if cache_path:
                _write_cache(cache_path, data)
            return StreamingResponse(
                io.BytesIO(data),
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Preview-Cache": "miss"},
            )
        except Exception:
            # Final fallback: serve original if browser-friendly
            if ext in {".jpg", ".jpeg", ".png"} and os.path.exists(abs_path):
                media_type = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
                return FileResponse(abs_path, media_type=media_type)
            return {"error": "unreadable_image"}


@router.get("/images/{image_id}/download")
def download_image(image_id: int, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    path = i.path
    abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    if not os.path.exists(abs_path):
        return {"error": "not_found"}
    filename = os.path.basename(abs_path)
    # Let FileResponse set headers; ensure attachment disposition for download
    headers = {"Content-Disposition": f"attachment; filename=\"{filename}\""}
    # Media type is not critical for download; use octet-stream for generic binary
    return FileResponse(abs_path, media_type="application/octet-stream", headers=headers)


@router.post("/images")
async def create_image(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    i = ImageAsset(
        film_roll_id=payload.get("film_roll_id"),
        type=ImageType(payload.get("type", "scan")),
        path=payload.get("path"),
        frame_number=payload.get("frame_number"),
        notes=payload.get("notes"),
        capture_date=date.fromisoformat(payload["capture_date"]) if payload.get("capture_date") else None,
    )
    db.add(i)
    db.commit()
    return {"ok": True, "image": image_to_dict(i)}


@router.put("/images/{image_id}")
async def update_image(image_id: int, request: Request, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    try:
        payload = await read_json(request)
        if "film_roll_id" in payload:
            # R#12: an explicit null unassigns the image from its roll
            raw = payload["film_roll_id"]
            if raw in (None, "", "none"):
                i.film_roll_id = None
            else:
                i.film_roll_id = _require_roll(db, parse_int(raw, "film_roll_id"))
        if "type" in payload and payload["type"]:
            try:
                i.type = ImageType(payload["type"])
            except ValueError:
                raise ApiError("invalid_type", "Type must be 'scan' or 'contact_sheet'.")
        if "frame_number" in payload:
            i.frame_number = parse_int(payload["frame_number"], "frame_number", minimum=0)
        if "notes" in payload:
            i.notes = payload["notes"] or None
        if "capture_date" in payload:
            i.capture_date = parse_date(payload["capture_date"], "capture_date")
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.commit()
    return {"ok": True, "image": image_to_dict(i)}


def _require_roll(db: Session, film_roll_id: Optional[int]) -> Optional[int]:
    if film_roll_id is None:
        return None
    if not db.get(FilmRoll, film_roll_id):
        raise ApiError("unknown_roll", "That roll does not exist.", 404)
    return film_roll_id


def _delete_asset_file(image: ImageAsset) -> None:
    if not image.path:
        return
    try:
        target_path = image.path if os.path.isabs(image.path) else os.path.join(os.getcwd(), image.path)
        if os.path.exists(target_path):
            os.remove(target_path)
    except OSError:
        pass


@router.delete("/images/{image_id}")
def delete_image(image_id: int, delete_file: bool = False, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    # Optionally delete file from disk
    if delete_file:
        _delete_asset_file(i)
    drop_cached_previews(i.id)
    db.delete(i)
    db.commit()
    return {"ok": True}


# ---------------------------
# Bulk frame operations (M1: multi-select in the roll workspace)
# ---------------------------
def _require_ids(payload: dict) -> List[int]:
    raw = payload.get("ids")
    if not isinstance(raw, list) or not raw:
        raise ApiError("invalid_ids", "Select at least one frame.")
    ids: List[int] = []
    for value in raw:
        parsed = parse_int(value, "id", minimum=1)
        if parsed is None:
            raise ApiError("invalid_ids", "Frame ids must be whole numbers.")
        ids.append(parsed)
    return ids


@router.post("/images/bulk_update")
async def bulk_update_images(request: Request, db: Session = Depends(get_db)):
    """Apply a partial patch to many frames at once.

    Body: ``{"ids": [1, 2], "film_roll_id": 3|null, "capture_date": "2024-07-01"|null,
    "frame_number": 7|null}``. Only the keys present are written.
    """
    try:
        payload = await read_json(request)
        ids = _require_ids(payload)
        fields = {}
        if "film_roll_id" in payload:
            raw = payload["film_roll_id"]
            fields["film_roll_id"] = (
                None if raw in (None, "", "none") else _require_roll(db, parse_int(raw, "film_roll_id"))
            )
        if "capture_date" in payload:
            fields["capture_date"] = parse_date(payload["capture_date"], "capture_date")
        if "frame_number" in payload:
            fields["frame_number"] = parse_int(payload["frame_number"], "frame_number", minimum=0)
        if not fields:
            raise ApiError("nothing_to_update", "No fields to update were supplied.")
    except ApiError as exc:
        return from_exc(exc)

    images = db.query(ImageAsset).filter(ImageAsset.id.in_(ids)).all()
    if not images:
        return error_response("not_found", "None of those frames exist.", 404)
    for image in images:
        for key, value in fields.items():
            setattr(image, key, value)
    db.commit()
    return {"ok": True, "updated": len(images), "images": [image_to_dict(i) for i in images]}


@router.post("/images/bulk_delete")
async def bulk_delete_images(request: Request, db: Session = Depends(get_db)):
    """Body: ``{"ids": [1, 2], "delete_file": false}``."""
    try:
        payload = await read_json(request)
        ids = _require_ids(payload)
    except ApiError as exc:
        return from_exc(exc)
    delete_file = bool(payload.get("delete_file"))

    images = db.query(ImageAsset).filter(ImageAsset.id.in_(ids)).all()
    for image in images:
        if delete_file:
            _delete_asset_file(image)
        drop_cached_previews(image.id)
        db.delete(image)
    db.commit()
    return {"ok": True, "deleted": len(images)}


@router.post("/images/upload")
async def upload_image(
    file: UploadFile = File(...),
    type: str = Form(...),
    film_roll_id: Optional[int] = Form(None),
    frame_number: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    capture_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    type = type.lower()
    if type not in {"scan", "contact_sheet"}:
        return {"error": "invalid_type"}
    subdir = "uploads/scans" if type == "scan" else "uploads/contact_sheets"
    os.makedirs(os.path.join("static", subdir), exist_ok=True)
    # Preserve extension, generate unique name
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid4().hex}{ext}"
    rel_path = os.path.join("static", subdir, unique_name)
    abs_path = os.path.join(os.getcwd(), rel_path)
    with open(abs_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    img = ImageAsset(
        film_roll_id=film_roll_id,
        type=ImageType(type),
        path=rel_path,
        frame_number=int(frame_number) if frame_number is not None else None,
        notes=notes or None,
        capture_date=date.fromisoformat(capture_date) if capture_date else None,
    )
    db.add(img)
    db.commit()
    return {"ok": True, "image": image_to_dict(img)}


# ---------------------------
# Contact sheet creation
# ---------------------------
@router.post("/films/{film_id}/contact_sheet")
def create_contact_sheet(film_id: int, columns: int = 6, thumb_size: int = 300, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}
    scans: List[ImageAsset] = (
        db.query(ImageAsset)
        .filter(ImageAsset.film_roll_id == film_id, ImageAsset.type == ImageType.scan)
        .order_by(ImageAsset.frame_number.asc().nulls_last(), ImageAsset.id.asc())
        .all()
    )
    if len(scans) < 2:
        return error_response(
            "not_enough_images",
            "A contact sheet needs at least two scans in this roll.",
        )

    # Prepare thumbnails
    thumbs: List[PILImage.Image] = []
    for i in scans:
        path = i.path
        abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
        try:
            img = PILImage.open(abs_path).convert("RGB")
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
            "not_enough_images",
            "At least two scans in this roll must be readable images.",
        )

    rows = ceil(len(thumbs) / columns)
    sheet_w = columns * thumb_size
    sheet_h = rows * thumb_size
    sheet = PILImage.new("RGB", (sheet_w, sheet_h), color=(255, 255, 255))

    for idx, t in enumerate(thumbs):
        r = idx // columns
        c = idx % columns
        sheet.paste(t, (c * thumb_size, r * thumb_size))

    # Save to contact sheets dir
    os.makedirs(os.path.join("static", "uploads", "contact_sheets"), exist_ok=True)
    filename = f"{uuid4().hex}.jpg"
    rel_path = os.path.join("static", "uploads", "contact_sheets", filename)
    abs_path = os.path.join(os.getcwd(), rel_path)
    sheet.save(abs_path, format="JPEG", quality=90)

    cs = ImageAsset(
        film_roll_id=film_id,
        type=ImageType.contact_sheet,
        path=rel_path,
        frame_number=None,
        notes="Generated contact sheet",
        capture_date=None,
    )
    db.add(cs)
    db.commit()
    return {"ok": True, "image": image_to_dict(cs)}


# ---------------------------
# Bulk upload (multiple files or ZIP)
# ---------------------------
@router.post("/films/{film_id}/images/bulk")
async def bulk_upload_images(film_id: int, files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}
    os.makedirs(os.path.join("static", "uploads", "scans"), exist_ok=True)
    created: List[ImageAsset] = []

    for file in files:
        try:
            ext = os.path.splitext(file.filename)[1] or ".jpg"
            unique_name = f"{uuid4().hex}{ext}"
            rel_path = os.path.join("static", "uploads", "scans", unique_name)
            abs_path = os.path.join(os.getcwd(), rel_path)
            with open(abs_path, "wb") as out:
                shutil.copyfileobj(file.file, out)
            img = ImageAsset(
                film_roll_id=film_id,
                type=ImageType.scan,
                path=rel_path,
                frame_number=None,
                notes=None,
                capture_date=None,
            )
            db.add(img)
            created.append(img)
        except Exception:
            continue

    db.commit()
    return {"ok": True, "images": [image_to_dict(i) for i in created]}


@router.post("/films/{film_id}/images/bulk_zip")
async def bulk_upload_zip(film_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}

    # Write uploaded zip to temp then extract
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "roll.zip")
        with open(zip_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmpdir)
        except Exception:
            return {"error": "invalid_zip"}

        os.makedirs(os.path.join("static", "uploads", "scans"), exist_ok=True)
        created: List[ImageAsset] = []

        # Walk extracted files and import images
        for root, _, files in os.walk(tmpdir):
            for name in files:
                src = os.path.join(root, name)
                # Skip the zip file itself
                if src == zip_path:
                    continue
                # Basic image filter by extension
                ext = os.path.splitext(name)[1].lower()
                if ext not in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
                    continue
                try:
                    unique_name = f"{uuid4().hex}{ext}"
                    rel_path = os.path.join("static", "uploads", "scans", unique_name)
                    abs_path = os.path.join(os.getcwd(), rel_path)
                    shutil.copy(src, abs_path)
                    img = ImageAsset(
                        film_roll_id=film_id,
                        type=ImageType.scan,
                        path=rel_path,
                        frame_number=None,
                        notes=None,
                        capture_date=None,
                    )
                    db.add(img)
                    created.append(img)
                except Exception:
                    continue

        db.commit()
        return {"ok": True, "images": [image_to_dict(i) for i in created]}


@router.get("/cameras")
def list_cameras(db: Session = Depends(get_db)):
    items = db.query(Camera).order_by(Camera.name.asc()).all()
    return [camera_to_dict(c) for c in items]


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return {"error": "not_found"}
    return camera_to_dict(c)


def commit_unique(db: Session, what: str, name: Optional[str]):
    """Commit, turning the UNIQUE violation on ``name`` into a 409 instead of a 500."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError("duplicate_name", f"A {what} named “{name}” already exists.", 409)


@router.post("/cameras")
async def create_camera(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await read_json(request)
        name = require_text(payload.get("name"), "name")
        c = Camera(name=name, mount=payload.get("mount"), image_path=payload.get("image_path"), notes=payload.get("notes"))
        db.add(c)
        commit_unique(db, "camera", name)
    except ApiError as exc:
        return from_exc(exc)
    return {"ok": True, "camera": camera_to_dict(c)}


@router.put("/cameras/{camera_id}")
async def update_camera(camera_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return {"error": "not_found"}
    try:
        payload = await read_json(request)
        if "name" in payload:
            c.name = require_text(payload.get("name"), "name")
        for key in ["mount", "image_path", "notes"]:
            if key in payload:
                setattr(c, key, payload[key] or None)
        commit_unique(db, "camera", c.name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "camera": camera_to_dict(c)}


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return {"error": "not_found"}
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/cameras/{camera_id}/image")
async def upload_camera_image(camera_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return {"error": "not_found"}
    os.makedirs(os.path.join("static", "catalog", "cameras"), exist_ok=True)
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid4().hex}{ext}"
    rel_path = os.path.join("static", "catalog", "cameras", unique_name)
    abs_path = os.path.join(os.getcwd(), rel_path)
    with open(abs_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    c.image_path = rel_path
    db.commit()
    return {"ok": True, "camera": camera_to_dict(c)}


@router.get("/filmstocks")
def list_filmstocks(db: Session = Depends(get_db)):
    items = db.query(FilmStock).order_by(FilmStock.name.asc()).all()
    return [filmstock_to_dict(s) for s in items]


@router.get("/filmstocks/{stock_id}")
def get_filmstock(stock_id: int, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return {"error": "not_found"}
    return filmstock_to_dict(s)


def parse_kind(value) -> FilmKind:
    try:
        return FilmKind(value)
    except (ValueError, KeyError):
        valid = ", ".join(k.value for k in FilmKind)
        raise ApiError("invalid_kind", f"Kind must be one of: {valid}.")


@router.post("/filmstocks")
async def create_filmstock(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await read_json(request)
        name = require_text(payload.get("name"), "name")
        s = FilmStock(
            name=name,
            iso=parse_int(payload.get("iso"), "iso", minimum=1),
            kind=parse_kind(payload.get("kind")),
            expired=to_bool(payload.get("expired")),
            expiration_date=parse_date(payload.get("expiration_date"), "expiration_date"),
            image_path=payload.get("image_path"),
        )
        db.add(s)
        commit_unique(db, "film stock", name)
    except ApiError as exc:
        return from_exc(exc)
    return {"ok": True, "filmstock": filmstock_to_dict(s)}


@router.put("/filmstocks/{stock_id}")
async def update_filmstock(stock_id: int, request: Request, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return {"error": "not_found"}
    try:
        payload = await read_json(request)
        if "kind" in payload and payload["kind"]:
            s.kind = parse_kind(payload["kind"])
        if "name" in payload:
            s.name = require_text(payload.get("name"), "name")
        if "iso" in payload:
            s.iso = parse_int(payload["iso"], "iso", minimum=1)
        if "image_path" in payload:
            s.image_path = payload["image_path"]
        if "expired" in payload:
            s.expired = to_bool(payload["expired"])
        if "expiration_date" in payload:
            s.expiration_date = parse_date(payload["expiration_date"], "expiration_date")
        commit_unique(db, "film stock", s.name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    # R#6: return the full object so the UI can chain an image upload
    return {"ok": True, "filmstock": filmstock_to_dict(s)}


@router.delete("/filmstocks/{stock_id}")
def delete_filmstock(stock_id: int, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return {"error": "not_found"}
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/filmstocks/{stock_id}/image")
async def upload_filmstock_image(stock_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return {"error": "not_found"}
    os.makedirs(os.path.join("static", "catalog", "films"), exist_ok=True)
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid4().hex}{ext}"
    rel_path = os.path.join("static", "catalog", "films", unique_name)
    abs_path = os.path.join(os.getcwd(), rel_path)
    with open(abs_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    s.image_path = rel_path
    db.commit()
    return {"ok": True, "filmstock": filmstock_to_dict(s)}


@router.get("/lenses")
def list_lenses(db: Session = Depends(get_db)):
    items = db.query(Lens).order_by(Lens.name.asc()).all()
    return [lens_to_dict(l) for l in items]


@router.get("/lenses/{lens_id}")
def get_lens(lens_id: int, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return {"error": "not_found"}
    return lens_to_dict(l)


@router.post("/lenses")
async def create_lens(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await read_json(request)
        name = require_text(payload.get("name"), "name")
        l = Lens(name=name, mount=payload.get("mount"), image_path=payload.get("image_path"), notes=payload.get("notes"))
        db.add(l)
        commit_unique(db, "lens", name)
    except ApiError as exc:
        return from_exc(exc)
    return {"ok": True, "lens": lens_to_dict(l)}


@router.put("/lenses/{lens_id}")
async def update_lens(lens_id: int, request: Request, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return {"error": "not_found"}
    try:
        payload = await read_json(request)
        if "name" in payload:
            l.name = require_text(payload.get("name"), "name")
        for key in ["mount", "image_path", "notes"]:
            if key in payload:
                setattr(l, key, payload[key] or None)
        commit_unique(db, "lens", l.name)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    # R#6: return the full object so the UI can chain an image upload
    return {"ok": True, "lens": lens_to_dict(l)}


@router.delete("/lenses/{lens_id}")
def delete_lens(lens_id: int, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return {"error": "not_found"}
    db.delete(l)
    db.commit()
    return {"ok": True}


@router.post("/lenses/{lens_id}/image")
async def upload_lens_image(lens_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return {"error": "not_found"}
    os.makedirs(os.path.join("static", "catalog", "lenses"), exist_ok=True)
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid4().hex}{ext}"
    rel_path = os.path.join("static", "catalog", "lenses", unique_name)
    abs_path = os.path.join(os.getcwd(), rel_path)
    with open(abs_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    l.image_path = rel_path
    db.commit()
    return {"ok": True, "lens": lens_to_dict(l)}