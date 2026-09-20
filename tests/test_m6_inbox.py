"""The inbox: the archive's own share, and the folder that empties itself (M6.2).

The rule under test is simple to state: a finished export dropped in the inbox is
taken *into* the archive — filed, marked a positive — and is gone from the inbox
afterwards; anything the archive could not take stays and is named. See
app/services/inbox.py for the reasoning.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from test_m5_negpy import jpeg_bytes, xmp_packet

from app import paths
from app.services import inbox, share

RECIPE = {"version": 3, "settings": {"invert": True, "exposure": 0.4}}
TIFF_LE = b"II*\x00\x08\x00\x00\x00" + b"\x00" * 56


def unique(prefix: str) -> str:
    return f"{prefix}-{os.urandom(4).hex()}"


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A fresh inbox per test, where a share would put it."""
    target = tmp_path / "inbox"
    monkeypatch.setenv(inbox.INBOX_DIR_ENV, str(target))
    return inbox.ensure()


def drop(box: Path, name: str, payload: bytes, *, settled: bool = True) -> Path:
    """Write a file the way an SMB client would have, some time ago."""
    path = box / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    if settled:
        old = time.time() - 120
        os.utime(path, (old, old))
    return path


def sweep(client) -> dict:
    res = client.post("/api/inbox/sweep")
    assert res.status_code == 200, res.text
    return res.json()


def make_roll(client, title: str | None = None) -> dict:
    stock = client.post("/api/filmstocks", json={"name": unique("Stock"), "iso": 200, "kind": "color"}).json()["filmstock"]
    return client.post("/api/films", json={"title": title or unique("Roll"), "film_stock_id": stock["id"]}).json()["film"]


def frames_of(client, roll_id: int) -> list:
    return client.get(f"/api/films/{roll_id}").json()["images"]


# --- the ordinary case ------------------------------------------------------------------


def test_an_export_is_taken_onto_its_roll_and_leaves_the_inbox(client, box):
    roll = make_roll(client)
    serial = roll["archive_serial"]
    export = jpeg_bytes(xmp=xmp_packet(CaptureRoll=serial, CaptureFrame="12"))
    dropped = drop(box, f"{serial}_012_Gold 200.jpg", export)

    body = sweep(client)
    result = body["result"]
    assert (result["imported"], result["filed"], result["unassigned"]) == (1, 1, 0)

    frames = frames_of(client, roll["id"])
    assert len(frames) == 1
    frame = frames[0]
    assert frame["frame_number"] == 12
    assert frame["positive"] is True  # the inbox holds finished positives
    assert frame["storage_mode"] == "managed"
    assert frame["original_filename"] == dropped.name
    assert paths.resolve(frame["path"]).is_file()  # the bytes now live in the archive
    assert not dropped.exists()  # and no longer in the inbox
    assert body["pending"]["count"] == 0

    # The roll moved on in its life, exactly as an upload would have moved it.
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["status"] == "scanned"
    # And it is never printed: the film is a colour negative, the frame is not.
    preview = client.get(f"/api/images/{frame['id']}/preview", params={"width": 120})
    assert preview.headers["X-Preview-Render"] == "raw"


def test_the_filename_alone_is_enough_to_find_the_roll(client, box):
    roll = make_roll(client)
    # No XMP at all — but unique bytes, or the archive rightly calls it a duplicate
    # of a JPEG some other test uploaded (same pixels, same file).
    drop(box, f"{roll['archive_serial']}_003_HP5 Plus.jpg", jpeg_bytes(exif={271: unique("Make")}))
    sweep(client)
    frames = frames_of(client, roll["id"])
    assert [f["frame_number"] for f in frames] == [3]


def test_a_subfolder_named_after_a_roll_files_everything_in_it(client, box):
    roll = make_roll(client)
    serial = roll["archive_serial"]
    drop(box, f"{serial}/frame_001.jpg", jpeg_bytes(size=(20, 12)))
    drop(box, f"{serial}/frame_002.jpg", jpeg_bytes(size=(24, 12)))

    body = sweep(client)
    assert body["result"]["filed"] == 2
    assert [f["frame_number"] for f in frames_of(client, roll["id"])] == [1, 2]
    # The emptied folder is gone too: the inbox is a letterbox, not a filing cabinet.
    assert not (box / serial).exists()
    assert body["result"]["folders_removed"] == 1


def test_a_file_that_names_no_roll_arrives_unassigned(client, box):
    drop(box, "IMG_4711.jpg", jpeg_bytes(size=(30, 12)))
    body = sweep(client)
    assert body["result"]["unassigned"] == 1
    image_id = body["result"]["image_ids"][0]
    frame = client.get(f"/api/images/{image_id}").json()
    assert frame["film_roll_id"] is None
    assert frame["positive"] is True
    assert not (box / "IMG_4711.jpg").exists()
    # The inbox never invents a roll for it.
    assert not any(r["title"] == "IMG_4711" for r in client.get("/api/films").json())


