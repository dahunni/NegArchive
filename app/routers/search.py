from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from ..db import get_db
from ..models import FilmRoll, ImageAsset, Person, Face

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    request: Request,
    q: str | None = Query(None, description="Text query: title, camera, lens, film_type, notes"),
    person: str | None = Query(None, description="Person name"),
    db: Session = Depends(get_db),
):
    films_q = db.query(FilmRoll)
    if q:
        like = f"%{q}%"
        films_q = films_q.filter(
            (FilmRoll.title.ilike(like))
            | (FilmRoll.camera.ilike(like))
            | (FilmRoll.lens.ilike(like))
            | (FilmRoll.film_type.ilike(like))
            | (FilmRoll.notes.ilike(like))
            | (FilmRoll.building.ilike(like))
            | (FilmRoll.folder.ilike(like))
            | (FilmRoll.archive_serial.ilike(like))
        )
    films = films_q.order_by(FilmRoll.created_at.desc()).limit(100).all()

    images_q = db.query(ImageAsset)
    if person:
        images_q = images_q.join(ImageAsset.faces).join(Face.person).filter(Person.name.ilike(f"%{person}%"))
    images = images_q.order_by(ImageAsset.created_at.desc()).limit(100).all()

    persons = db.query(Person).order_by(Person.name.asc()).all()

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "films": films,
            "images": images,
            "persons": persons,
            "q": q or "",
            "person": person or "",
        },
    )