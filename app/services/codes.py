"""Codes on paper and what they mean when scanned (roadmap M4).

Two symbologies, two jobs:

* **QR** carries a URL, so a phone camera opens the roll or the location. Content:
  ``{public base}/s/{serial}`` for a roll, ``{public base}/l/{id}`` for a location.
* **Code128** carries the bare token, so a USB/Bluetooth scanner typing into the
  focused search box opens it on the PC: the serial for a roll, ``LOC-<id>`` for a
  location, ``CMD-<verb>`` for a printable command card.

:func:`parse_token` is the one grammar every scan goes through, whichever way it
arrived (camera, wedge scanner, typed).
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urlparse

#: Commands a scanner can issue from the printable command sheet.
COMMANDS = {
    "LOOKUP": "Look up: the next code opens the roll or location.",
    "MOVE": "Move: scan one or more rolls, then the destination.",
    "STATUS-LOADED": "Set status: in camera.",
    "STATUS-SHOT": "Set status: shot.",
    "STATUS-ATLAB": "Set status: at the lab.",
    "STATUS-BACK": "Set status: back from the lab.",
    "STATUS-SCANNED": "Set status: scanned.",
    "STATUS-SLEEVED": "Set status: sleeved.",
    "PRINTED": "Mark the roll's label as printed.",
    "DONE": "Finish the current sequence.",
    "CANCEL": "Cancel the current sequence.",
}

_LOCATION = re.compile(r"^(?:LOC|L)-?(\d+)$", re.IGNORECASE)
_COMMAND = re.compile(r"^CMD-([A-Z][A-Z-]*)$", re.IGNORECASE)
_SERIAL_LIKE = re.compile(r"^[A-Z0-9]{1,10}-\d{4}-\d{1,6}$", re.IGNORECASE)


def parse_token(raw: str) -> dict:
    """Classify a scanned string.

    Returns ``{"kind": "roll", "serial": …}``, ``{"kind": "location", "id": …}``,
    ``{"kind": "command", "command": …}`` or ``{"kind": "unknown", "text": …}``.
    URLs printed in QR codes are unwrapped first.
    """
    text = (raw or "").strip()
    if not text:
        return {"kind": "unknown", "text": ""}

    # A QR code carries a URL; take the path part.
    if "://" in text or text.startswith("/"):
        try:
            path = urlparse(text).path if "://" in text else text
        except ValueError:
            path = text
        parts = [unquote(p) for p in path.split("/") if p]
        if len(parts) >= 2 and parts[-2] in ("s", "films"):
            text = parts[-1]
        elif len(parts) >= 2 and parts[-2] in ("l", "locations"):
            text = f"LOC-{parts[-1]}"
        elif parts:
            text = parts[-1]

    command = _COMMAND.match(text)
    if command:
        verb = command.group(1).upper()
        return {"kind": "command", "command": verb, "known": verb in COMMANDS}
    location = _LOCATION.match(text)
    if location:
        return {"kind": "location", "id": int(location.group(1))}
    if _SERIAL_LIKE.match(text):
        return {"kind": "roll", "serial": text.upper()}
    # Anything else is tried as a serial too — the archive may use a foreign scheme.
    return {"kind": "roll", "serial": text.upper(), "loose": True}


def qr_svg(text: str, scale: int = 4, border: int = 1) -> str:
    """A QR code as inline SVG, stroke ``currentColor`` so it follows the page colour."""
    import segno

    code = segno.make(text, error="m")
    return code.svg_inline(scale=scale, border=border).replace('stroke="#000"', 'stroke="currentColor"')


def code128_svg(text: str, module_height: float = 12.0, module_width: float = 0.3, show_text: bool = True) -> str:
    """A Code128 barcode as SVG. Text is limited to what a scanner will type back."""
    import barcode
    from barcode.writer import SVGWriter

    clean = re.sub(r"[^\x20-\x7e]", "", text or "")[:60] or "-"
    writer = SVGWriter()
    symbol = barcode.get("code128", clean, writer=writer)
    options = {
        "module_height": module_height,
        "module_width": module_width,
        "quiet_zone": 2.0,
        "font_size": 8,
        "text_distance": 3.0,
        "write_text": show_text,
    }
    payload = symbol.render(options)
    svg = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
    # Strip the XML prologue so the document can be inlined in HTML.
    svg = re.sub(r"^<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r"<!DOCTYPE[^>]*>\s*", "", svg)
    return svg


def roll_url(base: Optional[str], serial: str) -> str:
    return f"{(base or '').rstrip('/')}/s/{serial}"


def location_url(base: Optional[str], location_id: int) -> str:
    return f"{(base or '').rstrip('/')}/l/{location_id}"
