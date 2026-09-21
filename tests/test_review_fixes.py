"""Regression tests for the 2026-09-20 review fixes.

One test per finding that was confirmed by running it, so the fix cannot quietly
come undone. The numbers in the docstrings are the review's.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime

import pytest

from app.services import codes, network
from app.services.negpy import gear as negpy_gear
from app.services.negpy import naming, recipe, sidecar

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def make_roll(client, **fields) -> dict:
    payload = {"title": "Review roll"}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id, filename="frame.png", payload: bytes = PNG_1x1):
    res = client.post(
        "/api/images/upload",
        files={"file": (filename, payload, "image/png")},
        data={"type": "scan", "film_roll_id": str(roll_id)},
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


# --- 1: catalog pictures ------------------------------------------------------


def test_catalog_svgs_are_served_as_images(client):
    res = client.get("/static/catalog/cameras/nikon-f5.svg")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" not in (res.headers.get("content-disposition") or "")


def test_uploaded_html_is_still_never_a_page(client, data_dir):
    target = os.path.join(data_dir, "uploads", "scans", "evil.html")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("<script>alert(1)</script>")
    res = client.get("/static/uploads/scans/evil.html")
    assert res.headers["content-type"] == "application/octet-stream"
    assert res.headers["content-disposition"] == "attachment"


# --- 5: download filenames -----------------------------------------------------


def test_download_survives_a_non_latin1_filename(client):
    roll = make_roll(client)
    frame = upload(client, roll["id"], filename="Kodak – frame ü 1.png")
    res = client.get(f"/api/images/{frame['id']}/download")
    assert res.status_code == 200, res.text
    assert "filename*=utf-8''" in res.headers["content-disposition"]


# --- 6, 14, 15: URLs and tokens --------------------------------------------------


def test_a_public_host_with_a_port_is_not_given_a_second_one(monkeypatch):
    monkeypatch.setenv("UI_PORT", "8021")
    assert network.normalize_base_url("archive.local:8080") == "http://archive.local:8080"
    assert network.normalize_base_url("archive.local") == "http://archive.local:8021"
    assert network.normalize_base_url("[::1]:8080") == "http://[::1]:8080"
    assert network.normalize_base_url("https://archive.example.com/") == "https://archive.example.com"


def test_a_roll_page_url_resolves_by_id(client):
    roll = make_roll(client)
    assert codes.parse_token(f"http://host/films/{roll['id']}") == {"kind": "roll", "id": roll["id"]}
    res = client.post("/api/scan/resolve", json={"code": f"http://host:8021/films/{roll['id']}"})
    assert res.status_code == 200, res.text
    assert res.json()["roll"]["id"] == roll["id"]


def test_code_urls_are_encoded(client):
    roll = make_roll(client, archive_serial="RV-2024-0001")
    client.put("/api/system/settings", json={"public_base_url": "http://a.b/x?y=1&z=2"})
    try:
        res = client.get(f"/api/codes/for_roll/{roll['id']}")
        assert res.status_code == 200, res.text
        assert "&z" not in res.json()["qr_svg_url"].split("text=", 1)[1]
        assert "%26z" in res.json()["qr_svg_url"]
    finally:
        client.put("/api/system/settings", json={"public_base_url": ""})


# --- 7: registering a path --------------------------------------------------------


def test_registering_a_file_outside_the_archive_is_refused(client):
    res = client.post("/api/images", json={"path": "/etc/hosts"})
    assert res.status_code in (403, 404), res.text
    assert res.json()["error"]["code"] in {"path_not_allowed", "file_missing"}


def test_registering_a_managed_file_still_works(client):
    roll = make_roll(client)
    frame = upload(client, roll["id"])
    res = client.post("/api/images", json={"path": frame["path"], "film_roll_id": roll["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["image"]["storage_mode"] == "managed"


# --- 8, 70: ZIP uploads ---------------------------------------------------------------


def test_zip_upload_reports_skipped_files_and_takes_positive(client):
    roll = make_roll(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("good_001.png", PNG_1x1)
        archive.writestr("notes.txt", "not an image")
        archive.writestr("fake_002.png", b"definitely not a png")
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk_zip",
        files={"file": ("roll.zip", buffer.getvalue(), "application/zip")},
        data={"positive": "true"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [i["original_filename"] for i in body["images"]] == ["good_001.png"]
    assert body["images"][0]["positive"] is True
    assert body["skipped"] == ["fake_002.png", "notes.txt"]


# --- 17: needs_label ---------------------------------------------------------------------


def test_a_move_after_printing_needs_a_new_label(client):
    roll = make_roll(client)
    assert roll["needs_label"] is True
    client.post("/api/print/mark", json={"roll_ids": [roll["id"]]})
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["needs_label"] is False
    box = client.post("/api/locations", json={"kind": "box", "name": "Review box"}).json()["location"]
    client.post(f"/api/films/{roll['id']}/move", json={"location_id": box["id"]})
    film = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert film["needs_label"] is True
    assert client.get("/api/work").json()["needs_label"] >= 1


# --- 9, 10, 11, 16, 26: NegPy parsing -----------------------------------------------------


def test_lens_numbers_ignore_the_mount_code():
    from app.models import Lens

    entry = negpy_gear.lens_entry(Lens(id=1, name="Canon EF 50mm f/1.8"))
    assert entry["focalLength"] == 50.0
    assert entry["maxAperture"] == 1.8
    zoom = negpy_gear.lens_entry(Lens(id=2, name="AF-S 24-70mm f/2.8G"))
    assert zoom["focalLength"] == 24.0
    assert zoom["maxAperture"] == 2.8


def test_export_names_prefer_the_padded_frame():
    assert naming.parse("Trip_2024_Kyoto_005_HP5.tif").frame_number == 5
    assert naming.parse("Trip_2024_Kyoto_005_HP5.tif").roll == "Trip_2024_Kyoto"
    assert naming.parse("NEG-2026-0007_012_Kodak_400_TX.jpg").frame_number == 12
    assert naming.parse("NEG-2026-0007_012_HP5 Plus.tif").film == "HP5 Plus"


def test_rotation_keys_are_read_in_their_own_units():
    assert recipe.from_recipe({"settings": {"quarter_turns": 1}}).rotate_quarter_turns == 1
    assert recipe.from_recipe({"settings": {"orientation": 6}}).rotate_quarter_turns == 1
    assert recipe.from_recipe({"settings": {"rotation": 270}}).rotate_quarter_turns == 3
    fine = recipe.from_recipe({"settings": {"rotation": 2.5}})
    assert fine.rotate_quarter_turns == 0
    assert "rotation" in fine.ignored


def test_offsets_are_converted_to_utc_not_dropped():
    assert sidecar.parse_utc("2026-09-20T12:00:00+02:00") == datetime(2026, 9, 20, 10, 0, 0)
    assert sidecar.parse_utc("2026-09-20T12:00:00Z") == datetime(2026, 9, 20, 12, 0, 0)


def test_sidecar_stems_keep_dotted_names():
    assert sidecar.image_stem("my.photo.negpy") == "my.photo"
    assert sidecar.image_stem("my.photo.tif.negpy") == "my.photo"
    assert sidecar.image_stem("scan_001.negpy") == "scan_001"


# --- 3: gear sync never overwrites an unreadable file -----------------------------------


def test_gear_sync_leaves_an_unreadable_file_alone(client, tmp_path):
    from app.db import SessionLocal

    (tmp_path / "cameras.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "lenses.json").write_text(json.dumps({"version": 2, "lenses": [{"id": "theirs"}]}), encoding="utf-8")
    db = SessionLocal()
    try:
        result = negpy_gear.sync(db, tmp_path)
    finally:
        db.close()
    assert result.files["cameras"].get("skipped") is True
    assert (tmp_path / "cameras.json").read_text(encoding="utf-8") == "{ this is not json"
    written = json.loads((tmp_path / "lenses.json").read_text(encoding="utf-8"))
    assert written["version"] == 2, "other top-level keys of a wrapped file survive"
    assert any(entry["id"] == "theirs" for entry in written["lenses"])


# --- 2, 12: the import carries everything ------------------------------------------------------


def test_import_keeps_gear_links_location_status_and_positive(client):
    camera = client.post("/api/cameras", json={"name": "Review import camera"}).json()["camera"]
    box = client.post("/api/locations", json={"kind": "box", "name": "Review import box"}).json()["location"]
    roll = make_roll(
        client,
        title="Review import roll",
        archive_serial="IMP-2024-0001",
        camera_id=camera["id"],
        location_id=box["id"],
        developer="Rodinal",
        status="scanned",
    )
    # Unique bytes: the import matches frames by content hash, and every other
    # test uploads the same 1x1 PNG.
    frame = upload(client, roll["id"], filename="imp_001.png", payload=PNG_1x1 + os.urandom(16))
    client.put(f"/api/images/{frame['id']}", json={"positive": True})

    exported = client.get("/api/export").content
    # Drop the roll, its frame and the box, then import the export back.
    client.delete(f"/api/films/{roll['id']}")
    client.delete(f"/api/locations/{box['id']}?force=true")
    # Lower-case serial in the file must still match the upper-cased one here.
    payload = json.loads(zipfile.ZipFile(io.BytesIO(exported)).read("export.json"))
    for row in payload["tables"]["film_rolls"]:
        if row["archive_serial"] == "IMP-2024-0001":
            row["archive_serial"] = "imp-2024-0001"
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported)) as source, zipfile.ZipFile(rebuilt, "w") as target:
        for name in source.namelist():
            target.writestr(name, json.dumps(payload) if name == "export.json" else source.read(name))

    res = client.post("/api/import", files={"file": ("export.zip", rebuilt.getvalue(), "application/zip")})
    assert res.status_code == 200, res.text
    report = res.json()["report"]
    assert report["film_rolls_added"] >= 1
    assert report["locations_added"] >= 1

    found = client.get("/api/rolls/by-serial/imp-2024-0001").json()["roll"]
    assert found["camera_id"] == camera["id"]
    assert found["developer"] == "Rodinal"
    assert found["status"] == "scanned"
    assert found["location_path"] == "Review import box"
    detail = client.get(f"/api/films/{found['id']}").json()
    assert detail["images"][0]["positive"] is True

    # Importing the same export again matches the serial case-insensitively.
    again = client.post("/api/import", files={"file": ("export.zip", rebuilt.getvalue(), "application/zip")})
    assert again.status_code == 200, again.text
    assert again.json()["report"].get("film_rolls_added", 0) == 0


# --- 21: settings validation --------------------------------------------------------------------


def test_smb_and_preview_settings_are_validated_everywhere(client):
    res = client.put("/api/system/settings", json={"smb_host": "nas/../etc"})
    assert res.status_code == 400, res.text
    res = client.put("/api/system/settings", json={"preview_render": "banana"})
    assert res.status_code == 400, res.text
    res = client.put("/api/system/settings", json={"smb_version": "3.0,uid=0"})
    assert res.status_code == 400, res.text


# --- 34, 35, 44: bad input is a 4xx ------------------------------------------------------------------


def test_negpy_ingest_rejects_a_non_numeric_film_id(client):
    res = client.post("/api/negpy/ingest", json={"film_id": "abc"})
    assert res.status_code == 400, res.text


def test_duplicate_sleeve_layout_is_a_409(client):
    body = {"name": "Review layout", "rows": 7, "frames_per_row": 6}
    assert client.post("/api/sleeve_layouts", json=body).status_code == 200
    res = client.post("/api/sleeve_layouts", json=body)
    assert res.status_code == 409, res.text


def test_adding_pages_with_an_unknown_layout_is_a_404(client):
    binder = client.post("/api/locations", json={"kind": "binder", "name": "Review binder"}).json()["location"]
    res = client.post(f"/api/locations/{binder['id']}/pages", json={"count": 1, "sleeve_layout_id": 999999})
    assert res.status_code == 404, res.text


# --- 30: create cleans like update --------------------------------------------------------------------


def test_creating_a_roll_cleans_empty_strings(client):
    roll = make_roll(client, notes="", building="None", folder="  ", location_id="none")
    assert roll["notes"] is None
    assert roll["building"] is None
    assert roll["folder"] is None
    assert roll["location_id"] is None


# --- 32: preview_version ---------------------------------------------------------------------------------


def test_preview_version_changes_with_the_positive_flag(client):
    roll = make_roll(client)
    frame = upload(client, roll["id"])
    before = frame["preview_version"]
    assert before
    after = client.put(f"/api/images/{frame['id']}", json={"positive": True}).json()["image"]["preview_version"]
    assert after != before


# --- 18: un-sleeving clears the stamp ------------------------------------------------------------------


def test_unsleeving_clears_sleeved_at(client):
    binder = client.post("/api/locations", json={"kind": "binder", "name": "Review stamp binder"}).json()["location"]
    client.post(f"/api/locations/{binder['id']}/pages", json={"count": 1})
    roll = make_roll(client)
    client.post(f"/api/films/{roll['id']}/move", json={"location_id": binder["id"]})
    film = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert film["status"] == "sleeved" and film["sleeved_at"]
    client.post(f"/api/films/{roll['id']}/move", json={"location_id": None})
    film = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert film["status"] != "sleeved"
    assert film["sleeved_at"] is None


@pytest.mark.parametrize("value", ["2024-07-01", "2024-07-01T10:00:00"])
def test_status_at_accepts_a_date(client, value):
    roll = make_roll(client)
    res = client.post(f"/api/films/{roll['id']}/status", json={"status": "at_lab", "at": value[:10]})
    assert res.status_code == 200, res.text
    assert res.json()["film"]["lab_sent_at"].startswith("2024-07-01")


