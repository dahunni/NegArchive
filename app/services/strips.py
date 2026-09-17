"""Strip and position arithmetic (roadmap M4).

A 35mm roll is cut into strips of six and slid into the rows of a sleeve page, so
"frame 14" is physically "strip 3, position 2". The sleeve layout gives the default
strip length; a roll can override it with an explicit list (``[5,5,5,5,5,5,6]`` for
a roll doubled up on an old five-per-row page). The cover sheet mirrors the same
grid so the paper lines up with the negatives behind it.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from ..errors import ApiError

DEFAULT_ROWS = 7
DEFAULT_PER_ROW = 6


def parse_strips(value) -> Optional[List[int]]:
    """``"6,6,6,6,6,6"`` or ``[6, 6, …]`` → a list of positive ints; empty → None."""
    if value is None:
        return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
        parts = [p for p in parts if p]
        if not parts:
            return None
        value = parts
    if not isinstance(value, (list, tuple)):
        raise ApiError("invalid_strips", "Strips must be a list of strip lengths like 6,6,6,6,6,6.", 400, "strips")
    strips: List[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError) as exc:
            raise ApiError("invalid_strips", "Every strip length must be a whole number.", 400, "strips") from exc
        if number < 1 or number > 40:
            raise ApiError("invalid_strips", "A strip holds between 1 and 40 frames.", 400, "strips")
        strips.append(number)
    if len(strips) > 40:
        raise ApiError("invalid_strips", "That is more strips than a page can hold.", 400, "strips")
    return strips or None


def default_strips(rows: int = DEFAULT_ROWS, per_row: int = DEFAULT_PER_ROW) -> List[int]:
    return [per_row] * max(1, rows)


def effective_strips(override: Optional[Sequence[int]], rows: Optional[int], per_row: Optional[int]) -> List[int]:
    """The strips a roll is laid out in: its own override, else the layout, else PrintFile."""
    if override:
        return [int(n) for n in override]
    return default_strips(rows or DEFAULT_ROWS, per_row or DEFAULT_PER_ROW)


def position(frame_number: Optional[int], strips: Sequence[int]) -> Optional[tuple[int, int]]:
    """``(strip, position)`` for a frame number, both 1-based; None when it does not fit.

    Frame 1 is the first frame of strip 1. A frame numbered 0 (some scanners) is
    treated as the frame before 1 and gets no position.
    """
    if frame_number is None or frame_number < 1:
        return None
    remaining = frame_number
    for index, length in enumerate(strips, start=1):
        if remaining <= length:
            return index, remaining
        remaining -= length
    return None


def grid(frames: Iterable[dict], strips: Sequence[int]) -> List[List[Optional[dict]]]:
    """Rows of cells mirroring the sleeve: each cell is the frame dict or None.

    ``frames`` are dicts with a ``frame_number``; unnumbered frames and frames past
    the last strip are not placed (the caller lists them separately).
    """
    by_number = {}
    for frame in frames:
        number = frame.get("frame_number")
        if number is not None and number not in by_number:
            by_number[number] = frame
    rows: List[List[Optional[dict]]] = []
    next_number = 1
    for length in strips:
        row = []
        for _ in range(length):
            row.append(by_number.get(next_number))
            next_number += 1
        rows.append(row)
    return rows


def capacity(strips: Sequence[int]) -> int:
    return sum(int(n) for n in strips)
