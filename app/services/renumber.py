"""Renumbering the frames of a roll (M7).

Frame numbers come from the scanner's filenames, from a person typing them in,
or from nowhere, and they go wrong in the same few ways every time: the
scanner counted from 0, a frame was deleted and left a gap, a 120 roll was
scanned back to front, or two files got the same number. Fixing that one cell
at a time is the kind of chore that makes an archive fall behind, so this
service computes a whole new numbering in one go — and the endpoint that calls
it can answer with the plan *without* applying it, so the UI shows "12 → 13"
for every frame before anything is written.

Four modes, all on the frames in their display order (frame number, then id):

* ``sequential``      — ``start``, ``start + step``, … in the current order.
                        Closes gaps, resolves duplicates, keeps the order.
* ``reverse``         — the same, walking the current order backwards. A roll
                        that was scanned tail first.
* ``shift``           — add ``offset`` to every numbered frame; an unnumbered
                        one stays unnumbered. The scanner that counts from 0.
* ``from_filenames``  — read the number out of each original filename again
                        (the same rule an upload uses); a file that yields
                        nothing keeps the number it has.

Duplicates are allowed in the archive — two scans of one negative are a real
thing — so a plan that produces them is not an error, but it is reported, and
the dialog says so before the button is pressed.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable, Iterable, List, Optional, Sequence

from ..errors import ApiError
from ..models import ImageAsset

MODES = ("sequential", "reverse", "shift", "from_filenames")


def plan(
    frames: Sequence[ImageAsset],
    mode: str,
    *,
    start: int = 1,
    step: int = 1,
    offset: int = 0,
    from_filename: Optional[Callable[[Optional[str]], Optional[int]]] = None,
) -> List[dict]:
    """``[{"id", "from", "to", "original_filename"}]``, one per frame, in the order given."""
    if mode not in MODES:
        raise ApiError("invalid_mode", f"Mode must be one of: {', '.join(MODES)}.", 400, "mode")
    if start < 0:
        raise ApiError("invalid_start", "The first frame number cannot be negative.", 400, "start")
    if step < 1:
        raise ApiError("invalid_step", "The step must be at least 1.", 400, "step")

    count = len(frames)
    out: List[dict] = []
    for index, frame in enumerate(frames):
        current = frame.frame_number
        if mode == "sequential":
            target: Optional[int] = start + index * step
        elif mode == "reverse":
            target = start + (count - 1 - index) * step
        elif mode == "shift":
            target = current + offset if current is not None else None
            if target is not None and target < 0:
                raise ApiError(
                    "negative_frame_number",
                    f"Shifting by {offset} would give frame {current} a negative number.",
                    400,
                    "offset",
                )
        else:  # from_filenames
            derived = from_filename(frame.original_filename) if from_filename else None
            target = derived if derived is not None else current
        out.append({"id": frame.id, "from": current, "to": target, "original_filename": frame.original_filename})
    return out


def duplicates(numbers: Iterable[Optional[int]]) -> List[int]:
    """The frame numbers that would be used more than once, ascending."""
    counts = Counter(n for n in numbers if n is not None)
    return sorted(n for n, c in counts.items() if c > 1)
