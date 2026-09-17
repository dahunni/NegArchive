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
from app.models import FilmRoll, ImageAsset, ImageType  # noqa: E402
from app.services.hashing import safe_content_hash  # noqa: E402

#: (serial, title, camera, film, building, folder, start, end, frames)
ROLLS = [
    ("NEG-2024-0001", "Harbour at dawn", "Nikon F5", "Fomapan 400", "Archive A", "Binder 1", date(2024, 7, 1), date(2024, 7, 3), 8),
    ("NEG-2024-0002", "Kyoto in the rain", "Minolta XG9", "Kodak Gold 200", "Archive A", "Binder 1", date(2024, 8, 12), date(2024, 8, 19), 12),
    ("NEG-2024-0003", "Harbour, second visit", "Nikon F5", "Fomapan 100", "Archive A", "Binder 2", date(2024, 9, 2), date(2024, 9, 2), 6),
    ("NEG-2024-0004", "Winter light", "Nikon F5", "Fomapan 200", "Archive B", "Box 3", date(2024, 12, 20), date(2025, 1, 4), 5),
    ("NEG-2025-0001", "The long walk", "Minolta XG9", "Kodak Gold 200", "Archive B", "Box 3", date(2025, 3, 8), date(2025, 3, 8), 9),
]

#: Enough grey levels that the thumbnails are distinguishable at a glance.
SHADES = [(28, 28, 30), (70, 68, 66), (120, 116, 112), (168, 162, 156), (212, 208, 202)]


def frame_image(roll_index: int, frame_number: int) -> Image.Image:
    """A 3:2 placeholder with the frame number on it — 35mm proportions."""
    width, height = 600, 400
    image = Image.new("RGB", (width, height), SHADES[roll_index % len(SHADES)])
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 8, width - 8, height - 8], outline=(245, 245, 245), width=3)
    draw.text((24, 24), f"{frame_number:03d}", fill=(245, 245, 245))
    return image


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is not set.")

    target = paths.uploads_dir() / "scans"
    target.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    created = 0
    try:
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
            print(f"seeded {serial} ({title}) with {count} frames")
        db.commit()
    finally:
        db.close()

    print(f"done: {created} roll(s) added")


if __name__ == "__main__":
    main()
