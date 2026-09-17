"""M4 — paper ↔ virtual (docs/M4_PAPER.md): serials, locations, lifecycle, scanning,
strip math, codes and the print queue."""

import uuid

import pytest

from app.errors import ApiError
from app.services import codes, strips


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_roll(client, **fields) -> dict:
    payload = {"title": unique("Roll")}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def make_location(client, **fields) -> dict:
    payload = {"kind": "box", "name": unique("Box")}
    payload.update(fields)
    res = client.post("/api/locations", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["location"]


def make_binder(client, pages=3, parent_id=None) -> dict:
    binder = make_location(client, kind="binder", name=unique("Binder"), code="B01", parent_id=parent_id)
    res = client.post(f"/api/locations/{binder['id']}/pages", json={"count": pages})
    assert res.status_code == 200, res.text
    return client.get(f"/api/locations/{binder['id']}").json()


# --- serials -------------------------------------------------------------------


def test_a_new_roll_gets_a_serial_for_its_year(client):
    roll = make_roll(client, start_date="2031-03-01")
    assert roll["archive_serial"].startswith("NEG-2031-")
    number = int(roll["archive_serial"].rsplit("-", 1)[1])
    second = make_roll(client, start_date="2031-05-01")
    assert int(second["archive_serial"].rsplit("-", 1)[1]) == number + 1


def test_a_given_serial_is_kept_and_upper_cased(client):
    roll = make_roll(client, archive_serial="neg-1999-0007")
    assert roll["archive_serial"] == "NEG-1999-0007"


def test_duplicate_serials_are_refused(client):
    first = make_roll(client)
    res = client.post("/api/films", json={"title": "dup", "archive_serial": first["archive_serial"].lower()})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "duplicate_serial"
    assert res.json()["error"]["field"] == "archive_serial"


def test_a_printed_serial_is_frozen_unless_forced(client):
    roll = make_roll(client)
    client.post("/api/print/mark", json={"roll_ids": [roll["id"]]})
    res = client.put(f"/api/films/{roll['id']}", json={"archive_serial": unique("X-2020-1")})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "serial_frozen"
    res = client.put(f"/api/films/{roll['id']}?force=true", json={"archive_serial": "NEG-2020-9999"})
    assert res.status_code == 200
    assert res.json()["film"]["archive_serial"] == "NEG-2020-9999"


def test_lookup_by_serial(client):
    roll = make_roll(client)
    res = client.get(f"/api/rolls/by-serial/{roll['archive_serial'].lower()}")
    assert res.status_code == 200
    assert res.json()["roll"]["id"] == roll["id"]
    assert client.get("/api/rolls/by-serial/NOPE-0000-0000").status_code == 404


def test_the_serial_prefix_is_a_setting(client):
    client.put("/api/system/settings", json={"serial_prefix": "arc"})
    try:
        roll = make_roll(client, start_date="2032-01-01")
        assert roll["archive_serial"].startswith("ARC-2032-")
    finally:
        client.put("/api/system/settings", json={"serial_prefix": "NEG"})


# --- locations -----------------------------------------------------------------


def test_the_tree_carries_paths_and_counts(client):
    building = make_location(client, kind="building", name="Archive Q", code="Q")
    shelf = make_location(client, kind="shelf", name="Shelf 2", code="S2", parent_id=building["id"])
    binder = make_binder(client, pages=2, parent_id=shelf["id"])
    page = binder["children"][0]
    assert page["kind"] == "sleeve"
    assert page["path"] == "Q · Archive Q / S2 · Shelf 2 / B01 · " + binder["location"]["name"] + " / P01 · Page 1"
    roll = make_roll(client, location_id=page["id"])
    assert roll["location_id"] == page["id"]
    assert roll["status"] == "sleeved"
    tree = client.get("/api/locations").json()["locations"]
    by_id = {n["id"]: n for n in tree}
    assert by_id[page["id"]]["roll_count"] == 1
    assert by_id[building["id"]]["rolls_in_subtree"] == 1
    assert by_id[building["id"]]["roll_count"] == 0


def test_a_sleeve_holds_exactly_one_roll(client):
    binder = make_binder(client, pages=1)
    page = binder["children"][0]
    first = make_roll(client)
    second = make_roll(client)
    assert client.post(f"/api/films/{first['id']}/move", json={"location_id": page["id"]}).status_code == 200
    res = client.post(f"/api/films/{second['id']}/move", json={"location_id": page["id"]})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "sleeve_occupied"
    assert first["archive_serial"] in res.json()["error"]["message"]


def test_moving_into_a_binder_takes_the_next_free_page(client):
    binder = make_binder(client, pages=2)
    a, b, c = make_roll(client), make_roll(client), make_roll(client)
    first = client.post(f"/api/films/{a['id']}/move", json={"location_id": binder["location"]["id"]}).json()
    assert first["location"]["code"] == "P01"
    second = client.post(f"/api/films/{b['id']}/move", json={"location_id": binder["location"]["id"]}).json()
    assert second["location"]["code"] == "P02"
    res = client.post(f"/api/films/{c['id']}/move", json={"location_id": binder["location"]["id"]})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "no_free_page"
    detail = client.get(f"/api/locations/{binder['location']['id']}").json()
    assert detail["next_free_sleeve_id"] is None
    assert [child["rolls"][0]["id"] for child in detail["children"]] == [a["id"], b["id"]]


def test_moves_are_logged_and_unsleeving_changes_status(client):
    binder = make_binder(client, pages=1)
    box = make_location(client, kind="box", name="Lab box")
    roll = make_roll(client)
    client.post(f"/api/films/{roll['id']}/move", json={"location_id": binder["children"][0]["id"], "note": "filed"})
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["status"] == "sleeved"
    client.post(f"/api/films/{roll['id']}/move", json={"location_id": box["id"]})
    detail = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert detail["status"] == "back"  # no scans yet, so not "scanned"
    assert detail["location_path"] == "Lab box"
    moves = client.get(f"/api/films/{roll['id']}/moves").json()["moves"]
    assert len(moves) == 2
    assert moves[0]["to"] == "Lab box" and moves[1]["note"] == "filed"


def test_bulk_move_and_list_filter_by_location(client):
    building = make_location(client, kind="building", name=unique("House"))
    box = make_location(client, kind="box", name=unique("Box"), parent_id=building["id"])
    rolls = [make_roll(client) for _ in range(3)]
    res = client.post("/api/films/bulk_move", json={"ids": [r["id"] for r in rolls], "location_id": box["id"]})
    assert res.status_code == 200 and len(res.json()["moved"]) == 3
    listed = client.get(f"/api/films?location_id={building['id']}&limit=50").json()
    assert {r["id"] for r in rolls} <= {item["id"] for item in listed["items"]}


def test_deleting_a_location_in_use_needs_force(client):
    box = make_location(client)
    roll = make_roll(client, location_id=box["id"])
    res = client.delete(f"/api/locations/{box['id']}")
    assert res.status_code == 409
    res = client.delete(f"/api/locations/{box['id']}?force=true")
    assert res.status_code == 200 and res.json()["rolls_unfiled"] == 1
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["location_id"] is None


def test_a_location_cannot_be_moved_inside_itself(client):
    top = make_location(client, kind="shelf", name="Top")
    child = make_location(client, kind="box", name="Child", parent_id=top["id"])
    res = client.put(f"/api/locations/{top['id']}", json={"parent_id": child["id"]})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_parent"


def test_binder_discrepancies_report_missing_pages(client):
    binder = make_binder(client, pages=3)
    middle = binder["children"][1]
    assert client.delete(f"/api/locations/{middle['id']}").status_code == 200
    detail = client.get(f"/api/locations/{binder['location']['id']}").json()
    assert any(d["kind"] == "missing_page" and "Page 2" in d["message"] for d in detail["discrepancies"])


def test_sleeve_layouts_are_seeded_with_a_default(client):
    layouts = client.get("/api/sleeve_layouts").json()
    assert layouts[0]["is_default"] is True
    assert (layouts[0]["rows"], layouts[0]["frames_per_row"]) == (7, 6)
    assert len(layouts) >= 4


# --- strips --------------------------------------------------------------------


def test_strip_math():
    six = strips.default_strips(7, 6)
    assert strips.position(1, six) == (1, 1)
    assert strips.position(14, six) == (3, 2)
    assert strips.position(42, six) == (7, 6)
    assert strips.position(43, six) is None
    assert strips.position(0, six) is None
    doubled = [5, 5, 5, 5, 5, 5, 6]
    assert strips.position(31, doubled) == (7, 1)
    assert strips.capacity(doubled) == 36
    assert strips.parse_strips("6, 6,6") == [6, 6, 6]
    assert strips.parse_strips("") is None
    with pytest.raises(ApiError):
        strips.parse_strips("6,x")


def test_a_roll_layout_mirrors_the_sleeve(client):
    roll = make_roll(client, strips="5,5")
    assert roll["strips"] == [5, 5] and roll["effective_strips"] == [5, 5]
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[("files", ("NEG_007.png", PNG_1x1, "image/png")), ("files", ("NEG_002.png", PNG_1x1, "image/png"))],
    )
    assert res.status_code == 200, res.text
    layout = client.get(f"/api/films/{roll['id']}/layout").json()
    assert layout["capacity"] == 10
    assert layout["rows"][0][1]["frame_number"] == 2
    assert layout["rows"][1][1]["frame_number"] == 7
    assert layout["unplaced"] == []
    plain = make_roll(client)
    assert plain["effective_strips"] == [6] * 7


PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


# --- lifecycle -----------------------------------------------------------------


def test_status_steps_stamp_their_timestamps(client):
    roll = make_roll(client)
    assert roll["status"] == "back"
    res = client.post(f"/api/films/{roll['id']}/status", json={"status": "at lab"})
    assert res.status_code == 200
    film = res.json()["film"]
    assert film["status"] == "at_lab" and film["lab_sent_at"] is not None
    res = client.post(f"/api/films/{roll['id']}/status", json={"status": "bogus"})
    assert res.status_code == 400


def test_the_first_scan_marks_a_roll_scanned(client):
    roll = make_roll(client)
    client.post(f"/api/films/{roll['id']}/status", json={"status": "back"})
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk", files=[("files", ("a_001.png", PNG_1x1, "image/png"))]
    )
    assert res.status_code == 200
    film = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert film["status"] == "scanned" and film["scanned_at"] is not None


def test_load_film_blocks_a_second_roll_in_the_same_camera(client):
    camera = client.post("/api/cameras", json={"name": unique("Cam")}).json()["camera"]
    first = client.post(f"/api/cameras/{camera['id']}/load", json={"title": "Loaded one"})
    assert first.status_code == 200, first.text
    film = first.json()["film"]
    assert film["status"] == "loaded" and film["loaded_camera_id"] == camera["id"] and film["camera_id"] == camera["id"]
    assert film["archive_serial"]
    second = client.post(f"/api/cameras/{camera['id']}/load", json={})
    assert second.status_code == 409 and second.json()["error"]["code"] == "camera_occupied"
    assert client.get(f"/api/cameras/{camera['id']}/loaded").json()["roll"]["id"] == film["id"]
    # sending it to the lab frees the camera
    client.post(f"/api/films/{film['id']}/status", json={"status": "at_lab"})
    assert client.get(f"/api/cameras/{camera['id']}/loaded").json()["roll"] is None
    assert client.post(f"/api/cameras/{camera['id']}/load", json={}).status_code == 200


