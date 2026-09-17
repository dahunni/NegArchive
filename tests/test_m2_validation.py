"""Validation, status codes and the one error body (M2, R#11, R#16, R#17).

M1 gave the cases its dialogs could hit a real 4xx and a structured body. M2 does it
everywhere: nothing answers "not found" with an HTTP 200 any more, every 4xx body has
``code``, ``message`` and ``field``, and no bad input reaches a bare 500.
"""

import uuid

import pytest


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_roll(client) -> dict:
    res = client.post("/api/films", json={"title": unique("Roll")})
    assert res.status_code == 200, res.text
    return res.json()["film"]


MISSING = 10**8


# --- 404 instead of a 200 with an error string (R#17) -------------------------


@pytest.mark.parametrize(
    "path",
    [
        f"/api/films/{MISSING}",
        f"/api/images/{MISSING}",
        f"/api/images/{MISSING}/preview",
        f"/api/images/{MISSING}/download",
        f"/api/cameras/{MISSING}",
        f"/api/lenses/{MISSING}",
        f"/api/filmstocks/{MISSING}",
    ],
)
def test_reading_something_that_does_not_exist_is_a_404(client, path):
    res = client.get(path)
    assert res.status_code == 404, path
    assert res.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "method, path, payload",
    [
        ("put", f"/api/films/{MISSING}", {"title": "x"}),
        ("put", f"/api/images/{MISSING}", {"notes": "x"}),
        ("put", f"/api/cameras/{MISSING}", {"name": "x"}),
        ("put", f"/api/lenses/{MISSING}", {"name": "x"}),
        ("put", f"/api/filmstocks/{MISSING}", {"name": "x"}),
        ("delete", f"/api/films/{MISSING}", None),
        ("delete", f"/api/images/{MISSING}", None),
        ("delete", f"/api/cameras/{MISSING}", None),
        ("delete", f"/api/lenses/{MISSING}", None),
        ("delete", f"/api/filmstocks/{MISSING}", None),
        ("post", f"/api/films/{MISSING}/contact_sheet", None),
    ],
)
def test_writing_to_something_that_does_not_exist_is_a_404(client, method, path, payload):
    call = getattr(client, method)
    res = call(path, json=payload) if payload is not None else call(path)
    assert res.status_code == 404, f"{method} {path}: {res.text}"
    assert res.json()["error"]["code"] == "not_found"


def test_uploading_into_a_roll_that_does_not_exist_is_a_404(client):
    res = client.post(
        "/api/images/upload",
        files={"file": ("frame.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")},
        data={"type": "scan", "film_roll_id": str(MISSING)},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "unknown_roll"
    assert res.json()["error"]["field"] == "film_roll_id"


# --- the shape of an error ----------------------------------------------------


@pytest.mark.parametrize(
    "payload, code, field",
    [
        ({"title": "  "}, "invalid_title", "title"),
        ({"title": "ok", "start_date": "07/2024"}, "invalid_date", "start_date"),
        (
            {"title": "ok", "start_date": "2024-07-10", "end_date": "2024-07-01"},
            "invalid_date_range",
            "end_date",
        ),
    ],
)
def test_a_bad_roll_body_names_the_field_that_is_wrong(client, payload, code, field):
    res = client.post("/api/films", json=payload)
    assert res.status_code == 400
    body = res.json()["error"]
    assert (body["code"], body["field"]) == (code, field)
    assert body["message"] and body["message"][0].isupper()


def test_every_error_body_has_the_same_three_keys(client):
    responses = [
        client.post("/api/films", json={"title": ""}),
        client.get(f"/api/films/{MISSING}"),
        client.post("/api/cameras", json={"name": ""}),
        client.post("/api/images/bulk_update", json={"ids": []}),
        client.post(
            "/api/images/upload",
            files={"file": ("x.exe", b"MZ", "application/octet-stream")},
            data={"type": "scan"},
        ),
    ]
    for res in responses:
        assert 400 <= res.status_code < 500, res.text
        assert set(res.json()["error"]) == {"code", "message", "field"}


def test_a_duplicate_name_is_a_409_on_the_name_field(client):
    name = unique("Camera")
    assert client.post("/api/cameras", json={"name": name}).status_code == 200
    res = client.post("/api/cameras", json={"name": name})
    assert res.status_code == 409
    assert res.json()["error"]["field"] == "name"


# --- shape errors Pydantic catches (422) --------------------------------------


@pytest.mark.parametrize(
    "path, payload, field",
    [
        ("/api/films", {"title": ["a", "list"]}, "title"),
        ("/api/films", {"title": "ok", "camera_id": "not a number"}, "camera_id"),
        ("/api/films", {"title": "ok", "format": "110"}, "format"),
        ("/api/images/bulk_update", {"ids": "1,2"}, "ids"),
    ],
)
def test_a_body_of_the_wrong_shape_is_a_422_that_names_the_field(client, path, payload, field):
    res = client.post(path, json=payload)
    assert res.status_code == 422, res.text
    body = res.json()["error"]
    assert body["code"] == "invalid_request"
    assert body["field"] == field
    assert body["message"].lower().startswith(field.replace("_", " "))


def test_a_body_that_is_not_an_object_is_a_422(client):
    res = client.post("/api/films", json=["nope"])
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_request"


def test_nothing_returns_a_200_with_an_error_key(client):
    """The old `{"error": "not_found"}` at HTTP 200 is gone for good (R#17)."""
    for path in (f"/api/films/{MISSING}", f"/api/images/{MISSING}", f"/api/cameras/{MISSING}"):
        res = client.get(path)
        assert res.status_code != 200
        assert not isinstance(res.json().get("error"), str)


# --- seed data (R#11) ---------------------------------------------------------


def test_startup_seeding_never_resurrects_a_deleted_row(client):
    """A second startup against a populated catalog adds nothing."""
    from app.db import SessionLocal
    from app.models import Camera
    from app.seed import seed_catalog

    db = SessionLocal()
    try:
        assert db.query(Camera).count() > 0, "the first startup seeded the catalog"
        victim = db.query(Camera).filter(Camera.name == "Nikon F5").first()
        assert victim is not None
        db.delete(victim)
        db.commit()

        added = seed_catalog(db)  # what the next startup does
        assert added == {"cameras": 0, "film_stocks": 0}
        assert db.query(Camera).filter(Camera.name == "Nikon F5").first() is None
    finally:
        db.close()


def test_post_seed_puts_the_starter_catalog_back(client):
    res = client.post("/api/seed")
    assert res.status_code == 200, res.text
    added = res.json()["added"]
    assert added["cameras"] >= 1, "the camera deleted above comes back on request"

    names = {camera["name"] for camera in client.get("/api/cameras").json()}
    assert "Nikon F5" in names

    # asking twice adds nothing
    assert client.post("/api/seed").json()["added"] == {"cameras": 0, "film_stocks": 0}


def test_the_seeded_film_stocks_carry_the_new_fields(client):
    stocks = {s["name"]: s for s in client.get("/api/filmstocks").json()}
    gold = stocks.get("Kodak Gold 200")
    assert gold is not None
    assert (gold["manufacturer"], gold["format"], gold["kind"]) == ("Kodak", "35mm", "color")
