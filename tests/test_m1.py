"""Tests for the backend additions M1's UI needs (docs/ROADMAP.md, M1).

Four things were added, all driven by a concrete screen:

* ``image_count`` / ``cover_image_id`` on ``GET /api/films`` — the roll list
* ``POST /api/images/bulk_update`` and ``bulk_delete`` — multi-select in the roll workspace
* a disk thumbnail cache for ``GET /api/images/{id}/preview`` — the frame grid
* structured ``{"error": {"code", "message"}}`` bodies for the validation failures the
  dialogs can produce
"""

import glob
import os
import uuid

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_roll(client, **fields) -> dict:
    payload = {"title": unique("Roll")}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload_frame(client, roll_id=None, frame_number=None) -> dict:
    data = {"type": "scan"}
    if roll_id is not None:
        data["film_roll_id"] = str(roll_id)
    if frame_number is not None:
        data["frame_number"] = str(frame_number)
    res = client.post("/api/images/upload", files={"file": ("frame.png", PNG_1x1, "image/png")}, data=data)
    assert res.status_code == 200, res.text
    return res.json()["image"]


def find_roll(client, roll_id: int) -> dict:
    return next(f for f in client.get("/api/films").json() if f["id"] == roll_id)


# --- roll list: frame count and cover thumbnail, without an N+1 ---------------


def test_film_list_reports_zero_frames_for_an_empty_roll(client):
    roll = make_roll(client)
    listed = find_roll(client, roll["id"])
    assert listed["image_count"] == 0
    assert listed["cover_image_id"] is None
    assert listed["cover_image_ids"] == []


def test_film_list_returns_a_short_thumbnail_strip(client):
    roll = make_roll(client)
    frames = [upload_frame(client, roll["id"], frame_number=n) for n in range(1, 7)]

    listed = find_roll(client, roll["id"])
    assert listed["image_count"] == 6
    # capped, so a 36-frame roll does not ship 36 ids per row
    assert listed["cover_image_ids"] == [f["id"] for f in frames[:4]]
    assert listed["cover_image_id"] == listed["cover_image_ids"][0]


def test_film_list_counts_frames_and_picks_the_lowest_frame_as_cover(client):
    roll = make_roll(client)
    second = upload_frame(client, roll["id"], frame_number=2)
    first = upload_frame(client, roll["id"], frame_number=1)
    upload_frame(client, roll["id"])  # no frame number: sorts last

    listed = find_roll(client, roll["id"])
    assert listed["image_count"] == 3
    assert listed["cover_image_id"] == first["id"]
    assert listed["cover_image_id"] != second["id"]


def test_contact_sheets_do_not_count_as_frames(client):
    roll = make_roll(client)
    upload_frame(client, roll["id"], frame_number=1)
    client.post(
        "/api/images/upload",
        files={"file": ("sheet.png", PNG_1x1, "image/png")},
        data={"type": "contact_sheet", "film_roll_id": str(roll["id"])},
    )
    assert find_roll(client, roll["id"])["image_count"] == 1


def test_single_film_endpoint_agrees_with_the_list(client):
    roll = make_roll(client)
    upload_frame(client, roll["id"], frame_number=5)
    upload_frame(client, roll["id"], frame_number=3)

    detail = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert (detail["image_count"], detail["cover_image_id"]) == (
        find_roll(client, roll["id"])["image_count"],
        find_roll(client, roll["id"])["cover_image_id"],
    )


# --- bulk update -------------------------------------------------------------


