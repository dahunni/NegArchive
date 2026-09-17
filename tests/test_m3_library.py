"""Import by reference and the watch folder (docs/ROADMAP.md, M3).

The promise of link mode is narrow and absolute: NegArchive records where a file
is and never touches it. Most of what follows tests that promise from a different
angle — a rescan must not duplicate, a delete must not unlink, a folder outside
`LIBRARY_ROOTS_ALLOW` must not even be registerable.
"""

import os

import pytest

from app.services.importer import parse_folder_name, parse_frame_number

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


@pytest.fixture
def library(tmp_path, monkeypatch):
    """An allowed, empty library root on disk."""
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setenv("LIBRARY_ROOTS_ALLOW", str(tmp_path.resolve()))
    return root


def make_roll_folder(root, name: str, files: dict) -> None:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    for filename, payload in files.items():
        (folder / filename).write_bytes(payload)


def register(client, path, **fields):
    body = {"path": str(path)}
    body.update(fields)
    return client.post("/api/library/roots", json=body)


def scan(client, root_id):
    res = client.post(f"/api/library/roots/{root_id}/scan")
    assert res.status_code == 200, res.text
    return res.json()["result"]


# --- filename and folder parsing ---------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Roll12_007.tif", 7),
        ("harbour_Frame007.jpg", 7),
        ("007.jpg", 7),
        ("2024-0007_03.tif", 3),
        ("IMG_1234.jpg", 1234),
        ("frame-12.png", 12),
        ("untitled.tif", None),
        ("", None),
        (None, None),
    ],
)
def test_frame_numbers_are_parsed_from_the_filename(filename, expected):
    assert parse_frame_number(filename) == expected


@pytest.mark.parametrize(
    "folder,title,serial",
    [
        ("2024-0007 Harbour", "Harbour", "2024-0007"),
        ("NEG-2024-0007 Kyoto rain", "Kyoto rain", "NEG-2024-0007"),
        ("2024-0007", "2024-0007", "2024-0007"),
        ("Kyoto rain", "Kyoto rain", None),
        ("2024 was a good year", "2024 was a good year", None),
    ],
)
def test_folder_names_become_a_title_and_maybe_a_serial(folder, title, serial):
    assert parse_folder_name(folder) == (title, serial)


# --- registering a root -------------------------------------------------------


def test_registering_is_refused_when_the_allowlist_is_empty(client, tmp_path, monkeypatch):
    monkeypatch.delenv("LIBRARY_ROOTS_ALLOW", raising=False)
    res = register(client, tmp_path)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "library_roots_disabled"


def test_registering_a_folder_outside_the_allowlist_is_refused(client, library, tmp_path):
    outside = tmp_path.parent / "somewhere-else"
    outside.mkdir(exist_ok=True)
    res = register(client, outside)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "path_not_allowed"


