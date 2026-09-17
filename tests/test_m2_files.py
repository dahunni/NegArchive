"""File lifecycle and the upload allowlist (M2, R#9, R#18).

Deleting a record deletes the file it owns, unless you say otherwise or somebody
else owns the file; the sweep finds what fell through the cracks; and nothing that
is not an image gets in, or comes back out as a web page.
"""

import io
import os
import uuid

from PIL import Image as PILImage

from app import paths

#: The *stored* form of the scans directory — the shape `image_assets.path` has and
#: the shape the orphan sweep reports. M3 moved the bytes under DATA_DIR, so use
#: `on_disk()` whenever the filesystem is actually touched.
UPLOADS = os.path.join("static", "uploads", "scans")


def on_disk(stored_path: str) -> str:
    """Where a stored path really is (M3: under DATA_DIR, not the working directory)."""
    return str(paths.resolve(stored_path))


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def png_bytes(size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", size, (30, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def make_roll(client) -> dict:
    res = client.post("/api/films", json={"title": unique("Roll")})
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id=None, filename="frame.png") -> dict:
    data = {"type": "scan"}
    if roll_id is not None:
        data["film_roll_id"] = str(roll_id)
    res = client.post(
        "/api/images/upload", files={"file": (filename, png_bytes(), "image/png")}, data=data
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


# --- deleting a frame ---------------------------------------------------------


def test_deleting_a_frame_deletes_its_file_by_default(client):
    frame = upload(client)
    path = frame["path"]
    assert os.path.exists(on_disk(path))

    res = client.delete(f"/api/images/{frame['id']}")
    assert res.status_code == 200, res.text
    assert res.json()["files_deleted"] == 1
    assert not os.path.exists(on_disk(path)), "M2 default: the file goes with the record (R#9)"


def test_keep_files_leaves_the_file_alone(client):
    frame = upload(client)
    path = frame["path"]

    res = client.delete(f"/api/images/{frame['id']}?keep_files=true")
    assert res.status_code == 200, res.text
    assert res.json()["files_deleted"] == 0
    assert os.path.exists(on_disk(path))
    os.remove(on_disk(path))


def test_the_m1_delete_file_flag_still_wins_when_it_is_sent(client):
    """An older client that says `delete_file=false` keeps its behaviour."""
    frame = upload(client)
    path = frame["path"]
    assert client.delete(f"/api/images/{frame['id']}?delete_file=false").status_code == 200
    assert os.path.exists(on_disk(path))
    os.remove(on_disk(path))


def test_bulk_delete_removes_the_files_by_default(client):
    roll = make_roll(client)
    frames = [upload(client, roll["id"]) for _ in range(2)]
    res = client.post("/api/images/bulk_delete", json={"ids": [f["id"] for f in frames]})
    assert res.status_code == 200, res.text
    assert res.json()["files_deleted"] == 2
    assert not any(os.path.exists(on_disk(f["path"])) for f in frames)


# --- deleting a roll ----------------------------------------------------------


def test_deleting_a_roll_deletes_its_frames_and_their_files(client):
    roll = make_roll(client)
    frames = [upload(client, roll["id"]) for _ in range(3)]

    res = client.delete(f"/api/films/{roll['id']}")
    assert res.status_code == 200, res.text
    assert res.json()["files_deleted"] == 3
    assert not any(os.path.exists(on_disk(f["path"])) for f in frames)
    assert client.get(f"/api/films/{roll['id']}").status_code == 404
    assert client.get(f"/api/images/{frames[0]['id']}").status_code == 404


def test_deleting_a_roll_with_keep_files_leaves_the_scans(client):
    roll = make_roll(client)
    frame = upload(client, roll["id"])

    res = client.delete(f"/api/films/{roll['id']}?keep_files=true")
    assert res.status_code == 200, res.text
    assert res.json()["files_deleted"] == 0
    assert os.path.exists(on_disk(frame["path"]))
    # The file is now an orphan, which is exactly what the sweep is for.
    sweep = client.post("/api/maintenance/sweep_orphans").json()
    assert frame["path"] in sweep["orphan_files"]
    os.remove(on_disk(frame["path"]))


# --- storage_mode (M3's linked files) -----------------------------------------


def test_a_linked_file_is_never_deleted(client):
    """M3 registers files it does not own; M2 promises not to touch them."""
    path = os.path.join("static", "uploads", "linked", f"{unique('external')}.png")
    os.makedirs(os.path.dirname(on_disk(path)), exist_ok=True)
    with open(on_disk(path), "wb") as out:
        out.write(png_bytes())

    created = client.post(
        "/api/images",
        json={"path": path, "type": "scan", "storage_mode": "linked", "original_filename": "ext.png"},
    )
    assert created.status_code == 200, created.text
    image = created.json()["image"]
    assert image["storage_mode"] == "linked"

    res = client.delete(f"/api/images/{image['id']}")
    assert res.status_code == 200, res.text
    assert res.json()["files_deleted"] == 0
    assert os.path.exists(on_disk(path)), "a linked file belongs to somebody else"
    os.remove(on_disk(path))


def test_an_unknown_storage_mode_is_rejected(client):
    res = client.post(
        "/api/images", json={"path": "static/uploads/scans/x.png", "storage_mode": "borrowed"}
    )
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "storage_mode"


# --- the orphan sweep ---------------------------------------------------------


def test_the_sweep_is_a_dry_run_by_default(client):
    os.makedirs(on_disk(UPLOADS), exist_ok=True)
    orphan = os.path.join(UPLOADS, f"{unique('orphan')}.png")
    with open(on_disk(orphan), "wb") as out:
        out.write(png_bytes())

    res = client.post("/api/maintenance/sweep_orphans")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied"] is False
    assert orphan in body["orphan_files"]
    assert body["deleted_files"] == 0
    assert os.path.exists(on_disk(orphan)), "a dry run deletes nothing"

    applied = client.post("/api/maintenance/sweep_orphans?apply=true").json()
    assert applied["applied"] is True
    assert applied["deleted_files"] >= 1
    assert applied["bytes_reclaimed"] > 0
    assert not os.path.exists(on_disk(orphan))


def test_the_sweep_reports_records_whose_file_is_gone(client):
    roll = make_roll(client)
    frame = upload(client, roll["id"])
    os.remove(on_disk(frame["path"]))  # a file that vanished behind the archive's back

    body = client.post("/api/maintenance/sweep_orphans").json()
    missing = {entry["image_id"]: entry for entry in body["missing_files"]}
    assert frame["id"] in missing
    assert missing[frame["id"]]["film_roll_id"] == roll["id"]
    # reported, never deleted: the metadata is the point of the archive
    assert client.get(f"/api/images/{frame['id']}").status_code == 200


def test_a_frame_that_is_on_disk_is_not_reported(client):
    frame = upload(client)
    body = client.post("/api/maintenance/sweep_orphans").json()
    assert frame["path"] not in body["orphan_files"]
    assert frame["id"] not in {entry["image_id"] for entry in body["missing_files"]}


# --- upload allowlist (R#18) --------------------------------------------------


def test_an_html_upload_is_rejected(client):
    res = client.post(
        "/api/images/upload",
        files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
        data={"type": "scan"},
    )
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "unsupported_file_type"


def test_html_wearing_a_jpg_extension_is_rejected_by_the_sniff(client):
    res = client.post(
        "/api/images/upload",
        files={"file": ("evil.jpg", b"<html><script>alert(1)</script></html>", "image/jpeg")},
        data={"type": "scan"},
    )
    assert res.status_code == 415
    assert "does not look like an image" in res.json()["error"]["message"]


def test_every_allowed_extension_gets_in(client):
    tiff = b"II*\x00" + b"\x00" * 64
    for filename, payload in [
        ("a.jpg", b"\xff\xd8\xff" + b"\x00" * 32),
        ("a.png", png_bytes()),
        ("a.tif", tiff),
        ("a.tiff", tiff),
        ("a.dng", tiff),
        ("a.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 16),
    ]:
        res = client.post(
            "/api/images/upload",
            files={"file": (filename, payload, "application/octet-stream")},
            data={"type": "scan"},
        )
        assert res.status_code == 200, f"{filename}: {res.text}"
        client.delete(f"/api/images/{res.json()['image']['id']}")


def test_a_rejected_file_in_a_bulk_upload_takes_the_whole_batch_with_it(client):
    roll = make_roll(client)
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("good.png", png_bytes(), "image/png")),
            ("files", ("bad.exe", b"MZ\x00\x00", "application/octet-stream")),
        ],
    )
    assert res.status_code == 415
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["image_count"] == 0
    leftovers = client.post("/api/maintenance/sweep_orphans").json()["orphan_files"]
    assert not any("good" in name for name in leftovers), "the accepted file was rolled back too"


