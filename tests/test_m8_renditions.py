"""A NegPy export is a rendition of a frame, not a second frame (M8).

Found on a live archive on 2026-09-21, one roll after another: 33 frames were
listed as 66, each one twice, because the raw negative the scanner made and the
positive NegPy exported from it were two rows and everything counted rows.

What is asserted here is the invariant the whole feature exists for — **a frame
is counted once** — plus the two things that follow from it: the frame's picture
is the export, and a re-export replaces the one before it instead of adding a
third.
"""

import io
import os

from PIL import Image as PILImage

from app import paths

XMP_TEMPLATE = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:negpy="https://negpy.app/ns/1.0/" '
    'negpy:CaptureRoll="{roll}" negpy:CaptureFrame="{frame}"/>'
    "</rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
)


def unique(prefix: str) -> str:
    return f"{prefix}-{os.urandom(4).hex()}"


def jpeg_bytes(color=(120, 60, 30), xmp: str | None = None) -> bytes:
    buf = io.BytesIO()
    image = PILImage.new("RGB", (16, 16), color)
    if xmp is None:
        image.save(buf, format="JPEG")
        return buf.getvalue()
    # Pillow will not write an XMP packet for us on JPEG, so it goes in as an
    # APP1 segment by hand — which is exactly how NegPy's exports carry it.
    image.save(buf, format="JPEG")
    raw = buf.getvalue()
    packet = b"http://ns.adobe.com/xap/1.0/\x00" + xmp.encode("utf-8")
    segment = b"\xff\xe1" + (len(packet) + 2).to_bytes(2, "big") + packet
    return raw[:2] + segment + raw[2:]


