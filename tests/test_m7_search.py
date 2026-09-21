"""Search (docs/ROADMAP.md, M7): one grammar, one matcher, every list.

What is protected here: a word finds a roll by anything on or *in* it (its
frames' notes included), a typo still finds it when pg_trgm is there, the
qualifiers pin a word to one field, the results come best-first, and the
global endpoint groups everything by kind with honest totals. The roll list
and the frames page run on the same matcher, so they are checked through the
same fixtures.
"""

import uuid

import pytest

from app.services import search as search_svc

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)

#: One tag per run so the assertions ignore what other modules left behind.
TAG = f"s{uuid.uuid4().hex[:6]}"


def make_roll(client, title, **fields):
    payload = {"title": title}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id, filename, notes=None, frame_number=None):
    data = {"type": "scan", "film_roll_id": str(roll_id)}
    if notes is not None:
        data["notes"] = notes
    if frame_number is not None:
        data["frame_number"] = str(frame_number)
    res = client.post("/api/images/upload", files={"file": (filename, PNG_1x1, "image/png")}, data=data)
    assert res.status_code == 200, res.text
    return res.json()["image"]


def rolls(client, q, **extra):
    params = {"q": q, "limit": 50, **extra}
    res = client.get("/api/films", params=params)
    assert res.status_code == 200, res.text
    return [r["title"] for r in res.json()["items"]]


def frames(client, q):
    res = client.get("/api/images", params={"q": q, "limit": 50})
    assert res.status_code == 200, res.text
    return res.json()["items"]


