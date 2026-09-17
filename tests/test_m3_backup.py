"""Export, import and the CSV roll index (docs/ROADMAP.md, M3).

The export is the answer to "what happens to my archive when this software
stops being maintained", so the tests care less about round-tripping through
NegArchive than about the ZIP being *readable on its own*: a JSON file anyone can
open, and the pictures beside it under recognisable names.

The import is the other half, and its one rule is that it never overwrites: it is
run against an archive that already has things in it.
"""

import io
import json
import zipfile

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def upload(client, roll_id=None, filename="frame.png", payload=PNG_1x1):
    data = {"type": "scan"}
    if roll_id is not None:
        data["film_roll_id"] = str(roll_id)
    res = client.post("/api/images/upload", files={"file": (filename, payload, "image/png")}, data=data)
    assert res.status_code == 200, res.text
    return res.json()["image"]


def make_roll(client, **fields):
    payload = {"title": "Export roll"}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def export_zip(client) -> zipfile.ZipFile:
    res = client.get("/api/export")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert "attachment" in res.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(res.content))


# --- export -------------------------------------------------------------------


def test_the_export_is_a_readable_zip_with_json_and_the_files(client):
    roll = make_roll(client, title="Export roll A", archive_serial="EXP-2024-0001")
    frame = upload(client, roll["id"], filename="harbour_003.png")

    with export_zip(client) as archive:
        names = archive.namelist()
        assert "export.json" in names
        assert "README.txt" in names, "a stranger opening this in 2031 gets an explanation"

        payload = json.loads(archive.read("export.json"))
        assert payload["negarchive_export"] == 1
        assert payload["exported_at"].endswith("Z")

        rolls = payload["tables"]["film_rolls"]
        assert any(r["archive_serial"] == "EXP-2024-0001" for r in rolls)

        images = {i["id"]: i for i in payload["tables"]["image_assets"]}
        assert images[frame["id"]]["original_filename"] == "harbour_003.png"
        assert images[frame["id"]]["content_hash"]
        # Dates are strings, enums are their values: no SQL and no pickles.
        assert isinstance(images[frame["id"]]["created_at"], str)
        assert images[frame["id"]]["type"] == "scan"

        member = "files/" + images[frame["id"]]["path"].split("static/", 1)[1]
        assert member in names
        assert archive.read(member) == PNG_1x1


def test_every_table_is_in_the_export(client):
    with export_zip(client) as archive:
        tables = json.loads(archive.read("export.json"))["tables"]
    assert set(tables) == {
        "cameras",
        "lenses",
        "film_stocks",
        "film_rolls",
        "image_assets",
        "library_roots",
        "settings",
        # M4
        "sleeve_layouts",
        "locations",
        "location_moves",
    }


def test_the_json_only_export_matches(client):
    res = client.get("/api/export.json")
    assert res.status_code == 200
    assert set(res.json()["tables"]) >= {"film_rolls", "image_assets"}


