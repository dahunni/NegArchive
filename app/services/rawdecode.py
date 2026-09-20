"""Camera raw files — the scans NegPy's camera-scanning mode produces.

NegPy's *Live View & Scan* (its ``docs/CAMERA_SCANNING.md``) photographs a negative
with a tethered camera and saves **the camera's own raw file, untouched**, as
``<roll>_Frame001.ARW`` in a per-roll folder. No conversion, no sidecar, no
metadata: the raw *is* the scan. So the archive has to accept raws and show them,
and neither of its decoders can: Pillow opens a Sony ARW as a TIFF and stops at
"Invalid dimensions", OpenCV returns ``None``. LibRaw can, through ``rawpy``.

Two decodes, because two different questions get asked of a raw:

* :func:`embedded_preview` — the JPEG the camera stored inside the file. No
  demosaic, so it costs nothing; full size on most bodies; and it is what the
  photographer saw on the back of the camera — the negative, orange mask and all.
  Used when a frame is served *raw*, and for contact sheets.
* :func:`decode_linear` — a half-size demosaic to 16-bit **linear** RGB with the
  camera's white balance, no auto-brightening and no gamma. That is what
  :mod:`app.services.preview` wants: it takes the log of the pixels itself, and
  handing it a gamma-encoded JPEG would print the negative through two curves.
  Measured on a 28 MP ARW: 0.24 s, then the print renderer at preview width.

``rawpy`` is in the image (``requirements.txt``) but is a *soft* dependency here:
:func:`available` says whether it imported, and every caller falls back to the
generic decoders and their honest 415 rather than a 500. A laptop running the API
without it still serves every JPEG and TIFF it did before.

**Which extensions.** The still-camera formats LibRaw reads and NegPy lists in
``negpy/infrastructure/loaders/constants.py``, minus the video containers
(``.braw``, ``.r3d``) and the vendor leftovers nobody camera-scans film with. Kept
the same shape as NegPy's on purpose: a folder NegPy can open, the archive can link.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Optional, Tuple

#: Camera raw extensions the archive accepts, as ``.ext`` in lower case.
RAW_EXTENSIONS = frozenset(
    {
        ".3fr",  # Hasselblad
        ".arw", ".sr2", ".srf",  # Sony
        ".cr2", ".cr3", ".crw",  # Canon
        ".dcr", ".kdc",  # Kodak
        ".dng",  # Adobe, and every phone and scanner that writes it
        ".erf",  # Epson
        ".fff",  # Hasselblad / Imacon
        ".iiq",  # Phase One
        ".mef", ".mos",  # Mamiya / Leaf
        ".mrw",  # Minolta
        ".nef", ".nrw",  # Nikon
        ".orf",  # Olympus
        ".pef",  # Pentax
        ".raf",  # Fujifilm
        ".raw",  # Panasonic and Leica, the old one
        ".rw2", ".rwl",  # Panasonic, Leica
        ".srw",  # Samsung
        ".x3f",  # Sigma
    }
)

#: The ones worth naming in an error message. The full list is for the parser.
RAW_EXAMPLES = ("arw", "nef", "cr2", "cr3", "raf", "orf", "rw2", "pef")

#: ``(offset, bytes)`` signatures of the raws that are *not* TIFF underneath. Most
#: raws (ARW, NEF, CR2, DNG, PEF, SRW, 3FR, …) are TIFF files with private tags
#: and carry the TIFF magic the upload sniff already knows. These do not; the
#: offsets and strings are the ones LibRaw's ``identify()`` compares.
RAW_MAGIC: Tuple[Tuple[int, bytes], ...] = (
    (0, b"FUJIFILM"),  # RAF
    (0, b"\x00MRM"),  # MRW
    (0, b"FOVb"),  # X3F
    (4, b"ftypcrx "),  # CR3, an ISO base media file
    (6, b"HEAPCCDR"),  # CRW, Canon's CIFF
    (0, b"IIRO"),  # ORF, little-endian
    (0, b"IIRS"),  # ORF, the SP series
    (0, b"MMOR"),  # ORF, big-endian
    (0, b"IIU\x00"),  # RW2 / RWL: TIFF with 0x55 where 0x2a should be
)

#: How many leading bytes a sniff needs to see every signature above.
SNIFF_BYTES = 16


def is_raw_name(name: str) -> bool:
    return Path(str(name or "")).suffix.lower() in RAW_EXTENSIONS


def looks_like_raw(head: bytes) -> bool:
    """Do these leading bytes belong to a non-TIFF camera raw?

    TIFF-based raws are the caller's business (they pass the TIFF check); this is
    only for the formats with a magic of their own.
    """
    return any(head[offset : offset + len(magic)] == magic for offset, magic in RAW_MAGIC)


# ---------------------------------------------------------------------------
# rawpy, imported once and only when asked for
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_rawpy = None
_probed = False


def _module():
    global _rawpy, _probed
    if _probed:
        return _rawpy
    with _lock:
        if not _probed:
            try:
                import rawpy  # noqa: PLC0415 - optional at runtime, see module docstring

                _rawpy = rawpy
            except Exception:  # noqa: BLE001 - missing wheel, broken LibRaw: same answer
                _rawpy = None
            _probed = True
    return _rawpy


def available() -> bool:
    return _module() is not None


def version() -> Optional[str]:
    module = _module()
    if module is None:
        return None
    try:
        libraw = ".".join(str(part) for part in module.libraw_version)
    except Exception:  # noqa: BLE001
        libraw = "?"
    return f"rawpy {module.__version__} / LibRaw {libraw}"


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def embedded_preview(path: str | Path) -> Optional[bytes]:
    """The camera's own JPEG from inside the raw, or ``None`` if there is none.

    Some bodies store a bitmap instead of a JPEG; that is treated as "none",
    because a demosaic is cheaper than encoding somebody's uncompressed thumbnail.
    """
    module = _module()
    if module is None:
        return None
    try:
        with module.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
    except Exception:  # noqa: BLE001 - LibRaw has a dozen thumbnail errors; all mean "none"
        return None
    if getattr(thumb, "format", None) == module.ThumbFormat.JPEG:
        return bytes(thumb.data)
    return None


def decode_linear(path: str | Path, max_width: Optional[int] = None):
    """The raw as 16-bit linear RGB (H×W×3 ``uint16``), camera white balance applied.

    Always a half-size demosaic: a preview is never wider than 6000 px and the
    sensors this sees are 24–60 MP, so full size would only make the request slower.
    ``max_width`` shrinks the result further with an area filter, so the print
    renderer downstream works on the pixels that will actually be shown.

    Raises whatever LibRaw raises; callers decide what a failure means.
    """
    module = _module()
    if module is None:
        raise RuntimeError("rawpy is not installed")
    import numpy as np  # noqa: PLC0415

    with module.imread(str(path)) as raw:
        rgb = raw.postprocess(
            half_size=True,
            use_camera_wb=True,
            no_auto_bright=True,
            output_bps=16,
            gamma=(1, 1),
            user_flip=0,  # the recipe owns rotation (M5); the camera's tag does not
        )
    array = np.asarray(rgb, dtype=np.uint16)
    if max_width and array.shape[1] > max_width:
        import cv2  # noqa: PLC0415

        height = max(1, int(array.shape[0] * (max_width / array.shape[1])))
        array = cv2.resize(array, (int(max_width), height), interpolation=cv2.INTER_AREA)
    return array


def pil_image(path: str | Path, max_width: Optional[int] = None):
    """The raw as an 8-bit RGB Pillow image, for showing rather than printing.

    The embedded JPEG when there is one; otherwise the linear demosaic with a plain
    2.2 gamma so it looks like a photograph of a negative and not like a black
    rectangle with a faint orange glow.
    """
    from PIL import Image  # noqa: PLC0415

    data = embedded_preview(path)
    if data:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    else:
        import numpy as np  # noqa: PLC0415

        linear = decode_linear(path, max_width)
        top = float(linear.max()) or 1.0
        encoded = np.power(linear.astype(np.float32) / top, 1.0 / 2.2)
        image = Image.fromarray(np.clip(encoded * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="RGB")
    if max_width and image.width > max_width:
        height = max(1, int(image.height * (max_width / image.width)))
        image = image.resize((int(max_width), height), Image.LANCZOS)
    return image
