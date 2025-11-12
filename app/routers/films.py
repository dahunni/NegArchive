from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from ..db import get_db
from ..models import FilmRoll, Camera, FilmStock, Lens

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/films", tags=["films"])


@router.get("")
def list_films(request: Request, db: Session = Depends(get_db)):
    films = db.query(FilmRoll).order_by(FilmRoll.created_at.desc()).all()
    return templates.TemplateResponse("films/list.html", {"request": request, "films": films})


@router.get("/new")
def new_film(request: Request, db: Session = Depends(get_db)):
    cameras = db.query(Camera).order_by(Camera.name.asc()).all()
    films = db.query(FilmStock).order_by(FilmStock.name.asc()).all()
    lenses = db.query(Lens).order_by(Lens.name.asc()).all()
    return templates.TemplateResponse("films/new.html", {"request": request, "cameras": cameras, "films": films, "lenses": lenses})


@router.post("")
def create_film(
    request: Request,
    title: str = Form(...),
    camera_name: str | None = Form(None),
    lens_name: str | None = Form(None),
    film_stock_name: str | None = Form(None),
    notes: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    building: str | None = Form(None),
    folder: str | None = Form(None),
    archive_serial: str | None = Form(None),
    db: Session = Depends(get_db),
):
    sd = None
    ed = None
    try:
        from datetime import date
        if start_date:
            y, m, d = map(int, start_date.split("-"))
            sd = date(y, m, d)
        if end_date:
            y, m, d = map(int, end_date.split("-"))
            ed = date(y, m, d)
    except Exception:
        sd = None
        ed = None
    film = FilmRoll(
        title=title,
        camera=camera_name,
        lens=lens_name,
        film_type=film_stock_name,
        notes=notes,
        start_date=sd,
        end_date=ed,
        building=building,
        folder=folder,
        archive_serial=archive_serial,
    )
    db.add(film)
    db.commit()
    return RedirectResponse(url=f"/films/{film.id}", status_code=303)


@router.get("/{film_id}")
def film_detail(film_id: int, request: Request, db: Session = Depends(get_db)):
    film = db.get(FilmRoll, film_id)
    if not film:
        return RedirectResponse(url="/films", status_code=303)
    cam = None
    stock = None
    lens_obj = None
    if film.camera:
        cam = db.query(Camera).filter(Camera.name == film.camera).first()
    if film.film_type:
        stock = db.query(FilmStock).filter(FilmStock.name == film.film_type).first()
    if film.lens:
        lens_obj = db.query(Lens).filter(Lens.name == film.lens).first()
    return templates.TemplateResponse("films/detail.html", {"request": request, "film": film, "camera_obj": cam, "filmstock_obj": stock, "lens_obj": lens_obj})


@router.get("/{film_id}/edit")
def edit_film(film_id: int, request: Request, db: Session = Depends(get_db)):
    film = db.get(FilmRoll, film_id)
    if not film:
        return RedirectResponse(url="/films", status_code=303)
    cameras = db.query(Camera).order_by(Camera.name.asc()).all()
    films = db.query(FilmStock).order_by(FilmStock.name.asc()).all()
    lenses = db.query(Lens).order_by(Lens.name.asc()).all()
    return templates.TemplateResponse("films/edit.html", {"request": request, "film": film, "cameras": cameras, "films": films, "lenses": lenses})


@router.post("/{film_id}/edit")
def update_film(
    film_id: int,
    title: str = Form(...),
    camera_name: str | None = Form(None),
    lens_name: str | None = Form(None),
    film_stock_name: str | None = Form(None),
    notes: str | None = Form(None),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    building: str | None = Form(None),
    folder: str | None = Form(None),
    archive_serial: str | None = Form(None),
    db: Session = Depends(get_db),
):
    film = db.get(FilmRoll, film_id)
    if not film:
        return RedirectResponse(url="/films", status_code=303)
    film.title = title
    film.camera = camera_name
    film.lens = lens_name
    film.film_type = film_stock_name
    film.notes = notes
    film.building = building
    film.folder = folder
    film.archive_serial = archive_serial
    # parse dates
    try:
        from datetime import date
        film.start_date = None
        film.end_date = None
        if start_date:
            y, m, d = map(int, start_date.split("-"))
            film.start_date = date(y, m, d)
        if end_date:
            y, m, d = map(int, end_date.split("-"))
            film.end_date = date(y, m, d)
    except Exception:
        pass
    db.commit()
    return RedirectResponse(url=f"/films/{film.id}", status_code=303)