def test_a_linked_frame_is_recorded_but_its_file_is_not_copied(client, tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARY_ROOTS_ALLOW", str(tmp_path.resolve()))
    folder = tmp_path / "lib" / "Linked export"
    folder.mkdir(parents=True)
    (folder / "x_001.tif").write_bytes(PNG_1x1 + b"linked-export")

    root = client.post("/api/library/roots", json={"path": str(tmp_path / "lib")}).json()["root"]
    client.post(f"/api/library/roots/{root['id']}/scan")

    with export_zip(client) as archive:
        payload = json.loads(archive.read("export.json"))
        linked = [i for i in payload["tables"]["image_assets"] if i["storage_mode"] == "linked"]
        assert linked, "the record must be in the export"
        assert all(i["source_path"] and i["content_hash"] for i in linked)
        # …but not the bytes: they live in a folder the user backs up themselves.
        assert not any(name.endswith("x_001.tif") for name in archive.namelist())


# --- CSV ----------------------------------------------------------------------


def test_rolls_csv_has_a_header_and_one_line_per_roll(client):
    roll = make_roll(client, title="CSV roll", archive_serial="CSV-2024-0001", camera="Nikon F5")
    upload(client, roll["id"])

    res = client.get("/api/export/rolls.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    lines = res.text.strip().split("\n")
    assert lines[0].startswith("id,archive_serial,title,camera")

    row = next(line for line in lines if "CSV-2024-0001" in line)
    assert "CSV roll" in row
    assert "Nikon F5" in row
    assert row.strip().split(",")[10] == "1", "frame_count"


# --- import -------------------------------------------------------------------


def test_a_dry_run_reports_without_writing(client):
    roll = make_roll(client, title="Dry run roll", archive_serial="DRY-2024-0001")
    upload(client, roll["id"])
    res = client.get("/api/export")
    export = res.content

    before = client.get("/api/films?limit=1").json()["total"]
    report = client.post(
        "/api/import?dry_run=true",
        files={"file": ("export.zip", export, "application/zip")},
    ).json()["report"]

    assert report["dry_run"] is True
    assert client.get("/api/films?limit=1").json()["total"] == before, "a dry run writes nothing"


def test_importing_the_archives_own_export_changes_nothing(client):
    """Idempotence is the whole point: re-importing must not duplicate the archive."""
    make_roll(client, title="Idempotent roll", archive_serial="IDEM-2024-0001")
    upload(client, filename="idem_001.png", payload=PNG_1x1 + b"idem")
    export = client.get("/api/export").content

    rolls_before = client.get("/api/films?limit=1").json()["total"]
    frames_before = client.get("/api/images?limit=1").json()["total"]

    report = client.post(
        "/api/import", files={"file": ("export.zip", export, "application/zip")}
    ).json()["report"]

    assert report.get("image_assets_added", 0) == 0
    assert report.get("film_rolls_added", 0) == 0
    assert client.get("/api/films?limit=1").json()["total"] == rolls_before
    assert client.get("/api/images?limit=1").json()["total"] == frames_before
    assert report.get("cameras_skipped", 0) >= 1


def test_importing_a_foreign_export_adds_it_and_remaps_the_ids(client):
    """An export from another machine, with ids that collide with ours."""
    payload = {
        "negarchive_export": 1,
        "exported_at": "2026-01-01T00:00:00Z",
        "tables": {
            "cameras": [{"id": 1, "name": "Leica M6 (imported)", "mount": "M", "image_path": None, "notes": None}],
            "lenses": [],
            "film_stocks": [],
            "film_rolls": [
                {
                    "id": 1,
                    "title": "Imported roll",
                    "camera": "Leica M6 (imported)",
                    "lens": None,
                    "film_type": None,
                    "notes": "from another machine",
                    "start_date": "2024-05-01",
                    "end_date": "2024-05-03",
                    "building": None,
                    "folder": None,
                    "archive_serial": "FOREIGN-0001",
                    "source_dir": "/somewhere/on/their/disk",
                    "created_at": "2024-05-04T10:00:00",
                }
            ],
            "image_assets": [
                {
                    "id": 1,
                    "film_roll_id": 1,
                    "type": "scan",
                    "path": "static/uploads/scans/imported.png",
                    "frame_number": 5,
                    "notes": None,
                    "capture_date": "2024-05-02",
                    "created_at": "2024-05-04T10:00:00",
                    "original_filename": "imported_005.png",
                    "storage_mode": "managed",
                    "source_path": None,
                    "content_hash": "f" * 64,
                }
            ],
            "library_roots": [{"id": 1, "path": "/their/library", "label": None, "watch": True,
                               "last_scan_at": None, "last_scan_summary": None, "created_at": "2024-05-04T10:00:00"}],
            "settings": [],
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("export.json", json.dumps(payload))
        archive.writestr("files/uploads/scans/imported.png", PNG_1x1 + b"imported")

    res = client.post("/api/import", files={"file": ("export.zip", buffer.getvalue(), "application/zip")})
    assert res.status_code == 200, res.text
    report = res.json()["report"]
    assert report["film_rolls_added"] == 1
    assert report["image_assets_added"] == 1
    assert report["files_copied"] == 1
    assert report["library_roots_ignored"] == 1, "absolute paths from another machine are not imported"

    roll = next(r for r in client.get("/api/films").json() if r["archive_serial"] == "FOREIGN-0001")
    assert roll["id"] != 1, "ids are remapped"
    assert roll["notes"] == "from another machine"

    frames = client.get(f"/api/films/{roll['id']}").json()["images"]
    assert len(frames) == 1
    assert frames[0]["frame_number"] == 5
    assert frames[0]["original_filename"] == "imported_005.png"
    assert frames[0]["content_hash"] == "f" * 64
    # The file came across and is served.
    assert client.get(f"/api/images/{frames[0]['id']}/download").content == PNG_1x1 + b"imported"

    # The imported library root is not adopted.
    assert not any(r["path"] == "/their/library" for r in client.get("/api/library/roots").json()["roots"])


def test_a_frame_whose_file_is_missing_still_imports_its_metadata(client):
    payload = {
        "negarchive_export": 1,
        "tables": {
            "cameras": [], "lenses": [], "film_stocks": [], "film_rolls": [],
            "image_assets": [
                {
                    "id": 9, "film_roll_id": None, "type": "scan",
                    "path": "static/uploads/scans/gone.png", "frame_number": 12,
                    "notes": "the negative still exists", "capture_date": None,
                    "created_at": "2024-05-04T10:00:00", "original_filename": "gone.png",
                    "storage_mode": "managed", "source_path": None, "content_hash": "a" * 64,
                }
            ],
            "library_roots": [], "settings": [],
        },
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("export.json", json.dumps(payload))

    report = client.post(
        "/api/import", files={"file": ("export.zip", buffer.getvalue(), "application/zip")}
    ).json()["report"]
    assert report["image_assets_added"] == 1
    assert report["files_missing"] == 1


def test_a_zip_that_is_not_an_export_is_a_400(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("holiday.txt", "not an export")
    res = client.post("/api/import", files={"file": ("x.zip", buffer.getvalue(), "application/zip")})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_export"


def test_something_that_is_not_a_zip_at_all_is_a_400(client):
    res = client.post("/api/import", files={"file": ("x.zip", b"definitely not a zip", "application/zip")})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_export"


def test_a_newer_export_format_is_refused_rather_than_half_read(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("export.json", json.dumps({"negarchive_export": 99, "tables": {}}))
    res = client.post("/api/import", files={"file": ("x.zip", buffer.getvalue(), "application/zip")})
    assert res.status_code == 400
    assert "format 99" in res.json()["error"]["message"]


def test_the_backups_listing_reports_the_directory(client):
    body = client.get("/api/backups").json()
    assert body["directory"].endswith("backups")
    assert isinstance(body["backups"], list)