def test_bulk_update_reassigns_frames_to_another_roll(client):
    source, target = make_roll(client), make_roll(client)
    a = upload_frame(client, source["id"])
    b = upload_frame(client, source["id"])

    res = client.post("/api/images/bulk_update", json={"ids": [a["id"], b["id"]], "film_roll_id": target["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["updated"] == 2
    assert all(i["film_roll_id"] == target["id"] for i in res.json()["images"])
    assert find_roll(client, source["id"])["image_count"] == 0
    assert find_roll(client, target["id"])["image_count"] == 2


def test_bulk_update_sets_capture_date_and_leaves_other_fields_alone(client):
    roll = make_roll(client)
    frame = upload_frame(client, roll["id"], frame_number=7)

    res = client.post("/api/images/bulk_update", json={"ids": [frame["id"]], "capture_date": "2024-07-01"})
    assert res.status_code == 200, res.text
    updated = client.get(f"/api/images/{frame['id']}").json()
    assert updated["capture_date"] == "2024-07-01"
    assert updated["frame_number"] == 7
    assert updated["film_roll_id"] == roll["id"]


def test_bulk_update_can_unassign_and_clear_a_date(client):
    roll = make_roll(client)
    frame = upload_frame(client, roll["id"])
    client.post("/api/images/bulk_update", json={"ids": [frame["id"]], "capture_date": "2024-07-01"})

    res = client.post(
        "/api/images/bulk_update",
        json={"ids": [frame["id"]], "film_roll_id": None, "capture_date": None},
    )
    assert res.status_code == 200, res.text
    updated = client.get(f"/api/images/{frame['id']}").json()
    assert updated["film_roll_id"] is None
    assert updated["capture_date"] is None


def test_bulk_update_rejects_an_empty_selection(client):
    res = client.post("/api/images/bulk_update", json={"ids": [], "frame_number": 1})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_ids"


def test_bulk_update_rejects_a_bad_date(client):
    frame = upload_frame(client)
    res = client.post("/api/images/bulk_update", json={"ids": [frame["id"]], "capture_date": "01.07.2024"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_date"
    assert "2024-07-01" in res.json()["error"]["message"]


def test_bulk_update_rejects_an_unknown_roll(client):
    frame = upload_frame(client)
    res = client.post("/api/images/bulk_update", json={"ids": [frame["id"]], "film_roll_id": 10**8})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "unknown_roll"


def test_bulk_update_needs_at_least_one_field(client):
    frame = upload_frame(client)
    res = client.post("/api/images/bulk_update", json={"ids": [frame["id"]]})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "nothing_to_update"


# --- bulk delete -------------------------------------------------------------


def test_bulk_delete_removes_rows_but_keeps_files_by_default(client):
    roll = make_roll(client)
    frame = upload_frame(client, roll["id"])
    path = client.get(f"/api/images/{frame['id']}").json()["path"]
    assert os.path.exists(path)

    res = client.post("/api/images/bulk_delete", json={"ids": [frame["id"]]})
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] == 1
    assert client.get(f"/api/images/{frame['id']}").json() == {"error": "not_found"}
    assert os.path.exists(path), "delete_file defaults to false"
    os.remove(path)


def test_bulk_delete_with_delete_file_removes_the_file(client):
    roll = make_roll(client)
    frame = upload_frame(client, roll["id"])
    path = client.get(f"/api/images/{frame['id']}").json()["path"]

    res = client.post("/api/images/bulk_delete", json={"ids": [frame["id"]], "delete_file": True})
    assert res.status_code == 200, res.text
    assert not os.path.exists(path)
    assert find_roll(client, roll["id"])["image_count"] == 0


def test_bulk_delete_rejects_an_empty_selection(client):
    res = client.post("/api/images/bulk_delete", json={"ids": []})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_ids"


# --- preview thumbnail cache -------------------------------------------------


def test_preview_is_cached_on_disk_and_reused(client):
    frame = upload_frame(client)
    first = client.get(f"/api/images/{frame['id']}/preview?width=200")
    assert first.status_code == 200
    assert first.headers["x-preview-cache"] == "miss"
    assert first.headers["content-type"] == "image/jpeg"

    cached = glob.glob(os.path.join("static", "cache", f"{frame['id']}_200_*.jpg"))
    assert len(cached) == 1, cached

    second = client.get(f"/api/images/{frame['id']}/preview?width=200")
    assert second.status_code == 200
    assert second.headers["x-preview-cache"] == "hit"
    assert second.content == first.content


def test_preview_cache_is_keyed_by_width(client):
    frame = upload_frame(client)
    client.get(f"/api/images/{frame['id']}/preview?width=200")
    client.get(f"/api/images/{frame['id']}/preview?width=400")
    assert len(glob.glob(os.path.join("static", "cache", f"{frame['id']}_*.jpg"))) == 2


def test_preview_cache_follows_the_source_file_mtime(client):
    frame = upload_frame(client)
    client.get(f"/api/images/{frame['id']}/preview?width=200")
    path = client.get(f"/api/images/{frame['id']}").json()["path"]

    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    res = client.get(f"/api/images/{frame['id']}/preview?width=200")

    assert res.headers["x-preview-cache"] == "miss", "a changed file must not serve a stale thumbnail"
    # the superseded entry is swept, so the cache does not grow without bound
    assert len(glob.glob(os.path.join("static", "cache", f"{frame['id']}_200_*.jpg"))) == 1


def test_deleting_an_image_drops_its_cached_previews(client):
    frame = upload_frame(client)
    client.get(f"/api/images/{frame['id']}/preview?width=200")
    client.post("/api/images/bulk_delete", json={"ids": [frame["id"]], "delete_file": True})
    assert glob.glob(os.path.join("static", "cache", f"{frame['id']}_*.jpg")) == []


# --- structured validation errors for the dialogs ----------------------------


def test_roll_requires_a_title(client):
    res = client.post("/api/films", json={"title": "   "})
    assert res.status_code == 400
    body = res.json()["error"]
    assert body["code"] == "invalid_title"
    assert "required" in body["message"].lower()


def test_roll_rejects_a_malformed_date(client):
    res = client.post("/api/films", json={"title": unique("Roll"), "start_date": "07/2024"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_date"


def test_roll_rejects_an_inverted_date_range(client):
    res = client.post(
        "/api/films",
        json={"title": unique("Roll"), "start_date": "2024-07-10", "end_date": "2024-07-01"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_date_range"


def test_roll_update_rejects_a_malformed_date_and_changes_nothing(client):
    roll = make_roll(client, start_date="2024-07-01")
    res = client.put(f"/api/films/{roll['id']}", json={"title": "Renamed", "start_date": "nope"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_date"
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["title"] == roll["title"]


def test_duplicate_camera_name_is_a_409_not_a_500(client):
    name = unique("Nikon F5")
    assert client.post("/api/cameras", json={"name": name}).status_code == 200
    res = client.post("/api/cameras", json={"name": name})
    assert res.status_code == 409
    body = res.json()["error"]
    assert body["code"] == "duplicate_name"
    assert name in body["message"]


def test_duplicate_lens_name_is_a_409(client):
    name = unique("Nikkor 50")
    client.post("/api/lenses", json={"name": name})
    assert client.post("/api/lenses", json={"name": name}).status_code == 409


def test_duplicate_filmstock_name_is_a_409(client):
    name = unique("Portra")
    client.post("/api/filmstocks", json={"name": name, "iso": 400, "kind": "color"})
    res = client.post("/api/filmstocks", json={"name": name, "iso": 400, "kind": "color"})
    assert res.status_code == 409


def test_unknown_filmstock_kind_lists_the_valid_ones(client):
    res = client.post("/api/filmstocks", json={"name": unique("Stock"), "iso": 400, "kind": "Color Negative"})
    assert res.status_code == 400
    body = res.json()["error"]
    assert body["code"] == "invalid_kind"
    assert "black_and_white" in body["message"] and "motion_picture" in body["message"]


def test_non_numeric_iso_is_a_400(client):
    res = client.post("/api/filmstocks", json={"name": unique("Stock"), "iso": "four hundred", "kind": "color"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_number"


def test_catalog_name_is_required(client):
    res = client.post("/api/cameras", json={"name": ""})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_name"


def test_non_numeric_frame_number_is_a_400(client):
    frame = upload_frame(client)
    res = client.put(f"/api/images/{frame['id']}", json={"frame_number": "twelve"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_number"


def test_malformed_capture_date_on_a_frame_is_a_400(client):
    frame = upload_frame(client)
    res = client.put(f"/api/images/{frame['id']}", json={"capture_date": "yesterday"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_date"


def test_a_contact_sheet_needs_two_frames(client):
    roll = make_roll(client)
    upload_frame(client, roll["id"])
    res = client.post(f"/api/films/{roll['id']}/contact_sheet")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "not_enough_images"
