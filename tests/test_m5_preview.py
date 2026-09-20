"""M5 — printing a negative as a positive, for the preview only.

The archive stores one file per frame: the scan. What the browser shows can still
be a positive, because a rendering is derived, disposable and lives in the preview
cache. These tests hold three lines that matter more than the pixels:

* the render is **derived, never stored** — the file on disk is byte-identical
  afterwards, and a raw and a positive rendering of the same frame coexist in the
  cache instead of evicting each other;
* the archive only prints what it **knows** is a negative, because turning
  somebody's scan of a print inside out uninvited is worse than an orange
  thumbnail;
* the recipe reader **reports what it could not render**. NegArchive approximates
  NegPy's tone controls and runs none of its nine-stage pipeline, and the count in
  the viewer is how it says so.

The tone tests use a reference photograph put through a synthetic film gamma and
orange mask, so "did the print come back looking like the picture" is a number
rather than an opinion.
"""

import hashlib
import io
import os
import uuid

import numpy as np
import pytest
from PIL import Image

from app.services import preview
from app.services.negpy import recipe as negpy_recipe

# --- a reference photograph, and a negative of it ------------------------------


def reference_photo(width: int = 240, height: int = 160) -> np.ndarray:
    """Something with a sky, a ground, a grey ramp and saturated patches."""
    image = np.zeros((height, width, 3), dtype=np.float32)
    rows = np.linspace(0.9, 0.55, height // 2, dtype=np.float32)[:, None]
    image[: height // 2] = np.stack(
        [rows * 0.75, rows * 0.85, rows * np.ones_like(rows)], axis=2
    )[:, 0, :][:, None, :]
    image[height // 2 :] = np.array([0.27, 0.33, 0.21], dtype=np.float32)
    for index in range(10):
        left = 8 + index * ((width - 16) // 10)
        image[height - 60 : height - 40, left : left + 12] = index / 9.0
    for index, colour in enumerate(
        [(0.78, 0.24, 0.24), (0.24, 0.63, 0.35), (0.27, 0.35, 0.78), (0.86, 0.71, 0.24)]
    ):
        left = 8 + index * ((width - 16) // 4)
        image[height - 30 : height - 12, left : left + 20] = colour
    return np.clip(image, 0.0, 1.0)


def as_negative(positive: np.ndarray, gamma: float = 0.55) -> np.ndarray:
    """A colour negative of ``positive``: film gamma, inverted, orange mask."""
    linear = positive**2.2
    density = -np.log10(np.clip(linear, 1e-4, 1.0))
    negative = gamma * density
    negative = negative.max() - negative + np.array([0.15, 0.55, 0.95], dtype=np.float32)
    encoded = np.clip((10 ** (-negative)) ** (1 / 2.2), 0.0, 1.0)
    return (encoded * 255).astype(np.uint8)


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(((a.astype(float) - b.astype(float)) ** 2).mean()))


# --- the renderer -------------------------------------------------------------


def test_a_negative_prints_as_the_photograph_it_was():
    positive = reference_photo()
    rendered = preview.render(as_negative(positive))
    reference = (positive * 255).astype(np.uint8)

    assert rendered.shape == reference.shape
    assert rendered.dtype == np.uint8
    # Close enough to be the same picture, on a 0–255 scale. It is a print, not a
    # copy: the paper's shoulder holds the highlights back, which is most of what
    # is left in the error.
    assert rmse(rendered, reference) < 35
    # …and unmistakably not just the scan passed through.
    assert rmse(rendered, as_negative(positive)) > 60


@pytest.mark.parametrize("gamma", [0.35, 0.55, 0.75])
def test_a_flat_and_a_contrasty_negative_both_print_sensibly(gamma):
    """Auto Grade's job: the frame's own textural range sets the paper grade."""
    positive = reference_photo()
    rendered = preview.render(as_negative(positive, gamma=gamma)).astype(float)
    assert 100 < rendered.mean() < 200
    assert rendered.std() > 35  # not washed flat


def test_printing_longer_makes_a_darker_print():
    negative = as_negative(reference_photo())
    normal = preview.render(negative).astype(float).mean()
    longer = preview.render(negative, preview.RenderSettings(exposure_stops=1.0)).astype(float).mean()
    assert longer < normal - 20


def test_a_harder_grade_is_more_contrast():
    negative = as_negative(reference_photo())
    soft = preview.render(negative, preview.RenderSettings(grade_r=180, auto_density=False))
    hard = preview.render(negative, preview.RenderSettings(grade_r=50, auto_density=False))
    assert hard.astype(float).std() > soft.astype(float).std() + 2


def test_the_zone_sliders_move_their_own_end_of_the_scale():
    negative = as_negative(reference_photo())
    base = preview.render(negative).astype(float)
    burned = preview.render(negative, preview.RenderSettings(shadow_density=0.8)).astype(float)
    # A shadow burn darkens the shadows and leaves the highlights alone.
    dark = base < 80
    light = base > 190
    assert burned[dark].mean() < base[dark].mean()
    assert abs(burned[light].mean() - base[light].mean()) < 12


def test_a_slide_is_not_turned_inside_out():
    positive = (reference_photo() * 255).astype(np.uint8)
    rendered = preview.render(positive, preview.RenderSettings(polarity="positive"))
    # Still the same picture: bright stays bright, dark stays dark.
    correlation = np.corrcoef(rendered.reshape(-1).astype(float), positive.reshape(-1).astype(float))[0, 1]
    assert correlation > 0.9


def test_a_black_and_white_negative_prints_neutral():
    """A panchromatic negative collapses to one density, the way paper sees it."""
    rendered = preview.render(as_negative(reference_photo()), preview.RenderSettings(polarity="mono"))
    channels = rendered.astype(int)
    assert np.abs(channels[:, :, 0] - channels[:, :, 1]).max() <= 1
    assert np.abs(channels[:, :, 1] - channels[:, :, 2]).max() <= 1


def test_geometry_is_exact_rather_than_approximated():
    source = (reference_photo(240, 160) * 255).astype(np.uint8)
    cropped = preview.render(source, preview.RenderSettings(crop=(0.25, 0.5, 0.5, 0.25), polarity="positive"))
    assert cropped.shape[:2] == (40, 120)
    turned = preview.render(source, preview.RenderSettings(rotate_quarter_turns=1, polarity="positive"))
    assert turned.shape[:2] == (240, 160)


def test_a_crop_in_pixels_is_refused_rather_than_guessed_at():
    """Without the frame size a pixel rect would crop to a corner. It is ignored."""
    settings = negpy_recipe.from_recipe({"settings": {"crop_rect": [0, 0, 3000, 2000]}})
    assert settings.crop is None


@pytest.mark.parametrize(
    "kind,image_type,expected",
    [
        ("color", "scan", "negative"),
        ("black_and_white", "scan", "mono"),
        ("slide", "scan", "positive"),
        (None, "scan", "negative"),
        ("color", "contact_sheet", "positive"),
    ],
)
def test_the_film_stock_decides_how_a_frame_is_printed(kind, image_type, expected):
    assert preview.polarity_for(kind, image_type) == expected


# --- reading a recipe ---------------------------------------------------------


RECIPE = {
    "version": 3,
    "file_hash": "abc",
    "settings": {
        "mode": "color_negative",
        "exposure": 0.5,
        "grade": 130,
        "shadow_density": 0.3,
        "toe": 0.4,
        "geometry": {"crop_rect": [0.05, 0.1, 0.9, 0.8], "rotation": 90, "distortion_k1": 0.02},
        "local_masks": [{"stops": 1.0}],
        "toning": {"split": "selenium"},
        "lab": {"clahe_strength": 0.4},
        "paper_profile": "Kodak Endura Premier",
    },
}


def test_a_recipe_sets_the_controls_it_carries():
    settings = negpy_recipe.from_recipe(RECIPE)
    assert settings.grade_r == 130
    assert settings.exposure_stops == 0.5
    assert settings.shadow_density == 0.3
    assert settings.crop == (0.05, 0.1, 0.9, 0.8)
    assert settings.rotate_quarter_turns == 1
    assert settings.polarity == "negative"


def test_everything_it_cannot_render_is_named():
    """The honesty that makes an approximation usable."""
    ignored = set(negpy_recipe.report(RECIPE)["ignored"])
    assert {"local_masks", "toning.split", "lab.clahe_strength", "paper_profile"} <= ignored
    assert "geometry.distortion_k1" in ignored
    assert "grade" not in ignored  # what it *can* render is not reported as lost


def test_dotted_and_nested_keys_are_the_same_thing():
    dotted = negpy_recipe.from_recipe({"settings": {"geometry.crop_rect": [0.1, 0.1, 0.8, 0.8]}})
    nested = negpy_recipe.from_recipe({"settings": {"geometry": {"crop_rect": [0.1, 0.1, 0.8, 0.8]}}})
    assert dotted.crop == nested.crop == (0.1, 0.1, 0.8, 0.8)


def test_a_recipe_can_say_it_is_a_slide():
    assert negpy_recipe.from_recipe({"settings": {"mode": "transparency"}}).polarity == "positive"


def test_no_recipe_is_not_an_error():
    assert negpy_recipe.from_recipe(None).polarity == "negative"
    assert negpy_recipe.from_recipe({}).applied == []


def test_the_report_counts_both_sides():
    report = negpy_recipe.report(RECIPE)
    assert report["applied_count"] >= 5
    assert report["ignored_count"] >= 4
    assert report["summary"].endswith("settings rendered")
    assert str(report["applied_count"]) in report["summary"]


# --- through the API ----------------------------------------------------------


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def negative_png() -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(as_negative(reference_photo())).save(buffer, format="PNG")
    return buffer.getvalue()


def make_roll_with_stock(client, kind: str = "color") -> dict:
    stock = client.post(
        "/api/filmstocks", json={"name": unique("Stock"), "iso": 200, "kind": kind}
    ).json()["filmstock"]
    return client.post("/api/films", json={"title": unique("Roll"), "film_stock_id": stock["id"]}).json()["film"]


def upload_scan(client, roll_id: int, payload: bytes, image_type: str = "scan") -> dict:
    res = client.post(
        "/api/images/upload",
        files={"file": ("negative_001.png", payload, "image/png")},
        data={"type": image_type, "film_roll_id": str(roll_id)},
    )
    assert res.status_code == 200, res.text
    return res.json()["image"]


def fetch(client, image_id: int, **params):
    res = client.get(f"/api/images/{image_id}/preview", params={"width": 200, **params})
    assert res.status_code == 200, res.text
    return res.content, res.headers.get("X-Preview-Render")


def test_the_same_frame_comes_back_raw_or_printed(client):
    roll = make_roll_with_stock(client)
    image = upload_scan(client, roll["id"], negative_png())

    raw, raw_mode = fetch(client, image["id"], render="raw")
    printed, printed_mode = fetch(client, image["id"], render="positive")
    assert (raw_mode, printed_mode) == ("raw", "positive")
    assert raw != printed

    raw_mean = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB")).mean()
    printed_mean = np.asarray(Image.open(io.BytesIO(printed)).convert("RGB")).mean()
    assert printed_mean > raw_mean + 30  # the scan is dense; the print is not


def test_the_scan_on_disk_is_not_touched(client):
    """The whole promise: a rendering is derived, and the archive still has one file."""
    from app import paths

    roll = make_roll_with_stock(client)
    payload = negative_png()
    image = upload_scan(client, roll["id"], payload)
    on_disk = paths.resolve(image["path"])
    before = (os.stat(on_disk).st_size, hashlib.sha256(open(on_disk, "rb").read()).hexdigest())

    fetch(client, image["id"], render="positive")
    fetch(client, image["id"], render="raw")

    after = (os.stat(on_disk).st_size, hashlib.sha256(open(on_disk, "rb").read()).hexdigest())
    assert after == before


def test_both_renderings_are_cached_side_by_side(client):
    """A positive and a raw preview must not evict each other from the cache."""
    from app import paths

    roll = make_roll_with_stock(client)
    image = upload_scan(client, roll["id"], negative_png())
    fetch(client, image["id"], render="raw")
    fetch(client, image["id"], render="positive")

    cached = [name for name in os.listdir(paths.cache_dir()) if name.startswith(f"{image['id']}_")]
    assert len(cached) >= 2
    # …and both are served from the cache the second time round.
    for mode in ("raw", "positive"):
        res = client.get(f"/api/images/{image['id']}/preview", params={"width": 200, "render": mode})
        assert res.headers.get("X-Preview-Cache") == "hit"


def test_auto_prints_a_frame_the_archive_knows_is_a_negative(client):
    roll = make_roll_with_stock(client, kind="color")
    image = upload_scan(client, roll["id"], negative_png())
    _, mode = fetch(client, image["id"])
    assert mode == "positive"


def test_auto_leaves_a_frame_of_unknown_film_alone(client):
    """It might be a scan of a print. Guessing costs more than an orange thumbnail."""
    roll = client.post("/api/films", json={"title": unique("Roll")}).json()["film"]
    image = upload_scan(client, roll["id"], negative_png())
    _, mode = fetch(client, image["id"])
    assert mode == "raw"


def test_a_contact_sheet_is_never_printed(client):
    roll = make_roll_with_stock(client)
    sheet = upload_scan(client, roll["id"], negative_png(), image_type="contact_sheet")
    _, mode = fetch(client, sheet["id"])
    assert mode == "raw"


def test_the_setting_can_force_either_way(client):
    roll = make_roll_with_stock(client, kind="color")
    image = upload_scan(client, roll["id"], negative_png())
    try:
        client.put("/api/system/settings", json={"preview_render": "raw"})
        assert fetch(client, image["id"])[1] == "raw"
        client.put("/api/system/settings", json={"preview_render": "positive"})
        assert fetch(client, image["id"])[1] == "positive"
        # …and the query parameter still wins over the setting.
        assert fetch(client, image["id"], render="raw")[1] == "raw"
    finally:
        client.put("/api/system/settings", json={"preview_render": "auto"})


def test_the_frame_reports_what_its_recipe_could_not_render(client):
    import json as json_module

    roll = make_roll_with_stock(client)
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[
            ("files", ("report_001.png", negative_png(), "image/png")),
            ("files", ("report_001.png.negpy", json_module.dumps(RECIPE).encode(), "application/json")),
        ],
    )
    assert res.status_code == 200, res.text
    frame = res.json()["images"][0]
    assert frame["negpy_render"]["applied_count"] >= 5
    assert "local_masks" in frame["negpy_render"]["ignored"]
    assert "toning.split" in frame["negpy_render"]["ignored"]
    assert frame["negpy_render"]["summary"]


# --- M6.1: a frame that is already a positive ------------------------------------------
#
# The workflow that made this necessary: scan with NegPy, export a finished JPEG,
# upload the JPEG. The roll's film is a colour negative, so "auto" printed the
# export — a positive — a second time and turned it inside out. A frame can now say
# it is already a positive, and then nothing prints it: not the film, not the
# global setting, not the query.


def test_a_frame_marked_positive_is_shown_as_it_is_whatever_anyone_says(client):
    roll = make_roll_with_stock(client)  # a colour negative: auto would print this
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[("files", ("export_001.png", negative_png(), "image/png"))],
        data={"positive": "true"},
    )
    assert res.status_code == 200, res.text
    image = res.json()["images"][0]
    assert image["positive"] is True

    _, auto_mode = fetch(client, image["id"])
    _, forced_mode = fetch(client, image["id"], render="positive")
    assert (auto_mode, forced_mode) == ("raw", "raw")

    # The global "always print" setting does not reach it either.
    client.put("/api/settings", json={"preview_render": "positive"})
    try:
        assert fetch(client, image["id"])[1] == "raw"
    finally:
        client.put("/api/settings", json={"preview_render": "auto"})

    # Taking the flag away hands the decision back to the film stock.
    res = client.put(f"/api/images/{image['id']}", json={"positive": None})
    assert res.status_code == 200 and res.json()["image"]["positive"] is None
    assert fetch(client, image["id"])[1] == "positive"


def test_a_frame_marked_negative_is_printed_even_when_the_film_is_unknown(client):
    roll = client.post("/api/films", json={"title": unique("No film")}).json()["film"]
    image = upload_scan(client, roll["id"], negative_png())
    assert fetch(client, image["id"])[1] == "raw"  # unknown film: left alone (M5)

    res = client.put(f"/api/images/{image['id']}", json={"positive": False})
    assert res.status_code == 200 and res.json()["image"]["positive"] is False
    assert fetch(client, image["id"])[1] == "positive"


def test_the_flag_refuses_nonsense():
    from app.errors import ApiError
    from app.routers.api import parse_positive

    assert parse_positive("true") is True and parse_positive("0") is False
    assert parse_positive("") is None and parse_positive("auto") is None and parse_positive(None) is None
    with pytest.raises(ApiError):
        parse_positive("maybe")


def test_a_negpy_export_is_recognised_as_a_positive_by_its_xmp(client):
    """No checkbox needed for the common case: NegPy writes its `negpy:` namespace on
    export and nowhere else, so a file carrying it is a converted positive."""
    from test_m5_negpy import jpeg_bytes, xmp_packet

    roll = make_roll_with_stock(client)
    export = jpeg_bytes(xmp=xmp_packet(CaptureRoll="whatever", CaptureFrame="7"))
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[("files", ("NEG-2026-0001_007_Gold 200.jpg", export, "image/jpeg"))],
    )
    assert res.status_code == 200, res.text
    image = res.json()["images"][0]
    assert image["positive"] is True
    assert fetch(client, image["id"])[1] == "raw"

    # A plain scan on the same roll — no negpy XMP — is still a negative to print.
    scan = upload_scan(client, roll["id"], negative_png())
    assert scan["positive"] is None
    assert fetch(client, scan["id"])[1] == "positive"


def test_ingest_does_not_overwrite_a_flag_somebody_set(client):
    """Fills blanks, never overwrites — the M5 rule, applied to the new field."""
    from test_m5_negpy import jpeg_bytes, xmp_packet

    roll = make_roll_with_stock(client)
    export = jpeg_bytes(xmp=xmp_packet(CaptureRoll="x", CaptureFrame="1"))
    res = client.post(
        f"/api/films/{roll['id']}/images/bulk",
        files=[("files", ("odd.jpg", export, "image/jpeg"))],
        data={"positive": "false"},
    )
    assert res.json()["images"][0]["positive"] is False
