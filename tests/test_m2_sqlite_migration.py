"""``scripts/migrate_sqlite_to_pg.py``: the way off SQLite (M2, roadmap decision 2).

The script is run as a real subprocess against a throwaway Postgres, because that is
how somebody upgrading an existing archive will use it.
"""

import os
import sqlite3
import subprocess
import sys

from sqlalchemy import create_engine, text
from test_m2_migrations import REPO_ROOT, scratch_database

#: The schema a pre-M2 NegArchive left behind on SQLite (`create_all` on the old
#: models plus the startup ALTERs), trimmed to what the script reads.
OLD_SCHEMA = """
CREATE TABLE cameras (id INTEGER PRIMARY KEY, name VARCHAR(200), image_path VARCHAR(500),
    mount VARCHAR(100), notes TEXT, created_at DATETIME);
CREATE TABLE lenses (id INTEGER PRIMARY KEY, name VARCHAR(200), mount VARCHAR(100),
    image_path VARCHAR(500), notes TEXT, created_at DATETIME);
CREATE TABLE film_stocks (id INTEGER PRIMARY KEY, name VARCHAR(200), iso INTEGER, kind VARCHAR(20),
    expired INTEGER, expiration_date DATE, image_path VARCHAR(500), created_at DATETIME);
CREATE TABLE film_rolls (id INTEGER PRIMARY KEY, title VARCHAR(200), camera VARCHAR(200),
    lens VARCHAR(200), film_type VARCHAR(200), notes TEXT, start_date DATE, end_date DATE,
    building VARCHAR(200), folder VARCHAR(200), archive_serial VARCHAR(200), created_at DATETIME);
CREATE TABLE image_assets (id INTEGER PRIMARY KEY, film_roll_id INTEGER, type VARCHAR(20),
    path VARCHAR(500), frame_number INTEGER, notes TEXT, capture_date DATE, created_at DATETIME);
CREATE TABLE persons (id INTEGER PRIMARY KEY, name VARCHAR(200), created_at DATETIME);
CREATE TABLE faces (id INTEGER PRIMARY KEY, image_id INTEGER, bbox_x INTEGER, bbox_y INTEGER,
    bbox_w INTEGER, bbox_h INTEGER, embedding TEXT, person_id INTEGER, created_at DATETIME);
"""


def build_old_database(path: str) -> None:
    db = sqlite3.connect(path)
    try:
        db.executescript(OLD_SCHEMA)
        db.execute(
            "INSERT INTO cameras VALUES (1, 'Nikon F5', 'static/catalog/cameras/f5.svg',"
            " 'Nikon F', 'the workhorse', '2024-01-02 10:00:00')"
        )
        db.execute("INSERT INTO lenses VALUES (2, 'Nikkor 50mm', 'Nikon F', NULL, NULL, '2024-01-02 10:00:00')")
        db.execute(
            "INSERT INTO film_stocks VALUES (3, 'Fomapan 400', 400, 'black_and_white', 1,"
            " '2023-05-01', NULL, '2024-01-02 10:00:00')"
        )
        db.execute(
            "INSERT INTO film_rolls VALUES (4, 'Japan 2024', 'Nikon F5', 'Nikkor 50mm', 'Fomapan 400',"
            " 'pushed one stop', '2024-07-01', '2024-07-08', 'Archive A', '2024-Q3', 'NEG-2024-011',"
            " '2024-07-09 08:00:00')"
        )
        # R#8: an old database can hold the literal string "None" as a gear name.
        db.execute(
            "INSERT INTO film_rolls VALUES (5, 'Stray roll', 'None', NULL, NULL, NULL, NULL, NULL,"
            " NULL, NULL, NULL, '2024-07-10 08:00:00')"
        )
        db.execute(
            "INSERT INTO image_assets VALUES (6, 4, 'scan', 'static/uploads/scans/abc.tif', 7,"
            " 'the one with the bike', '2024-07-02', '2024-07-09 09:00:00')"
        )
        db.execute(
            "INSERT INTO image_assets VALUES (7, NULL, 'contact_sheet',"
            " 'static/uploads/contact_sheets/def.jpg', NULL, NULL, NULL, '2024-07-09 09:30:00')"
        )
        db.execute("INSERT INTO persons VALUES (8, 'Somebody', '2024-07-09 09:30:00')")
        db.execute("INSERT INTO faces VALUES (9, 6, 1, 2, 3, 4, '{}', 8, '2024-07-09 09:30:00')")
        db.commit()
    finally:
        db.close()


