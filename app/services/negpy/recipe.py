"""Reading a NegPy edit as render settings — and saying what was left out.

:mod:`app.services.preview` can print a negative on its own. This module is what
lets it print *your* negative the way you graded it: it maps the settings in a
``.negpy`` sidecar or an ``edits.db`` row onto the renderer's parameters.

It maps the **tone controls** and the **geometry**, because those are the ones
NegPy documents as formulas with constants (``docs/PIPELINE.md`` §1–§3) and the
ones a person means by "my edit": the grade, the print exposure, the toe and
shoulder, the zone densities, the midtone snap, the crop and the rotation.

It maps nothing else, and this is the important part: **every key it does not
understand is reported, by name, as ignored.** Dodge and burn masks, the contrast
mask, paper profiles with their dye-coupling matrices, cast removal, crosstalk
unmix, flat-field, HDR merge, CLAHE, retouching, Lab mode, toning, alt processes,
ICC soft-proofing — NegPy does all of it, this does none of it, and the frame
viewer says so with the count. An approximation that admits its own edges is
useful; one that quietly drops half a recipe and calls itself the edit is not.

Key names are matched **tolerantly**, the same way :mod:`app.services.negpy.edits`
sniffs a table: dotted (``geometry.crop_rect``) or bare (``crop_rect``), nested
one level deep, and several spellings per parameter. NegPy's stored schema is not
a published interface and may change; when it does, this reads less of a recipe
rather than failing to read any of it.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..preview import RenderSettings

#: ``{our parameter: the keys that may carry it}``. First match wins, and a key
#: is matched with or without its ``section.`` prefix.
KEYS: Dict[str, Tuple[str, ...]] = {
    "exposure_stops": ("exposure", "print_exposure", "exposure_stops", "density"),
    "grade_r": ("grade", "grade_r", "iso_r", "paper_grade", "contrast"),
    "shadow_density": ("shadow_density", "shadows", "zone_shadow_density"),
    "highlight_density": ("highlight_density", "highlights", "zone_highlight_density"),
    "shadow_grade": ("shadow_grade", "split_grade_shadow"),
    "highlight_grade": ("highlight_grade", "split_grade_highlight"),
    "toe": ("toe", "toe_height"),
    "shoulder": ("shoulder", "shoulder_height"),
    "toe_width": ("toe_width", "toe_sharpness"),
    "shoulder_width": ("shoulder_width", "shoulder_sharpness"),
    "midtone_gamma": ("midtone_gamma", "snap"),
    "paper_dmin": ("paper_dmin", "paper_white_base"),
    "paper_black": ("paper_black",),
    "auto_density": ("auto_exposure", "auto_density"),
}

#: Geometry, kept separate because it is exact rather than approximated.
CROP_KEYS = ("crop_rect", "crop", "geometry_crop_rect")
ROTATION_KEYS = ("rotation", "rotate", "orientation", "quarter_turns")
ANGLE_KEYS = ("angle", "fine_rotation", "deskew", "straighten")
FLIP_H_KEYS = ("flip_horizontal", "flip_h", "mirror_horizontal", "mirror")
FLIP_V_KEYS = ("flip_vertical", "flip_v", "mirror_vertical")

#: The mode/process a recipe was made in, which decides the polarity.
MODE_KEYS = ("mode", "process", "film_mode", "film_type", "negative_type")

#: Keys that carry no picture: metadata, ids, bookkeeping. Not reported as
#: ignored, because listing them as "not rendered" would be noise.
UNINTERESTING = {
    "version",
    "schema",
    "file_hash",
    "hash",
    "file_path",
    "path",
    "saved_at",
    "updated_at",
    "modified_at",
    "created_at",
    "id",
    "uuid",
    "app_version",
    "negpy_version",
    "source",
    "settings",
    "settings_json",
}


def _flatten(data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """``{"geometry": {"crop_rect": …}}`` → ``{"geometry.crop_rect": …}``.

    One level of nesting and dotted keys are the two shapes a settings blob comes
    in; flattening both into one map means the lookups below do not care which.
    """
    flat: Dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value and all(isinstance(k, str) for k in value):
            nested = _flatten(value, f"{name}.")
            if nested:
                flat.update(nested)
                continue
        flat[name] = value
    return flat


def _leaf(key: str) -> str:
    return key.rsplit(".", 1)[-1].strip().lower()


def _find(flat: Dict[str, Any], names: Iterable[str]) -> Tuple[Optional[str], Any]:
    """The first key whose leaf name matches, with its value."""
    wanted = [n.lower() for n in names]
    for name in wanted:
        for key, value in flat.items():
            if _leaf(key) == name and value is not None:
                return key, value
    return None, None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "on", "1"}:
            return True
        if text in {"false", "no", "off", "0"}:
            return False
    return None


def _crop(value: Any) -> Optional[Tuple[float, float, float, float]]:
    """A crop rect as fractions of the frame, from whatever shape it arrives in.

    Accepts ``[x, y, w, h]`` and ``{"x":…, "y":…, "w"/"width":…, "h"/"height":…}``,
    in fractions (0–1) or in pixels — pixels only when the recipe also carries the
    frame's size, because a rect of ``[0, 0, 3000, 2000]`` is meaningless without
    it and guessing would crop the picture to a corner.
    """
    rect: Optional[List[float]] = None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        numbers = [_number(part) for part in value]
        if all(n is not None for n in numbers):
            rect = [float(n) for n in numbers]  # type: ignore[arg-type]
    elif isinstance(value, dict):
        x = _number(value.get("x", value.get("left")))
        y = _number(value.get("y", value.get("top")))
        w = _number(value.get("w", value.get("width")))
        h = _number(value.get("h", value.get("height")))
        if None not in (x, y, w, h):
            rect = [float(x), float(y), float(w), float(h)]  # type: ignore[arg-type]
    if rect is None:
        return None
    if max(rect) <= 1.0001 and min(rect) >= -0.0001:
        x, y, w, h = rect
        if w > 0 and h > 0:
            return (x, y, w, h)
    return None  # pixels without a frame size: not usable, and not guessed at


def polarity_from_mode(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    if "transparency" in text or "slide" in text or "positive" in text or text == "e6":
        return "positive"
    if "b&w" in text or "bw" in text or "black" in text or "mono" in text or "pan" in text:
        return "mono"
    if "negative" in text or "c41" in text or "color" in text or "colour" in text:
        return "negative"
    return None


def from_recipe(
    recipe: Optional[Dict[str, Any]],
    *,
    polarity: str = "negative",
) -> RenderSettings:
    """Render settings for one frame: the archive's defaults, refined by the edit.

    ``polarity`` is what the archive already knows from the film stock's kind; a
    mode in the recipe overrides it, because the person converting the scan said
    so explicitly.
    """
    settings = RenderSettings(polarity=polarity)
    if not isinstance(recipe, dict) or not recipe:
        return settings

    payload = recipe.get("settings") if isinstance(recipe.get("settings"), dict) else recipe
    flat = _flatten(payload if isinstance(payload, dict) else {})
    consumed: set[str] = set()

    def take(names: Iterable[str]) -> Tuple[Optional[str], Any]:
        key, value = _find(flat, names)
        if key is not None:
            consumed.add(key)
        return key, value

    # --- polarity -------------------------------------------------------------
    key, value = take(MODE_KEYS)
    if key is not None:
        mode = polarity_from_mode(value)
        if mode:
            settings.polarity = mode
            settings.applied.append(key)
        else:
            consumed.discard(key)

    # --- the tone controls ----------------------------------------------------
    for field_name, names in KEYS.items():
        key, value = take(names)
        if key is None:
            continue
        current = getattr(settings, field_name)
        if isinstance(current, bool):
            parsed: Any = _bool(value)
        else:
            parsed = _number(value)
        if parsed is None:
            consumed.discard(key)
            continue
        setattr(settings, field_name, parsed)
        settings.applied.append(key)

    # --- geometry -------------------------------------------------------------
    key, value = take(CROP_KEYS)
    if key is not None:
        crop = _crop(value)
        if crop:
            settings.crop = crop
            settings.applied.append(key)
        else:
            consumed.discard(key)

    key, value = take(ROTATION_KEYS)
    if key is not None:
        degrees = _number(value)
        if degrees is not None and abs(degrees) >= 1.0:
            settings.rotate_quarter_turns = int(round(degrees / 90.0)) % 4
            settings.applied.append(key)
        else:
            consumed.discard(key)

    for names, field_name in ((FLIP_H_KEYS, "flip_horizontal"), (FLIP_V_KEYS, "flip_vertical")):
        key, value = take(names)
        if key is None:
            continue
        flag = _bool(value)
        if flag is None:
            consumed.discard(key)
            continue
        setattr(settings, field_name, flag)
        if flag:
            settings.applied.append(key)

    # A fine rotation angle is read but deliberately not applied: resampling a
    # preview by a degree and a half costs more than it shows at thumbnail size.
    key, _ = _find(flat, ANGLE_KEYS)
    if key is not None:
        consumed.add(key)
        settings.ignored.append(key)

    # --- everything else ------------------------------------------------------
    for key, value in flat.items():
        if key in consumed or _leaf(key) in UNINTERESTING:
            continue
        if value in (None, False, 0, 0.0, "", [], {}):
            continue  # a setting at its default is not something we dropped
        settings.ignored.append(key)

    settings.applied.sort()
    settings.ignored.sort()
    return settings


def report(recipe: Optional[Dict[str, Any]], *, polarity: str = "negative") -> Dict[str, Any]:
    """What the UI says about rendering this recipe: applied, ignored, how much.

    Kept cheap — it reads a dict and touches no pixels — because the frame list
    computes it for every frame it returns.
    """
    settings = from_recipe(recipe, polarity=polarity)
    # The keys are shown as NegPy spells them — "toning.split", not "split" —
    # because the section is half of what the name means.
    applied = list(settings.applied)
    ignored = list(settings.ignored)
    total = len(applied) + len(ignored)
    return {
        "applied": applied,
        "ignored": ignored[:12],
        "applied_count": len(applied),
        "ignored_count": len(ignored),
        "total": total,
        # One line for the viewer, e.g. "10 of 16 settings rendered".
        "summary": (
            f"{len(applied)} of {total} settings rendered" if total else "nothing to render"
        ),
    }
