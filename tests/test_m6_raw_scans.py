"""Camera raws, the files NegPy's scan mode saves (roadmap M6.1).

NegPy's *Live View & Scan* photographs a negative with a tethered camera and writes
the camera's own raw, untouched, as ``Roll001/Roll001_Frame001.ARW``. Before M6.1
the archive answered ``"Roll001_Frame001.ARW" is not an accepted image``.

A real raw is 25–60 MB and cannot be a fixture in the repository, so most of this
is about the archive *behaving* around raws: accepting them, numbering them, and
never turning a file LibRaw cannot open into a 500. One test does decode a real
file, when ``NEGARCHIVE_RAW_FIXTURE`` names one — run it by hand:

    NEGARCHIVE_RAW_FIXTURE=~/Documents/scan/Roll001/Roll001_Frame001.ARW pytest tests/test_m6_raw_scans.py
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from app.routers import api
from app.services import rawdecode

TIFF_LE = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 56


def unique(prefix: str) -> str:
    return f"{prefix}-{os.urandom(4).hex()}"


# --- the allowlist ---------------------------------------------------------------


def test_negpys_raw_list_is_the_archives_raw_list():
    """The extensions NegPy opens (negpy/infrastructure/loaders/constants.py, still
    cameras only). If NegPy can scan into it, the archive must be able to link it."""
    for ext in (".arw", ".nef", ".cr2", ".cr3", ".raf", ".orf", ".rw2", ".pef", ".dng", ".srw", ".x3f"):
        assert ext in rawdecode.RAW_EXTENSIONS
        assert ext in api.ALLOWED_EXTENSIONS
    # Video containers are LibRaw's business, not a film scan's.
    assert ".braw" not in rawdecode.RAW_EXTENSIONS
    assert ".r3d" not in rawdecode.RAW_EXTENSIONS


@pytest.mark.parametrize(
    "head",
    [
        b"FUJIFILMCCD-RAW 0201",
        b"\x00MRM\x00\x00",
        b"FOVb\x00\x00",
        b"\x00\x00\x00\x18ftypcrx ",
        b"II\x1a\x00\x00\x00HEAPCCDR",
        b"IIRO\x08\x00\x00\x00",
        b"IIRS\x08\x00\x00\x00",
        b"MMOR\x00\x00\x00\x08",
        b"IIU\x00\x18\x00\x00\x00",
    ],
)
def test_the_non_tiff_raws_are_recognised_by_their_own_magic(head):
    assert rawdecode.looks_like_raw(head)
    assert api._looks_like_image(head)


def test_html_is_still_not_a_raw():
    for head in (b"<html><script>", b"%PDF-1.7", b"PK\x03\x04", b"\x00" * 16, b""):
        assert not rawdecode.looks_like_raw(head)


def test_the_error_message_names_the_raws_by_example_not_by_the_dozen(client):
    res = client.post(
        "/api/images/upload",
        files={"file": ("Roll001_Frame001.xyz", TIFF_LE, "application/octet-stream")},
        data={"type": "scan"},
    )
    assert res.status_code == 415
    message = res.json()["error"]["message"]
    assert "arw" in message and "nef" in message
    assert message.count(",") < 20  # a phrase, not the whole allowlist


# --- a raw through the archive ---------------------------------------------------


def make_roll(client) -> dict:
    return client.post("/api/films", json={"title": unique("Roll")}).json()["film"]


def test_a_scan_mode_file_is_accepted_and_numbered(client):
    roll = make_roll(client)
    res = client.post(
        "/api/images/upload",
        files={"file": ("Roll001_Frame023.ARW", TIFF_LE, "application/octet-stream")},
        data={"type": "scan", "film_roll_id": str(roll["id"])},
    )
    assert res.status_code == 200, res.text
    image = res.json()["image"]
    assert image["frame_number"] == 23
    assert image["original_filename"] == "Roll001_Frame023.ARW"
    assert image["path"].lower().endswith(".arw")


def test_a_file_libraw_cannot_open_is_a_415_not_a_500(client):
    """A TIFF header with nothing behind it wears .ARW. LibRaw refuses it, Pillow
    refuses it, OpenCV refuses it — and the answer is the honest one from before."""
    roll = make_roll(client)
    res = client.post(
        "/api/images/upload",
        files={"file": ("Roll001_Frame001.ARW", TIFF_LE, "application/octet-stream")},
        data={"type": "scan", "film_roll_id": str(roll["id"])},
    )
    image = res.json()["image"]
    preview = client.get(f"/api/images/{image['id']}/preview", params={"width": 200})
    assert preview.status_code == 415
    assert preview.json()["error"]["code"] == "unreadable_image"
    # And the raw-mode request takes the same road.
    preview = client.get(f"/api/images/{image['id']}/preview", params={"width": 200, "render": "raw"})
    assert preview.status_code == 415


def test_a_contact_sheet_skips_a_raw_it_cannot_read_instead_of_failing(client):
    roll = make_roll(client)
    for name in ("Roll001_Frame001.ARW", "Roll001_Frame002.ARW"):
        client.post(
            "/api/images/upload",
            files={"file": (name, TIFF_LE, "application/octet-stream")},
            data={"type": "scan", "film_roll_id": str(roll["id"])},
        )
    res = client.post(f"/api/films/{roll['id']}/contact_sheet", json={})
    # Two unreadable scans: the same "not enough readable images" answer a folder of
    # broken TIFFs gets, and no traceback.
    assert res.status_code in (200, 400, 422)
    if res.status_code != 200:
        assert res.json()["error"]["code"] == "not_enough_images"


# --- rawpy itself ----------------------------------------------------------------


def test_rawpy_is_in_the_environment():
    """requirements.txt pins it; a CI that installs requirements must have it, or the
    previews above silently degrade to a 415 for every real raw."""
    assert rawdecode.available(), "rawpy did not import — is it installed?"
    assert rawdecode.version() and rawdecode.version().startswith("rawpy ")


def test_decode_helpers_do_not_raise_on_garbage(tmp_path):
    fake = tmp_path / "x.arw"
    fake.write_bytes(TIFF_LE)
    assert rawdecode.embedded_preview(fake) is None
    rawpy = pytest.importorskip("rawpy")
    with pytest.raises(rawpy.LibRawError):
        rawdecode.decode_linear(fake, 200)


FIXTURE = os.getenv("NEGARCHIVE_RAW_FIXTURE", "")


@pytest.mark.skipif(not FIXTURE or not Path(FIXTURE).expanduser().is_file(), reason="set NEGARCHIVE_RAW_FIXTURE to a real raw")
def test_a_real_raw_is_previewed_raw_and_printed(client):
    """Run by hand against a real camera scan. Proves the two decodes and the route."""
    import numpy as np
    from PIL import Image

    from app.services import preview as preview_render

    path = Path(FIXTURE).expanduser()
    assert rawdecode.embedded_preview(path), "this camera stores no JPEG preview; the test needs another file"
    linear = rawdecode.decode_linear(path, 600)
    assert linear.dtype == np.uint16 and linear.shape[2] == 3 and linear.shape[1] <= 600

    stock = client.post("/api/filmstocks", json={"name": unique("Stock"), "iso": 200, "kind": "color"}).json()["filmstock"]
    roll = client.post("/api/films", json={"title": unique("Roll"), "film_stock_id": stock["id"]}).json()["film"]
    with path.open("rb") as handle:
        res = client.post(
            "/api/images/upload",
            files={"file": (path.name, handle, "application/octet-stream")},
            data={"type": "scan", "film_roll_id": str(roll["id"])},
        )
    assert res.status_code == 200, res.text
    image = res.json()["image"]

    raw = client.get(f"/api/images/{image['id']}/preview", params={"width": 400, "render": "raw"})
    printed = client.get(f"/api/images/{image['id']}/preview", params={"width": 400, "render": "positive"})
    assert raw.status_code == 200 and printed.status_code == 200
    assert raw.headers["X-Preview-Render"] == "raw"
    assert printed.headers["X-Preview-Render"] == "positive"
    a = np.asarray(Image.open(io.BytesIO(raw.content)).convert("RGB"))
    b = np.asarray(Image.open(io.BytesIO(printed.content)).convert("RGB"))
    assert a.shape[1] == 400 and b.shape[1] == 400
    # Compare the middle half: the raw carries the black film holder around the
    # frame and the print a white one, and whole-image means cancel out.
    h, w = a.shape[:2]
    middle = (slice(h // 4, 3 * h // 4), slice(w // 4, 3 * w // 4))
    assert abs(float(a[middle].mean()) - float(b[middle].mean())) > 30  # the print is not the negative
    # The second request is a cache hit.
    again = client.get(f"/api/images/{image['id']}/preview", params={"width": 400, "render": "positive"})
    assert again.headers.get("X-Preview-Cache") == "hit"
    client.delete(f"/api/images/{image['id']}")
    del preview_render
