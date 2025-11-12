import os
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from ..db import get_db
from ..models import ImageAsset, FilmRoll, ImageType, Face, Person
from ..services.face import process_image

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/images", tags=["images"])

BASE_UPLOAD_DIR = Path("static/uploads")
CONTACT_DIR = BASE_UPLOAD_DIR / "contact_sheets"
SCAN_DIR = BASE_UPLOAD_DIR / "scans"

for d in [BASE_UPLOAD_DIR, CONTACT_DIR, SCAN_DIR]:
    d.mkdir(parents=True, exist_ok=True)


@router.get("/upload")
def upload_page(request: Request, db: Session = Depends(get_db)):
    films = db.query(FilmRoll).order_by(FilmRoll.created_at.desc()).all()
    return templates.TemplateResponse("images/upload.html", {"request": request, "films": films})


@router.post("/upload")
async def upload_image(
    request: Request,
    film_roll_id: int = Form(...),
    type: ImageType = Form(...),
    frame_number: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    capture_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    film = db.get(FilmRoll, film_roll_id)
    if not film:
        return RedirectResponse(url="/images/upload", status_code=303)

    filename = file.filename or "upload.jpg"
    safe_name = filename.replace(" ", "_")
    target_dir = CONTACT_DIR if type == ImageType.contact_sheet else SCAN_DIR
    target_path = target_dir / safe_name

    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)

    # parse capture date
    cd = None
    try:
        if capture_date:
            y, m, d = map(int, capture_date.split("-"))
            from datetime import date
            cd = date(y, m, d)
    except Exception:
        cd = None

    img = ImageAsset(
        film_roll_id=film.id,
        type=type,
        path=str(target_path.resolve()),
        frame_number=frame_number,
        notes=notes,
        capture_date=cd,
    )
    db.add(img)
    db.commit()

    # Process faces in background-like manner (synchronous here for simplicity)
    try:
        process_image(db, img)
    except Exception:
        pass

    return RedirectResponse(url=f"/films/{film.id}", status_code=303)


@router.get("/{image_id}/edit")
def edit_image(image_id: int, request: Request, db: Session = Depends(get_db)):
    image = db.get(ImageAsset, image_id)
    if not image:
        return RedirectResponse(url="/", status_code=303)
    films = db.query(FilmRoll).order_by(FilmRoll.created_at.desc()).all()
    return templates.TemplateResponse("images/edit.html", {"request": request, "image": image, "films": films})


@router.post("/{image_id}/edit")
def update_image(
    image_id: int,
    film_roll_id: int = Form(...),
    type: ImageType = Form(...),
    frame_number: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    capture_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    image = db.get(ImageAsset, image_id)
    if not image:
        return RedirectResponse(url="/", status_code=303)
    film = db.get(FilmRoll, film_roll_id)
    if not film:
        return RedirectResponse(url="/", status_code=303)
    image.film_roll_id = film.id
    image.type = type
    image.frame_number = frame_number
    image.notes = notes
    try:
        image.capture_date = None
        if capture_date:
            y, m, d = map(int, capture_date.split("-"))
            from datetime import date
            image.capture_date = date(y, m, d)
    except Exception:
        pass
    db.commit()
    return RedirectResponse(url=f"/films/{film.id}", status_code=303)


@router.post("/faces/{face_id}/label")
def label_face(face_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    face = db.get(Face, face_id)
    if not face:
        return RedirectResponse(url="/", status_code=303)
    person = db.query(Person).filter(Person.name == name).first()
    if not person:
        person = Person(name=name)
        db.add(person)
        db.flush()
    face.person_id = person.id
    db.commit()
    return RedirectResponse(url=f"/images/{face.image_id}", status_code=303)


@router.get("/{image_id}")
def image_detail(image_id: int, request: Request, db: Session = Depends(get_db)):
    image = db.get(ImageAsset, image_id)
    if not image:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("films/detail.html", {"request": request, "film": image.film_roll})
