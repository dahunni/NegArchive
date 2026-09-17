"""Gear by foreign key, not by name (M2, R#14), and the film-stock fields (R#21)."""

import uuid


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_camera(client, **fields) -> dict:
    payload = {"name": unique("Camera")}
    payload.update(fields)
    res = client.post("/api/cameras", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["camera"]


def make_lens(client, **fields) -> dict:
    payload = {"name": unique("Lens")}
    payload.update(fields)
    res = client.post("/api/lenses", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["lens"]


def make_stock(client, **fields) -> dict:
    payload = {"name": unique("Stock"), "kind": "color", "iso": 400}
    payload.update(fields)
    res = client.post("/api/filmstocks", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["filmstock"]


def make_roll(client, **fields) -> dict:
    payload = {"title": unique("Roll")}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


# --- writing gear by id -------------------------------------------------------


def test_a_roll_can_be_created_with_gear_ids(client):
    camera, lens, stock = make_camera(client), make_lens(client), make_stock(client)
    roll = make_roll(
        client, camera_id=camera["id"], lens_id=lens["id"], film_stock_id=stock["id"]
    )
    assert (roll["camera_id"], roll["lens_id"], roll["film_stock_id"]) == (
        camera["id"],
        lens["id"],
        stock["id"],
    )
    # the names come along for clients that only know about them
    assert (roll["camera"], roll["lens"], roll["film_type"]) == (
        camera["name"],
        lens["name"],
        stock["name"],
    )


def test_names_are_still_accepted_and_resolved_to_ids(client):
    camera = make_camera(client)
    roll = make_roll(client, camera=camera["name"])
    assert roll["camera_id"] == camera["id"]
    assert roll["camera"] == camera["name"]


def test_a_name_that_matches_nothing_stays_free_text(client):
    roll = make_roll(client, camera="A camera nobody catalogued")
    assert roll["camera_id"] is None
    assert roll["camera"] == "A camera nobody catalogued"


def test_gear_can_be_cleared_by_id_or_by_name(client):
    camera = make_camera(client)
    roll = make_roll(client, camera_id=camera["id"])

    cleared = client.put(f"/api/films/{roll['id']}", json={"camera_id": None}).json()["film"]
    assert cleared["camera_id"] is None and cleared["camera"] is None

    again = client.put(f"/api/films/{roll['id']}", json={"camera": camera["name"]}).json()["film"]
    assert again["camera_id"] == camera["id"]

    by_name = client.put(f"/api/films/{roll['id']}", json={"camera": None}).json()["film"]
    assert by_name["camera_id"] is None and by_name["camera"] is None


def test_an_unknown_gear_id_is_a_404_on_the_right_field(client):
    res = client.post("/api/films", json={"title": unique("Roll"), "camera_id": 10**8})
    assert res.status_code == 404
    body = res.json()["error"]
    assert body["code"] == "unknown_camera"
    assert body["field"] == "camera_id"


def test_renaming_a_camera_updates_every_roll_that_points_at_it(client):
    camera = make_camera(client, name=unique("Nikon"))
    roll = make_roll(client, camera_id=camera["id"])
    new_name = unique("Nikon F5 renamed")
    assert client.put(f"/api/cameras/{camera['id']}", json={"name": new_name}).status_code == 200

    updated = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert updated["camera_id"] == camera["id"]
    assert updated["camera"] == new_name, "the name follows the catalog entry (R#14)"


# --- deleting gear that is in use ---------------------------------------------


def test_deleting_a_camera_in_use_is_a_409_with_a_count(client):
    camera = make_camera(client)
    make_roll(client, camera_id=camera["id"])
    make_roll(client, camera_id=camera["id"])

    res = client.delete(f"/api/cameras/{camera['id']}")
    assert res.status_code == 409
    body = res.json()["error"]
    assert body["code"] == "gear_in_use"
    assert "2 rolls" in body["message"]
    assert client.get(f"/api/cameras/{camera['id']}").status_code == 200, "nothing was deleted"


def test_force_deletes_the_camera_and_unlinks_the_rolls(client):
    camera = make_camera(client)
    roll = make_roll(client, camera_id=camera["id"])

    res = client.delete(f"/api/cameras/{camera['id']}?force=true")
    assert res.status_code == 200, res.text
    assert res.json()["rolls_affected"] == 1
    assert client.get(f"/api/cameras/{camera['id']}").status_code == 404

    orphaned = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert orphaned["camera_id"] is None, "ON DELETE SET NULL"
    assert orphaned["camera"] == camera["name"], "the name is kept so the roll still reads right"


def test_gear_that_nothing_uses_deletes_without_force(client):
    for kind, factory in (("lenses", make_lens), ("filmstocks", make_stock)):
        item = factory(client)
        res = client.delete(f"/api/{kind}/{item['id']}")
        assert res.status_code == 200, res.text
        assert client.get(f"/api/{kind}/{item['id']}").status_code == 404


def test_a_legacy_name_reference_also_counts_as_in_use(client):
    """A roll written before M2 refers to gear by name only; it still protects it."""
    camera = make_camera(client)
    make_roll(client, camera=camera["name"].upper())  # matched case-insensitively
    res = client.delete(f"/api/cameras/{camera['id']}")
    assert res.status_code == 409
    assert "1 roll" in res.json()["error"]["message"]


def test_lens_and_film_stock_are_protected_the_same_way(client):
    lens, stock = make_lens(client), make_stock(client)
    make_roll(client, lens_id=lens["id"], film_stock_id=stock["id"])
    assert client.delete(f"/api/lenses/{lens['id']}").status_code == 409
    assert client.delete(f"/api/filmstocks/{stock['id']}").status_code == 409


# --- film stock and roll detail (R#21) ----------------------------------------


def test_film_stocks_carry_a_manufacturer_and_a_format(client):
    stock = make_stock(client, manufacturer="Kodak", format="120", kind="slide", iso=100)
    assert (stock["manufacturer"], stock["format"], stock["kind"]) == ("Kodak", "120", "slide")

    updated = client.put(
        f"/api/filmstocks/{stock['id']}", json={"manufacturer": "Eastman Kodak", "format": "4x5"}
    ).json()["filmstock"]
    assert (updated["manufacturer"], updated["format"]) == ("Eastman Kodak", "4x5")
    assert client.get(f"/api/filmstocks/{stock['id']}").json()["format"] == "4x5"


def test_every_film_kind_in_the_enum_is_accepted(client):
    for kind in ("black_and_white", "color", "slide", "motion_picture"):
        assert make_stock(client, kind=kind)["kind"] == kind


def test_a_roll_has_a_format(client):
    roll = make_roll(client, format="120")
    assert roll["format"] == "120"
    assert client.get(f"/api/films/{roll['id']}").json()["film"]["format"] == "120"


def test_an_unknown_format_is_rejected(client):
    res = client.post("/api/films", json={"title": unique("Roll"), "format": "110"})
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "format"

    res = client.post(
        "/api/filmstocks", json={"name": unique("Stock"), "kind": "color", "format": "APS"}
    )
    assert res.status_code == 422
    assert res.json()["error"]["field"] == "format"
