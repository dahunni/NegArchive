"""``.negpy`` sidecars: knowing that a scan has been edited, and roughly how (M5).

NegPy keeps its edits in ``<user dir>/edits.db`` keyed by content hash, and can
additionally write a JSON **sidecar** next to the source file
(``negpy/services/assets/sidecar.py``). The sidecar is the part NegArchive can
use: it travels with the file, it is plain JSON, and it is the difference between
"there is a TIFF" and "there is a TIFF *and somebody has already worked on it*".

NegArchive does not interpret the recipe. It does not know what NegPy's curve
points mean and it must not pretend to: a film archive that renders somebody
else's edit badly is worse than one that does not render it at all. What it does
is much smaller and stays true as NegPy's settings evolve:

* record **that** a sidecar exists, and when it was last written;
* keep the parsed JSON, so nothing is lost;
* summarise it into a handful of human sentences — "23 settings · inverted ·
  cropped · white balance 5200 K" — by looking only at keys whose meaning is
  obvious from their name, and counting the rest.

Both sidecar spellings are accepted, because NegPy has used both next to a file
called ``scan_001.tif``::

    scan_001.tif.negpy      (extension appended)
    scan_001.negpy          (extension replaced)

A sidecar is data, never a command: nothing in it can change where a file lives,
what it is called, or which roll it belongs to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

#: The extension NegPy uses.
SUFFIX = ".negpy"

#: Sidecars are small. A "sidecar" that is not is not one.
MAX_SIDECAR_BYTES = 4 * 1024 * 1024

#: Keys whose meaning is plain enough to put in a one-line summary, and how to say
#: it. The value is a function of the setting's value, or ``None`` to just name it.
_PLAIN_KEYS: Dict[str, str] = {
    "invert": "inverted",
    "inverted": "inverted",
    "crop": "cropped",
    "rotation": "rotated",
    "rotate": "rotated",
    "flip": "flipped",
    "white_balance": "white balance",
    "temperature": "temperature",
    "exposure": "exposure",
    "contrast": "contrast",
    "saturation": "saturation",
    "curve": "curve",
    "curves": "curve",
    "film_stock": "film stock",
    "base_color": "film base",
    "dust_removal": "dust removal",
    "sharpening": "sharpening",
    "grain": "grain",
}


@dataclass
class Sidecar:
    """One parsed ``.negpy`` file."""

    path: str
    edited_at: Optional[datetime] = None
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def settings(self) -> Dict[str, Any]:
        """The settings block, wherever this version of NegPy puts it."""
        for key in ("settings", "settings_json", "edit", "edits", "recipe"):
            value = self.data.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError):
                    continue
                if isinstance(parsed, dict):
                    return parsed
        # A sidecar that *is* the settings object, with no wrapper.
        return {k: v for k, v in self.data.items() if k not in {"version", "file_path", "file_hash", "saved_at", "updated_at"}}

    def summary(self) -> str:
        """One line a person can read, e.g. ``12 settings · inverted · cropped``."""
        settings = self.settings
        if not settings:
            return "edited in NegPy"
        named: List[str] = []
        for key, label in _PLAIN_KEYS.items():
            if key in settings and _is_set(settings[key]) and label not in named:
                named.append(label)
        count = sum(1 for value in settings.values() if _is_set(value))
        parts = [f"{count} setting{'s' if count != 1 else ''}"] if count else []
        parts.extend(named[:4])
        return " · ".join(parts) or "edited in NegPy"

    def to_dict(self) -> Dict[str, Any]:
        """What is stored on the frame and shown in the viewer."""
        return {
            "path": self.path,
            "edited_at": self.edited_at.isoformat() if self.edited_at else None,
            "summary": self.summary(),
            "setting_count": sum(1 for value in self.settings.values() if _is_set(value)),
            "file_hash": self.data.get("file_hash") or self.data.get("hash"),
            "version": self.data.get("version"),
            "settings": self.settings,
        }


def _is_set(value: Any) -> bool:
    """Is this setting actually doing something?

    ``false``, ``null``, ``0``, ``""`` and empty containers are NegPy's defaults
    for "off", so counting them would make every untouched file look edited.
    """
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) > 0
    return True


def candidates(image_path: str | Path) -> List[Path]:
    """The two places a sidecar for ``image_path`` may be, in preference order."""
    target = Path(image_path)
    return [
        target.with_name(target.name + SUFFIX),
        target.with_suffix(SUFFIX),
    ]


def find(image_path: str | Path) -> Optional[Path]:
    """The sidecar next to ``image_path``, if there is one."""
    for candidate in candidates(image_path):
        try:
            if candidate.is_file():
                return candidate
        except OSError:  # pragma: no cover - unreadable directory
            continue
    return None


def is_sidecar_name(filename: Optional[str]) -> bool:
    return bool(filename) and str(filename).lower().endswith(SUFFIX)


def image_stem(filename: str) -> str:
    """``scan_001.tif.negpy`` and ``scan_001.negpy`` both belong to ``scan_001``."""
    name = Path(str(filename)).name
    if name.lower().endswith(SUFFIX):
        name = name[: -len(SUFFIX)]
    return Path(name).stem if Path(name).suffix else name


def read(path: str | Path) -> Optional[Sidecar]:
    """Parse a sidecar file. ``None`` when it is missing, huge or not JSON."""
    target = Path(path)
    try:
        if not target.is_file() or target.stat().st_size > MAX_SIDECAR_BYTES:
            return None
        raw = target.read_text(encoding="utf-8", errors="replace")
        edited_at = datetime.utcfromtimestamp(target.stat().st_mtime)
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    stated = data.get("saved_at") or data.get("updated_at") or data.get("modified_at")
    if isinstance(stated, str):
        try:
            edited_at = datetime.fromisoformat(stated.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return Sidecar(path=str(target), edited_at=edited_at, data=data)


def read_for(image_path: str | Path) -> Optional[Sidecar]:
    """:func:`read` the sidecar belonging to an image, if it has one."""
    found = find(image_path)
    return read(found) if found else None
