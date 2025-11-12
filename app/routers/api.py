import os
import shutil
import tempfile
import zipfile
from datetime import date
from typing import Optional, List
from uuid import uuid4
from math import ceil
from PIL import Image as PILImage
from PIL import ImageFile as PILImageFile

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
import io
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FilmRoll, ImageAsset, Camera, FilmStock, Lens, ImageType, FilmKind

router = APIRouter(prefix="/api", tags=["api"])


def film_to_dict(f: FilmRoll):
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
    }


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


@router.get("/films")
def list_films(db: Session = Depends(get_db)):
    films = db.query(FilmRoll).order_by(FilmRoll.created_at.desc()).all()
    return [film_to_dict(f) for f in films]


@router.get("/films/{film_id}")
def get_film(film_id: int, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}
    images = db.query(ImageAsset).filter(ImageAsset.film_roll_id == f.id).order_by(ImageAsset.id.asc()).all()
    return {
        "film": film_to_dict(f),
        "images": [image_to_dict(i) for i in images],
    }


@router.post("/films")
async def create_film(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    f = FilmRoll(
        title=payload.get("title") or "Untitled",
        camera=payload.get("camera"),
        lens=payload.get("lens"),
        film_type=payload.get("film_type"),
        notes=payload.get("notes"),
        building=payload.get("building"),
        folder=payload.get("folder"),
        archive_serial=payload.get("archive_serial"),
        start_date=date.fromisoformat(payload["start_date"]) if payload.get("start_date") else None,
        end_date=date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
    )
    db.add(f)
    db.commit()
    return {"ok": True, "film": film_to_dict(f)}


@router.put("/films/{film_id}")
async def update_film(film_id: int, request: Request, db: Session = Depends(get_db)):
    f = db.get(FilmRoll, film_id)
    if not f:
        return {"error": "not_found"}
    payload = await request.json()
    for key in ["title", "camera", "lens", "film_type", "notes", "building", "folder", "archive_serial"]:
        if key in payload:
            setattr(f, key, payload[key] or None)
    if "start_date" in payload:
        f.start_date = date.fromisoformat(payload["start_date"]) if payload["start_date"] else None
    if "end_date" in payload:
        f.end_date = date.fromisoformat(payload["end_date"]) if payload["end_date"] else None
    db.commit()
    return {"ok": True, "film": film_to_dict(f)}


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
def list_images(film_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(ImageAsset)
    if film_id:
        q = q.filter(ImageAsset.film_roll_id == film_id)
    items = q.order_by(ImageAsset.id.asc()).all()
    return [image_to_dict(i) for i in items]


@router.get("/images/{image_id}")
def get_image(image_id: int, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    return image_to_dict(i)


@router.get("/images/{image_id}/preview")
def get_image_preview(image_id: int, width: int = 1200, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    # Resolve absolute path
    path = i.path
    abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    ext = os.path.splitext(abs_path)[1].lower()
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
            new_h = int(img.height * (width / img.width))
            img = img.resize((width, new_h), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/jpeg")
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
            buf = io.BytesIO(enc.tobytes())
            buf.seek(0)
            return StreamingResponse(buf, media_type="image/jpeg")
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
    payload = await request.json()
    if "film_roll_id" in payload and payload["film_roll_id"]:
        i.film_roll_id = int(payload["film_roll_id"])
    if "type" in payload and payload["type"]:
        i.type = ImageType(payload["type"])  # type validation
    if "frame_number" in payload:
        i.frame_number = int(payload["frame_number"]) if payload["frame_number"] is not None else None
    if "notes" in payload:
        i.notes = payload["notes"] or None
    if "capture_date" in payload:
        i.capture_date = date.fromisoformat(payload["capture_date"]) if payload["capture_date"] else None
    db.commit()
    return {"ok": True, "image": image_to_dict(i)}


@router.delete("/images/{image_id}")
def delete_image(image_id: int, delete_file: bool = False, db: Session = Depends(get_db)):
    i = db.get(ImageAsset, image_id)
    if not i:
        return {"error": "not_found"}
    # Optionally delete file from disk
    if delete_file and i.path:
        try:
            if os.path.isabs(i.path):
                target_path = i.path
            else:
                target_path = os.path.join(os.getcwd(), i.path)
            if os.path.exists(target_path):
                os.remove(target_path)
        except Exception:
            pass
    db.delete(i)
    db.commit()
    return {"ok": True}


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
        return {"error": "not_enough_images"}

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
        return {"error": "not_enough_images"}

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
    return [{"id": c.id, "name": c.name, "mount": c.mount, "image_path": c.image_path, "url": catalog_url(c.image_path), "notes": c.notes} for c in items]


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return {"error": "not_found"}
    return {"id": c.id, "name": c.name, "mount": c.mount, "image_path": c.image_path, "url": catalog_url(c.image_path), "notes": c.notes}


@router.post("/cameras")
async def create_camera(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    c = Camera(name=payload.get("name"), mount=payload.get("mount"), image_path=payload.get("image_path"), notes=payload.get("notes"))
    db.add(c)
    db.commit()
    return {"ok": True, "camera": {"id": c.id, "name": c.name, "mount": c.mount, "image_path": c.image_path, "url": catalog_url(c.image_path), "notes": c.notes}}


@router.put("/cameras/{camera_id}")
async def update_camera(camera_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(Camera, camera_id)
    if not c:
        return {"error": "not_found"}
    payload = await request.json()
    for key in ["name", "mount", "image_path", "notes"]:
        if key in payload:
            setattr(c, key, payload[key] or None)
    db.commit()
    return {"ok": True, "camera": {"id": c.id, "name": c.name, "mount": c.mount, "image_path": c.image_path, "url": catalog_url(c.image_path), "notes": c.notes}}


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
    return {"ok": True, "camera": {"id": c.id, "name": c.name, "mount": c.mount, "image_path": c.image_path, "url": catalog_url(c.image_path), "notes": c.notes}}


@router.get("/filmstocks")
def list_filmstocks(db: Session = Depends(get_db)):
    items = db.query(FilmStock).order_by(FilmStock.name.asc()).all()
    return [{
        "id": s.id,
        "name": s.name,
        "iso": s.iso,
        "kind": s.kind.value if isinstance(s.kind, FilmKind) else str(s.kind),
        "expired": s.expired,
        "expiration_date": s.expiration_date.isoformat() if s.expiration_date else None,
        "image_path": s.image_path,
        "url": catalog_url(s.image_path),
    } for s in items]


@router.get("/filmstocks/{stock_id}")
def get_filmstock(stock_id: int, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return {"error": "not_found"}
    return {
        "id": s.id,
        "name": s.name,
        "iso": s.iso,
        "kind": s.kind.value if isinstance(s.kind, FilmKind) else str(s.kind),
        "expired": s.expired,
        "expiration_date": s.expiration_date.isoformat() if s.expiration_date else None,
        "image_path": s.image_path,
        "url": catalog_url(s.image_path),
    }


@router.post("/filmstocks")
async def create_filmstock(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    kind = payload.get("kind")
    kind_enum = FilmKind(kind) if kind else None
    s = FilmStock(
        name=payload.get("name"),
        iso=payload.get("iso"),
        kind=kind_enum,
        expired=payload.get("expired"),
        expiration_date=date.fromisoformat(payload["expiration_date"]) if payload.get("expiration_date") else None,
        image_path=payload.get("image_path"),
    )
    db.add(s)
    db.commit()
    return {"ok": True, "filmstock": {
        "id": s.id,
        "name": s.name,
        "iso": s.iso,
        "kind": s.kind.value if isinstance(s.kind, FilmKind) else str(s.kind),
        "expired": s.expired,
        "expiration_date": s.expiration_date.isoformat() if s.expiration_date else None,
        "image_path": s.image_path,
        "url": catalog_url(s.image_path),
    }}


@router.put("/filmstocks/{stock_id}")
async def update_filmstock(stock_id: int, request: Request, db: Session = Depends(get_db)):
    s = db.get(FilmStock, stock_id)
    if not s:
        return {"error": "not_found"}
    payload = await request.json()
    if "kind" in payload and payload["kind"]:
        try:
            s.kind = FilmKind(payload["kind"])
        except Exception:
            pass
    for key in ["name", "iso", "expired", "image_path"]:
        if key in payload:
            setattr(s, key, payload[key])
    if "expiration_date" in payload:
        s.expiration_date = date.fromisoformat(payload["expiration_date"]) if payload["expiration_date"] else None
    db.commit()
    return {"ok": True}


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
    return {"ok": True, "filmstock": {
        "id": s.id,
        "name": s.name,
        "iso": s.iso,
        "kind": s.kind.value if isinstance(s.kind, FilmKind) else str(s.kind),
        "expired": s.expired,
        "expiration_date": s.expiration_date.isoformat() if s.expiration_date else None,
        "image_path": s.image_path,
        "url": catalog_url(s.image_path),
    }}


@router.get("/lenses")
def list_lenses(db: Session = Depends(get_db)):
    items = db.query(Lens).order_by(Lens.name.asc()).all()
    return [{"id": l.id, "name": l.name, "mount": l.mount, "image_path": l.image_path, "url": catalog_url(l.image_path), "notes": l.notes} for l in items]


@router.get("/lenses/{lens_id}")
def get_lens(lens_id: int, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return {"error": "not_found"}
    return {"id": l.id, "name": l.name, "mount": l.mount, "image_path": l.image_path, "url": catalog_url(l.image_path), "notes": l.notes}


@router.post("/lenses")
async def create_lens(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    l = Lens(name=payload.get("name"), mount=payload.get("mount"), image_path=payload.get("image_path"), notes=payload.get("notes"))
    db.add(l)
    db.commit()
    return {"ok": True, "lens": {"id": l.id, "name": l.name, "mount": l.mount, "image_path": l.image_path, "url": catalog_url(l.image_path), "notes": l.notes}}


@router.put("/lenses/{lens_id}")
async def update_lens(lens_id: int, request: Request, db: Session = Depends(get_db)):
    l = db.get(Lens, lens_id)
    if not l:
        return {"error": "not_found"}
    payload = await request.json()
    for key in ["name", "mount", "image_path", "notes"]:
        if key in payload:
            setattr(l, key, payload[key] or None)
    db.commit()
    return {"ok": True}


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
    return {"ok": True, "lens": {"id": l.id, "name": l.name, "mount": l.mount, "image_path": l.image_path, "url": catalog_url(l.image_path), "notes": l.notes}}