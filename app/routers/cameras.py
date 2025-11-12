from pathlib import Path
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from ..db import get_db
from ..models import Camera

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/cameras", tags=["cameras"])

BASE_DIR = Path("static/catalog/cameras")
BASE_DIR.mkdir(parents=True, exist_ok=True)


@router.get("")
def list_cameras(request: Request, db: Session = Depends(get_db)):
    items = db.query(Camera).order_by(Camera.name.asc()).all()
    return templates.TemplateResponse("catalog/cameras_list.html", {"request": request, "items": items})


@router.get("/new")
def new_camera(request: Request):
    return templates.TemplateResponse("catalog/cameras_new.html", {"request": request})


@router.post("")
async def create_camera(
    name: str = Form(...),
    mount: str | None = Form(None),
    notes: str | None = Form(None),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    image_path = None
    if image and image.filename:
        fname = image.filename.replace(" ", "_")
        target = BASE_DIR / fname
        content = await image.read()
        with open(target, "wb") as f:
            f.write(content)
        image_path = f"static/catalog/cameras/{fname}"
    cam = Camera(name=name, image_path=image_path, mount=mount, notes=notes)
    db.add(cam)
    db.commit()
    return RedirectResponse(url="/cameras", status_code=303)


@router.get("/{camera_id}/edit")
def edit_camera(camera_id: int, request: Request, db: Session = Depends(get_db)):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        return RedirectResponse(url="/cameras", status_code=303)
    return templates.TemplateResponse("catalog/cameras_edit.html", {"request": request, "camera": cam})


@router.post("/{camera_id}/edit")
async def update_camera(
    camera_id: int,
    name: str = Form(...),
    mount: str | None = Form(None),
    notes: str | None = Form(None),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        return RedirectResponse(url="/cameras", status_code=303)

    cam.name = name
    cam.mount = mount
    cam.notes = notes

    if image and image.filename:
        fname = image.filename.replace(" ", "_")
        target = BASE_DIR / fname
        content = await image.read()
        with open(target, "wb") as f:
            f.write(content)
        cam.image_path = f"static/catalog/cameras/{fname}"

    db.commit()
    return RedirectResponse(url="/cameras", status_code=303)