def test_work_lists_and_bucket_filter(client):
    loaded = make_roll(client, status="loaded")
    lab = make_roll(client, status="at_lab")
    work = client.get("/api/work").json()
    assert loaded["id"] in {r["id"] for r in work["in_cameras"]["items"]}
    assert lab["id"] in {r["id"] for r in work["at_lab"]["items"]}
    listed = client.get("/api/films?bucket=at_lab&limit=100").json()
    assert lab["id"] in {r["id"] for r in listed["items"]}
    assert client.get("/api/films?status=at_lab&limit=100").status_code == 200
    assert client.get("/api/films?bucket=nope").status_code == 400


# --- scanning ------------------------------------------------------------------


def test_token_grammar():
    assert codes.parse_token("NEG-2024-0011") == {"kind": "roll", "serial": "NEG-2024-0011"}
    assert codes.parse_token("http://negarchive.local:8021/s/NEG-2024-0011")["serial"] == "NEG-2024-0011"
    assert codes.parse_token("https://x/l/17") == {"kind": "location", "id": 17}
    assert codes.parse_token("LOC-5") == {"kind": "location", "id": 5}
    assert codes.parse_token("cmd-move") == {"kind": "command", "command": "MOVE", "known": True}
    assert codes.parse_token("CMD-STATUS-ATLAB")["known"] is True
    assert codes.parse_token("  ") == {"kind": "unknown", "text": ""}
    assert codes.parse_token("harbour")["loose"] is True


