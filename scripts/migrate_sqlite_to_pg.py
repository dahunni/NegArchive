#!/usr/bin/env python
"""Copy an old SQLite ``negarchive.db`` into Postgres.

NegArchive ran on SQLite by default until M2. Postgres is now the only supported
database, so this is the one-way door: it reads the old file directly (no SQLAlchemy
models are needed for the source, which may be older than the current schema) and
writes everything back through the models, so the target ends up exactly as if the
rows had been created through the API.

    # 1. have a Postgres to write into
    docker compose up -d db
    export DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive

    # 2. look first
    python scripts/migrate_sqlite_to_pg.py negarchive.db --dry-run

    # 3. then do it
    python scripts/migrate_sqlite_to_pg.py negarchive.db

What it does:

* runs ``alembic upgrade head`` on the target first, so the schema is current
* copies cameras, lenses, film stocks, rolls and image assets, keeping their ids
  (paths and bookmarks keep working) and then fixes the id sequences
* resolves each roll's camera/lens/film name to the new foreign keys (R#14)
* leaves ``faces`` and ``persons`` behind — that feature was deleted in M2
* refuses to run against a target that already holds rolls or images, unless
  ``--allow-non-empty`` is given

The scan files themselves are not touched: they are still where the paths say they
are, under ``static/uploads``.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

# Run from anywhere: put the repo root on the path.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TABLES = ("cameras", "lenses", "film_stocks", "film_rolls", "image_assets")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sqlite_path", nargs="?", default="negarchive.db", help="the old negarchive.db")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="target Postgres URL (defaults to $DATABASE_URL)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would be copied, write nothing")
    parser.add_argument(
        "--allow-non-empty",
        action="store_true",
        help="write into a target that already has rolls or images (ids may collide)",
    )
    return parser.parse_args(argv)


def read_rows(connection: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    """Every row of a table as dicts, or nothing when the table is not there."""
    cursor = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    if cursor.fetchone() is None:
        return []
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]


def as_date(value) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return datetime.utcnow()
    text = str(value).replace("T", " ").split("+")[0].strip()
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return datetime.utcnow()


def as_bool(value) -> Optional[bool]:
    """SQLite stored booleans as 0/1 — and the review found "None" strings too."""
    if value in (None, "", "None"):
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "expired"}
    return bool(value)


def clean(value) -> Optional[str]:
    """R#8: the literal string "None" was stored as a gear name; drop it."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "None") else text


def enum_value(raw, enum_class, default):
    """Accept the name or the value SQLite happened to hold."""
    if raw is None:
        return default
    text = str(raw)
    for member in enum_class:
        if text in (member.name, member.value):
            return member
    return default


