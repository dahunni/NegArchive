import os
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .db import Base, engine, get_db, SessionLocal
from sqlalchemy import inspect, text
from .models import FilmRoll, Camera, FilmStock, FilmKind, ImageAsset
from .routers import films, images, search, cameras, filmstocks, lenses, api

app = FastAPI(title="NegArchive")

# Enable CORS for Node/Next.js frontends (local dev and hosted)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure tables
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # Ensure film_stocks.expiration_date exists (SQLite/Postgres simple migration)
    try:
        inspector = inspect(engine)
        cols = [c["name"] for c in inspector.get_columns("film_stocks")]
        if "expiration_date" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE film_stocks ADD COLUMN expiration_date DATE"))
        # Ensure cameras.mount and cameras.notes exist
        cam_cols = [c["name"] for c in inspector.get_columns("cameras")]
        with engine.begin() as conn:
            if "mount" not in cam_cols:
                try:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN mount VARCHAR(100)"))
                except Exception:
                    pass
            if "notes" not in cam_cols:
                try:
                    conn.execute(text("ALTER TABLE cameras ADD COLUMN notes TEXT"))
                except Exception:
                    pass
        # Ensure film_rolls.start_date and end_date
        fr_cols = [c["name"] for c in inspector.get_columns("film_rolls")]
        with engine.begin() as conn:
            if "start_date" not in fr_cols:
                try:
                    conn.execute(text("ALTER TABLE film_rolls ADD COLUMN start_date DATE"))
                except Exception:
                    pass
            if "end_date" not in fr_cols:
                try:
                    conn.execute(text("ALTER TABLE film_rolls ADD COLUMN end_date DATE"))
                except Exception:
                    pass
        # Ensure image_assets.capture_date
        ia_cols = [c["name"] for c in inspector.get_columns("image_assets")]
        if "capture_date" not in ia_cols:
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE image_assets ADD COLUMN capture_date DATE"))
                except Exception:
                    pass
    except Exception:
        # Non-fatal: continue
        pass
    # Seed default cameras and films with placeholder images
    from pathlib import Path
    Path("static/catalog/cameras").mkdir(parents=True, exist_ok=True)
    Path("static/catalog/films").mkdir(parents=True, exist_ok=True)
    Path("static/catalog/lenses").mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        def ensure_camera(name: str, image_rel: str | None, mount: str | None = None):
            if not db.query(Camera).filter(Camera.name == name).first():
                db.add(Camera(name=name, image_path=image_rel, mount=mount))

        def ensure_film(name: str, kind: FilmKind, iso: int | None, expired: int, image_rel: str | None):
            if not db.query(FilmStock).filter(FilmStock.name == name).first():
                db.add(FilmStock(name=name, kind=kind, iso=iso, expired=expired, image_path=image_rel))

        ensure_camera("Nikon F5", "static/catalog/cameras/nikon-f5.svg", mount="Nikon F")
        ensure_camera("Minolta XG9", "static/catalog/cameras/minolta-xg9.svg", mount="Minolta SR")
        ensure_film("Kodak Gold 200", FilmKind.color, 200, 0, "static/catalog/films/kodak-gold-200.svg")
        ensure_film("Fomapan 100", FilmKind.black_and_white, 100, 0, "static/catalog/films/fomapan-100.svg")
        ensure_film("Fomapan 200", FilmKind.black_and_white, 200, 0, "static/catalog/films/fomapan-200.svg")
        ensure_film("Fomapan 400", FilmKind.black_and_white, 400, 0, "static/catalog/films/fomapan-400.svg")
        db.commit()
    finally:
        db.close()

# Mount static
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return {
        "ok": True,
        "app": "NegArchive API",
        "message": "Frontend runs separately (Next.js). See http://localhost:3000 during development.",
    }


# Routers
app.include_router(films.router)
app.include_router(images.router)
app.include_router(search.router)
app.include_router(cameras.router)
app.include_router(filmstocks.router)
app.include_router(api.router)
app.include_router(lenses.router)