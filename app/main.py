import os
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .db import Base, engine, get_db, SessionLocal
from sqlalchemy import inspect, text
from .models import FilmRoll, Camera, FilmStock, FilmKind, ImageAsset
from .routers import api

app = FastAPI(title="NegArchive")

# Enable CORS for Node/Next.js frontends (local dev and hosted)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def _run_migrations() -> None:
    """Minimal, idempotent schema fixups until Alembic lands (roadmap M2).

    Every statement is guarded so a partially migrated database still boots.
    """
    inspector = inspect(engine)

    def columns(table: str) -> dict:
        try:
            return {c["name"]: c for c in inspector.get_columns(table)}
        except Exception:
            return {}

    def execute(sql: str) -> None:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception:
            # Non-fatal: the column/constraint is probably already in the target state
            pass

    fs_cols = columns("film_stocks")
    if fs_cols and "expiration_date" not in fs_cols:
        execute("ALTER TABLE film_stocks ADD COLUMN expiration_date DATE")

    cam_cols = columns("cameras")
    if cam_cols and "mount" not in cam_cols:
        execute("ALTER TABLE cameras ADD COLUMN mount VARCHAR(100)")
    if cam_cols and "notes" not in cam_cols:
        execute("ALTER TABLE cameras ADD COLUMN notes TEXT")

    fr_cols = columns("film_rolls")
    if fr_cols and "start_date" not in fr_cols:
        execute("ALTER TABLE film_rolls ADD COLUMN start_date DATE")
    if fr_cols and "end_date" not in fr_cols:
        execute("ALTER TABLE film_rolls ADD COLUMN end_date DATE")

    ia_cols = columns("image_assets")
    if ia_cols and "capture_date" not in ia_cols:
        execute("ALTER TABLE image_assets ADD COLUMN capture_date DATE")

    if _is_postgres():
        # R#1: film_stocks.expired used to be INTEGER; the API and the UI speak booleans.
        expired = fs_cols.get("expired")
        if expired is not None and "INT" in str(expired["type"]).upper():
            execute(
                "ALTER TABLE film_stocks ALTER COLUMN expired TYPE BOOLEAN "
                "USING (expired <> 0)"
            )
        # R#5: an image may exist before it is assigned to a film roll.
        film_roll_id = ia_cols.get("film_roll_id")
        if film_roll_id is not None and not film_roll_id.get("nullable", True):
            execute("ALTER TABLE image_assets ALTER COLUMN film_roll_id DROP NOT NULL")

    # R#8: one-off data fix for rolls that stored the literal string "None".
    if fr_cols:
        for column in ("camera", "lens", "film_type"):
            if column in fr_cols:
                execute(
                    f"UPDATE film_rolls SET {column} = NULL "
                    f"WHERE {column} IN ('None', '')"
                )


def _seed_catalog() -> None:
    from pathlib import Path

    Path("static/catalog/cameras").mkdir(parents=True, exist_ok=True)
    Path("static/catalog/films").mkdir(parents=True, exist_ok=True)
    Path("static/catalog/lenses").mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        def ensure_camera(name: str, image_rel: str | None, mount: str | None = None):
            if not db.query(Camera).filter(Camera.name == name).first():
                db.add(Camera(name=name, image_path=image_rel, mount=mount))

        def ensure_film(name: str, kind: FilmKind, iso: int | None, expired: bool, image_rel: str | None):
            if not db.query(FilmStock).filter(FilmStock.name == name).first():
                db.add(FilmStock(name=name, kind=kind, iso=iso, expired=expired, image_path=image_rel))

        ensure_camera("Nikon F5", "static/catalog/cameras/nikon-f5.svg", mount="Nikon F")
        ensure_camera("Minolta XG9", "static/catalog/cameras/minolta-xg9.svg", mount="Minolta SR")
        ensure_film("Kodak Gold 200", FilmKind.color, 200, False, "static/catalog/films/kodak-gold-200.svg")
        ensure_film("Fomapan 100", FilmKind.black_and_white, 100, False, "static/catalog/films/fomapan-100.svg")
        ensure_film("Fomapan 200", FilmKind.black_and_white, 200, False, "static/catalog/films/fomapan-200.svg")
        ensure_film("Fomapan 400", FilmKind.black_and_white, 400, False, "static/catalog/films/fomapan-400.svg")
        db.commit()
    finally:
        db.close()


# Ensure tables
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    try:
        _run_migrations()
    except Exception:
        # Non-fatal: continue
        pass
    _seed_catalog()


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
app.include_router(api.router)