def search(client, q, **extra):
    res = client.get("/api/search", params={"q": q, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def group(payload, kind):
    return next(g for g in payload["groups"] if g["kind"] == kind)


@pytest.fixture(scope="module")
def archive(client):
    """Three rolls, a camera, a film stock, a binder with a page, and a few frames."""
    camera = client.post("/api/cameras", json={"name": f"Nikon FM2 {TAG}", "mount": "Nikon F"}).json()["camera"]
    film = client.post("/api/filmstocks", json={"name": f"Kodak Portra 400 {TAG}", "manufacturer": "Kodak", "iso": 400, "kind": "color"}).json()["filmstock"]

    building = client.post("/api/locations", json={"kind": "building", "name": f"Archive {TAG}"}).json()["location"]
    binder = client.post("/api/locations", json={"kind": "binder", "name": f"Binder Harbour {TAG}", "parent_id": building["id"]}).json()["location"]
    pages = client.post(f"/api/locations/{binder['id']}/pages", json={"count": 1}).json()["pages"]

    harbour = make_roll(
        client,
        f"Harbour at dawn {TAG}",
        camera_id=camera["id"],
        film_stock_id=film["id"],
        start_date="2024-07-01",
        end_date="2024-07-03",
        notes="Fog on the water",
        location_id=pages[0]["id"],
    )
    kyoto = make_roll(client, f"Kyoto in the rain {TAG}", film_type="Fuji C200", start_date="2023-08-12")
    winter = make_roll(client, f"Winter light {TAG}", camera="Leica M6", start_date="2024-12-20", end_date="2025-01-04")

    upload(client, harbour["id"], f"{TAG}_001.png", notes="Anna on the pier", frame_number=1)
    upload(client, harbour["id"], f"{TAG}_002.png", frame_number=2)
    upload(client, kyoto["id"], f"kyoto_{TAG}_07.png", notes="Umbrellas at Gion", frame_number=7)

    # Filing the harbour roll on a page made it "sleeved"; the winter roll is at the lab.
    client.post(f"/api/films/{winter['id']}/status", json={"status": "at_lab"})

    return {
        "camera": camera,
        "film": film,
        "binder": binder,
        "page": pages[0],
        "harbour": harbour,
        "kyoto": kyoto,
        "winter": winter,
    }


# --- the grammar ---------------------------------------------------------------


def test_the_parser_splits_words_phrases_and_qualifiers():
    q = search_svc.parse('harbour "second  visit" "one" camera:nikon in:"binder 3" f:2.8 YEAR:2024')
    assert q.terms == ["harbour", "one", "f:2.8"]
    assert q.phrases == ["second visit"]
    assert q.qualifiers == {"camera": ["nikon"], "location": ["binder 3"], "year": ["2024"]}
    assert q.phrase == "harbour one f:2.8 second visit"
    assert search_svc.parse("   ").empty
    assert not search_svc.parse("status:sleeved").empty


def test_like_metacharacters_are_escaped():
    assert search_svc.like_pattern("50%_x") == "%50\\%\\_x%"


# --- rolls ----------------------------------------------------------------------


def test_every_word_must_match_somewhere_on_the_roll(client, archive):
    assert rolls(client, f"harbour {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"{TAG} dawn fog") == [archive["harbour"]["title"]]
    assert rolls(client, f"{TAG} dawn kyoto") == []


def test_a_roll_is_found_by_its_frames_notes_and_filenames(client, archive):
    assert rolls(client, f"anna {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"gion {TAG}") == [archive["kyoto"]["title"]]
    assert archive["kyoto"]["title"] in rolls(client, f"kyoto_{TAG}_07")


def test_a_roll_is_found_by_its_catalog_gear_and_legacy_names(client, archive):
    assert rolls(client, f"portra {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"nikon {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"leica {TAG}") == [archive["winter"]["title"]]
    assert rolls(client, f"c200 {TAG}") == [archive["kyoto"]["title"]]


def test_a_roll_is_found_by_the_year_it_was_shot(client, archive):
    found = rolls(client, f"2024 {TAG}")
    assert archive["harbour"]["title"] in found
    assert archive["winter"]["title"] in found  # ran into 2025, started in 2024
    assert archive["kyoto"]["title"] not in found
    assert rolls(client, f"2025 {TAG}") == [archive["winter"]["title"]]


def test_a_roll_is_found_by_its_location_path(client, archive):
    # The roll sits on a *page* of the binder; the binder's name finds it anyway.
    assert rolls(client, f"binder {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"archive {TAG}") == [archive["harbour"]["title"]]


def test_a_roll_is_found_by_its_status_label(client, archive):
    assert rolls(client, f"sleeved {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"lab {TAG}") == [archive["winter"]["title"]]


def test_a_quoted_phrase_must_appear_as_written(client, archive):
    assert rolls(client, f'"in the rain" {TAG}') == [archive["kyoto"]["title"]]
    assert rolls(client, f'"rain in" {TAG}') == []


def test_qualifiers_pin_a_word_to_one_field(client, archive):
    assert rolls(client, f"camera:nikon {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"camera:leica {TAG}") == [archive["winter"]["title"]]
    assert rolls(client, f"film:portra {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"film:c200 {TAG}") == [archive["kyoto"]["title"]]
    assert rolls(client, f"year:2023 {TAG}") == [archive["kyoto"]["title"]]
    assert rolls(client, f"status:sleeved {TAG}") == [archive["harbour"]["title"]]
    assert rolls(client, f"status:lab {TAG}") == [archive["winter"]["title"]]
    assert rolls(client, f'status:"at the lab" {TAG}') == [archive["winter"]["title"]]
    assert rolls(client, f"status:shot {TAG}") == []
    assert rolls(client, f'location:"binder harbour" {TAG}') == [archive["harbour"]["title"]]
    assert rolls(client, f"in:nowhere {TAG}") == []
    assert rolls(client, f"serial:{archive['kyoto']['archive_serial']} {TAG}") == [archive["kyoto"]["title"]]
    assert rolls(client, f"serial:2023 {TAG}") == [archive["kyoto"]["title"]]  # the year is in the serial
    assert rolls(client, f"frame:7 {TAG}") == [archive["kyoto"]["title"]]
    # "fog" is in the notes, not the camera: the qualifier does not leak.
    assert rolls(client, f"camera:fog {TAG}") == []


def test_an_unknown_qualifier_is_just_a_word(client, archive):
    make_roll(client, f"Aperture test {TAG}", notes="shot at f:2.8 throughout")
    assert rolls(client, f"f:2.8 {TAG}") == [f"Aperture test {TAG}"]


def test_the_best_match_comes_first(client, archive):
    make_roll(client, f"Harbour {TAG}")  # exact title beats "Harbour at dawn"
    make_roll(client, f"Notes only {TAG}", notes="a harbour in the notes")
    found = rolls(client, f"harbour {TAG}")
    assert found[0] == f"Harbour {TAG}"
    assert found[1] == archive["harbour"]["title"]
    assert found[-1] == f"Notes only {TAG}"


def test_a_typo_still_finds_the_roll_when_pg_trgm_is_installed(client, archive):
    payload = search(client, f"harbor {TAG}", kinds="roll")
    if not payload["fuzzy"]:
        pytest.skip("pg_trgm is not installed in this database")
    assert archive["harbour"]["title"] in [i["title"] for i in group(payload, "roll")["items"]]
    assert rolls(client, f"kodack {TAG}") == [archive["harbour"]["title"]]  # via the film stock's name
    assert rolls(client, f"xyzzy {TAG}") == []  # nothing is nearly that
    assert rolls(client, f'"harbor at dawn" {TAG}') == []  # a quoted phrase is never fuzzy


def test_the_unfiltered_list_is_still_newest_first(client, archive):
    before = client.get("/api/films", params={"limit": 1}).json()["total"]
    newest = make_roll(client, f"Newest {TAG}")
    page = client.get("/api/films", params={"limit": 1}).json()
    assert page["items"][0]["title"] == newest["title"]
    assert page["total"] == before + 1


# --- frames ---------------------------------------------------------------------


def test_frames_are_found_by_note_filename_number_and_roll(client, archive):
    assert [f["notes"] for f in frames(client, f"anna {TAG}")] == ["Anna on the pier"]
    assert [f["frame_number"] for f in frames(client, f"kyoto_{TAG}_07")] == [7]
    assert {f["frame_number"] for f in frames(client, f"harbour {TAG}")} == {1, 2}
    assert [f["frame_number"] for f in frames(client, f"frame:2 roll:harbour {TAG}")] == [2]
    assert [f["frame_number"] for f in frames(client, f"#7 {TAG}")] == [7]
    assert [f["frame_number"] for f in frames(client, f"camera:nikon {TAG}")] == [1, 2]


# --- the global endpoint --------------------------------------------------------


def test_the_global_search_groups_everything_it_finds(client, archive):
    payload = search(client, f"harbour {TAG}")
    kinds = [g["kind"] for g in payload["groups"]]
    assert kinds == ["roll", "frame", "camera", "lens", "film_stock", "location"]

    roll_group = group(payload, "roll")
    assert roll_group["items"][0]["title"] == f"Harbour {TAG}"
    item = next(i for i in roll_group["items"] if i["id"] == archive["harbour"]["id"])
    assert item["url"] == f"/films/{archive['harbour']['id']}"
    assert item["serial"] == archive["harbour"]["archive_serial"]
    assert item["camera"] == archive["camera"]["name"]
    assert item["film_type"] == archive["film"]["name"]
    assert item["image_count"] == 2
    assert item["cover_image_id"] is not None
    assert "Binder Harbour" in item["location_path"]

    assert group(payload, "frame")["total"] == 2
    frame = group(payload, "frame")["items"][0]
    assert frame["url"].startswith("/images/")
    assert frame["roll_title"] == archive["harbour"]["title"]

    location = group(payload, "location")
    assert location["total"] >= 2  # the binder and its page
    assert location["items"][0]["title"] == archive["binder"]["name"]
    assert location["items"][0]["url"] == f"/locations/{archive['binder']['id']}"
    assert location["items"][0]["kind_label"] == "Binder"

    assert payload["total"] == sum(g["total"] for g in payload["groups"])


def test_the_global_search_finds_gear(client, archive):
    payload = search(client, f"nikon {TAG}")
    camera = group(payload, "camera")
    assert camera["total"] == 1
    assert camera["items"][0]["title"] == archive["camera"]["name"]
    assert camera["items"][0]["url"] == f"/gear?tab=cameras&highlight={archive['camera']['id']}"
    assert camera["items"][0]["subtitle"] == "Nikon F"

    film = group(search(client, f"portra {TAG}"), "film_stock")
    assert film["items"][0]["title"] == archive["film"]["name"]
    assert film["items"][0]["subtitle"] == "Kodak · ISO 400"


def test_kinds_and_limit_narrow_the_answer(client, archive):
    payload = search(client, TAG, kinds="roll", limit=2)
    assert [g["kind"] for g in payload["groups"]] == ["roll"]
    assert len(payload["groups"][0]["items"]) == 2
    assert payload["groups"][0]["total"] >= 3  # the count is honest, the page is not the total

    res = client.get("/api/search", params={"q": TAG, "kinds": "roll,cats"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_kind"


def test_an_empty_query_answers_with_nothing_rather_than_everything(client, archive):
    payload = search(client, "   ")
    assert payload["groups"] == []
    assert payload["total"] == 0
    assert client.get("/api/search").json()["groups"] == []
