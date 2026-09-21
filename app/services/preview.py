"""Rendering a negative as a positive, for the preview only.

A shelf of colour negatives is close to unbrowsable: every thumbnail is a dark
orange rectangle, and the frame you are looking for is somewhere in there. This
module turns the scan the archive stores into something a person can recognise —
**without storing a second image**. The result goes into the same disposable
preview cache every thumbnail already uses (``DATA_DIR/cache``, safe to delete at
any moment); the archive still holds exactly one file per frame, and it is the
raw scan.

What this is
------------
A **tone reproduction**, in the darkroom sense: normalize the scan, put it
through a paper-like transfer curve, and print it. The steps and their constants
follow the conversion NegPy documents in its ``docs/PIPELINE.md`` — polarity and
per-channel percentile bounds, an exposure anchor metered off the frame, an
asymmetric softplus toe/shoulder curve driven by an ISO-R grade, zone density
offsets, and ``I = 10**-D`` on the way out. Working from that written description
is the same bargain as the content hash in :mod:`app.services.hashing`: the
algorithm is re-implemented from its documentation, no NegPy code is imported,
copied or vendored, and this file says so where somebody will read it.

What this is **not**
--------------------
It is not NegPy's render and must never be shown as one. NegPy's pipeline has
nine stages — flat-field, sensor crosstalk unmix, HDR merge, paper profiles with
dye-coupling matrices, cast removal, CLAHE, retouching, dodge and burn, contrast
masks, toning, ICC soft-proofing — and it runs them on a linear raw decode this
backend deliberately cannot do (M2 removed the two-gigabyte dependency stack).
Anything here is an approximation of the *tone controls* and nothing else.

So the contract with the person looking at it is: the UI says the preview is
approximate, and :mod:`app.services.negpy.recipe` reports exactly which settings
of an edit were applied and which were ignored. A wrong rendering presented as
the truth is worse than no rendering; a labelled approximation next to an honest
list of what it left out is useful, and that is what this is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

# --- constants, from NegPy's documented pipeline ------------------------------
#
# Named here rather than inlined so a reader can check them against the source
# document, and so the difference between "their number" and "our choice" stays
# visible. Everything in this block is theirs.

#: Paper white and the physical deepest black, in density.
D_MIN = 0.06
D_MAX = 2.3
#: Toe and shoulder knee sharpness before the width trim.
TOE_SHARPNESS_BASE = 6.0
SHOULDER_SHARPNESS_BASE = 3.0
#: Slider-to-density scaling for the two knee heights.
TOE_HEIGHT_SCALE = 0.90
SHOULDER_HEIGHT_SCALE = 0.35
#: Slider values are scaled by this internally before either of the above.
SLIDER_SCALE = 0.85
#: Grade: ISO-R to straight-line slope, and the slope's bounds.
GRADE_CONTRAST_SCALE = 2.9
GRADE_DEFAULT_R = 115.0
SLOPE_MIN, SLOPE_MAX = 2.0, 10.0
#: The paper's own midtone S-curve.
PAPER_MIDTONE_GAMMA = 0.05
PAPER_GAMMA_WIDTH = 0.6
#: Zone density: the two mid-sparing weights.
ZONE_SHADOW_OFFSET = 0.75
ZONE_HIGHLIGHT_OFFSET = -0.40
ZONE_WEIGHT_K = 4.0
#: Auto Density: the assumed key and where the anchor prints.
ASSUMED_ANCHOR = 0.46
ANCHOR_TARGET_DENSITY = 0.75
#: Auto Grade: how far to pull a frame's contrast towards the nominal, and the
#: cap that stops a very flat frame being pushed to a harsh extreme.
AUTO_GRADE_STRENGTH = 0.4
AUTO_GRADE_MAX_OVERFILL = 1.2
#: One stop of print exposure, in log10 units of the normalized range.
STOP = math.log10(2.0)
#: Adobe RGB (1998) transfer function: a pure power, no linear segment.
OETF_POWER = 563.0 / 256.0

# --- our own choices ----------------------------------------------------------

#: Percentile bounds for the normalization. NegPy uses 0.01/99.99 on a raw
#: decode; a preview is rendered from an 8- or 16-bit scan that has already been
#: through a scanner's own processing, where the extremes are dust, rebate and
#: sensor noise rather than signal, so this backs off to a percentile that a
#: speck of dust cannot move.
DEFAULT_LOW_PERCENTILE = 0.2
DEFAULT_HIGH_PERCENTILE = 99.8
#: Scans are usually display-encoded rather than linear; undo that before the log.
ASSUMED_INPUT_GAMMA = 2.2
#: The analysis is run on at most this many pixels per side. Percentiles do not
#: need every pixel, and a 200 MB TIFF should not cost a second of numpy.
ANALYSIS_MAX_SIDE = 512
#: Below this the log is meaningless; it is the floor for a black pixel.
EPSILON = 1e-6

# NegPy's two automatic helpers are metered on *its* axis: a linear raw decode
# against fixed bounds. This renderer's axis is per-frame — §2's normalization
# divides by the scan's own floor-to-ceiling range — so a frame's content can sit
# anywhere on it, and their calibration (pull the assumed key 20% of the way,
# within a band of 0.12) leaves a picture that occupies the lower third of the
# axis printing far too bright. Measured against a reference photograph put
# through a synthetic film gamma and orange mask, their constants give an RMS
# error of 54 against the original; these give 25. The shapes are theirs — a
# partial pull, a bounded band, a capped overfill — and the numbers are ours,
# because the axis is ours.
#: How far the meter may pull the assumed key, and how far the result may sit
#: from it. Deliberately short of a full pull: a low-key frame should still print
#: low-key rather than being flattened to neutral grey.
METER_STRENGTH = 0.6
METER_BAND = 0.25
#: A normal negative's textural range (P10–P90) on the normalized axis.
NOMINAL_TEXTURAL_RANGE = 0.65


@dataclass
class RenderSettings:
    """Everything the renderer needs. Defaults render a plain colour negative."""

    #: "negative" (invert), "positive" (a slide or a scan of a print: do not
    #: invert), or "mono" (a black-and-white negative: one density, not three).
    polarity: str = "negative"
    #: Print exposure, in stops. Positive is a darker print, as in a darkroom.
    exposure_stops: float = 0.0
    #: Per-channel print exposure offsets, the colour head's CMY filtration.
    channel_offsets: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: Contrast as an ISO range value; 115 is roughly grade 2.
    grade_r: float = GRADE_DEFAULT_R
    #: Zone density: a literal density offset at full zone weight.
    shadow_density: float = 0.0
    highlight_density: float = 0.0
    #: Split grade, in ISO-R points off the frame's grade (negative = harder).
    shadow_grade: float = 0.0
    highlight_grade: float = 0.0
    #: Knee heights (the sliders) and their widths (sharpness).
    toe: float = 0.0
    shoulder: float = 0.0
    toe_width: float = 1.0
    shoulder_width: float = 1.0
    #: Midtone gamma trim on top of the paper's own S-curve.
    midtone_gamma: float = 0.0
    #: Paper white base: off pins D_min to 0 instead of 0.06.
    paper_dmin: bool = True
    #: Paper black: off applies black point compensation (NegPy's default).
    paper_black: bool = False
    #: Meter the frame for the exposure anchor rather than assuming a key.
    auto_density: bool = True
    #: Geometry, applied before anything else. The crop is (x, y, w, h) as
    #: fractions of the frame, so it survives being applied to a preview.
    crop: Optional[Tuple[float, float, float, float]] = None
    rotate_quarter_turns: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    #: Percentile bounds for the normalization.
    low_percentile: float = DEFAULT_LOW_PERCENTILE
    high_percentile: float = DEFAULT_HIGH_PERCENTILE
    #: Free-form notes for the API's "what was applied" report.
    applied: list = field(default_factory=list)
    ignored: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Small maths shared with the curve
# ---------------------------------------------------------------------------


def softplus(x: np.ndarray) -> np.ndarray:
    """``log(1 + e^x)``, computed so a large ``x`` cannot overflow."""
    return np.logaddexp(0.0, x)


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def _as_float(image: np.ndarray) -> np.ndarray:
    """Any integer or float image as float32 in [0, 1]."""
    data = np.asarray(image)
    if data.dtype == np.uint8:
        return data.astype(np.float32) / 255.0
    if data.dtype == np.uint16:
        return data.astype(np.float32) / 65535.0
    data = data.astype(np.float32)
    peak = float(data.max()) if data.size else 1.0
    if peak > 1.0:
        data = data / peak
    return np.clip(data, 0.0, 1.0)


def _analysis_copy(data: np.ndarray) -> np.ndarray:
    """A cheap subsample for the meters: percentiles do not need every pixel."""
    height, width = data.shape[:2]
    step = max(1, int(max(height, width) // ANALYSIS_MAX_SIDE))
    return data[::step, ::step]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def apply_geometry(data: np.ndarray, settings: RenderSettings) -> np.ndarray:
    """Crop, rotate and flip — the part of a recipe that is exact, not guessed."""
    result = data
    if settings.crop:
        x, y, w, h = settings.crop
        height, width = result.shape[:2]
        left = int(round(max(0.0, min(1.0, x)) * width))
        top = int(round(max(0.0, min(1.0, y)) * height))
        right = int(round(min(1.0, x + max(0.0, w)) * width))
        bottom = int(round(min(1.0, y + max(0.0, h)) * height))
        if right - left >= 8 and bottom - top >= 8:
            result = result[top:bottom, left:right]
    if settings.rotate_quarter_turns % 4:
        # numpy rotates counter-clockwise; a photo application means clockwise.
        result = np.rot90(result, k=-(settings.rotate_quarter_turns % 4))
    if settings.flip_horizontal:
        result = result[:, ::-1]
    if settings.flip_vertical:
        result = result[::-1, :]
    return np.ascontiguousarray(result)


# ---------------------------------------------------------------------------
# The render
# ---------------------------------------------------------------------------


def _normalized_log(data: np.ndarray, settings: RenderSettings) -> np.ndarray:
    """The scan as print exposure in [0, 1]: 0 prints white, 1 prints black.

    Per channel, because that is what defeats a colour negative's orange mask:
    each layer is stretched between its own bounds, so the mask — a constant
    offset in one channel — normalizes away with it.
    """
    linear = np.power(np.clip(data, EPSILON, 1.0), ASSUMED_INPUT_GAMMA)
    log_exposure = np.log10(np.clip(linear, EPSILON, 1.0))

    if settings.polarity == "mono" and log_exposure.ndim == 3:
        # A panchromatic negative collapses to one density before the curve, the
        # way paper sees it, instead of having three curves mixed afterwards.
        luma = (
            0.2126 * log_exposure[:, :, 0]
            + 0.7152 * log_exposure[:, :, 1]
            + 0.0722 * log_exposure[:, :, 2]
        )
        log_exposure = np.repeat(luma[:, :, None], 3, axis=2)

    sample = _analysis_copy(log_exposure)
    flat = sample.reshape(-1, sample.shape[2]) if sample.ndim == 3 else sample.reshape(-1, 1)
    low = np.percentile(flat, settings.low_percentile, axis=0)
    high = np.percentile(flat, settings.high_percentile, axis=0)
    span = np.maximum(high - low, 1e-4)

    normalized = (log_exposure - low) / span
    if settings.polarity == "positive":
        # A negative is already the right way round: clear film (a scene shadow)
        # passes the most light and so prints darkest. A positive has to be
        # flipped, so that its highlights print as highlights.
        normalized = 1.0 - normalized
    return np.clip(normalized, 0.0, 1.0).astype(np.float32)


def _anchor(exposure: np.ndarray, settings: RenderSettings) -> float:
    """Where the metered midtone sits, in print-exposure units (Auto Density).

    Meter the textured content — the average of the trimmed window's mean and its
    midpoint, so a skewed histogram is placed by its detail-bearing span rather
    than by its median — then pull the assumed key part of the way towards it and
    only so far.
    """
    if not settings.auto_density:
        return ASSUMED_ANCHOR
    values = _analysis_copy(exposure).reshape(-1)
    if values.size == 0:
        return ASSUMED_ANCHOR
    low, high = np.percentile(values, [5.0, 95.0])
    window = values[(values >= low) & (values <= high)]
    if window.size == 0:
        return ASSUMED_ANCHOR
    metered = 0.5 * (float(window.mean()) + 0.5 * (float(low) + float(high)))
    pulled = ASSUMED_ANCHOR + METER_STRENGTH * (metered - ASSUMED_ANCHOR)
    return float(np.clip(pulled, ASSUMED_ANCHOR - METER_BAND, ASSUMED_ANCHOR + METER_BAND))


def _base_slope(settings: RenderSettings) -> float:
    """Grade, as the literal H&D gamma: density range over exposure range."""
    grade_r = max(50.0, min(float(settings.grade_r or GRADE_DEFAULT_R), 180.0))
    return float(np.clip(GRADE_CONTRAST_SCALE / (grade_r / 100.0), SLOPE_MIN, SLOPE_MAX))


def _slope(exposure: Optional[np.ndarray], settings: RenderSettings) -> float:
    """The grade, matched to this frame's own textural range (Auto Grade).

    A printer picks the paper grade from how much of the scale the negative's
    *textured* tones occupy — not its extremes, which are rebate, dust and
    specular highlights. A flat frame gets a lift and a punchy one keeps its
    punch, and the overfill cap stops a very flat scan being pushed somewhere
    harsh. Turn Auto Density off and this goes with it: the grade is then exactly
    what the recipe (or the default) asks for.
    """
    slope = _base_slope(settings)
    if exposure is None or not settings.auto_density:
        return slope
    values = _analysis_copy(exposure).reshape(-1)
    if values.size == 0:
        return slope
    low, high = np.percentile(values, [10.0, 90.0])
    textural = float(high - low)
    if textural <= 1e-3:
        return slope
    ratio = NOMINAL_TEXTURAL_RANGE / textural
    factor = min(
        (1.0 - AUTO_GRADE_STRENGTH) + AUTO_GRADE_STRENGTH * ratio,
        AUTO_GRADE_MAX_OVERFILL * ratio,
    )
    return float(np.clip(slope * factor, SLOPE_MIN, SLOPE_MAX))


def print_curve(
    exposure: np.ndarray,
    settings: RenderSettings,
    anchor: float,
    slope: Optional[float] = None,
) -> np.ndarray:
    """Print exposure in [0, 1] → density, through a paper-like transfer curve.

    Straight line of slope ``k`` through the pivot, an anchor-preserving midtone
    S-curve, the two zone-density offsets, then the shoulder and toe as
    independent softplus knees, so each end of the scale rolls off on its own.
    """
    slope = _base_slope(settings) if slope is None else slope
    # The pivot is placed so the metered anchor prints at its target density.
    pivot = anchor - (ANCHOR_TARGET_DENSITY / slope)

    adjusted = exposure + settings.exposure_stops * STOP
    if any(settings.channel_offsets) and adjusted.ndim == 3:
        offsets = np.asarray(settings.channel_offsets, dtype=np.float32).reshape(1, 1, 3)
        adjusted = adjusted + offsets

    value = slope * (adjusted - pivot)

    # Split grade: rotate the curve about each zone centre, mid-sparing.
    for delta_r, centre_offset in (
        (settings.shadow_grade, ZONE_SHADOW_OFFSET),
        (settings.highlight_grade, ZONE_HIGHLIGHT_OFFSET),
    ):
        if delta_r:
            grade_r = max(50.0, min(float(settings.grade_r or GRADE_DEFAULT_R), 180.0))
            ratio = grade_r / max(grade_r + float(delta_r), 1.0)
            centre = ANCHOR_TARGET_DENSITY + centre_offset
            weight = sigmoid(ZONE_WEIGHT_K * (value - centre))
            if centre_offset < 0:
                weight = 1.0 - weight
            value = value + (ratio - 1.0) * weight * (value - centre)

    # The paper's own variable gamma, plus the user's trim, centred on the
    # reference tone so the anchor is preserved.
    gamma = PAPER_MIDTONE_GAMMA + float(settings.midtone_gamma or 0.0)
    if gamma:
        width = PAPER_GAMMA_WIDTH
        value = value + gamma * width * np.tanh((value - ANCHOR_TARGET_DENSITY) / width)

    # Zone density: a literal density offset at full zone weight, mid-sparing.
    if settings.shadow_density:
        centre = ANCHOR_TARGET_DENSITY + ZONE_SHADOW_OFFSET
        value = value + settings.shadow_density * sigmoid(ZONE_WEIGHT_K * (value - centre))
    if settings.highlight_density:
        centre = ANCHOR_TARGET_DENSITY + ZONE_HIGHLIGHT_OFFSET
        value = value + settings.highlight_density * (1.0 - sigmoid(ZONE_WEIGHT_K * (value - centre)))

    d_min = D_MIN if settings.paper_dmin else 0.0
    toe = float(settings.toe or 0.0) * SLIDER_SCALE
    shoulder = float(settings.shoulder or 0.0) * SLIDER_SCALE
    d_min_eff = d_min + shoulder * SHOULDER_HEIGHT_SCALE
    d_max_eff = D_MAX - toe * TOE_HEIGHT_SCALE

    sharp_hl = SHOULDER_SHARPNESS_BASE / max(float(settings.shoulder_width or 1.0), 0.1)
    sharp_sh = TOE_SHARPNESS_BASE / max(float(settings.toe_width or 1.0), 0.1)

    bounded = d_min_eff + softplus(sharp_hl * (value - d_min_eff)) / sharp_hl
    density = d_max_eff - softplus(sharp_sh * (d_max_eff - bounded)) / sharp_sh
    return density


def to_display(density: np.ndarray, settings: RenderSettings) -> np.ndarray:
    """Density → 8-bit RGB: ``10**-D``, black point compensation, then the OETF."""
    light = np.power(10.0, -density)
    if not settings.paper_black:
        # The adapted eye reads paper black as black, so the display should too.
        floor = 10.0 ** -D_MAX
        light = np.clip((light - floor) / (1.0 - floor), 0.0, 1.0)
    light = np.clip(light, 0.0, 1.0)
    encoded = np.power(light, 1.0 / OETF_POWER)
    return np.clip(encoded * 255.0 + 0.5, 0, 255).astype(np.uint8)


def render(image: np.ndarray, settings: Optional[RenderSettings] = None) -> np.ndarray:
    """A scan as a print. Input any RGB array; output 8-bit RGB, same geometry."""
    settings = settings or RenderSettings()
    data = _as_float(image)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    if data.shape[2] > 3:
        data = data[:, :, :3]
    data = apply_geometry(data, settings)
    exposure = _normalized_log(data, settings)
    anchor = _anchor(exposure, settings)
    slope = _slope(exposure, settings)
    density = print_curve(exposure, settings, anchor, slope)
    return to_display(density, settings)


def polarity_for(film_kind: Optional[str], image_type: str = "scan") -> str:
    """What the archive already knows about a frame decides how to print it.

    The film stock's kind is in the catalog, so a slide is not inverted, a
    black-and-white negative collapses to one density, and a contact sheet — a
    picture *of* frames, not one of them — is never inverted at all.
    """
    if image_type != "scan":
        return "positive"
    kind = (film_kind or "").strip().lower()
    if kind in {"slide", "positive"}:
        return "positive"
    if kind in {"black_and_white", "bw", "mono"}:
        return "mono"
    return "negative"


def describe(settings: RenderSettings) -> dict:
    """What the UI says about a render: never "this is your edit"."""
    return {
        "polarity": settings.polarity,
        "grade_r": settings.grade_r,
        "exposure_stops": settings.exposure_stops,
        "applied": list(settings.applied),
        "ignored": list(settings.ignored),
        "applied_count": len(settings.applied),
        "ignored_count": len(settings.ignored),
    }