def copy(sqlite_path: str, database_url: str, dry_run: bool, allow_non_empty: bool) -> Dict[str, int]:
    if not os.path.exists(sqlite_path):
        raise SystemExit(f"No such SQLite database: {sqlite_path}")
    if not database_url:
        raise SystemExit(
            "No target database. Set DATABASE_URL or pass --database-url, e.g.\n"
            "  postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive"
        )
    os.environ["DATABASE_URL"] = database_url

    # Imported here, after DATABASE_URL is set: app.db reads it at import time.
    from app.db import SessionLocal, engine
    from app.main import run_migrations
    from app.models import Camera, FilmKind, FilmRoll, FilmStock, ImageAsset, ImageType, Lens

    source = sqlite3.connect(sqlite_path)
    try:
        rows = {table: read_rows(source, table) for table in TABLES}
        skipped = {table: len(read_rows(source, table)) for table in ("faces", "persons")}
    finally:
        source.close()

    counts = {table: len(items) for table, items in rows.items()}
    for table, number in skipped.items():
        if number:
            print(f"  skipping {number} {table} rows (face detection was removed in M2)")

    if dry_run:
        return counts

    run_migrations()
    db = SessionLocal()
    try:
        if not allow_non_empty and (db.query(FilmRoll).count() or db.query(ImageAsset).count()):
            raise SystemExit(
                "The target database already holds rolls or images. Use an empty database, "
                "or pass --allow-non-empty if you know the ids cannot collide."
            )

        for row in rows["cameras"]:
            db.merge(
                Camera(
                    id=row["id"],
                    name=row["name"],
                    image_path=row.get("image_path"),
                    mount=row.get("mount"),
                    notes=row.get("notes"),
                    created_at=as_datetime(row.get("created_at")),
                )
            )
        for row in rows["lenses"]:
            db.merge(
                Lens(
                    id=row["id"],
                    name=row["name"],
                    mount=row.get("mount"),
                    image_path=row.get("image_path"),
                    notes=row.get("notes"),
                    created_at=as_datetime(row.get("created_at")),
                )
            )
        for row in rows["film_stocks"]:
            db.merge(
                FilmStock(
                    id=row["id"],
                    name=row["name"],
                    manufacturer=None,
                    format=None,
                    iso=row.get("iso"),
                    kind=enum_value(row.get("kind"), FilmKind, FilmKind.black_and_white),
                    expired=as_bool(row.get("expired")),
                    expiration_date=as_date(row.get("expiration_date")),
                    image_path=row.get("image_path"),
                    created_at=as_datetime(row.get("created_at")),
                )
            )
        db.flush()

        cameras = {c.name.lower(): c for c in db.query(Camera).all()}
        lenses = {l.name.lower(): l for l in db.query(Lens).all()}
        stocks = {s.name.lower(): s for s in db.query(FilmStock).all()}

        for row in rows["film_rolls"]:
            camera_name = clean(row.get("camera"))
            lens_name = clean(row.get("lens"))
            film_name = clean(row.get("film_type"))
            camera = cameras.get(camera_name.lower()) if camera_name else None
            lens = lenses.get(lens_name.lower()) if lens_name else None
            stock = stocks.get(film_name.lower()) if film_name else None
            db.merge(
                FilmRoll(
                    id=row["id"],
                    title=row.get("title") or "Untitled roll",
                    camera_id=camera.id if camera else None,
                    lens_id=lens.id if lens else None,
                    film_stock_id=stock.id if stock else None,
                    camera=camera.name if camera else camera_name,
                    lens=lens.name if lens else lens_name,
                    film_type=stock.name if stock else film_name,
                    format=None,
                    notes=row.get("notes"),
                    start_date=as_date(row.get("start_date")),
                    end_date=as_date(row.get("end_date")),
                    building=clean(row.get("building")),
                    folder=clean(row.get("folder")),
                    archive_serial=clean(row.get("archive_serial")),
                    created_at=as_datetime(row.get("created_at")),
                )
            )
        db.flush()

        for row in rows["image_assets"]:
            db.merge(
                ImageAsset(
                    id=row["id"],
                    film_roll_id=row.get("film_roll_id"),
                    type=enum_value(row.get("type"), ImageType, ImageType.scan),
                    path=row.get("path") or "",
                    # The old schema never stored it; there is nothing to invent (R#7).
                    original_filename=None,
                    storage_mode="managed",
                    frame_number=row.get("frame_number"),
                    notes=row.get("notes"),
                    capture_date=as_date(row.get("capture_date")),
                    created_at=as_datetime(row.get("created_at")),
                )
            )
        db.commit()

        # Explicit ids leave the sequences behind; without this the next INSERT
        # through the API collides with a copied row.
        from sqlalchemy import text

        with engine.begin() as connection:
            for table in TABLES:
                connection.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)"
                    )
                )
    finally:
        db.close()
    return counts


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(list(argv) if argv is not None else None)
    print(f"Reading {args.sqlite_path}")
    counts = copy(args.sqlite_path, args.database_url, args.dry_run, args.allow_non_empty)
    for table in TABLES:
        print(f"  {counts.get(table, 0):>6}  {table}")
    if args.dry_run:
        print("Dry run: nothing was written.")
    else:
        print("Done. The scan files under static/uploads are untouched.")
        print("Keep the old negarchive.db until you have checked the archive in the UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
