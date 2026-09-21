#!/usr/bin/env python3
"""Repair an archive that went through the NegPy flow before the flow was fixed.

    DATABASE_URL=… .venv/bin/python scripts/repair_negpy_archive.py            # dry run
    DATABASE_URL=… .venv/bin/python scripts/repair_negpy_archive.py --apply

Three bugs, all fixed for good elsewhere, left wrong rows behind in every archive
that had already scanned a roll through the NegPy flow. This walks what is there
and offers to correct it. It reads filenames, XMP the archive already recorded
and the serials it already holds; the only file it ever deletes is one superseded
by a newer export of the same frame, and only when the archive owns it.

**The roll in the archive twice.** NegPy's scan mode, pointed straight at the
watch folder instead of a subfolder under it, wrote ``NEG-2026-0001_Frame001.ARW``
and its 32 siblings into ``…/rolls``. :mod:`app.services.importer` only ever read
the *folder* name, so it made a roll called "rolls" with a serial of its own, and
the real roll — the one that knows the camera, the film and where the negatives
are filed — sat next to it, empty. Any roll whose frames unanimously name a
different roll that the archive actually has is that roll's frames: they move,
and the husk they were on is removed once it is empty and nobody has typed
anything into it.

**The whole roll filed as frame 2026.** NegPy's export templating slugs the roll
name, so ``NEG-2026-0001`` comes back as ``NEG_2026_0001_001.jpg`` — and the
preset parser, reading ``<roll>_<frame>_<film>`` by shape alone, took the year as
the frame and ``0001_001`` as the film. Every frame of the roll became 2026. Any
frame whose filename now reads differently from what is stored is offered the
number in its name.

**Every frame counted twice.** A roll that has been through NegPy holds two files
per frame — the raw negative and the positive NegPy exported from it. Before M8
those were two rows, so a 33-frame roll listed 66 and every frame appeared twice
in every grid. The export is hung off the negative it names
(:mod:`app.services.renditions`), which is the same rule new imports now follow;
where a frame turns out to have several exports, the newest is kept and the rest
are retired with their files.

Every pass is reported before anything is written, and ``--apply`` is the only
thing that writes. The renumbering pass is the same rule as the roll page's
"Renumber → from filenames", so it can equally well be done in the UI, one roll at
a time, with the plan on screen — this is for doing it to a whole archive at once.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal  # noqa: E402
from app.models import FilmRoll, ImageAsset, ImageType  # noqa: E402
from app.routers.api import delete_asset_file, frame_number_from_filename  # noqa: E402
from app.services import renditions as renditions_svc  # noqa: E402
from app.services import serials  # noqa: E402

#: Columns that mean a person has been here. A roll carrying any of them is never
#: removed, however empty it ends up: re-typing them is the one cost this script
#: must not impose.
TOUCHED = (
    "camera_id",
    "lens_id",
    "film_stock_id",
    "notes",
    "developer",
    "development_dilution",
    "push_pull",
    "development_time",
    "start_date",
    "end_date",
    "location_id",
    "building",
    "folder",
    "label_printed_at",
)


def _scans(db, roll_id: int) -> list[ImageAsset]:
    return (
        db.query(ImageAsset)
        .filter(ImageAsset.film_roll_id == roll_id, ImageAsset.type == ImageType.scan)
        .order_by(ImageAsset.id)
        .all()
    )


def _claimed_roll(db, frames: list[ImageAsset], cache: dict) -> Optional[FilmRoll]:
    """The one roll every frame's filename names, or None if they do not agree.

    Unanimity is the point. A roll holding frames from two different rolls is a
    mess a script should describe and not silently rearrange, and a roll whose
    filenames say nothing is simply a roll that was named by hand.
    """
    claimed = set()
    for frame in frames:
        serial = serials.serial_in_filename(frame.original_filename)
        if serial is None:
            return None
        claimed.add(serial)
    if len(claimed) != 1:
        return None
    serial = claimed.pop()
    if serial not in cache:
        cache[serial] = serials.find_by_serial_loose(db, serial)
    return cache[serial]


def find_misfiled(db) -> list[tuple[FilmRoll, FilmRoll, list[ImageAsset]]]:
    """``[(from_roll, to_roll, frames)]`` for every roll that is really another one."""
    out = []
    cache: dict = {}
    for roll in db.query(FilmRoll).order_by(FilmRoll.id).all():
        frames = _scans(db, roll.id)
        if not frames:
            continue
        target = _claimed_roll(db, frames, cache)
        if target is None or target.id == roll.id:
            continue
        out.append((roll, target, frames))
    return out


def find_renumbers(db) -> dict[int, list[tuple[ImageAsset, int]]]:
    """``{roll_id: [(frame, number_its_filename_says)]}`` where the two disagree."""
    out: dict[int, list[tuple[ImageAsset, int]]] = defaultdict(list)
    for frame in (
        db.query(ImageAsset).filter(ImageAsset.type == ImageType.scan).order_by(ImageAsset.id).all()
    ):
        derived = frame_number_from_filename(frame.original_filename)
        if derived is not None and derived != frame.frame_number:
            out[frame.film_roll_id].append((frame, derived))
    return out


def find_unpaired_exports(db) -> list[tuple[ImageAsset, ImageAsset]]:
    """``[(export, negative)]`` for every NegPy export still standing as a frame."""
    out = []
    for image in (
        db.query(ImageAsset)
        .filter(ImageAsset.type == ImageType.scan, ImageAsset.derived_from_id.is_(None))
        .order_by(ImageAsset.id)
        .all()
    ):
        negative = renditions_svc.negative_for(db, image)
        if negative is not None:
            out.append((image, negative))
    return out


def _is_untouched(roll: FilmRoll) -> bool:
    return not any(getattr(roll, column) for column in TOUCHED)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument(
        "--no-renumber", action="store_true", help="leave frame numbers as they are"
    )
    parser.add_argument(
        "--no-pair", action="store_true", help="leave NegPy exports standing as frames of their own"
    )
    parser.add_argument(
        "--keep-empty-rolls",
        action="store_true",
        help="do not remove a roll left empty by a merge",
    )
    args = parser.parse_args()

    # A dry run does the whole repair and then rolls it back. Reporting it pass by
    # pass without doing it would lie about everything downstream: until the
    # misfiled roll is merged, the exports and their negatives are still on two
    # different rolls, and the pairing pass would truthfully report nothing to do.
    # Files are the one thing a transaction cannot take back, so on a dry run
    # nothing is handed the deleter.
    delete = delete_asset_file if args.apply else None

    db = SessionLocal()
    changed = False
    try:
        misfiled = find_misfiled(db)
        if not misfiled:
            print("No roll is holding another roll's frames.")
        for roll, target, frames in misfiled:
            print(
                f"roll {roll.id} {roll.archive_serial or '(no serial)'} "
                f'"{roll.title}": {len(frames)} frames name '
                f'{target.archive_serial} "{target.title}" (roll {target.id})'
            )
            for frame in frames[:3]:
                print(f"    {frame.original_filename}")
            if len(frames) > 3:
                print(f"    … and {len(frames) - 3} more")
            # Through the relationship, not the id: `FilmRoll.images` cascades
            # delete-orphan, so a roll removed below would take frames with it
            # that the session still believes are its own.
            for frame in frames:
                frame.film_roll = target
            db.flush()
            changed = True
            if args.keep_empty_rolls:
                print(f"  → moved; roll {roll.id} left in place and empty")
                continue
            if not _is_untouched(roll):
                roll.source_dir = None
                print(f"  → moved; roll {roll.id} kept (it has details typed into it)")
                continue
            db.delete(roll)
            db.flush()
            print(f"  → moved, and the empty roll {roll.id} removed")

        if not args.no_renumber:
            # After the merge, so a moved frame is reported under the roll it
            # now belongs to rather than the one it was rescued from.
            print()
            renumbers = find_renumbers(db)
            if not renumbers:
                print("Every frame number already matches its filename.")
            for roll_id, pairs in sorted(renumbers.items()):
                roll = db.get(FilmRoll, roll_id)
                shown = ", ".join(f"{f.frame_number}→{n}" for f, n in pairs[:6])
                more = f", … and {len(pairs) - 6} more" if len(pairs) > 6 else ""
                print(
                    f"roll {roll_id} {roll.archive_serial or '(no serial)'} "
                    f'"{roll.title}": {len(pairs)} frames  {shown}{more}'
                )
                for frame, number in pairs:
                    frame.frame_number = number
                changed = True
            db.flush()

        if not args.no_pair:
            # Last, because an export only finds its negative once both are on
            # the same roll and numbered the same.
            print()
            unpaired = find_unpaired_exports(db)
            if not unpaired:
                print("Every NegPy export is already hung off its negative.")
            by_roll: dict = defaultdict(list)
            for export, negative in unpaired:
                by_roll[negative.film_roll_id].append((export, negative))
            for roll_id, pairs in sorted(by_roll.items(), key=lambda kv: kv[0] or 0):
                roll = db.get(FilmRoll, roll_id) if roll_id else None
                name = f'{roll.archive_serial} "{roll.title}"' if roll else "(no roll)"
                print(f"roll {roll_id} {name}: {len(pairs)} exports become renditions")
                for export, negative in pairs[:3]:
                    print(f"    {export.original_filename} → frame {negative.frame_number}")
                if len(pairs) > 3:
                    print(f"    … and {len(pairs) - 3} more")
                for export, _negative in pairs:
                    renditions_svc.attach(db, export, delete_file=delete)
                changed = True
            db.flush()

        if not changed:
            db.rollback()
            print("\nNothing to do.")
        elif args.apply:
            db.commit()
            print("\nWritten.")
        else:
            db.rollback()
            print("\nDry run — nothing written. Re-run with --apply.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
