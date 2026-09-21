"""The recommended NegPy export filename, and how to read one back (M5).

NegPy renders export filenames from a template
(``negpy/services/export/templating.py``). The pattern NegArchive recommends, and
the one it publishes in Settings, is::

    {{ roll }}_{{ frame|pad(3) }}_{{ film }}

which produces ``NEG-2026-0007_012_HP5 Plus.tif``. Three fields in one name, in an
order that sorts correctly in every file browser, and it survives the trip through
a converter that drops EXIF and XMP — which is the whole point: **the filename is
the metadata of last resort.**

Parsing it is deliberately stricter than :func:`app.routers.api.frame_number_from_filename`,
which takes the last number in the name. That rule is right for a scanner dump and
wrong here: ``NEG-2026-0007_012_Tri-X 400.tif`` ends in ``400``, and a roll where
every frame is number 400 is worse than a roll with no frame numbers at all. So a
name is only read as a preset name when the whole shape matches: something, an
underscore, one to four digits, an underscore, something.

And the "something" on the right has to look like a film: **it must contain a
letter.** Strictness in the shape alone was not enough, because NegPy's export
templating replaces the hyphens in a roll name with underscores, so the serial
``NEG-2026-0001`` reaches the archive as ``NEG_2026_0001_001.jpg`` — a name in
which the *roll* now contains the preset's own separator. Read by shape alone that
is roll ``NEG``, frame ``2026``, film ``0001_001``, and a whole roll arrives filed
as frame 2026. No film stock is called ``0001_001``; requiring a letter throws the
candidate out, the name falls through to the ``<roll>_<frame>`` rule below, and the
frame is 1 as it should be.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

#: What to set as NegPy's ``filename_pattern``. Shown in Settings and in the docs.
FILENAME_PATTERN = "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"

#: Every ``_<1–4 digits>_`` boundary in a stem is a candidate frame number; the
#: roll is what comes before it and the film what comes after.
_BOUNDARY = re.compile(r"_(?P<frame>\d{1,4})_")

#: ``<roll>_<frame>`` with no film part, which is what ``{{ roll }}_{{ frame|pad(3) }}``
#: produces and what most scanner software writes anyway.
_ROLL_FRAME = re.compile(r"^(?P<roll>\S.*?)_(?P<frame>\d{1,4})$")

#: One letter, in any alphabet. What tells a film name from a run of digits that
#: is really part of the roll's serial.
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _split_preset(stem: str) -> Optional[tuple[str, int, str]]:
    """``(roll, frame, film)`` for ``<roll>_<frame>_<film>``, or None.

    A roll name may itself carry an underscore and a number (``Trip_2024_Kyoto``),
    and so may a film (``Kodak_400_TX``), so the frame is not simply the first or
    the last numeric group. The preset pads the frame to three digits, so a
    three-digit group is preferred; among equals, the first wins — the roll is
    the part people write by hand, the film comes from a catalog.

    A candidate whose film part has no letter in it is not a candidate at all:
    ``NEG_2026_0001_001`` splits into roll ``NEG``, frame ``2026``, film
    ``0001_001``, and there is no such film. Dropping it is what stops an
    underscored serial from turning a whole roll into frame 2026.
    """
    candidates = []
    for match in _BOUNDARY.finditer(stem):
        roll, film = stem[: match.start()].strip(), stem[match.end() :].strip()
        if roll and film and _LETTER.search(film):
            candidates.append((match.group("frame"), roll, film))
    if not candidates:
        return None
    preferred = [c for c in candidates if len(c[0]) == 3] or candidates
    digits, roll, film = preferred[0]
    return roll, int(digits), film


@dataclass(frozen=True)
class ParsedName:
    """What a filename claims about the frame inside it."""

    roll: Optional[str] = None
    frame_number: Optional[int] = None
    film: Optional[str] = None

    def __bool__(self) -> bool:
        return any((self.roll, self.frame_number is not None, self.film))


def parse(filename: Optional[str]) -> ParsedName:
    """Read ``NEG-2026-0007_012_HP5 Plus.tif`` as roll, frame and film.

    Returns an empty :class:`ParsedName` — which is falsy — for a name that does
    not have the preset's shape. It never guesses: a name this cannot read is left
    to the looser scanner-filename rule instead.
    """
    if not filename:
        return ParsedName()
    stem = os.path.splitext(os.path.basename(str(filename)))[0].strip()
    if not stem:
        return ParsedName()

    preset = _split_preset(stem)
    if preset:
        roll, frame, film = preset
        return ParsedName(roll=roll or None, frame_number=frame, film=film or None)
    match = _ROLL_FRAME.match(stem)
    if match:
        return ParsedName(roll=match.group("roll").strip() or None, frame_number=int(match.group("frame")))
    return ParsedName()