def make_roll(client, **fields) -> dict:
    res = client.post("/api/films", json={"title": unique("Roll"), **fields})
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id, filename, *, frame=None, positive=None, payload=None) -> dict:
    form = {"type": "scan", "film_roll_id": str(roll_id)}
    if frame is not None:
        form["frame_number"] = str(frame)
    if positive is not None:
        form["positive"] = "true" if positive else "false"
    res = client.post(
        "/api/images/upload",
        files={"file": (filename, payload or jpeg_bytes(), "image/jpeg")},
        data=form,
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


def frames_of(client, roll_id) -> list[dict]:
    return client.get(f"/api/films/{roll_id}").json()["images"]


def negpy_pair(client, frames=3):
    """A roll as the NegPy round trip leaves it: a negative and its export each."""
    roll = make_roll(client)
    serial = roll["archive_serial"]
    negatives, exports = [], []
    for n in range(1, frames + 1):
        negatives.append(upload(client, roll["id"], f"{serial}_Frame{n:03d}.jpg", frame=n))
        exports.append(
            upload(
                client,
                roll["id"],
                f"{serial.replace('-', '_')}_{n:03d}.jpg",
                positive=True,
                payload=jpeg_bytes((230, 230, 225), XMP_TEMPLATE.format(roll=serial, frame=n)),
            )
        )
    return roll, negatives, exports


# --- the invariant -------------------------------------------------------------


def test_a_frame_that_went_through_negpy_is_counted_once(client):
    roll, negatives, _exports = negpy_pair(client, frames=3)

    listed = next(r for r in client.get("/api/films").json() if r["id"] == roll["id"])
    assert listed["image_count"] == 3, "three frames, six files"

    frames = frames_of(client, roll["id"])
    assert [f["id"] for f in frames] == [n["id"] for n in negatives]
    assert [f["frame_number"] for f in frames] == [1, 2, 3]

    # …and the same answer from every other list in the archive.
    assert len(client.get("/api/images", params={"film_id": roll["id"], "type": "scan"}).json()) == 3
    layout = client.get(f"/api/films/{roll['id']}/layout").json()
    assert len([c for row in layout["rows"] for c in row if c]) == 3


def test_the_export_is_hung_off_the_negative_it_names(client):
    """NegPy writes `negpy:CaptureRoll` and `CaptureFrame` into the export itself."""
    roll, negatives, exports = negpy_pair(client, frames=2)
    frames = {f["id"]: f for f in frames_of(client, roll["id"])}
    for negative, export in zip(negatives, exports, strict=True):
        assert frames[negative["id"]]["rendition"]["id"] == export["id"]
        assert frames[negative["id"]]["rendition"]["original_filename"] == export["original_filename"]


def test_the_export_keeps_its_own_file_and_identity(client):
    """It is not swallowed: an archive meant to outlive its software keeps the file."""
    roll, negatives, exports = negpy_pair(client, frames=1)
    rendition = frames_of(client, roll["id"])[0]["rendition"]
    assert rendition["content_hash"] and rendition["content_hash"] != negatives[0]["content_hash"]
    assert client.get(rendition["url"]).status_code in (200, 307)
    assert client.get(f"/api/images/{exports[0]['id']}").json()["id"] == exports[0]["id"]


# --- what a frame shows ---------------------------------------------------------


def test_a_frames_preview_is_the_export_and_raw_is_still_the_negative(client):
    roll, negatives, _exports = negpy_pair(client, frames=1)
    negative_id = negatives[0]["id"]

    shown = client.get(f"/api/images/{negative_id}/preview", params={"width": 16})
    as_stored = client.get(f"/api/images/{negative_id}/preview", params={"width": 16, "render": "raw"})
    assert shown.status_code == 200 and as_stored.status_code == 200
    assert shown.content != as_stored.content, "auto shows the export, raw shows the negative"

    frame = frames_of(client, roll["id"])[0]
    assert frame["preview_version"] == frame["rendition"]["preview_version"]
    assert frame["negative_version"] != frame["preview_version"]


def test_a_roll_with_no_export_is_untouched(client):
    roll = make_roll(client)
    serial = roll["archive_serial"]
    for n in (1, 2):
        upload(client, roll["id"], f"{serial}_Frame{n:03d}.jpg", frame=n)
    frames = frames_of(client, roll["id"])
    assert len(frames) == 2
    assert all(f["rendition"] is None for f in frames)
    assert all(f["preview_version"] == f["negative_version"] for f in frames)


# --- a fresher export replaces the one before it ---------------------------------


def test_a_re_export_replaces_the_previous_one(client):
    roll, negatives, exports = negpy_pair(client, frames=1)
    serial = roll["archive_serial"]
    first = frames_of(client, roll["id"])[0]["rendition"]
    on_disk = str(paths.resolve(client.get(f"/api/images/{exports[0]['id']}").json()["path"]))
    assert os.path.exists(on_disk)

    again = upload(
        client,
        roll["id"],
        f"{serial.replace('-', '_')}_001.jpg",
        positive=True,
        payload=jpeg_bytes((10, 90, 170), XMP_TEMPLATE.format(roll=serial, frame=1)),
    )

    frames = frames_of(client, roll["id"])
    assert len(frames) == 1, "still one frame, not a third"
    rendition = frames[0]["rendition"]
    assert rendition is not None
    assert rendition["id"] == again["id"], "the newest export is the rendition"
    assert rendition["content_hash"] != first["content_hash"]
    assert rendition["preview_version"] != first["preview_version"]
    assert not os.path.exists(on_disk), "the superseded file is gone"
    # …and the row that used to point at it with it.
    assert client.get(f"/api/images/{exports[0]['id']}").status_code == 404
    assert client.get(f"/api/images/{again['id']}").status_code == 200


def test_a_re_export_keeps_notes_typed_on_the_rendition(client):
    roll, _negatives, exports = negpy_pair(client, frames=1)
    serial = roll["archive_serial"]
    client.put(f"/api/images/{exports[0]['id']}", json={"notes": "the good one"})

    upload(
        client,
        roll["id"],
        f"{serial.replace('-', '_')}_001.jpg",
        positive=True,
        payload=jpeg_bytes((5, 5, 5), XMP_TEMPLATE.format(roll=serial, frame=1)),
    )
    rendition_id = frames_of(client, roll["id"])[0]["rendition"]["id"]
    assert client.get(f"/api/images/{rendition_id}").json()["notes"] == "the good one"


# --- what must *not* become a rendition ------------------------------------------


def test_a_positive_naming_no_frame_stays_a_frame_of_its_own(client):
    """A scan of a print, or an export whose negative was never imported."""
    roll = make_roll(client)
    lone = upload(client, roll["id"], "a print on the wall.jpg", frame=4, positive=True)
    frames = frames_of(client, roll["id"])
    assert [f["id"] for f in frames] == [lone["id"]]
    assert frames[0]["rendition"] is None


def test_an_export_does_not_attach_across_rolls(client):
    """`CaptureRoll` names another roll, but the file is filed on this one."""
    other = make_roll(client)
    upload(client, other["id"], f"{other['archive_serial']}_Frame001.jpg", frame=1)
    here = make_roll(client)
    export = upload(
        client,
        here["id"],
        "stray_001.jpg",
        frame=1,
        positive=True,
        payload=jpeg_bytes((9, 9, 9), XMP_TEMPLATE.format(roll=other["archive_serial"], frame=1)),
    )
    assert [f["id"] for f in frames_of(client, here["id"])] == [export["id"]]
    assert frames_of(client, other["id"])[0]["rendition"] is None


def test_deleting_a_frame_takes_its_export_with_it(client):
    roll, negatives, exports = negpy_pair(client, frames=1)
    client.delete(f"/api/images/{negatives[0]['id']}")
    assert client.get(f"/api/images/{exports[0]['id']}").status_code == 404
    assert frames_of(client, roll["id"]) == []


def test_renumbering_a_roll_does_not_see_the_exports(client):
    roll, negatives, _exports = negpy_pair(client, frames=3)
    res = client.post(
        f"/api/films/{roll['id']}/frames/renumber",
        json={"mode": "sequential", "start": 10, "dry_run": True},
    )
    plan = res.json()["plan"]
    assert [p["id"] for p in plan] == [n["id"] for n in negatives]
    assert [p["to"] for p in plan] == [10, 11, 12]