def test_registering_a_missing_folder_is_a_404(client, library):
    res = register(client, library / "nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "unknown_path"


def test_a_root_can_only_be_registered_once(client, library):
    assert register(client, library).status_code == 200
    duplicate = register(client, library)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_root"


def test_the_roots_listing_says_why_the_feature_is_off(client, monkeypatch):
    monkeypatch.delenv("LIBRARY_ROOTS_ALLOW", raising=False)
    body = client.get("/api/library/roots").json()
    assert body["enabled"] is False
    assert body["allowed_bases"] == []


# --- scanning -----------------------------------------------------------------


def test_a_scan_turns_subfolders_into_rolls_and_files_into_linked_frames(client, library):
    make_roll_folder(library, "2024-0007 Harbour", {"harbour_001.tif": PNG_1x1, "harbour_002.tif": PNG_1x1 + b"x"})
    root = register(client, library).json()["root"]

    result = scan(client, root["id"])
    assert result["rolls_created"] == 1
    assert result["frames_added"] == 2

    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Harbour")
    assert roll["archive_serial"] == "2024-0007"
    assert roll["image_count"] == 2

    frames = client.get(f"/api/films/{roll['id']}").json()["images"]
    assert [f["frame_number"] for f in frames] == [1, 2]
    for frame in frames:
        assert frame["storage_mode"] == "linked"
        assert frame["source_path"].startswith(str(library))
        assert frame["content_hash"]
        assert frame["original_filename"].endswith(".tif")
        # A linked file is outside /static, so the API serves it instead.
        assert frame["url"] == f"/api/images/{frame['id']}/download"


def test_rescanning_changes_nothing(client, library):
    make_roll_folder(library, "Kyoto", {"a_001.tif": PNG_1x1, "a_002.tif": PNG_1x1 + b"y"})
    root = register(client, library).json()["root"]

    first = scan(client, root["id"])
    second = scan(client, root["id"])

    assert first["frames_added"] == 2
    assert second["frames_added"] == 0
    assert second["rolls_created"] == 0
    assert second["frames_unchanged"] == 2

    # And the roll really does hold two frames, not four.
    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Kyoto")
    assert roll["image_count"] == 2


def test_a_moved_file_is_rehomed_rather_than_imported_twice(client, library):
    make_roll_folder(library, "Moves", {"m_001.tif": PNG_1x1 + b"unique-moves"})
    root = register(client, library).json()["root"]
    scan(client, root["id"])

    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Moves")
    frame = client.get(f"/api/films/{roll['id']}").json()["images"][0]
    client.put(f"/api/images/{frame['id']}", json={"notes": "keep me"})

    # Same bytes, new home.
    (library / "Moves elsewhere").mkdir()
    os.replace(library / "Moves" / "m_001.tif", library / "Moves elsewhere" / "m_001.tif")

    result = scan(client, root["id"])
    assert result["frames_rehomed"] == 1
    assert result["frames_added"] == 0

    moved = client.get(f"/api/images/{frame['id']}").json()
    assert moved["source_path"].endswith("Moves elsewhere/m_001.tif")
    assert moved["notes"] == "keep me", "re-homing must not lose the metadata"


def test_a_file_edited_in_place_updates_its_hash(client, library):
    make_roll_folder(library, "Edited", {"e_001.tif": PNG_1x1 + b"first"})
    root = register(client, library).json()["root"]
    scan(client, root["id"])

    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Edited")
    before = client.get(f"/api/films/{roll['id']}").json()["images"][0]

    (library / "Edited" / "e_001.tif").write_bytes(PNG_1x1 + b"second, longer")
    result = scan(client, root["id"])

    assert result["frames_updated"] == 1
    after = client.get(f"/api/images/{before['id']}").json()
    assert after["content_hash"] != before["content_hash"]


def test_non_images_are_ignored(client, library):
    make_roll_folder(library, "Mixed", {"m_001.tif": PNG_1x1, "notes.txt": b"hello", "m_002.xmp": b"<x/>"})
    root = register(client, library).json()["root"]
    assert scan(client, root["id"])["frames_added"] == 1


def test_an_empty_subfolder_becomes_a_roll_draft(client, library):
    (library / "Waiting for the scanner").mkdir()
    root = register(client, library).json()["root"]
    result = scan(client, root["id"])
    assert result["rolls_created"] == 1
    assert result["frames_added"] == 0
    assert any(r["title"] == "Waiting for the scanner" for r in client.get("/api/films").json())


# --- previews, downloads and the no-delete promise ----------------------------


def test_a_linked_file_can_be_previewed_and_downloaded(client, library):
    make_roll_folder(library, "Served", {"s_001.png": PNG_1x1})
    root = register(client, library).json()["root"]
    scan(client, root["id"])
    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Served")
    frame = client.get(f"/api/films/{roll['id']}").json()["images"][0]

    preview = client.get(f"/api/images/{frame['id']}/preview?width=64")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"

    download = client.get(f"/api/images/{frame['id']}/download")
    assert download.status_code == 200
    assert download.content == PNG_1x1
    assert "s_001.png" in download.headers["content-disposition"]


def test_deleting_a_linked_frame_never_deletes_the_file(client, library):
    make_roll_folder(library, "Precious", {"p_001.tif": PNG_1x1 + b"precious"})
    root = register(client, library).json()["root"]
    scan(client, root["id"])
    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Precious")
    frame = client.get(f"/api/films/{roll['id']}").json()["images"][0]
    on_disk = library / "Precious" / "p_001.tif"

    # Even with delete_file=true, which does remove a managed file.
    res = client.delete(f"/api/images/{frame['id']}?delete_file=true")
    assert res.status_code == 200, res.text
    assert on_disk.exists(), "a linked file belongs to the user, not to NegArchive"


def test_bulk_delete_never_deletes_a_linked_file(client, library):
    make_roll_folder(library, "Bulk", {"b_001.tif": PNG_1x1 + b"bulk"})
    root = register(client, library).json()["root"]
    scan(client, root["id"])
    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Bulk")
    frame = client.get(f"/api/films/{roll['id']}").json()["images"][0]
    on_disk = library / "Bulk" / "b_001.tif"

    client.post("/api/images/bulk_delete", json={"ids": [frame["id"]], "delete_file": True})
    assert on_disk.exists()


def test_unregistering_a_root_keeps_the_frames_by_default(client, library):
    make_roll_folder(library, "Forget", {"f_001.tif": PNG_1x1 + b"forget"})
    root = register(client, library).json()["root"]
    scan(client, root["id"])
    before = client.get("/api/images?storage_mode=linked&limit=500").json()["total"]

    res = client.delete(f"/api/library/roots/{root['id']}")
    assert res.status_code == 200
    assert res.json()["forgotten_frames"] == 0
    assert client.get("/api/images?storage_mode=linked&limit=500").json()["total"] == before
    assert (library / "Forget" / "f_001.tif").exists()


def test_unregistering_with_forget_frames_removes_the_records_only(client, library):
    make_roll_folder(library, "Drop", {"d_001.tif": PNG_1x1 + b"drop"})
    root = register(client, library).json()["root"]
    result = scan(client, root["id"])
    assert result["frames_added"] == 1

    res = client.delete(f"/api/library/roots/{root['id']}?forget_frames=true")
    assert res.json()["forgotten_frames"] == 1
    assert (library / "Drop" / "d_001.tif").exists()


# --- the watch toggle and the last-scan readout -------------------------------


def test_watching_is_recorded_and_reported(client, library):
    root = register(client, library, watch=True, label="Scanner").json()["root"]
    assert root["watch"] is True

    info = client.get("/api/system/info").json()["watch"]
    assert info["roots_watched"] >= 1

    updated = client.put(f"/api/library/roots/{root['id']}", json={"watch": False}).json()["root"]
    assert updated["watch"] is False


def test_a_scan_records_when_it_last_ran(client, library):
    make_roll_folder(library, "Timed", {"t_001.tif": PNG_1x1 + b"timed"})
    root = register(client, library).json()["root"]
    assert root["last_scan_at"] is None

    scan(client, root["id"])
    listed = next(r for r in client.get("/api/library/roots").json()["roots"] if r["id"] == root["id"])
    assert listed["last_scan_at"] is not None
    assert "1 new" in listed["last_scan_summary"]
    assert listed["frame_count"] == 1


def test_the_watch_sweep_picks_up_a_new_folder(client, library):
    """The poller's one pass, called directly — no waiting on a timer in a test."""
    from app.services.watcher import _sweep_once

    register(client, library, watch=True)
    make_roll_folder(library, "Dropped in later", {"l_001.tif": PNG_1x1 + b"later"})

    message = _sweep_once()
    assert message and "Dropped in later" not in message  # the summary names the root, not the folder
    roll = next(r for r in client.get("/api/films").json() if r["title"] == "Dropped in later")
    assert roll["image_count"] == 1


def test_the_watch_sweep_respects_the_settings_toggle(client, library, monkeypatch):
    from app.services.watcher import _sweep_once

    register(client, library, watch=True)
    client.put("/api/system/settings", json={"watch_enabled": False})
    make_roll_folder(library, "Ignored while off", {"i_001.tif": PNG_1x1 + b"off"})
    try:
        assert _sweep_once() is None
        assert not any(r["title"] == "Ignored while off" for r in client.get("/api/films").json())
    finally:
        client.put("/api/system/settings", json={"watch_enabled": True})