def test_a_camera_raw_in_the_inbox_is_not_called_a_positive(client, box):
    """The one exception to 'everything here is finished': a raw never is."""
    roll = make_roll(client)
    drop(box, f"{roll['archive_serial']}_Frame005.ARW", TIFF_LE + os.urandom(64))
    body = sweep(client)
    assert body["result"]["imported"] == 1
    frame = frames_of(client, roll["id"])[0]
    assert frame["frame_number"] == 5
    assert frame["positive"] is None  # the film stock decides, as for any scan


# --- what stays, and why ------------------------------------------------------------------


def test_a_file_still_arriving_is_left_alone(client, box):
    fresh = drop(box, "arriving.jpg", jpeg_bytes(size=(40, 12)), settled=False)
    body = sweep(client)
    assert body["result"]["settling"] == 1 and body["result"]["imported"] == 0
    assert fresh.exists()
    # Once it has settled, it is taken.
    old = time.time() - 120
    os.utime(fresh, (old, old))
    assert sweep(client)["result"]["imported"] == 1
    assert not fresh.exists()


def test_what_cannot_be_taken_stays_and_is_named(client, box):
    html = drop(box, "notes.html", b"<html>not a photo</html>")
    truncated = drop(box, "half.jpg", b"\x00\x00garbage")
    body = sweep(client)
    reasons = {r["name"]: r["reason"] for r in body["result"]["rejected"]}
    assert "notes.html" in reasons and "half.jpg" in reasons
    assert html.exists() and truncated.exists()
    assert body["pending"]["count"] == 2
    assert any(f["name"] == "notes.html" and f["accepted"] is False for f in body["pending"]["files"])


def test_the_same_bytes_twice_are_a_duplicate_not_a_second_frame(client, box):
    roll = make_roll(client)
    export = jpeg_bytes(xmp=xmp_packet(CaptureRoll=roll["archive_serial"], CaptureFrame="1"), size=(50, 12))
    drop(box, "first.jpg", export)
    assert sweep(client)["result"]["imported"] == 1
    again = drop(box, "exported again.jpg", export)
    body = sweep(client)
    assert body["result"]["duplicates"] == 1 and body["result"]["imported"] == 0
    assert not again.exists()
    assert len(frames_of(client, roll["id"])) == 1


def test_a_sidecar_travels_with_its_scan(client, box):
    roll = make_roll(client)
    serial = roll["archive_serial"]
    drop(box, f"{serial}_007_Gold 200.jpg", jpeg_bytes(size=(60, 12)))
    sidecar = drop(box, f"{serial}_007_Gold 200.jpg.negpy", json.dumps(RECIPE).encode())
    sweep(client)
    frame = frames_of(client, roll["id"])[0]
    assert frame["sidecar_path"] and frame["sidecar_path"].endswith(".negpy")
    assert frame["negpy_summary"]
    assert not sidecar.exists()


def test_finders_droppings_are_cleared_but_never_mistaken_for_photos(client, box):
    roll = make_roll(client)
    name = f"{roll['archive_serial']}_002_Gold 200.jpg"
    drop(box, name, jpeg_bytes(size=(70, 12)))
    twin = drop(box, f"._{name}", b"\x00\x05\x16\x07" + b"\x00" * 60)  # AppleDouble
    drop(box, ".DS_Store", b"\x00" * 16)
    body = sweep(client)
    assert body["result"]["imported"] == 1 and body["result"]["rejected"] == []
    assert not twin.exists()


# --- the address on the card ----------------------------------------------------------------


def test_status_says_where_the_share_is(client, box, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "archive.local")
    monkeypatch.setenv(share.SHARE_NAME_ENV, "negarchive")
    monkeypatch.setenv(share.SHARE_USER_ENV, "tim")
    body = client.get("/api/inbox").json()
    assert body["ok"] and body["dir"] == str(box)
    assert body["share"]["url"] == "smb://archive.local/negarchive"
    assert body["share"]["user"] == "tim" and body["share"]["mac_path"] == "/Volumes/negarchive/inbox"
    assert body["filename_pattern"] == "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"
    assert "password" not in json.dumps(body).lower()


def test_a_non_default_port_is_in_the_address(monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "192.168.1.10")
    monkeypatch.setenv(share.SHARE_PORT_ENV, "1445")
    assert share.urls()[0] == "smb://192.168.1.10:1445/negarchive"
