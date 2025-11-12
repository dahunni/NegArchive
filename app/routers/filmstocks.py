from pathlib import Path
from datetime import date
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from ..db import get_db
from ..models import FilmStock, FilmKind

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/filmstocks", tags=["filmstocks"])

BASE_DIR = Path("static/catalog/films")
BASE_DIR.mkdir(parents=True, exist_ok=True)


@router.get("")
def list_films(request: Request, db: Session = Depends(get_db)):
    items = db.query(FilmStock).order_by(FilmStock.name.asc()).all()
    return templates.TemplateResponse("catalog/films_list.html", {"request": request, "items": items})


@router.get("/new")
def new_film(request: Request):
    return templates.TemplateResponse("catalog/films_new.html", {"request": request, "kinds": list(FilmKind)})


@router.post("")
async def create_film(
    name: str = Form(...),
    iso: int | None = Form(None),
    kind: FilmKind = Form(...),
    expired: int = Form(0),
    expiration_date: str | None = Form(None),
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
        image_path = f"static/catalog/films/{fname}"
    exp_date = None
    try:
        if expiration_date:
            exp_date = date.fromisoformat(expiration_date)
            # Auto-compute expired if not provided
            if expired in (None, 0) and exp_date and exp_date < date.today():
                expired = 1
    except Exception:
        exp_date = None
    film = FilmStock(name=name, iso=iso, kind=kind, expired=int(expired), expiration_date=exp_date, image_path=image_path)
    db.add(film)
    db.commit()
    return RedirectResponse(url="/filmstocks", status_code=303)


@router.get("/{film_id}/edit")
def edit_film(film_id: int, request: Request, db: Session = Depends(get_db)):
    film = db.get(FilmStock, film_id)
    if not film:
        return RedirectResponse(url="/filmstocks", status_code=303)
    return templates.TemplateResponse("catalog/films_edit.html", {"request": request, "film": film, "kinds": list(FilmKind)})


@router.post("/{film_id}/edit")
async def update_film(
    film_id: int,
    name: str = Form(...),
    iso: int | None = Form(None),
    kind: FilmKind = Form(...),
    expired: int = Form(0),
    expiration_date: str | None = Form(None),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    film = db.get(FilmStock, film_id)
    if not film:
        return RedirectResponse(url="/filmstocks", status_code=303)
    film.name = name
    film.iso = iso
    film.kind = kind
    try:
        film.expiration_date = date.fromisoformat(expiration_date) if expiration_date else None
    except Exception:
        film.expiration_date = None
    film.expired = int(expired)

    if image and image.filename:
        fname = image.filename.replace(" ", "_")
        target = BASE_DIR / fname
        content = await image.read()
        with open(target, "wb") as f:
            f.write(content)
        film.image_path = f"static/catalog/films/{fname}"

    db.commit()
    return RedirectResponse(url="/filmstocks", status_code=303)