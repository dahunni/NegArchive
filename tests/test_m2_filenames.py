"""Original filenames and the frame numbers hiding in them (M2, R#7, R#24).

For an archive the scanner's filename is the link between a physical frame and its
file. Every upload path keeps it, parses a frame number out of it when the client did
not send one, and every list comes back in frame order.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage

from app import paths
from app.routers.api import frame_number_from_filename


def on_disk(stored_path: str) -> str:
    """Where a stored path really is (M3: under DATA_DIR, not the working directory)."""
    return str(paths.resolve(stored_path))


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def png_bytes(color=(10, 20, 30), size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def make_roll(client, **fields) -> dict:
    payload = {"title": unique("Roll")}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, filename: str, roll_id=None, **data) -> dict:
    form = {"type": "scan", **{k: str(v) for k, v in data.items()}}
    if roll_id is not None:
        form["film_roll_id"] = str(roll_id)
    res = client.post(
        "/api/images/upload", files={"file": (filename, png_bytes(), "image/png")}, data=form
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


# --- the parser itself --------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("Roll12_007.tif", 7),  # NegPy's {roll}_{frame}
        ("NEG-2024-011_007.jpg", 7),
        ("scan_Frame007.tif", 7),
        ("_Frame007.jpg", 7),
        ("Frame 12.png", 12),
        ("007.jpg", 7),
        ("img_0007.png", 7),
        ("IMG-0042.dng", 42),
        ("Roll001_Frame023.ARW", 23),  # NegPy's camera-scan mode (M6.1)
        ("NEG-2026-0007_Frame023.ARW", 23),  # the same, with the archive's serial as the roll
        ("/somewhere/else/Roll12_009.tiff", 9),
        ("Roll12.tif", None),  # a number glued to a word is part of the word
        ("untitled.jpg", None),
        ("", None),
        (None, None),
    ],
)
def test_frame_number_from_filename(filename, expected):
    assert frame_number_from_filename(filename) == expected


# --- single upload ------------------------------------------------------------


def test_single_upload_keeps_the_name_and_reads_the_frame_number(client):
    roll = make_roll(client)
    frame = upload(client, "Roll12_007.tif".replace(".tif", ".png"), roll["id"])
    assert frame["original_filename"] == "Roll12_007.png"
    assert frame["frame_number"] == 7
    assert frame["storage_mode"] == "managed"
    # and it is still there on the read path
    assert client.get(f"/api/images/{frame['id']}").json()["original_filename"] == "Roll12_007.png"


def test_an_explicit_frame_number_beats_the_filename(client):
    roll = make_roll(client)
    frame = upload(client, "Roll12_007.png", roll["id"], frame_number=99)
    assert frame["frame_number"] == 99


def test_a_contact_sheet_is_not_given_a_frame_number(client):
    roll = make_roll(client)
    res = client.post(
        "/api/images/upload",
        files={"file": ("Roll12_007.png", png_bytes(), "image/png")},
        data={"type": "contact_sheet", "film_roll_id": str(roll["id"])},
    )
    assert res.status_code == 200, res.text
    assert res.json()["image"]["frame_number"] is None
    assert res.json()["image"]["original_filename"] == "Roll12_007.png"


def test_the_download_is_named_like_the_original(client):
    roll = make_roll(client)
    frame = upload(client, "Roll12_007.png", roll["id"])
    res = client.get(f"/api/images/{frame['id']}/download")
    assert res.status_code == 200
    assert 'filename="Roll12_007.png"' in res.headers["content-disposition"]


# --- bulk and ZIP -------------------------------------------------------------


def test_bulk_upload_keeps_every_name(client):
    roll = make_roll(client)
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("Roll12_002.png", png_bytes(), "image/png")),
            ("files", ("Roll12_001.png", png_bytes(), "image/png")),
        ],
    )
    assert res.status_code == 200, res.text
    images = res.json()["images"]
    assert [i["original_filename"] for i in images] == ["Roll12_002.png", "Roll12_001.png"]
    assert sorted(i["frame_number"] for i in images) == [1, 2]


def test_zip_upload_keeps_names_and_numbers(client):
    import zipfile

    roll = make_roll(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("roll/NEG-2024-011_003.png", png_bytes())
        zf.writestr("roll/NEG-2024-011_001.png", png_bytes())
        zf.writestr("roll/notes.txt", "not an image")
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk_zip",
        files={"file": ("roll.zip", buf.getvalue(), "application/zip")},
    )
    assert res.status_code == 200, res.text
    images = res.json()["images"]
    assert len(images) == 2, "the .txt is skipped"
    assert {i["original_filename"] for i in images} == {
        "NEG-2024-011_003.png",
        "NEG-2024-011_001.png",
    }
    assert sorted(i["frame_number"] for i in images) == [1, 3]


# --- ordering (R#24) ----------------------------------------------------------


def test_the_roll_lists_its_frames_in_frame_order(client):
    roll = make_roll(client)
    third = upload(client, "c.png", roll["id"], frame_number=3)
    first = upload(client, "a.png", roll["id"], frame_number=1)
    unnumbered = upload(client, "z.png", roll["id"])
    second = upload(client, "b.png", roll["id"], frame_number=2)

    listed = client.get(f"/api/films/{roll['id']}").json()["images"]
    assert [i["id"] for i in listed] == [first["id"], second["id"], third["id"], unnumbered["id"]]


def test_the_frames_endpoint_sorts_the_same_way(client):
    roll = make_roll(client)
    second = upload(client, "b.png", roll["id"], frame_number=6)
    first = upload(client, "a.png", roll["id"], frame_number=5)
    loose = upload(client, "z.png", roll["id"])

    listed = client.get(f"/api/images?film_id={roll['id']}&type=scan").json()
    assert [i["id"] for i in listed] == [first["id"], second["id"], loose["id"]]


def test_the_contact_sheet_is_laid_out_in_frame_order(client):
    """The sheet's first cell must be frame 1, whatever order the files arrived in."""
    roll = make_roll(client)
    colors = {1: (255, 0, 0), 2: (0, 255, 0), 3: (0, 0, 255)}
    for number in (3, 1, 2):  # deliberately out of order
        client.post(
            "/api/images/upload",
            files={"file": (f"f{number}.png", png_bytes(colors[number], (40, 40)), "image/png")},
            data={"type": "scan", "film_roll_id": str(roll["id"]), "frame_number": str(number)},
        )

    res = client.post(f"/api/films/{roll['id']}/contact_sheet?columns=3&thumb_size=40")
    assert res.status_code == 200, res.text
    sheet = PILImage.open(on_disk(res.json()["image"]["path"])).convert("RGB")
    # The sheet is a JPEG, so compare the dominant channel rather than exact RGB.
    cells = [
        max(range(3), key=lambda c, x=column: sheet.getpixel((20 + 40 * x, 20))[c])
        for column in range(3)
    ]
    assert cells == [0, 1, 2], "red (frame 1), green (2), blue (3), left to right"
