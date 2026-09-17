#!/usr/bin/env python3
"""Draw the PWA icons (roadmap M3).

    .venv/bin/python scripts/make_icons.py

The icons are checked in — a build must not need this script — but they are
*generated* rather than drawn by hand so the motif can be changed in one place
and so nobody has to wonder where a stray PNG came from.

The motif is a single 35mm frame with its sprocket holes: the smallest thing that
reads as "film" at 48 pixels on a phone's home screen, and unambiguous next to a
photo app's icon. White on near-black, because the icon sits on wallpapers we do
not control and a maskable icon gets cropped to a circle on Android.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"

BACKGROUND = (10, 10, 11, 255)
FOREGROUND = (250, 250, 250, 255)

#: (filename, size, safe-area fraction). A maskable icon must keep everything
#: important inside the middle 80%, because Android crops it to whatever shape
#: the launcher uses.
TARGETS = [
    ("icon-192.png", 192, 0.82),
    ("icon-512.png", 512, 0.82),
    ("icon-maskable-512.png", 512, 0.62),
    ("apple-touch-icon.png", 180, 0.82),
]

#: Supersampling factor: draw big, shrink down, get smooth edges without any
#: antialiasing code of our own.
SCALE = 4


def draw_icon(size: int, content: float) -> Image.Image:
    canvas = size * SCALE
    image = Image.new("RGBA", (canvas, canvas), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # The film strip: a rounded rectangle a little wider than it is tall.
    strip_w = canvas * content
    strip_h = strip_w * 0.72
    left = (canvas - strip_w) / 2
    top = (canvas - strip_h) / 2
    radius = strip_w * 0.06
    draw.rounded_rectangle(
        [left, top, left + strip_w, top + strip_h], radius=radius, fill=FOREGROUND
    )

    # The image area, punched out of the strip: a 3:2 frame, as 35mm is.
    margin_x = strip_w * 0.08
    margin_y = strip_h * 0.22
    draw.rectangle(
        [left + margin_x, top + margin_y, left + strip_w - margin_x, top + strip_h - margin_y],
        fill=BACKGROUND,
    )

    # Sprocket holes along the top and bottom edges.
    holes = 6
    hole_w = strip_w * 0.075
    hole_h = strip_h * 0.10
    gap = (strip_w - 2 * margin_x - holes * hole_w) / (holes - 1)
    hole_radius = hole_h * 0.3
    for index in range(holes):
        x0 = left + margin_x + index * (hole_w + gap)
        for y0 in (top + strip_h * 0.055, top + strip_h - strip_h * 0.055 - hole_h):
            draw.rounded_rectangle(
                [x0, y0, x0 + hole_w, y0 + hole_h], radius=hole_radius, fill=BACKGROUND
            )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size, content in TARGETS:
        icon = draw_icon(size, content)
        icon.save(OUT / name, format="PNG", optimize=True)
        print(f"wrote {OUT / name} ({size}×{size})")


if __name__ == "__main__":
    main()