def test_the_upload_size_limit_is_configurable(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    too_big = png_bytes() + b"\x00" * (2 * 1024 * 1024)
    res = client.post(
        "/api/images/upload",
        files={"file": ("huge.png", too_big, "image/png")},
        data={"type": "scan"},
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "file_too_large"
    assert "1 MB" in res.json()["error"]["message"]
    # and nothing half-written stayed behind
    assert not client.post("/api/maintenance/sweep_orphans").json()["orphan_files"]


# --- serving uploads back (R#18) ----------------------------------------------


def test_an_html_file_under_uploads_is_never_served_as_a_page(client):
    """Even if one gets in another way, /static must not render it."""
    os.makedirs(on_disk(UPLOADS), exist_ok=True)
    path = os.path.join(UPLOADS, f"{unique('planted')}.html")
    with open(on_disk(path), "w") as out:
        out.write("<html><body><script>alert(1)</script></body></html>")
    try:
        res = client.get(f"/{path}")
        assert res.status_code == 200
        assert res.headers["content-type"].split(";")[0] == "application/octet-stream"
        assert res.headers["content-disposition"] == "attachment"
        assert res.headers["x-content-type-options"] == "nosniff"
    finally:
        os.remove(on_disk(path))


def test_a_normal_scan_is_still_served_as_an_image(client):
    frame = upload(client)
    res = client.get(f"/{frame['path']}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.headers["x-content-type-options"] == "nosniff"
    client.delete(f"/api/images/{frame['id']}")
