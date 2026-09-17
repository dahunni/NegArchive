"""Starter catalog entries.

R#11: the old startup hook re-added Nikon F5, Minolta XG9, Kodak Gold 200 and the
Fomapans on every boot, so deleting one only lasted until the next restart. Seeding
now happens once, when a catalog table is still empty, and otherwise only on request
through ``POST /api/seed``. A row you deleted never comes back as long as the table
still holds anything at all.
"""

import shutil
from pathlib import Path
from typing import Dict

from sqlalchemy.orm import Session

from . import paths
from .models import Camera, FilmKind, FilmStock

CATALOG_DIRS = ("cameras", "films", "lenses")

#: The catalog pictures that ship with the repository. M3 moved the directory
#: `/static` serves to DATA_DIR, so they are copied there on first start instead of
#: being read out of the source tree — one directory holds the whole archive, and a
#: `git clean` cannot take half of it with it.
BUNDLED_CATALOG = Path(__file__).resolve().parent.parent / "static" / "catalog"

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
    """Create DATA_DIR/catalog/* and copy the bundled pictures into it (M3).

    Copying is "only what is missing": a picture the user replaced through
    `POST /api/cameras/{id}/image` is never overwritten by the one from the repo.
    """
    for directory in CATALOG_DIRS:
        (paths.catalog_dir() / directory).mkdir(parents=True, exist_ok=True)

    if not BUNDLED_CATALOG.is_dir():
        return
    for source in BUNDLED_CATALOG.rglob("*"):
        if not source.is_file():
            continue
        target = paths.catalog_dir() / source.relative_to(BUNDLED_CATALOG)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, target)
        except OSError:
            # A read-only data directory is a deployment problem, not a reason to
            # refuse to boot: the catalog simply shows no picture.
            pass


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
