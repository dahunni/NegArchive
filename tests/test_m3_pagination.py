"""Pagination and server-side search (docs/ROADMAP.md, M3; R#20).

Two things are being protected here. One is the obvious feature: the archive must
not ship every roll and every frame to the browser. The other is the promise that
made it safe to add — **without `limit` the endpoints answer exactly as they did
before**, so nothing written against M0/M1 breaks.
"""

import uuid

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)

#: One tag shared by the rolls this module creates, so the assertions can ignore
#: everything the other test modules left behind in the session's database.
TAG = f"pg{uuid.uuid4().hex[:8]}"


def make_roll(client, title, **fields):
    payload = {"title": title}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id=None, filename="frame.png", notes=None):
    data = {"type": "scan"}
    if roll_id is not None:
        data["film_roll_id"] = str(roll_id)
    if notes is not None:
        data["notes"] = notes
    res = client.post("/api/images/upload", files={"file": (filename, PNG_1x1, "image/png")}, data=data)
    assert res.status_code == 200, res.text
    return res.json()["image"]


def search(client, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    res = client.get(f"/api/films?{query}")
    assert res.status_code == 200, res.text
    return res.json()


# --- backwards compatibility --------------------------------------------------


def test_without_limit_both_endpoints_still_return_a_bare_array(client):
    films = client.get("/api/films")
    assert isinstance(films.json(), list)
    assert films.headers["x-total-count"] == str(len(films.json()))

    images = client.get("/api/images")
    assert isinstance(images.json(), list)
    assert images.headers["x-total-count"] == str(len(images.json()))


def test_with_limit_the_response_carries_the_total(client):
    make_roll(client, f"{TAG} paging one")
    make_roll(client, f"{TAG} paging two")
    make_roll(client, f"{TAG} paging three")

    page = search(client, q=TAG, limit=2, offset=0)
    assert set(page) == {"items", "total", "limit", "offset", "has_more"}
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["has_more"] is True

    rest = search(client, q=TAG, limit=2, offset=2)
    assert len(rest["items"]) == 1
    assert rest["has_more"] is False

    ids = [r["id"] for r in page["items"]] + [r["id"] for r in rest["items"]]
    assert len(set(ids)) == 3, "pages must not overlap or skip"


def test_an_oversized_limit_is_clamped(client):
    page = client.get("/api/films?limit=100000").json()
    assert page["limit"] == 500


# --- searching ----------------------------------------------------------------


def test_the_query_searches_every_text_field(client):
    needle = f"{TAG}-needle"
    make_roll(client, f"{TAG} in the title {needle}")
    make_roll(client, f"{TAG} in the notes", notes=f"shot on a {needle} afternoon")
    make_roll(client, f"{TAG} in the serial", archive_serial=f"{needle}-0001")
    make_roll(client, f"{TAG} not a match")

    assert search(client, q=needle, limit=50)["total"] == 3


def test_every_word_has_to_match(client):
    make_roll(client, f"{TAG} harbour at dawn")
    make_roll(client, f"{TAG} harbour at dusk")

    assert search(client, q=f"{TAG}+harbour", limit=50)["total"] == 2
    assert search(client, q=f"{TAG}+harbour+dawn", limit=50)["total"] == 1
    assert search(client, q=f"{TAG}+harbour+midnight", limit=50)["total"] == 0


def test_the_search_is_case_insensitive(client):
    make_roll(client, f"{TAG} Kyoto In The Rain")
    assert search(client, q=f"{TAG}+kyoto+RAIN", limit=50)["total"] == 1


def test_filtering_by_camera_and_film(client):
    make_roll(client, f"{TAG} f5 roll", camera="Nikon F5", film_type="Fomapan 400")
    make_roll(client, f"{TAG} xg9 roll", camera="Minolta XG9", film_type="Fomapan 400")

    camera = next(c for c in client.get("/api/cameras").json() if c["name"] == "Nikon F5")
    stock = next(s for s in client.get("/api/filmstocks").json() if s["name"] == "Fomapan 400")

    # By id — M2 adds the foreign keys; until then the id resolves to the name.
    by_id = search(client, q=TAG, camera_id=camera["id"], limit=50)
    assert by_id["total"] == 1
    assert by_id["items"][0]["camera"] == "Nikon F5"

    assert search(client, q=TAG, film_stock_id=stock["id"], limit=50)["total"] == 2


def test_an_unknown_gear_id_matches_nothing_rather_than_everything(client):
    assert search(client, q=TAG, camera_id=999999, limit=50)["total"] == 0


def test_the_date_filter_matches_an_overlapping_range(client):
    make_roll(client, f"{TAG} july", start_date="2024-07-01", end_date="2024-07-31")
    make_roll(client, f"{TAG} august", start_date="2024-08-01", end_date="2024-08-31")
    make_roll(client, f"{TAG} the long summer", start_date="2024-06-01", end_date="2024-09-30")

    # "Shot in August" includes the roll that merely ran through August.
    august = search(client, q=TAG, **{"from": "2024-08-01"}, to="2024-08-31", limit=50)
    titles = {r["title"] for r in august["items"]}
    assert titles == {f"{TAG} august", f"{TAG} the long summer"}


def test_a_broken_date_is_a_400_not_a_500(client):
    res = client.get("/api/films?from=07/2024")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_date"


# --- frames -------------------------------------------------------------------


def test_frames_can_be_paginated_and_filtered_by_roll(client):
    roll = make_roll(client, f"{TAG} frames roll")
    for index in range(5):
        upload(client, roll["id"], filename=f"{TAG}_{index + 1:03d}.png")

    page = client.get(f"/api/images?film_id={roll['id']}&limit=2").json()
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert page["has_more"] is True

    last = client.get(f"/api/images?film_id={roll['id']}&limit=2&offset=4").json()
    assert len(last["items"]) == 1
    assert last["has_more"] is False


def test_frames_can_be_narrowed_to_the_ones_without_a_roll(client):
    loose = upload(client, None, filename=f"{TAG}_loose.png")
    page = client.get("/api/images?unassigned=true&limit=500").json()
    assert any(item["id"] == loose["id"] for item in page["items"])
    assert all(item["film_roll_id"] is None for item in page["items"])


def test_frames_can_be_searched_by_note_and_original_filename(client):
    roll = make_roll(client, f"{TAG} searchable frames")
    upload(client, roll["id"], filename=f"{TAG}-findme.png")
    upload(client, roll["id"], filename=f"{TAG}-other.png", notes=f"{TAG} a note worth finding")

    assert client.get(f"/api/images?q={TAG}-findme&limit=50").json()["total"] == 1
    assert client.get(f"/api/images?q={TAG}+worth+finding&limit=50").json()["total"] == 1
