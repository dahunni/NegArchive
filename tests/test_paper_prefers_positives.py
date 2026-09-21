"""What goes on paper when a frame has two files (2026-09-21).

A roll scanned through NegPy ends up with two files per frame: the raw negative
the scanner made and the positive NegPy exported from it. Both are scans of the
same frame and both belong in the archive — but a cover sheet, an index card or
a roll-list thumbnail can only show one of them, and it has to be the positive.
Thirty-six orange negatives tell you nothing about a roll, and before this the
raw won every time simply for having the lower id.

Two mechanisms do this, and they cover different cases.

M8's :mod:`app.services.renditions` is the main one: the export is hung off the
negative it was made from, so there is only ever *one* frame, and every surface
shows it with the export's picture. `strips.better_for_paper` is the fallback
for two frames that merely share a number and are not paired — two scans of one
negative, or an export the archive could not match to anything.
"""

import io
import os

import pytest
from PIL import Image as PILImage

from app.services import strips


def unique(prefix: str) -> str:
    return f"{prefix}-{os.urandom(4).hex()}"


def jpeg_bytes(color=(90, 40, 20)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 8), color).save(buf, format="JPEG")
    return buf.getvalue()


def make_roll(client, **fields) -> dict:
    res = client.post("/api/films", json={"title": unique("Roll"), **fields})
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id: int, filename: str, frame_number: int, positive=None) -> dict:
    form = {"type": "scan", "film_roll_id": str(roll_id), "frame_number": str(frame_number)}
    if positive is not None:
        form["positive"] = "true" if positive else "false"
    res = client.post(
        "/api/images/upload", files={"file": (filename, jpeg_bytes(), "image/jpeg")}, data=form
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


def scanned_roll(client, frames=3):
    """A roll as NegPy leaves it: the negative first, then the positive exported from it."""
    roll = make_roll(client)
    serial = roll["archive_serial"]
    pairs = []
    for n in range(1, frames + 1):
        negative = upload(client, roll["id"], f"{serial}_Frame{n:03d}.jpg", n)
        positive = upload(client, roll["id"], f"{serial}_{n:03d}_HP5 Plus.jpg", n, positive=True)
        pairs.append((negative, positive))
    return roll, pairs


# --- the rule itself ----------------------------------------------------------


@pytest.mark.parametrize(
    "current,candidate,expected",
    [
        ({"id": 1, "positive": None}, {"id": 2, "positive": True}, True),  # the export wins
        ({"id": 1, "positive": True}, {"id": 2, "positive": None}, False),  # …either way round
        ({"id": 1, "positive": True}, {"id": 2, "positive": True}, True),  # newest export
        ({"id": 2, "positive": True}, {"id": 1, "positive": True}, False),
        ({"id": 1, "positive": None}, {"id": 2, "positive": None}, False),  # no positive: as before
        ({"id": 1, "positive": False}, {"id": 2, "positive": True}, True),
    ],
)
def test_better_for_paper(current, candidate, expected):
    assert strips.better_for_paper(current, candidate) is expected


def test_the_sleeve_grid_shows_the_positive():
    cells = strips.grid(
        [
            {"id": 10, "frame_number": 1, "positive": None},
            {"id": 11, "frame_number": 1, "positive": True},
            {"id": 12, "frame_number": 2, "positive": None},
        ],
        [2],
    )
    assert [cell["id"] for cell in cells[0]] == [11, 12]


# --- and through the API ------------------------------------------------------


def test_the_roll_lists_cover_strip_shows_the_export(client):
    """The strip links to the *frame* (M8) and shows the export's picture."""
    roll, pairs = scanned_roll(client, frames=3)
    listed = next(r for r in client.get("/api/films").json() if r["id"] == roll["id"])
    assert listed["cover_image_ids"] == [negative["id"] for negative, _positive in pairs]
    assert listed["image_count"] == 3, "three frames, not six files"

    detail = client.get(f"/api/films/{roll['id']}").json()["images"]
    by_id = {f["id"]: f for f in detail}
    assert listed["cover_versions"] == [
        by_id[negative["id"]]["rendition"]["preview_version"] for negative, _p in pairs
    ], "the thumbnail is of the export, not of the negative"


def test_the_sleeve_layout_puts_the_export_in_the_cell(client):
    roll, pairs = scanned_roll(client, frames=3)
    layout = client.get(f"/api/films/{roll['id']}/layout").json()
    cells = [cell for row in layout["rows"] for cell in row if cell]
    assert [cell["id"] for cell in cells] == [negative["id"] for negative, _p in pairs]

    detail = {f["id"]: f for f in client.get(f"/api/films/{roll['id']}").json()["images"]}
    assert [cell["preview_version"] for cell in cells] == [
        detail[negative["id"]]["rendition"]["preview_version"] for negative, _p in pairs
    ]


def test_nothing_is_called_unplaced_for_a_roll_that_went_through_negpy(client):
    roll, _pairs = scanned_roll(client, frames=3)
    layout = client.get(f"/api/films/{roll['id']}/layout").json()
    assert layout["unplaced"] == []


def test_a_roll_with_no_positives_is_unchanged(client):
    """The old rule where there is nothing to prefer: first in display order."""
    roll = make_roll(client)
    frames = [upload(client, roll["id"], f"plain_{n:03d}.jpg", n) for n in (1, 2, 3)]
    listed = next(r for r in client.get("/api/films").json() if r["id"] == roll["id"])
    assert listed["cover_image_ids"] == [f["id"] for f in frames]
    layout = client.get(f"/api/films/{roll['id']}/layout").json()
    cells = [cell for row in layout["rows"] for cell in row if cell]
    assert [cell["id"] for cell in cells] == [f["id"] for f in frames]


def test_a_frame_past_the_sleeve_is_still_reported_unplaced(client):
    """The guard that matters: "unplaced" must keep meaning something."""
    roll = make_roll(client, strips=[2])
    upload(client, roll["id"], "p_001.jpg", 1)
    beyond = upload(client, roll["id"], "p_009.jpg", 9)
    layout = client.get(f"/api/films/{roll['id']}/layout").json()
    assert [f["id"] for f in layout["unplaced"]] == [beyond["id"]]
