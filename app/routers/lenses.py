from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lens

router = APIRouter(prefix="/lenses", tags=["lenses"])
templates = Jinja2Templates(directory="templates")

STATIC_LENSES_DIR = Path("static/catalog/lenses")


@router.get("")
def list_lenses(request: Request, db: Session = Depends(get_db)):
    lenses = db.query(Lens).order_by(Lens.name.asc()).all()
    return templates.TemplateResponse(
        "catalog/lenses_list.html",
        {"request": request, "lenses": lenses},
    )


@router.get("/new")
def new_lens(request: Request):
    return templates.TemplateResponse(
        "catalog/lenses_new.html",
        {"request": request},
    )


@router.post("")
async def create_lens(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    mount: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    image: Optional[UploadFile] = None,
):
    image_path: Optional[str] = None
    if image and image.filename:
        STATIC_LENSES_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = name.lower().replace(" ", "-")
        dest = STATIC_LENSES_DIR / f"{safe_name}{Path(image.filename).suffix}"
        content = await image.read()
        dest.write_bytes(content)
        image_path = str(dest)

    lens = Lens(name=name, mount=mount, notes=notes, image_path=image_path)
    db.add(lens)
    db.commit()
    return RedirectResponse(url="/lenses", status_code=303)


@router.get("/{lens_id}/edit")
def edit_lens(lens_id: int, request: Request, db: Session = Depends(get_db)):
    lens = db.query(Lens).filter(Lens.id == lens_id).first()
    if not lens:
        return RedirectResponse(url="/lenses", status_code=303)
    return templates.TemplateResponse(
        "catalog/lenses_edit.html",
        {"request": request, "lens": lens},
    )


@router.post("/{lens_id}/edit")
async def update_lens(
    lens_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    mount: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    image: Optional[UploadFile] = None,
):
    lens = db.query(Lens).filter(Lens.id == lens_id).first()
    if not lens:
        return RedirectResponse(url="/lenses", status_code=303)

    lens.name = name
    lens.mount = mount
    lens.notes = notes

    if image and image.filename:
        STATIC_LENSES_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = name.lower().replace(" ", "-")
        dest = STATIC_LENSES_DIR / f"{safe_name}{Path(image.filename).suffix}"
        content = await image.read()
        dest.write_bytes(content)
        lens.image_path = str(dest)

    db.commit()
    return RedirectResponse(url="/lenses", status_code=303)