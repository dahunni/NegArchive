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
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

#: What to set as NegPy's ``filename_pattern``. Shown in Settings and in the docs.
FILENAME_PATTERN = "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"

#: ``<roll>_<frame>_<film>``. The roll part is non-greedy so the *first* numeric
#: group that is followed by another underscore wins: ``NEG-2026-0007_012_HP5``
#: gives roll ``NEG-2026-0007`` and frame 12, never roll ``NEG`` and frame 2026.
_PRESET = re.compile(r"^(?P<roll>\S.*?)_(?P<frame>\d{1,4})_(?P<film>\S.*)$")

#: ``<roll>_<frame>`` with no film part, which is what ``{{ roll }}_{{ frame|pad(3) }}``
#: produces and what most scanner software writes anyway.
_ROLL_FRAME = re.compile(r"^(?P<roll>\S.*?)_(?P<frame>\d{1,4})$")


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

    match = _PRESET.match(stem)
    if match:
        return ParsedName(
            roll=match.group("roll").strip() or None,
            frame_number=int(match.group("frame")),
            film=match.group("film").strip() or None,
        )
    match = _ROLL_FRAME.match(stem)
    if match:
        return ParsedName(roll=match.group("roll").strip() or None, frame_number=int(match.group("frame")))
    return ParsedName()
