"""Starter catalog entries.

R#11: the old startup hook re-added Nikon F5, Minolta XG9, Kodak Gold 200 and the
Fomapans on every boot, so deleting one only lasted until the next restart. Seeding
now happens once, when a catalog table is still empty, and otherwise only on request
through ``POST /api/seed``. A row you deleted never comes back as long as the table
still holds anything at all.
"""

from pathlib import Path
from typing import Dict

from sqlalchemy.orm import Session

from .models import Camera, FilmKind, FilmStock

CATALOG_DIRS = ("static/catalog/cameras", "static/catalog/films", "static/catalog/lenses")

SEED_CAMERAS = [
    {"name": "Nikon F5", "mount": "Nikon F", "image_path": "static/catalog/cameras/nikon-f5.svg"},
    {"name": "Minolta XG9", "mount": "Minolta SR", "image_path": "static/catalog/cameras/minolta-xg9.svg"},
]

SEED_FILM_STOCKS = [
    {
        "name": "Kodak Gold 200",
        "manufacturer": "Kodak",
        "format": "35mm",
        "kind": FilmKind.color,
        "iso": 200,
        "expired": False,
        "image_path": "static/catalog/films/kodak-gold-200.svg",
    },
    {
        "name": "Fomapan 100",
        "manufacturer": "Foma",
        "format": "35mm",
        "kind": FilmKind.black_and_white,
        "iso": 100,
        "expired": False,
        "image_path": "static/catalog/films/fomapan-100.svg",
    },
    {
        "name": "Fomapan 200",
        "manufacturer": "Foma",
        "format": "35mm",
        "kind": FilmKind.black_and_white,
        "iso": 200,
        "expired": False,
        "image_path": "static/catalog/films/fomapan-200.svg",
    },
    {
        "name": "Fomapan 400",
        "manufacturer": "Foma",
        "format": "35mm",
        "kind": FilmKind.black_and_white,
        "iso": 400,
        "expired": False,
        "image_path": "static/catalog/films/fomapan-400.svg",
    },
]


def ensure_catalog_dirs() -> None:
    for directory in CATALOG_DIRS:
        Path(directory).mkdir(parents=True, exist_ok=True)


def seed_catalog(db: Session, force: bool = False) -> Dict[str, int]:
    """Add the starter gear.

    Without ``force`` a table is only touched while it is completely empty, which is
    what makes a deletion permanent. With ``force`` (``POST /api/seed``) the missing
    entries are added back by name, and existing rows are left exactly as they are.
    """
    ensure_catalog_dirs()
    added = {"cameras": 0, "film_stocks": 0}

    if force or db.query(Camera).count() == 0:
        for entry in SEED_CAMERAS:
            if not db.query(Camera).filter(Camera.name == entry["name"]).first():
                db.add(Camera(**entry))
                added["cameras"] += 1

    if force or db.query(FilmStock).count() == 0:
        for entry in SEED_FILM_STOCKS:
            if not db.query(FilmStock).filter(FilmStock.name == entry["name"]).first():
                db.add(FilmStock(**entry))
                added["film_stocks"] += 1

    db.commit()
    return added
