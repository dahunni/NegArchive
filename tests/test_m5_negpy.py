"""M5 — the NegPy integration (docs/NEGPY_INTEGRATION.md).

NegArchive and NegPy exchange *files*: a scan carrying EXIF and ``negpy:`` XMP, a
``.negpy`` sidecar beside it, three gear JSON files, one metadata preset per roll.
No NegPy code is imported, so every one of those formats is an agreement written
down in a docstring — and these tests are what keeps this side of the agreement
honest.

The properties that matter, in the order they are tested below:

* a file's own metadata **fills blanks and never overwrites** anything a person
  typed, so ingest can run automatically on every upload;
* the recommended filename preset is read **strictly**, because the loose scanner
  rule would turn "Tri-X 400" into frame 400;
* a gear sync **never touches an entry that is not ours** (id prefix ``na-``);
* a handoff **never moves or renames an original**;
* the content hash matches the documented algorithm byte for byte, because that
  is what ties a NegArchive frame to a NegPy edit.
"""

import hashlib
import io
import json
import os
import zipfile

import pytest
from PIL import Image as PILImage

from app.services.hashing import content_hash
from app.services.negpy import gear, naming, sidecar
from app.services.negpy import metadata as negpy_metadata
from app.services.negpy.xmp import NEGPY_NS, parse_namespace

# --- fixtures and builders ----------------------------------------------------


