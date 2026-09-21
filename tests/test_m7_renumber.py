"""Renumbering a roll's frames (docs/ROADMAP.md, M7; app/services/renumber.py).

The four modes on a roll with a gap and a duplicate, the dry run that writes
nothing, the selection that leaves the rest alone, and the conflicts report.
"""

import uuid

import pytest

from app.errors import ApiError
from app.services import renumber

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


class Frame:
    def __init__(self, id, frame_number=None, original_filename=None):
        self.id = id
        self.frame_number = frame_number
        self.original_filename = original_filename


def numbers(plan):
    return [item["to"] for item in plan]


# --- the planner, without a database ------------------------------------------


def test_sequential_closes_gaps_and_duplicates_in_the_current_order():
    frames = [Frame(1, 2), Frame(2, 2), Frame(3, 5), Frame(4, None)]
    assert numbers(renumber.plan(frames, "sequential")) == [1, 2, 3, 4]
    assert numbers(renumber.plan(frames, "sequential", start=0)) == [0, 1, 2, 3]
    assert numbers(renumber.plan(frames, "sequential", start=10, step=2)) == [10, 12, 14, 16]


def test_reverse_walks_the_order_backwards():
    frames = [Frame(1, 1), Frame(2, 2), Frame(3, 3)]
    assert numbers(renumber.plan(frames, "reverse")) == [3, 2, 1]
    assert numbers(renumber.plan(frames, "reverse", start=5)) == [7, 6, 5]


def test_shift_moves_numbered_frames_and_leaves_unnumbered_ones():
    frames = [Frame(1, 0), Frame(2, 1), Frame(3, None)]
    assert numbers(renumber.plan(frames, "shift", offset=1)) == [1, 2, None]
    with pytest.raises(ApiError) as exc:
        renumber.plan(frames, "shift", offset=-1)
    assert exc.value.code == "negative_frame_number"


def test_from_filenames_rereads_the_scanner_names():
    from app.routers.api import frame_number_from_filename

    frames = [Frame(1, 9, "Roll12_Frame003.tif"), Frame(2, 9, "scan_017.jpg"), Frame(3, 4, "nothing here.tif")]
    plan = renumber.plan(frames, "from_filenames", from_filename=frame_number_from_filename)
    assert numbers(plan) == [3, 17, 4]  # the last one keeps its number


def test_the_planner_refuses_nonsense():
    with pytest.raises(ApiError):
        renumber.plan([], "sideways")
    with pytest.raises(ApiError):
        renumber.plan([], "sequential", start=-1)
    with pytest.raises(ApiError):
        renumber.plan([], "sequential", step=0)


def test_duplicates_reports_each_number_used_twice():
    assert renumber.duplicates([1, 2, 2, None, 3, 3, 3]) == [2, 3]
    assert renumber.duplicates([1, 2, 3]) == []


# --- the endpoint -----------------------------------------------------------------


def upload(client, roll_id, filename, frame_number=None):
    data = {"type": "scan", "film_roll_id": str(roll_id)}
    if frame_number is not None:
        data["frame_number"] = str(frame_number)
    res = client.post("/api/images/upload", files={"file": (filename, PNG_1x1, "image/png")}, data=data)
    assert res.status_code == 200, res.text
    return res.json()["image"]


def roll_numbers(client, roll_id):
    res = client.get(f"/api/images?film_id={roll_id}&type=scan")
    return [(i["id"], i["frame_number"]) for i in res.json()]


@pytest.fixture()
def roll(client):
    tag = uuid.uuid4().hex[:6]
    film = client.post("/api/films", json={"title": f"Renumber {tag}"}).json()["film"]
    # Frame numbers were set by hand: a gap after 2, and 7 twice. Filenames say
    # something else again, which "from_filenames" reads back.
    a = upload(client, film["id"], f"{tag}_Frame001.png", 1)
    b = upload(client, film["id"], f"{tag}_Frame002.png", 2)
    c = upload(client, film["id"], f"{tag}_Frame004.png", 7)
    d = upload(client, film["id"], f"{tag}_Frame005.png", 7)
    return {"id": film["id"], "frames": [a, b, c, d]}


def test_a_dry_run_shows_the_plan_and_writes_nothing(client, roll):
    before = roll_numbers(client, roll["id"])
    res = client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "sequential", "dry_run": True})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dry_run"] is True
    assert [(p["from"], p["to"]) for p in body["plan"]] == [(1, 1), (2, 2), (7, 3), (7, 4)]
    assert body["updated"] == 2
    assert body["conflicts"] == []
    assert "images" not in body
    assert roll_numbers(client, roll["id"]) == before


def test_sequential_renumbers_the_whole_roll(client, roll):
    res = client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "sequential", "start": 0})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated"] == 4
    assert [n for _, n in roll_numbers(client, roll["id"])] == [0, 1, 2, 3]
    assert len(body["images"]) == 4


def test_reverse_and_shift(client, roll):
    client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "reverse"})
    ids_then = [i for i, _ in roll_numbers(client, roll["id"])]
    # Reversed: the frame that was first (id a) is now 4, and the grid order flips.
    assert ids_then == [f["id"] for f in reversed(roll["frames"])]
    assert [n for _, n in roll_numbers(client, roll["id"])] == [1, 2, 3, 4]

    client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "shift", "offset": 10})
    assert [n for _, n in roll_numbers(client, roll["id"])] == [11, 12, 13, 14]

    res = client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "shift", "offset": -20})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "negative_frame_number"


def test_from_filenames_rereads_the_names(client, roll):
    res = client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "from_filenames"})
    assert res.status_code == 200, res.text
    assert [n for _, n in roll_numbers(client, roll["id"])] == [1, 2, 4, 5]


def test_a_selection_is_renumbered_on_its_own_and_conflicts_are_reported(client, roll):
    a, b, c, d = roll["frames"]
    # Only the two "7"s, numbered from 2: the new 2 collides with frame b.
    res = client.post(
        f"/api/films/{roll['id']}/frames/renumber",
        json={"mode": "sequential", "start": 2, "ids": [c["id"], d["id"]], "dry_run": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["conflicts"] == [2]
    assert [(p["id"], p["to"]) for p in res.json()["plan"]] == [(c["id"], 2), (d["id"], 3)]

    res = client.post(
        f"/api/films/{roll['id']}/frames/renumber",
        json={"mode": "sequential", "start": 3, "ids": [d["id"], c["id"]]},  # order given does not matter
    )
    assert res.status_code == 200, res.text
    assert res.json()["conflicts"] == []
    assert roll_numbers(client, roll["id"]) == [(a["id"], 1), (b["id"], 2), (c["id"], 3), (d["id"], 4)]


def test_frames_of_another_roll_are_refused(client, roll):
    other = client.post("/api/films", json={"title": "Other roll"}).json()["film"]
    stray = upload(client, other["id"], "stray.png", 1)
    res = client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "sequential", "ids": [stray["id"]]})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_in_roll"

    assert client.post("/api/films/999999/frames/renumber", json={"mode": "sequential"}).status_code == 404
    assert client.post(f"/api/films/{roll['id']}/frames/renumber", json={"mode": "magic"}).status_code == 400
    assert client.post(f"/api/films/{roll['id']}/frames/renumber", json={}).status_code == 400