def test_resolve_roll_location_and_command(client):
    roll = make_roll(client)
    box = make_location(client)
    assert client.post("/api/scan/resolve", json={"code": roll["archive_serial"].lower()}).json()["roll"]["id"] == roll["id"]
    assert client.post("/api/scan/resolve", json={"code": f"/s/{roll['archive_serial']}"}).json()["url"] == f"/films/{roll['id']}"
    assert client.post("/api/scan/resolve", json={"code": f"LOC-{box['id']}"}).json()["location"]["id"] == box["id"]
    assert client.post("/api/scan/resolve", json={"code": "CMD-MOVE"}).json()["command"] == "MOVE"
    assert client.post("/api/scan/resolve", json={"code": "NEG-1900-0001"}).status_code == 404
    assert client.post("/api/scan/resolve", json={"code": "LOC-999999"}).status_code == 404
    # a typed title still finds the roll
    assert client.post("/api/scan/resolve", json={"code": roll["title"]}).json()["roll"]["id"] == roll["id"]


def test_codes_render_as_svg(client, monkeypatch):
    monkeypatch.setenv("NEGARCHIVE_PUBLIC_HOST", "192.168.1.9")
    roll = make_roll(client)
    qr = client.get("/api/codes/qr.svg", params={"text": "hello"})
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg+xml") and "<svg" in qr.text
    bar = client.get("/api/codes/code128.svg", params={"text": roll["archive_serial"]})
    assert bar.status_code == 200 and "<svg" in bar.text and "<?xml" not in bar.text
    info = client.get(f"/api/codes/for_roll/{roll['id']}").json()
    assert info["qr_text"] == f"http://192.168.1.9:8021/s/{roll['archive_serial']}"
    assert info["barcode_text"] == roll["archive_serial"]
    client.put("/api/system/settings", json={"public_base_url": "https://neg.example.org/"})
    try:
        info = client.get(f"/api/codes/for_roll/{roll['id']}").json()
        assert info["qr_text"] == f"https://neg.example.org/s/{roll['archive_serial']}"
    finally:
        client.put("/api/system/settings", json={"public_base_url": ""})
    assert client.get("/api/scan/commands").json()["commands"][0]["code"].startswith("CMD-")


# --- printing ------------------------------------------------------------------


def test_print_queue_tracks_unprinted_and_moved_rolls(client):
    roll = make_roll(client)
    queue = client.get("/api/print/queue").json()
    entry = next(item for item in queue["items"] if item["id"] == roll["id"])
    assert entry["reason"] == "never_printed" and entry["needs_label"] is True
    assert client.post("/api/print/mark", json={"roll_ids": [roll["id"]]}).json()["marked"] == 1
    assert roll["id"] not in {item["id"] for item in client.get("/api/print/queue").json()["items"]}
    box = make_location(client)
    client.post(f"/api/films/{roll['id']}/move", json={"location_id": box["id"]})
    queue = client.get("/api/print/queue").json()
    entry = next(item for item in queue["items"] if item["id"] == roll["id"])
    assert entry["reason"] == "moved_since_print"