def run_script(sqlite_path: str, url: str, *extra: str) -> subprocess.CompletedProcess:
    environment = dict(os.environ, DATABASE_URL=url)
    return subprocess.run(
        [sys.executable, os.path.join("scripts", "migrate_sqlite_to_pg.py"), sqlite_path, *extra],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_a_dry_run_writes_nothing(tmp_path):
    sqlite_path = str(tmp_path / "negarchive.db")
    build_old_database(sqlite_path)
    with scratch_database() as url:
        result = run_script(sqlite_path, url, "--dry-run")
        assert result.returncode == 0, result.stderr
        assert "2  film_rolls" in result.stdout
        assert "Dry run" in result.stdout

        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                tables = connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).scalars().all()
        finally:
            engine.dispose()
        assert tables == [], "a dry run does not even migrate the schema"


def test_the_whole_archive_comes_across(tmp_path):
    sqlite_path = str(tmp_path / "negarchive.db")
    build_old_database(sqlite_path)
    with scratch_database() as url:
        result = run_script(sqlite_path, url)
        assert result.returncode == 0, result.stderr
        assert "skipping 1 faces rows" in result.stdout

        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                roll = connection.execute(
                    text(
                        "SELECT id, title, camera_id, lens_id, film_stock_id, camera, notes,"
                        " start_date, end_date, building, archive_serial FROM film_rolls WHERE id = 4"
                    )
                ).one()
                stray = connection.execute(
                    text("SELECT camera, camera_id FROM film_rolls WHERE id = 5")
                ).one()
                stock = connection.execute(
                    text("SELECT kind, iso, expired, expiration_date FROM film_stocks WHERE id = 3")
                ).one()
                images = connection.execute(
                    text(
                        "SELECT id, film_roll_id, type, path, frame_number, capture_date,"
                        " original_filename, storage_mode FROM image_assets ORDER BY id"
                    )
                ).all()
                tables = set(
                    connection.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    ).scalars()
                )
        finally:
            engine.dispose()

        # ids are kept, so every stored path and bookmark still points at the same row
        assert roll.id == 4 and roll.title == "Japan 2024"
        # names resolved to the new foreign keys (R#14)
        assert (roll.camera_id, roll.lens_id, roll.film_stock_id) == (1, 2, 3)
        assert roll.camera == "Nikon F5"
        assert str(roll.start_date) == "2024-07-01" and str(roll.end_date) == "2024-07-08"
        assert roll.building == "Archive A" and roll.archive_serial == "NEG-2024-011"
        assert roll.notes == "pushed one stop"

        # R#8: the "None" string is dropped instead of copied
        assert stray.camera is None and stray.camera_id is None

        # R#1: SQLite's 0/1 becomes a real boolean
        assert stock.expired is True
        assert stock.kind == "black_and_white" and stock.iso == 400
        assert str(stock.expiration_date) == "2023-05-01"

        assert [i.id for i in images] == [6, 7]
        assert images[0].type == "scan" and images[0].frame_number == 7
        assert images[0].path == "static/uploads/scans/abc.tif"
        assert str(images[0].capture_date) == "2024-07-02"
        assert images[0].storage_mode == "managed"
        assert images[0].original_filename is None
        assert images[1].type == "contact_sheet" and images[1].film_roll_id is None

        # faces and persons stay behind
        assert "faces" not in tables and "persons" not in tables


def test_the_id_sequences_are_fixed_afterwards(tmp_path):
    """Copying explicit ids must not leave the next INSERT colliding with them."""
    sqlite_path = str(tmp_path / "negarchive.db")
    build_old_database(sqlite_path)
    with scratch_database() as url:
        assert run_script(sqlite_path, url).returncode == 0
        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                new_id = connection.execute(
                    text(
                        "INSERT INTO film_rolls (title, created_at) VALUES ('After', now())"
                        " RETURNING id"
                    )
                ).scalar()
        finally:
            engine.dispose()
        assert new_id > 5


def test_it_refuses_to_overwrite_an_archive_that_is_already_there(tmp_path):
    sqlite_path = str(tmp_path / "negarchive.db")
    build_old_database(sqlite_path)
    with scratch_database() as url:
        assert run_script(sqlite_path, url).returncode == 0
        second = run_script(sqlite_path, url)
        assert second.returncode != 0
        assert "already holds rolls or images" in second.stdout + second.stderr
