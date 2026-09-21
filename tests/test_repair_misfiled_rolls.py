"""``scripts/repair_misfiled_rolls.py``: the rows the two NegPy bugs left behind.

The state rebuilt here is the one found on a live archive on 2026-09-21, after a
single roll had been through the whole NegPy flow:

* ``NEG-2026-0001`` "London 2026 + Birthday" — the real roll, with the camera, the
  film and the developer on it, holding 33 exported positives named
  ``NEG_2026_0001_001.jpg``… every one of them filed as **frame 2026**, because
  NegPy's templating had slugged the serial's hyphens into the preset's own
  separator;
* ``NEG-2026-0002`` "rolls" — a roll the archive invented out of the *watch
  folder's* name, holding the same roll's 33 raw negatives
  (``NEG-2026-0001_Frame001.ARW``…), because the importer only read folder names.

One roll, in the archive twice, with the frame numbers of one half all wrong. The
script is run as a subprocess against a throwaway database, because that is how
somebody with a damaged archive will use it.
"""

import os
import subprocess
import sys

from alembic.command import upgrade
from sqlalchemy import create_engine, text
from test_m2_migrations import REPO_ROOT, run, scratch_database


def build_broken_archive(url: str) -> dict:
    """The live failure, rebuilt: one roll, two records, 33 frames called 2026."""
    run(url, upgrade, "head")
    engine = create_engine(url)
    ids = {}
    try:
        with engine.begin() as db:
            ids["real"] = db.execute(
                text(
                    "INSERT INTO film_rolls (title, archive_serial, status, camera, developer, created_at)"
                    " VALUES ('London 2026 + Birthday', 'NEG-2026-0001', 'scanned',"
                    " 'Nikon F5', 'Kodak D76', now()) RETURNING id"
                )
            ).scalar_one()
            ids["invented"] = db.execute(
                text(
                    "INSERT INTO film_rolls (title, archive_serial, status, source_dir, created_at)"
                    " VALUES ('rolls', 'NEG-2026-0002', 'scanned', '/data/share/rolls', now())"
                    " RETURNING id"
                )
            ).scalar_one()
            for n in range(1, 34):
                db.execute(
                    text(
                        "INSERT INTO image_assets (film_roll_id, type, path, original_filename,"
                        " frame_number, storage_mode, positive, created_at)"
                        " VALUES (:roll, 'scan', :path, :name, 2026, 'managed', true, now())"
                    ),
                    {
                        "roll": ids["real"],
                        "path": f"static/uploads/scans/{n:03d}.jpg",
                        "name": f"NEG_2026_0001_{n:03d}.jpg",
                    },
                )
                db.execute(
                    text(
                        "INSERT INTO image_assets (film_roll_id, type, path, source_path,"
                        " original_filename, frame_number, storage_mode, created_at)"
                        " VALUES (:roll, 'scan', :path, :path, :name, :frame, 'linked', now())"
                    ),
                    {
                        "roll": ids["invented"],
                        "path": f"/data/share/rolls/NEG-2026-0001_Frame{n:03d}.ARW",
                        "name": f"NEG-2026-0001_Frame{n:03d}.ARW",
                        "frame": n,
                    },
                )
    finally:
        engine.dispose()
    return ids


def repair(url: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join("scripts", "repair_misfiled_rolls.py"), *extra],
        cwd=REPO_ROOT,
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
    )


def rows(url: str, sql: str, **params):
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            return db.execute(text(sql), params).all()
    finally:
        engine.dispose()


def test_a_dry_run_describes_both_repairs_and_writes_nothing():
    with scratch_database() as url:
        ids = build_broken_archive(url)
        result = repair(url)
        assert result.returncode == 0, result.stderr

        assert '"rolls": 33 frames name NEG-2026-0001' in result.stdout
        assert "2026→1" in result.stdout
        assert "Dry run" in result.stdout

        still_there = rows(url, "SELECT film_roll_id, count(*) FROM image_assets GROUP BY 1")
        assert sorted(still_there) == sorted([(ids["real"], 33), (ids["invented"], 33)])
        assert rows(url, "SELECT count(*) FROM image_assets WHERE frame_number = 2026")[0][0] == 33


def test_apply_puts_the_roll_back_together():
    with scratch_database() as url:
        ids = build_broken_archive(url)
        assert repair(url, "--apply").returncode == 0

        # One roll, holding both halves: 33 raw negatives and 33 positives.
        assert rows(url, "SELECT count(*) FROM film_rolls") == [(1,)]
        surviving = rows(url, "SELECT id, title, camera FROM film_rolls")[0]
        assert surviving == (ids["real"], "London 2026 + Birthday", "Nikon F5")
        assert rows(url, "SELECT count(*) FROM image_assets WHERE film_roll_id = :r", r=ids["real"]) == [(66,)]

        # And every frame number now comes from the name of its file.
        numbered = rows(
            url,
            "SELECT frame_number, count(*) FROM image_assets GROUP BY 1 ORDER BY 1",
        )
        assert numbered == [(n, 2) for n in range(1, 34)]

        # Idempotent: a second run has nothing left to do.
        again = repair(url, "--apply")
        assert "No roll is holding another roll's frames." in again.stdout
        assert "Every frame number already matches its filename." in again.stdout


def test_a_roll_somebody_has_typed_into_is_never_removed():
    """The husk goes; a roll with details on it is emptied and kept."""
    with scratch_database() as url:
        ids = build_broken_archive(url)
        engine = create_engine(url)
        try:
            with engine.begin() as db:
                db.execute(
                    text("UPDATE film_rolls SET notes = 'I typed this' WHERE id = :i"),
                    {"i": ids["invented"]},
                )
        finally:
            engine.dispose()

        result = repair(url, "--apply")
        assert "kept (it has details typed into it)" in result.stdout
        assert rows(url, "SELECT count(*) FROM film_rolls") == [(2,)]
        # Emptied, and no longer claiming the watch folder as its own.
        assert rows(
            url, "SELECT count(*) FROM image_assets WHERE film_roll_id = :i", i=ids["invented"]
        ) == [(0,)]
        assert rows(url, "SELECT source_dir FROM film_rolls WHERE id = :i", i=ids["invented"]) == [(None,)]


def test_no_renumber_leaves_the_frame_numbers_alone():
    with scratch_database() as url:
        build_broken_archive(url)
        assert repair(url, "--apply", "--no-renumber").returncode == 0
        assert rows(url, "SELECT count(*) FROM image_assets WHERE frame_number = 2026")[0][0] == 33


def test_a_healthy_archive_is_left_alone():
    with scratch_database() as url:
        run(url, upgrade, "head")
        engine = create_engine(url)
        try:
            with engine.begin() as db:
                roll = db.execute(
                    text(
                        "INSERT INTO film_rolls (title, archive_serial, status, created_at)"
                        " VALUES ('Kyoto rain', 'NEG-2026-0009', 'scanned', now()) RETURNING id"
                    )
                ).scalar_one()
                db.execute(
                    text(
                        "INSERT INTO image_assets (film_roll_id, type, path, original_filename,"
                        " frame_number, storage_mode, created_at)"
                        " VALUES (:r, 'scan', 'a.tif', 'NEG-2026-0009_007.tif', 7, 'managed', now())"
                    ),
                    {"r": roll},
                )
        finally:
            engine.dispose()

        result = repair(url, "--apply")
        assert "No roll is holding another roll's frames." in result.stdout
        assert "Every frame number already matches its filename." in result.stdout
        assert rows(url, "SELECT count(*) FROM film_rolls") == [(1,)]
