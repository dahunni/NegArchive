"""Regression tests for the M0 fixes (docs/ROADMAP.md, findings R#1-R#8, R#12, R#22).

Every one of these reproduces a bug that was confirmed against Postgres 16.
"""

import uuid

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# --- R#1 / R#22: filmstock expired is a boolean, on Postgres too --------------


def test_filmstock_create_with_boolean_expired(client):
    res = client.post(
        "/api/filmstocks",
        json={"name": unique("Portra 400"), "iso": 400, "kind": "color", "expired": True},
    )
    assert res.status_code == 200, res.text
    stock = res.json()["filmstock"]
    assert stock["expired"] is True


def test_filmstock_update_returns_boolean_and_full_object(client):
    created = client.post(
        "/api/filmstocks",
        json={"name": unique("HP5"), "iso": 400, "kind": "black_and_white", "expired": True},
    ).json()["filmstock"]

    # R#6: the PUT returns the object so the UI can chain an image upload
    res = client.put(f"/api/filmstocks/{created['id']}", json={"expired": False})
    assert res.status_code == 200, res.text
    stock = res.json()["filmstock"]
    assert stock["id"] == created["id"]
    assert stock["expired"] is False
    assert stock["name"] == created["name"]

    # and the read path agrees
    assert client.get(f"/api/filmstocks/{created['id']}").json()["expired"] is False


def test_filmstock_expired_is_never_an_integer(client):
    for stock in client.get("/api/filmstocks").json():
        assert isinstance(stock["expired"], bool), stock


# --- R#6: lens PUT returns the object ---------------------------------------


def test_lens_update_returns_full_object(client):
    created = client.post("/api/lenses", json={"name": unique("Nikkor 50"), "mount": "Nikon F"}).json()["lens"]
    res = client.put(f"/api/lenses/{created['id']}", json={"notes": "sharp"})
    assert res.status_code == 200, res.text
    lens = res.json()["lens"]
    assert lens["id"] == created["id"]
    assert lens["notes"] == "sharp"
    assert lens["mount"] == "Nikon F"


# --- R#5 / R#12: an image can live without a film roll -----------------------


def test_upload_without_film_roll_id(client):
    res = client.post(
        "/api/images/upload",
        files={"file": ("frame.png", PNG_1x1, "image/png")},
        data={"type": "scan"},
    )
    assert res.status_code == 200, res.text
    image = res.json()["image"]
    assert image["film_roll_id"] is None
    assert client.get(f"/api/images/{image['id']}").json()["film_roll_id"] is None


def test_image_can_be_unassigned_from_a_film(client):
    film = client.post("/api/films", json={"title": unique("Roll")}).json()["film"]
    image = client.post(
        "/api/images/upload",
        files={"file": ("frame.png", PNG_1x1, "image/png")},
        data={"type": "scan", "film_roll_id": str(film["id"])},
    ).json()["image"]
    assert image["film_roll_id"] == film["id"]

    res = client.put(f"/api/images/{image['id']}", json={"film_roll_id": None})
    assert res.status_code == 200, res.text
    assert res.json()["image"]["film_roll_id"] is None
    assert client.get(f"/api/images/{image['id']}").json()["film_roll_id"] is None


# --- R#8: the literal string "None" must never be stored ---------------------


def test_film_create_maps_none_string_to_null(client):
    res = client.post(
        "/api/films",
        json={"title": unique("Roll"), "camera": "None", "lens": "None", "film_type": ""},
    )
    assert res.status_code == 200, res.text
    film = res.json()["film"]
    assert film["camera"] is None
    assert film["lens"] is None
    assert film["film_type"] is None


def test_film_update_maps_none_string_to_null(client):
    film = client.post("/api/films", json={"title": unique("Roll"), "camera": "Nikon F5"}).json()["film"]
    res = client.put(f"/api/films/{film['id']}", json={"camera": "None"})
    assert res.status_code == 200, res.text
    assert res.json()["film"]["camera"] is None


# --- R#4: the legacy HTML routes are gone ------------------------------------


def test_legacy_html_routes_are_gone(client):
    for path in ["/films", "/images/upload", "/search", "/cameras", "/filmstocks", "/lenses"]:
        assert client.get(path).status_code == 404, path


def test_openapi_has_no_legacy_paths(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) - {"/"} == {p for p in paths if p.startswith("/api/")}, sorted(paths)
