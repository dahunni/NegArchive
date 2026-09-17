#!/usr/bin/env python3
"""Fill an empty archive with a few rolls, so there is something to look at.

    DATABASE_URL=… DATA_DIR=… .venv/bin/python scripts/seed_demo.py

Used by CI before the Playwright smoke test (which walks a *populated* archive:
it searches, filters, opens the fullest roll and drives the frame viewer) and by
anyone refreshing the README screenshots. Not called at startup and not part of
the application — an archive is somebody's real work, and inventing rolls in it
would be rude.

Idempotent: it skips any roll whose archive serial is already there, so running
it twice does nothing the second time.
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

from app import paths  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import FilmRoll, ImageAsset, ImageType, Location, SleeveLayout  # noqa: E402
from app.services import lifecycle  # noqa: E402
from app.services import locations as loc_svc  # noqa: E402
from app.services.hashing import safe_content_hash  # noqa: E402

#: (serial, title, camera, film, building, folder, start, end, frames)
ROLLS = [
    ("NEG-2024-0001", "Harbour at dawn", "Nikon F5", "Fomapan 400", "Archive A", "Binder 1", date(2024, 7, 1), date(2024, 7, 3), 8),
    ("NEG-2024-0002", "Kyoto in the rain", "Minolta XG9", "Kodak Gold 200", "Archive A", "Binder 1", date(2024, 8, 12), date(2024, 8, 19), 12),
    ("NEG-2024-0003", "Harbour, second visit", "Nikon F5", "Fomapan 100", "Archive A", "Binder 2", date(2024, 9, 2), date(2024, 9, 2), 6),
    ("NEG-2024-0004", "Winter light", "Nikon F5", "Fomapan 200", "Archive B", "Box 3", date(2024, 12, 20), date(2025, 1, 4), 5),
    ("NEG-2025-0001", "The long walk", "Minolta XG9", "Kodak Gold 200", "Archive B", "Box 3", date(2025, 3, 8), date(2025, 3, 8), 9),
]

#: Base tone per roll, so the thumbnails are distinguishable at a glance.
SHADES = [(196, 186, 172), (150, 143, 134), (122, 112, 104), (176, 170, 160), (98, 94, 92)]


def frame_image(roll_index: int, frame_number: int) -> Image.Image:
    """A placeholder that reads as a scanned negative at thumbnail size.

    3:2 like 35mm, sprocketed edges, and a few soft shapes whose positions come
    from the frame number, so consecutive frames look related but not identical.
    Good enough for a screenshot; obviously not a photograph, which is the point.
    """
    width, height = 600, 400
    base = SHADES[roll_index % len(SHADES)]
    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image)

    # Soft blobs, deterministic from (roll, frame).
    seed = roll_index * 37 + frame_number * 101
    for blob in range(4):
        value = seed + blob * 53
        cx = 60 + (value * 47) % (width - 120)
        cy = 70 + (value * 29) % (height - 140)
        radius = 24 + (value * 13) % 70
        tint = min(250, base[0] + 35 + (value % 40))
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(tint, tint - 4, tint - 10))

    # Sprocketed edges, top and bottom.
    edge = 26
    draw.rectangle([0, 0, width, edge], fill=(24, 24, 26))
    draw.rectangle([0, height - edge, width, height], fill=(24, 24, 26))
    for x in range(14, width - 20, 44):
        draw.rounded_rectangle([x, 6, x + 26, edge - 6], radius=3, fill=(238, 238, 238))
        draw.rounded_rectangle([x, height - edge + 6, x + 26, height - 6], radius=3, fill=(238, 238, 238))

    draw.text((16, edge + 8), f"{frame_number:03d}", fill=(250, 250, 250))
    return image


def seed_locations(db) -> dict:
    """Archive A / Shelf 1 / Binder 1 + 2 (with pages) and Archive B / Box 3 (M4).

    Returns ``{(building, folder): node}`` so the rolls above can be filed.
    """
    layout = db.query(SleeveLayout).filter(SleeveLayout.is_default.is_(True)).first()

    def ensure(parent, kind, name, code=None, **extra):
        query = db.query(Location).filter(Location.name == name, Location.kind == kind)
        query = query.filter(Location.parent_id == (parent.id if parent else None))
        node = query.first()
        if node is None:
            node = Location(parent_id=parent.id if parent else None, kind=kind, name=name, code=code, **extra)
            db.add(node)
            db.flush()
        return node

    archive_a = ensure(None, "building", "Archive A", "A")
    shelf = ensure(archive_a, "shelf", "Shelf 1", "S1")
    row = ensure(shelf, "row", "Row 1", "R1")
    binder1 = ensure(row, "binder", "Binder 1", "B01", capacity=20, sleeve_layout_id=layout.id if layout else None)
    binder2 = ensure(row, "binder", "Binder 2", "B02", capacity=20, sleeve_layout_id=layout.id if layout else None)
    for binder in (binder1, binder2):
        if not any(c.kind == "sleeve" for c in binder.children):
            loc_svc.add_pages(db, binder, 10, layout)
    archive_b = ensure(None, "building", "Archive B", "B")
    box = ensure(archive_b, "box", "Box 3", "X3", capacity=40)
    ensure(archive_b, "envelope", "DM envelope (unsorted)", "ENV")
    db.flush()
    return {
        ("Archive A", "Binder 1"): binder1,
        ("Archive A", "Binder 2"): binder2,
        ("Archive B", "Box 3"): box,
    }


def seed_lifecycle_rolls(db) -> None:
    """One roll in a camera and one at the lab, so the work lists have something in them."""
    from app.models import Camera
    from app.services import serials

    if db.query(FilmRoll).filter(FilmRoll.status.in_(("loaded", "at_lab"))).first():
        return
    camera = db.query(Camera).order_by(Camera.id.asc()).first()
    loaded = FilmRoll(title="Spring street walk", camera=camera.name if camera else None, camera_id=camera.id if camera else None, film_type="Fomapan 400", start_date=date.today())
    serials.assign(db, loaded, None)
    db.add(loaded)
    db.flush()
    if camera:
        lifecycle.load_into_camera(db, camera, loaded)
    else:
        lifecycle.set_status(loaded, "loaded")
    at_lab = FilmRoll(title="Birthday roll", film_type="Kodak Gold 200", start_date=date.today())
    serials.assign(db, at_lab, None)
    db.add(at_lab)
    db.flush()
    lifecycle.set_status(at_lab, "at_lab")
    print(f"seeded {loaded.archive_serial} (in camera) and {at_lab.archive_serial} (at the lab)")


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set.")

    target = paths.uploads_dir() / "scans"
    target.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    created = 0
    try:
        tree = seed_locations(db)
        for index, (serial, title, camera, film, building, folder, start, end, count) in enumerate(ROLLS):
            if db.query(FilmRoll).filter(FilmRoll.archive_serial == serial).first():
                print(f"skip {serial} ({title}) — already there")
                continue

            roll = FilmRoll(
                title=title,
                archive_serial=serial,
                camera=camera,
                film_type=film,
                building=building,
                folder=folder,
                start_date=start,
                end_date=end,
                notes=f"Seeded demo roll. {count} frames.",
            )
            db.add(roll)
            db.flush()

            for frame_number in range(1, count + 1):
                filename = f"{serial}_{frame_number:03d}.jpg"
                absolute = target / filename
                frame_image(index, frame_number).save(absolute, format="JPEG", quality=80)
                db.add(
                    ImageAsset(
                        film_roll_id=roll.id,
                        type=ImageType.scan,
                        path=paths.public_path("uploads", "scans", filename),
                        frame_number=frame_number,
                        original_filename=filename,
                        storage_mode="managed",
                        content_hash=safe_content_hash(absolute),
                        capture_date=start,
                    )
                )
            created += 1
            # M4: file the roll where the old free-text columns say it is.
            lifecycle.touch_scanned(roll)
            target_node = tree.get((building, folder))
            if target_node is not None:
                loc_svc.move_roll(db, roll, target_node, note="Seeded")
            print(f"seeded {serial} ({title}) with {count} frames → {loc_svc.path_string(roll.location_ref) if roll.location_ref else 'unfiled'}")

        seed_lifecycle_rolls(db)
        db.commit()
    finally:
        db.close()

    print(f"done: {created} roll(s) added")


if __name__ == "__main__":
    main()
