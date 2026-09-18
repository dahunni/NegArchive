"""Finding and reading the XMP packet in an image file (M5).

NegPy writes its per-frame metadata into XMP on export, in its own namespace
``https://negpy.app/ns/1.0/`` — ``negpy:CaptureRoll``, ``negpy:CaptureFrame``,
``negpy:CaptureFilmStock`` and the rest (docs/NEGPY_INTEGRATION.md). Where that
packet lives depends on the container:

===========  ==========================================================
JPEG / WebP  an APP1 / ``XMP `` segment; Pillow puts it in ``info["xmp"]``
PNG          an ``iTXt`` chunk; Pillow uses the key ``XML:com.adobe.xmp``
TIFF / DNG   tag 700, readable through ``Image.tag_v2``
===========  ==========================================================

so :func:`packet` tries all of them and returns bytes or nothing.

**Why this parses the XML itself.** Pillow's ``Image.getxmp()`` needs the
``defusedxml`` package and returns a nested dict shaped by the RDF nesting, which
is more work to read than the packet. ``xml.etree`` on its own is documented as
vulnerable to entity-expansion attacks ("billion laughs"), and an archive that
ingests files off a scanner's SMB share is exactly the wrong place to be relaxed
about that. So :func:`parse_namespace` refuses a packet that declares a DTD or an
entity at all, and refuses one that is implausibly large, before ``xml.etree``
ever sees it. A real XMP packet has neither.

A value can be written either as an attribute (``negpy:CaptureRoll="NEG-…"``) or
as a child element (``<negpy:CaptureRoll>NEG-…</negpy:CaptureRoll>``); both are
valid RDF and both are read here, attribute first.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Dict, Optional

#: NegPy's XMP namespace, from ``negpy/features/metadata/xmp.py``.
NEGPY_NS = "https://negpy.app/ns/1.0/"

#: Namespaces worth reading beyond NegPy's own.
PHOTOSHOP_NS = "http://ns.adobe.com/photoshop/1.0/"
EXIF_NS = "http://ns.adobe.com/exif/1.0/"
TIFF_NS = "http://ns.adobe.com/tiff/1.0/"
XMP_NS = "http://ns.adobe.com/xap/1.0/"
DC_NS = "http://purl.org/dc/elements/1.1/"

#: TIFF tag holding the XMP packet.
TIFF_XMP_TAG = 700

#: Nothing legitimate is bigger than this, and anything bigger is not worth parsing.
MAX_PACKET_BYTES = 4 * 1024 * 1024

#: A packet carrying either of these is refused unparsed (see the module docstring).
_FORBIDDEN = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


def _as_bytes(value) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8", "replace")
    if isinstance(value, (tuple, list)) and value:  # TIFF tags arrive as tuples
        return _as_bytes(value[0])
    return None


def packet_from_image(image) -> Optional[bytes]:
    """The XMP packet of an already-open :class:`PIL.Image.Image`, if it has one."""
    info = getattr(image, "info", {}) or {}
    for key in ("xmp", "XML:com.adobe.xmp", "Raw profile type xmp"):
        found = _as_bytes(info.get(key))
        if found:
            return found
    tags = getattr(image, "tag_v2", None)
    if tags is not None:
        try:
            return _as_bytes(tags.get(TIFF_XMP_TAG))
        except Exception:  # noqa: BLE001 - a broken tag directory is not our problem
            return None
    return None


def packet(path: str | Path) -> Optional[bytes]:
    """The XMP packet of the file at ``path``, or ``None``.

    Never raises: an unreadable file, a format Pillow cannot open (a DNG from an
    unusual camera, say) and a file with no XMP are all simply "no metadata".
    """
    try:
        from PIL import Image as PILImage

        with PILImage.open(str(path)) as image:
            return packet_from_image(image)
    except Exception:  # noqa: BLE001 - see docstring
        return None


def parse_namespace(data: Optional[bytes], namespace: str = NEGPY_NS) -> Dict[str, str]:
    """Every property of ``namespace`` in an XMP packet, as ``{local name: value}``.

    Returns ``{}`` for anything that is not a parseable, safe XMP packet.
    """
    if not data:
        return {}
    if len(data) > MAX_PACKET_BYTES or _FORBIDDEN.search(data):
        return {}

    # Trim the xpacket processing instructions: some writers put trailing padding
    # after the closing one, which is not well-formed XML on its own.
    start = data.find(b"<x:xmpmeta")
    if start < 0:
        start = data.find(b"<rdf:RDF")
    if start > 0:
        data = data[start:]
    end = max(data.rfind(b"</x:xmpmeta>") + len(b"</x:xmpmeta>"), data.rfind(b"</rdf:RDF>") + len(b"</rdf:RDF>"))
    if end > 0:
        data = data[:end]

    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return {}

    prefix = "{" + namespace + "}"
    found: Dict[str, str] = {}
    for element in root.iter():
        for name, value in element.attrib.items():
            if name.startswith(prefix):
                text = str(value).strip()
                if text:
                    found.setdefault(name[len(prefix):], text)
        if element.tag.startswith(prefix):
            text = _element_text(element)
            if text:
                found.setdefault(element.tag[len(prefix):], text)
    return found


def _element_text(element) -> str:
    """The text of an XMP property element, flattening ``rdf:Alt``/``rdf:Seq``."""
    direct = (element.text or "").strip()
    if direct:
        return direct
    for child in element.iter():
        if child is element:
            continue
        text = (child.text or "").strip()
        if text:
            return text
    return ""