def unique(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def xmp_packet(**properties) -> bytes:
    """An XMP packet carrying ``negpy:`` properties, the way NegPy writes them.

    Half as attributes and half as elements, because both are valid RDF and both
    turn up in the wild.
    """
    items = list(properties.items())
    attributes = " ".join(f'negpy:{key}="{value}"' for key, value in items[::2])
    elements = "".join(f"<negpy:{key}>{value}</negpy:{key}>" for key, value in items[1::2])
    return (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        f'<rdf:Description rdf:about="" xmlns:negpy="{NEGPY_NS}" {attributes}>{elements}</rdf:Description>'
        "</rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    ).encode("utf-8")


def jpeg_bytes(*, xmp: bytes | None = None, exif: dict | None = None, size=(16, 12)) -> bytes:
    """A real JPEG, optionally carrying an XMP packet and a few EXIF tags."""
    image = PILImage.new("RGB", size, (200, 180, 160))
    buffer = io.BytesIO()
    kwargs = {}
    if xmp is not None:
        kwargs["xmp"] = xmp
    if exif is not None:
        payload = PILImage.Exif()
        for tag, value in exif.items():
            payload[tag] = value
        kwargs["exif"] = payload
    image.save(buffer, format="JPEG", **kwargs)
    return buffer.getvalue()


def make_roll(client, **fields) -> dict:
    payload = {"title": unique("Roll")}
    payload.update(fields)
    res = client.post("/api/films", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["film"]


def upload(client, roll_id, filename, payload, **form) -> dict:
    data = {"type": "scan", "film_roll_id": str(roll_id)}
    data.update({k: str(v) for k, v in form.items()})
    res = client.post(
        "/api/images/upload",
        files={"file": (filename, payload, "image/jpeg")},
        data=data,
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


@pytest.fixture(autouse=True)
def negpy_defaults(client):
    """Every test starts from the shipped settings, and leaves them that way.

    The suite shares one database, and a test that turns gear creation on would
    otherwise change what the next one means.
    """
    defaults = {
        "negpy_ingest": True,
        "negpy_create_gear": False,
        "negpy_user_dir": "",
        "negpy_handoff_dir": "",
        "negpy_handoff_mode": "link",
    }
    client.put("/api/system/settings", json=defaults)
    yield
    client.put("/api/system/settings", json=defaults)


# --- the filename preset ------------------------------------------------------


@pytest.mark.parametrize(
    "filename,roll,frame,film",
    [
        ("NEG-2026-0007_012_HP5 Plus.tif", "NEG-2026-0007", 12, "HP5 Plus"),
        # The point of the strict parse: the loose rule would read frame 400.
        ("NEG-2026-0007_012_Tri-X 400.tif", "NEG-2026-0007", 12, "Tri-X 400"),
        ("NEG-2026-0007_012.tif", "NEG-2026-0007", 12, None),
        ("Roll12_007.tif", "Roll12", 7, None),
    ],
)
def test_the_export_preset_is_read_back(filename, roll, frame, film):
    parsed = naming.parse(filename)
    assert (parsed.roll, parsed.frame_number, parsed.film) == (roll, frame, film)


@pytest.mark.parametrize("filename", ["007.jpg", "Kyoto rain.tif", "", "scan.tif"])
def test_a_name_that_is_not_the_preset_is_left_alone(filename):
    assert not naming.parse(filename)


@pytest.mark.parametrize(
    "filename,expected",
    [
        # The regression that found this: the preset ends in the film name, and
        # most film names end in their ISO. The loose rule read 200 as the frame.
        ("NEG-2026-0007_013_Kodak Gold 200.jpg", 13),
        ("NEG-2026-0007_013_Tri-X 400.tif", 13),
        # …and the shapes M2 already handled keep working.
        ("Roll12_007.tif", 7),
        ("NEG-2024-011_007.jpg", 7),
        ("scan_Frame007.tif", 7),
        ("007.jpg", 7),
        ("img_0007.png", 7),
        ("Roll12.tif", None),
    ],
)
def test_the_upload_frame_number_prefers_the_preset(filename, expected):
    """One rule for every path into the archive (uploads, ZIPs, link mode)."""
    from app.routers.api import frame_number_from_filename

    assert frame_number_from_filename(filename) == expected


def test_a_roll_of_preset_named_files_is_numbered_by_frame_not_by_iso(client):
    roll = make_roll(client)
    serial = roll["archive_serial"]
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", (f"{serial}_{n:03d}_Kodak Gold 200.jpg", jpeg_bytes(), "image/jpeg"))
            for n in (11, 12, 13)
        ],
    )
    assert res.status_code == 200, res.text
    assert sorted(image["frame_number"] for image in res.json()["images"]) == [11, 12, 13]


def test_the_published_pattern_is_the_one_that_parses():
    assert naming.FILENAME_PATTERN == "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"


# --- XMP ----------------------------------------------------------------------


def test_negpy_properties_are_read_as_attributes_and_as_elements():
    found = parse_namespace(xmp_packet(CaptureRoll="NEG-2026-0003", CaptureFrame="7"))
    assert found == {"CaptureRoll": "NEG-2026-0003", "CaptureFrame": "7"}


def test_a_packet_declaring_entities_is_refused_unparsed():
    """Billion laughs: an archive ingesting files off a share must not expand DTDs."""
    hostile = b'<!DOCTYPE x [<!ENTITY a "aaaa">]><x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
    assert parse_namespace(hostile) == {}


def test_an_implausibly_large_packet_is_refused():
    assert parse_namespace(b"<x/>" + b" " * (5 * 1024 * 1024)) == {}


def test_a_file_with_no_xmp_is_simply_empty(tmp_path):
    path = tmp_path / "plain.jpg"
    path.write_bytes(jpeg_bytes())
    assert parse_namespace(None) == {}
    assert negpy_metadata.read(path).roll is None


# --- reading a file -----------------------------------------------------------


def test_the_negpy_namespace_fills_every_field(tmp_path):
    path = tmp_path / "scan.jpg"
    path.write_bytes(
        jpeg_bytes(
            xmp=xmp_packet(
                CaptureRoll="NEG-2026-0009",
                CaptureFrame="14",
                CaptureFilmStock="HP5 Plus",
                CaptureFilmManufacturer="Ilford",
                CaptureCameraMake="Nikon",
                CaptureCameraModel="Nikon F5",
                CaptureLensModel="AF Nikkor 50mm f/1.8D",
                CaptureDate="2026-03-14",
                Developer="Rodinal",
                DevelopmentDilution="1+50",
                Notes="Rain on the harbour wall",
            )
        )
    )
    meta = negpy_metadata.read(path)
    assert meta.roll == "NEG-2026-0009"
    assert meta.frame_number == 14
    assert meta.film_stock == "HP5 Plus"
    assert meta.film_manufacturer == "Ilford"
    assert meta.camera == "Nikon F5"  # the make is not repeated
    assert meta.lens == "AF Nikkor 50mm f/1.8D"
    assert meta.capture_date.isoformat() == "2026-03-14"
    assert meta.developer == "Rodinal"
    assert "1+50" in meta.development
    assert meta.notes == "Rain on the harbour wall"
    assert "xmp" in meta.sources


def test_exif_is_read_when_there_is_no_xmp(tmp_path):
    path = tmp_path / "exif.jpg"
    path.write_bytes(
        jpeg_bytes(
            exif={
                271: "NIKON CORPORATION",
                272: "NIKON F5",
                0x8769: {36867: "2026:05:02 09:30:00", 42036: "AF-S 35mm f/1.8G", 34855: 400},
            }
        )
    )
    meta = negpy_metadata.read(path)
    assert meta.camera == "NIKON F5"
    assert meta.lens == "AF-S 35mm f/1.8G"
    assert meta.film_iso == 400
    assert meta.capture_date.isoformat() == "2026-05-02"
    assert "exif" in meta.sources


@pytest.mark.parametrize(
    "make,model,expected",
    [
        ("NIKON CORPORATION", "NIKON F5", "NIKON F5"),
        ("Hasselblad", "500 C/M", "Hasselblad 500 C/M"),
        (None, "F5", "F5"),
        ("Leica", None, "Leica"),
    ],
)
def test_the_make_is_not_repeated_in_the_camera_name(make, model, expected):
    assert negpy_metadata.camera_name(make, model) == expected


def test_the_filename_is_the_last_resort(tmp_path):
    path = tmp_path / "x.jpg"
    path.write_bytes(jpeg_bytes())
    meta = negpy_metadata.read(path, "NEG-2026-0011_003_Portra 400.jpg")
    assert (meta.roll, meta.frame_number, meta.film_stock) == ("NEG-2026-0011", 3, "Portra 400")
    assert "filename" in meta.sources


# --- ingest on upload ---------------------------------------------------------


def test_an_upload_is_filled_in_from_its_own_metadata(client):
    roll = make_roll(client)
    image = upload(
        client,
        roll["id"],
        "anything.jpg",
        jpeg_bytes(xmp=xmp_packet(CaptureFrame="21", CaptureDate="2026-04-01", Notes="Kite")),
    )
    assert image["frame_number"] == 21
    assert image["capture_date"] == "2026-04-01"
    assert image["notes"] == "Kite"
    assert image["capture_metadata"]["sources"] == ["xmp"]


def test_ingest_never_overwrites_what_the_client_sent(client):
    roll = make_roll(client)
    image = upload(
        client,
        roll["id"],
        "anything.jpg",
        jpeg_bytes(xmp=xmp_packet(CaptureFrame="21", CaptureDate="2026-04-01")),
        frame_number=5,
        capture_date="2020-01-01",
    )
    assert image["frame_number"] == 5
    assert image["capture_date"] == "2020-01-01"
    # …but what the file said is still on the record.
    assert image["capture_metadata"]["frame_number"] == 21


def test_an_unassigned_upload_is_filed_by_its_capture_roll(client):
    roll = make_roll(client)
    res = client.post(
        "/api/images/upload",
        files={"file": ("loose.jpg", jpeg_bytes(xmp=xmp_packet(CaptureRoll=roll["archive_serial"], CaptureFrame="3")), "image/jpeg")},
        data={"type": "scan"},
    )
    assert res.status_code == 200, res.text
    image = res.json()["image"]
    assert image["film_roll_id"] == roll["id"]
    assert image["frame_number"] == 3


def test_a_capture_roll_that_names_no_roll_leaves_the_frame_loose(client):
    res = client.post(
        "/api/images/upload",
        files={"file": ("loose.jpg", jpeg_bytes(xmp=xmp_packet(CaptureRoll="NEG-1899-9999")), "image/jpeg")},
        data={"type": "scan"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["image"]["film_roll_id"] is None


def test_a_roll_learns_its_gear_from_the_first_scan(client):
    camera = client.post("/api/cameras", json={"name": unique("Pentax MX")}).json()["camera"]
    roll = make_roll(client)
    upload(client, roll["id"], "a.jpg", jpeg_bytes(xmp=xmp_packet(CaptureCameraModel=camera["name"], CaptureFrame="1")))
    updated = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert updated["camera_id"] == camera["id"]


def test_gear_the_catalog_does_not_have_is_not_invented(client):
    roll = make_roll(client)
    made_up = unique("Nonexistent Camera")
    upload(client, roll["id"], "a.jpg", jpeg_bytes(xmp=xmp_packet(CaptureCameraModel=made_up, CaptureFrame="1")))
    updated = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert updated["camera_id"] is None
    names = [c["name"] for c in client.get("/api/cameras").json()]
    assert made_up not in names


def test_gear_can_be_created_when_the_setting_says_so(client):
    client.put("/api/system/settings", json={"negpy_create_gear": True})
    roll = make_roll(client)
    wanted = unique("Voigtlander Bessa")
    upload(client, roll["id"], "a.jpg", jpeg_bytes(xmp=xmp_packet(CaptureCameraModel=wanted, CaptureFrame="1")))
    updated = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert updated["camera"] == wanted


def test_ingest_can_be_switched_off(client):
    client.put("/api/system/settings", json={"negpy_ingest": False})
    roll = make_roll(client)
    image = upload(client, roll["id"], "plain.jpg", jpeg_bytes(xmp=xmp_packet(CaptureFrame="30")))
    assert image["frame_number"] is None
    assert image["capture_metadata"] is None


def test_the_roll_dates_grow_to_cover_its_frames(client):
    roll = make_roll(client)
    upload(client, roll["id"], "a.jpg", jpeg_bytes(xmp=xmp_packet(CaptureFrame="1", CaptureDate="2026-06-02")))
    upload(client, roll["id"], "b.jpg", jpeg_bytes(xmp=xmp_packet(CaptureFrame="2", CaptureDate="2026-05-30")))
    updated = client.get(f"/api/films/{roll['id']}").json()["film"]
    assert updated["start_date"] == "2026-05-30"
    assert updated["end_date"] == "2026-06-02"


# --- sidecars -----------------------------------------------------------------


RECIPE = {
    "version": 3,
    "file_hash": "abc123",
    "settings": {"invert": True, "exposure": 0.4, "crop": [0, 0, 100, 100], "contrast": 0},
}


def test_a_sidecar_uploaded_beside_its_scan_is_kept(client):
    roll = make_roll(client)
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("harbour_001.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("harbour_001.jpg.negpy", json.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    assert res.status_code == 200, res.text
    images = res.json()["images"]
    assert len(images) == 1  # the sidecar is not a frame
    frame = images[0]
    assert frame["sidecar_path"].endswith(".negpy")
    assert os.path.isfile(frame["sidecar_path"])
    assert frame["negpy_edited_at"] is not None
    assert "inverted" in frame["negpy_summary"]


def test_the_summary_counts_only_settings_that_do_something():
    parsed = sidecar.Sidecar(path="x", data=RECIPE)
    # contrast is 0, which is NegPy's "off"; the other three count.
    assert parsed.summary().startswith("3 settings")
    assert "inverted" in parsed.summary()
    assert "cropped" in parsed.summary()


@pytest.mark.parametrize("name", ["scan_001.tif.negpy", "scan_001.negpy"])
def test_both_sidecar_spellings_belong_to_the_same_scan(name):
    assert sidecar.is_sidecar_name(name)
    assert sidecar.image_stem(name) == "scan_001"


def test_a_zip_of_scans_and_sidecars_keeps_both(client):
    roll = make_roll(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("kyoto_001.jpg", jpeg_bytes())
        archive.writestr("kyoto_001.jpg.negpy", json.dumps(RECIPE))
        archive.writestr("kyoto_002.jpg", jpeg_bytes())
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk_zip",
        files={"file": ("roll.zip", buffer.getvalue(), "application/zip")},
    )
    assert res.status_code == 200, res.text
    images = sorted(res.json()["images"], key=lambda i: i["original_filename"])
    assert [i["original_filename"] for i in images] == ["kyoto_001.jpg", "kyoto_002.jpg"]
    assert images[0]["sidecar_path"] and images[1]["sidecar_path"] is None


def test_deleting_a_frame_deletes_its_sidecar(client):
    roll = make_roll(client)
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("gone_001.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("gone_001.jpg.negpy", json.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    frame = res.json()["images"][0]
    sidecar_path = frame["sidecar_path"]
    assert os.path.isfile(sidecar_path)
    assert client.delete(f"/api/images/{frame['id']}").status_code == 200
    assert not os.path.exists(sidecar_path)


def test_a_sidecar_is_not_reported_as_an_orphan_file(client):
    roll = make_roll(client)
    client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("sweep_001.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("sweep_001.jpg.negpy", json.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    report = client.post("/api/maintenance/sweep_orphans").json()
    assert not [path for path in report["orphan_files"] if path.endswith(".negpy")]


def test_the_export_carries_the_sidecars(client):
    roll = make_roll(client)
    client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("export_001.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("export_001.jpg.negpy", json.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    res = client.get("/api/export")
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as archive:
        names = archive.namelist()
    assert any(name.endswith(".negpy") for name in names)


# --- link mode ----------------------------------------------------------------


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setenv("LIBRARY_ROOTS_ALLOW", str(tmp_path.resolve()))
    return root


def test_a_linked_scan_is_read_like_an_uploaded_one(client, library):
    folder = library / "2026-0101 Harbour"
    folder.mkdir()
    (folder / "harbour_004.jpg").write_bytes(
        jpeg_bytes(xmp=xmp_packet(CaptureFrame="4", CaptureDate="2026-02-02"))
    )
    (folder / "harbour_004.jpg.negpy").write_text(json.dumps(RECIPE))

    root_id = client.post("/api/library/roots", json={"path": str(library)}).json()["root"]["id"]
    result = client.post(f"/api/library/roots/{root_id}/scan").json()["result"]
    assert result["frames_added"] == 1
    assert result["sidecars_seen"] == 1

    frames = client.get("/api/images", params={"film_id": result["roll_ids"][0]}).json()
    frame = frames[0]
    assert frame["storage_mode"] == "linked"
    assert frame["capture_date"] == "2026-02-02"
    assert frame["negpy_summary"]
    # The original folder is untouched: no new files, nothing renamed.
    assert sorted(p.name for p in folder.iterdir()) == ["harbour_004.jpg", "harbour_004.jpg.negpy"]


def test_a_sidecar_written_after_the_import_is_picked_up(client, library):
    folder = library / "2026-0102 Later"
    folder.mkdir()
    scan_path = folder / "later_001.jpg"
    scan_path.write_bytes(jpeg_bytes())
    root_id = client.post("/api/library/roots", json={"path": str(library)}).json()["root"]["id"]
    first = client.post(f"/api/library/roots/{root_id}/scan").json()["result"]
    assert first["sidecars_seen"] == 0

    (folder / "later_001.jpg.negpy").write_text(json.dumps(RECIPE))
    second = client.post(f"/api/library/roots/{root_id}/scan").json()["result"]
    assert second["sidecars_seen"] == 1
    assert second["frames_updated"] == 1

    frames = client.get("/api/images", params={"film_id": first["roll_ids"][0]}).json()
    assert frames[0]["negpy_edited_at"] is not None


# --- gear sync ----------------------------------------------------------------


def test_gear_sync_writes_the_three_files(client):
    client.post("/api/cameras", json={"name": unique("Rolleiflex"), "mount": "fixed"})
    res = client.post("/api/negpy/gear/sync")
    assert res.status_code == 200, res.text
    result = res.json()["result"]
    directory = result["directory"]
    for name in ("cameras.json", "lenses.json", "film_stocks.json"):
        assert os.path.isfile(os.path.join(directory, name))

    cameras = json.loads(open(os.path.join(directory, "cameras.json"), encoding="utf-8").read())
    assert all(str(entry["id"]).startswith("na-cam-") for entry in cameras)
    entry = cameras[0]
    assert entry["displayName"] and entry["source"] == "NegArchive"


def test_a_camera_mount_lands_in_notes_because_negpy_has_no_field_for_it(client):
    name = unique("Nikon F3")
    client.post("/api/cameras", json={"name": name, "mount": "Nikon F"})
    directory = client.post("/api/negpy/gear/sync").json()["result"]["directory"]
    cameras = json.loads(open(os.path.join(directory, "cameras.json"), encoding="utf-8").read())
    ours = next(entry for entry in cameras if entry["displayName"] == name)
    assert "Mount: Nikon F" in ours["notes"]
    # NegPy shows displayName; make/model are split on the first space.
    assert ours["make"] == "Nikon" and ours["model"] == name.split(" ", 1)[1]


def test_a_lens_gets_its_focal_length_and_aperture_from_its_name(client):
    name = unique("Summicron 50mm f/2")
    client.post("/api/lenses", json={"name": name})
    directory = client.post("/api/negpy/gear/sync").json()["result"]["directory"]
    lenses = json.loads(open(os.path.join(directory, "lenses.json"), encoding="utf-8").read())
    ours = next(entry for entry in lenses if entry["displayName"] == name)
    assert ours["focalLength"] == 50.0
    assert ours["maxAperture"] == 2.0
    assert ours["lensModel"] == name


def test_film_kinds_are_translated_into_negpys_spelling(client):
    name = unique("Velvia 50")
    client.post("/api/filmstocks", json={"name": name, "iso": 50, "kind": "slide", "manufacturer": "Fujifilm"})
    directory = client.post("/api/negpy/gear/sync").json()["result"]["directory"]
    stocks = json.loads(open(os.path.join(directory, "film_stocks.json"), encoding="utf-8").read())
    ours = next(entry for entry in stocks if entry["displayName"] == name)
    assert ours["colorType"] == "ColorSlide"
    assert ours["manufacturer"] == "Fujifilm"
    assert ours["iso"] == 50


def test_a_sync_never_touches_an_entry_that_is_not_ours():
    """NegPy's bundled gear, and anything the user wrote by hand, survives a sync."""
    theirs = {"id": "cam-leica-m6", "displayName": "Leica M6"}
    mine_gone = {"id": "na-cam-999", "displayName": "Deleted in NegArchive"}
    mine_kept = {"id": "na-cam-1", "displayName": "Old name"}
    merged = gear.merge([theirs, mine_gone, mine_kept], [{"id": "na-cam-1", "displayName": "New name"}], "na-cam-")
    assert merged[0] == theirs  # untouched, and still first
    assert {entry["id"] for entry in merged} == {"cam-leica-m6", "na-cam-1"}
    assert merged[1]["displayName"] == "New name"


def test_a_sync_keeps_the_shape_of_an_existing_file(client, tmp_path):
    """Some gear files are ``{"cameras": [...]}``; that file stays that way."""
    directory = tmp_path / "gear"
    directory.mkdir()
    (directory / "cameras.json").write_text(json.dumps({"cameras": [{"id": "cam-bundled"}]}))
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        gear.sync(db, directory)
    finally:
        db.close()
    written = json.loads((directory / "cameras.json").read_text())
    assert isinstance(written, dict) and "cameras" in written
    assert any(entry["id"] == "cam-bundled" for entry in written["cameras"])


def test_a_dry_run_writes_nothing(client, tmp_path, monkeypatch):
    res = client.post("/api/negpy/gear/sync", params={"dry_run": "true"})
    assert res.status_code == 200
    result = res.json()["result"]
    assert result["dry_run"] is True
    assert result["synced_at"] is None


def test_the_gear_directory_cannot_be_pointed_anywhere(client, tmp_path):
    res = client.put("/api/system/settings", json={"negpy_user_dir": str(tmp_path / "somewhere-else")})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "path_not_allowed"
    assert res.json()["error"]["field"] == "negpy_user_dir"


def test_a_relative_directory_is_refused(client):
    res = client.put("/api/system/settings", json={"negpy_user_dir": "negpy/user"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_path"


def test_a_directory_inside_the_data_directory_is_accepted(client):
    from app import paths

    target = paths.data_dir() / "negpy" / "elsewhere"
    res = client.put("/api/system/settings", json={"negpy_user_dir": str(target)})
    assert res.status_code == 200, res.text
    assert res.json()["settings"]["negpy_user_dir"] == str(target)
    status = client.get("/api/negpy/status").json()
    assert status["paths"]["gear_dir"] == str(target / "gear")


# --- roll handoff -------------------------------------------------------------


def make_roll_with_scans(client, count=2) -> dict:
    stock = client.post(
        "/api/filmstocks", json={"name": unique("HP5"), "iso": 400, "kind": "black_and_white"}
    ).json()["filmstock"]
    roll = make_roll(client, film_stock_id=stock["id"])
    for number in range(1, count + 1):
        upload(client, roll["id"], f"scan_{number:03d}.jpg", jpeg_bytes(), frame_number=number)
    return client.get(f"/api/films/{roll['id']}").json()["film"]


def test_a_handoff_prepares_a_folder_a_preset_and_a_readme(client):
    roll = make_roll_with_scans(client, 2)
    res = client.post(f"/api/negpy/rolls/{roll['id']}/handoff")
    assert res.status_code == 200, res.text
    result = res.json()["handoff"]
    folder = result["folder"]

    assert os.path.basename(folder) == roll["archive_serial"]
    assert result["frames"] == 2
    assert os.path.isfile(os.path.join(folder, "README.txt"))

    # The files are named with the preset, so a re-import reads them back.
    names = sorted(n for n in os.listdir(folder) if n.endswith(".jpg"))
    assert names[0].startswith(f"{roll['archive_serial']}_001_")
    parsed = naming.parse(names[0])
    assert parsed.roll == roll["archive_serial"] and parsed.frame_number == 1

    preset = json.loads(open(result["preset_path"], encoding="utf-8").read())
    assert preset["capture_roll"] == roll["archive_serial"]
    assert preset["film_stock_id"] == f"na-film-{roll['film_stock_id']}"


def test_a_handoff_hard_links_rather_than_copying(client):
    roll = make_roll_with_scans(client, 1)
    result = client.post(f"/api/negpy/rolls/{roll['id']}/handoff").json()["handoff"]
    assert result["linked"] == 1 and result["copied"] == 0

    frame = client.get("/api/images", params={"film_id": roll["id"]}).json()[0]
    original = os.path.join(str(__import__("app").paths.data_dir()), frame["path"].replace("static/", "", 1))
    placed = next(
        os.path.join(result["folder"], name)
        for name in os.listdir(result["folder"])
        if name.endswith(".jpg")
    )
    assert os.path.samefile(original, placed)


def test_a_handoff_can_be_asked_for_copies(client):
    roll = make_roll_with_scans(client, 1)
    result = client.post(f"/api/negpy/rolls/{roll['id']}/handoff", json={"mode": "copy"}).json()["handoff"]
    assert result["copied"] == 1 and result["linked"] == 0


def test_a_handoff_is_idempotent(client):
    roll = make_roll_with_scans(client, 2)
    first = client.post(f"/api/negpy/rolls/{roll['id']}/handoff").json()["handoff"]
    second = client.post(f"/api/negpy/rolls/{roll['id']}/handoff").json()["handoff"]
    assert first["folder"] == second["folder"]
    assert second["frames"] == 2
    assert len([n for n in os.listdir(second["folder"]) if n.endswith(".jpg")]) == 2


def test_a_handoff_takes_the_sidecar_with_it(client):
    roll = make_roll(client)
    client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("hand_001.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("hand_001.jpg.negpy", json.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    result = client.post(f"/api/negpy/rolls/{roll['id']}/handoff").json()["handoff"]
    assert result["sidecars"] == 1
    assert any(name.endswith(".negpy") for name in os.listdir(result["folder"]))


def test_a_roll_with_no_scans_cannot_be_handed_over(client):
    roll = make_roll(client)
    res = client.post(f"/api/negpy/rolls/{roll['id']}/handoff")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "no_frames"


def test_an_unknown_roll_is_a_404(client):
    assert client.post("/api/negpy/rolls/999999/handoff").status_code == 404


def test_an_invalid_mode_is_refused(client):
    roll = make_roll_with_scans(client, 1)
    res = client.post(f"/api/negpy/rolls/{roll['id']}/handoff", json={"mode": "move"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invalid_mode"


# --- ingesting what is already here -------------------------------------------


def test_the_backlog_can_be_read_after_the_fact(client):
    """Everything imported before M5 has no capture_metadata; this is the catch-up."""
    client.put("/api/system/settings", json={"negpy_ingest": False})
    roll = make_roll(client)
    image = upload(client, roll["id"], "old.jpg", jpeg_bytes(xmp=xmp_packet(CaptureFrame="33")))
    assert image["capture_metadata"] is None

    client.put("/api/system/settings", json={"negpy_ingest": True})
    res = client.post("/api/negpy/ingest", json={"film_id": roll["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["changed"] >= 1

    after = client.get(f"/api/images/{image['id']}").json()
    assert after["frame_number"] == 33


def test_ingest_reports_when_it_is_switched_off(client):
    client.put("/api/system/settings", json={"negpy_ingest": False})
    res = client.post("/api/negpy/ingest", json={})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ingest_disabled"


# --- the content hash, and looking a frame up by it ---------------------------


def sampled_hash_from_the_specification(path: str) -> str:
    """The algorithm as docs/NEGPY_INTEGRATION.md states it, written out again.

    Deliberately a second implementation: if someone "optimises"
    ``app/services/hashing.py`` and changes what it produces, every NegArchive
    record silently stops matching the ``edits.db`` rows NegPy keyed by the same
    hash. This test is the only thing that would notice.
    """
    head_tail = 1024 * 1024
    chunk = 256 * 1024
    size = os.path.getsize(path)
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with open(path, "rb") as handle:
        handle.seek(0)
        digest.update(handle.read(min(head_tail, size)))
        if size > head_tail:
            handle.seek(size - head_tail)
            digest.update(handle.read(head_tail))
        start, end = head_tail, max(head_tail, size - head_tail)
        span = end - start
        if span > 0:
            for index in range(16):
                offset = start + (span * index) // 16
                handle.seek(offset)
                digest.update(handle.read(min(chunk, end - offset)))
    return digest.hexdigest()


@pytest.mark.parametrize("size", [0, 1000, 1024 * 1024, 3 * 1024 * 1024, 7 * 1024 * 1024 + 13])
def test_the_hash_matches_its_written_specification(tmp_path, size):
    path = tmp_path / f"file-{size}.bin"
    path.write_bytes(bytes((index * 31 + 7) % 251 for index in range(size)))
    assert content_hash(path) == sampled_hash_from_the_specification(str(path))


def test_a_frame_can_be_looked_up_by_its_hash(client):
    roll = make_roll(client)
    image = upload(client, roll["id"], "lookup.jpg", jpeg_bytes(), frame_number=9)
    res = client.get("/api/negpy/lookup", params={"hash": image["content_hash"]})
    assert res.status_code == 200, res.text
    found = res.json()["frames"]
    assert any(f["image_id"] == image["id"] and f["archive_serial"] == roll["archive_serial"] for f in found)


def test_a_lookup_without_a_query_is_refused(client):
    assert client.get("/api/negpy/lookup").status_code == 400


# --- status -------------------------------------------------------------------


def test_status_says_where_everything_goes(client):
    status = client.get("/api/negpy/status").json()
    assert status["ingest_enabled"] is True
    assert status["filename_pattern"] == naming.FILENAME_PATTERN
    assert status["xmp_namespace"] == "https://negpy.app/ns/1.0/"
    assert status["paths"]["gear_dir"].endswith(os.path.join("negpy", "user", "gear"))
    assert status["allowed_bases"]


def test_status_counts_what_has_been_read_and_edited(client):
    roll = make_roll(client)
    client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("status_001.jpg", jpeg_bytes(), "image/jpeg")),
            ("files", ("status_001.jpg.negpy", json.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    status = client.get("/api/negpy/status").json()
    assert status["frames_with_metadata"] >= 1
    assert status["frames_edited_in_negpy"] >= 1
