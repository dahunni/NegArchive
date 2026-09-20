"""Reading a scan's own metadata, and writing it onto the frame (M5).

A file exported from NegPy already knows what NegArchive spends a whole UI asking
for: which roll it belongs to, which frame it is, when it was taken, on what
camera, through which lens, on which film. It is in the file — standard EXIF plus
NegPy's ``negpy:`` XMP namespace (docs/NEGPY_INTEGRATION.md). This module reads
it and fills the blanks in.

Three sources, in this order of authority:

1. **XMP** ``negpy:CaptureRoll`` / ``CaptureFrame`` / ``CaptureFilmStock`` / … —
   what the photographer typed into NegPy, so it wins;
2. **EXIF** ``Make``, ``Model``, ``LensModel``, ``ISOSpeedRatings``,
   ``DateTimeOriginal`` — what the scanner or the converter passed through;
3. the **filename**, parsed as the recommended export preset
   (:mod:`app.services.negpy.naming`) — the metadata of last resort.

**Ingest never overwrites.** It fills a field that is empty and leaves every field
a person has touched exactly as it is; a re-ingest of the same file therefore
changes nothing the second time. That is the whole contract, and it is why this
can run automatically on every upload: the archive is the system of record for the
physical roll, and a file can inform it but never correct it.

Gear is **matched**, not invented, unless the ``negpy_create_gear`` setting says
otherwise: a scan that names a camera the catalog does not have records the name
(it is kept in ``capture_metadata``) and leaves the roll's gear alone, rather than
filling the Gear page with near-duplicates of entries that are already there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...models import Camera, FilmKind, FilmRoll, FilmStock, ImageAsset, ImageType, Lens
from .. import serials, settings_store
from . import edits as edits_mod
from . import naming
from . import sidecar as sidecar_mod
from .xmp import DC_NS, EXIF_NS, NEGPY_NS, PHOTOSHOP_NS, TIFF_NS, XMP_NS, packet, parse_namespace

#: EXIF tag numbers, spelled out so the reads below stay legible.
EXIF_MAKE = 271
EXIF_MODEL = 272
EXIF_DATETIME = 306
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME_DIGITIZED = 36868
EXIF_LENS_MODEL = 42036
EXIF_LENS_MAKE = 42035
EXIF_ISO = 34855
EXIF_USER_COMMENT = 37510
EXIF_IMAGE_DESCRIPTION = 270


@dataclass
class FrameMetadata:
    """What a file says about itself. Every field is optional; most files have few."""

    roll: Optional[str] = None
    frame_number: Optional[int] = None
    capture_date: Optional[date] = None
    camera: Optional[str] = None
    lens: Optional[str] = None
    film_stock: Optional[str] = None
    film_manufacturer: Optional[str] = None
    film_iso: Optional[int] = None
    developer: Optional[str] = None
    dilution: Optional[str] = None
    push_pull: Optional[str] = None
    development_time: Optional[str] = None
    notes: Optional[str] = None
    #: Which of "xmp", "exif", "filename" contributed anything.
    sources: List[str] = field(default_factory=list)
    #: Everything that was read, verbatim, for the record and for the UI.
    raw: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.sources)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "roll": self.roll,
            "frame_number": self.frame_number,
            "capture_date": self.capture_date.isoformat() if self.capture_date else None,
            "camera": self.camera,
            "lens": self.lens,
            "film_stock": self.film_stock,
            "film_manufacturer": self.film_manufacturer,
            "film_iso": self.film_iso,
            "developer": self.developer,
            "dilution": self.dilution,
            "push_pull": self.push_pull,
            "development_time": self.development_time,
            "notes": self.notes,
            "sources": list(self.sources),
            "raw": dict(self.raw),
        }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().strip("\x00").strip()
    return text or None


def _int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


_DATE_PATTERNS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y:%m:%d")


def _date(value: Any) -> Optional[date]:
    """An EXIF or XMP date-time in any of the spellings those two standards allow."""
    text = _clean(value)
    if not text:
        return None
    text = text.split("+")[0].split("Z")[0].strip()
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(pattern))], pattern).date()
        except ValueError:
            continue
    # Last resort: a leading ISO date inside something longer.
    match = re.match(r"(\d{4})[:-](\d{2})[:-](\d{2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    return None


def camera_name(make: Optional[str], model: Optional[str]) -> Optional[str]:
    """``"NIKON CORPORATION"`` + ``"NIKON F5"`` → ``"NIKON F5"``, not ``"NIKON …"``.

    Cameras write the manufacturer into both fields more often than not, so the
    make is only prepended when the model does not already start with the first
    word of it.
    """
    make = _clean(make)
    model = _clean(model)
    if not model:
        return make
    if not make:
        return model
    first = make.split()[0].lower()
    if model.lower().startswith(first):
        return model
    return f"{make} {model}"


def _exif_values(path: str | Path) -> Dict[str, Any]:
    """The handful of EXIF tags this archive cares about, as plain values."""
    try:
        from PIL import Image as PILImage

        with PILImage.open(str(path)) as image:
            exif = image.getexif()
            if not exif:
                return {}
            sub = {}
            try:
                sub = dict(exif.get_ifd(EXIF_IFD) or {})
            except Exception:  # noqa: BLE001 - a malformed sub-IFD is not fatal
                sub = {}
            merged = {**dict(exif), **sub}
    except Exception:  # noqa: BLE001 - unreadable or unsupported file
        return {}

    found: Dict[str, Any] = {}
    for key, tag in (
        ("Make", EXIF_MAKE),
        ("Model", EXIF_MODEL),
        ("LensMake", EXIF_LENS_MAKE),
        ("LensModel", EXIF_LENS_MODEL),
        ("ISOSpeedRatings", EXIF_ISO),
        ("DateTimeOriginal", EXIF_DATETIME_ORIGINAL),
        ("DateTimeDigitized", EXIF_DATETIME_DIGITIZED),
        ("DateTime", EXIF_DATETIME),
        ("ImageDescription", EXIF_IMAGE_DESCRIPTION),
    ):
        value = merged.get(tag)
        cleaned = _clean(value) if not isinstance(value, (int, float)) else value
        if cleaned not in (None, ""):
            found[key] = cleaned
    return found


def read(path: str | Path, filename: Optional[str] = None) -> FrameMetadata:
    """Everything :mod:`app.services.negpy` can learn about the file at ``path``.

    ``filename`` is the *original* name (an upload stores the file under a UUID),
    which is what the preset parser is given.
    """
    meta = FrameMetadata()
    target = Path(path)

    negpy = parse_namespace(packet(target), NEGPY_NS)
    if negpy:
        meta.sources.append("xmp")
        meta.raw["negpy"] = dict(negpy)
        meta.roll = _clean(negpy.get("CaptureRoll"))
        meta.frame_number = _int(negpy.get("CaptureFrame"))
        meta.camera = camera_name(negpy.get("CaptureCameraMake"), negpy.get("CaptureCameraModel"))
        meta.lens = _clean(negpy.get("CaptureLensModel")) or _clean(negpy.get("CaptureLens"))
        meta.film_stock = _clean(negpy.get("CaptureFilmStock"))
        meta.film_manufacturer = _clean(negpy.get("CaptureFilmManufacturer"))
        meta.film_iso = _int(negpy.get("CaptureFilmISO")) or _int(negpy.get("CaptureISO"))
        meta.developer = _clean(negpy.get("Developer"))
        meta.notes = _clean(negpy.get("Notes"))
        meta.capture_date = _date(negpy.get("CaptureDate"))
        meta.dilution = _clean(negpy.get("DevelopmentDilution"))
        meta.push_pull = _clean(negpy.get("PushPull"))
        meta.development_time = _clean(negpy.get("DevelopmentTime"))

    # Other XMP namespaces, for files that went through a converter which kept XMP
    # but not the negpy properties.
    if meta.capture_date is None:
        raw_packet = packet(target)
        for namespace, key in (
            (PHOTOSHOP_NS, "DateCreated"),
            (EXIF_NS, "DateTimeOriginal"),
            (XMP_NS, "CreateDate"),
        ):
            found = parse_namespace(raw_packet, namespace)
            if found.get(key):
                meta.capture_date = _date(found[key])
                if meta.capture_date and "xmp" not in meta.sources:
                    meta.sources.append("xmp")
                if meta.capture_date:
                    meta.raw.setdefault("xmp", {})[key] = found[key]
                    break
        if meta.camera is None:
            tiff = parse_namespace(raw_packet, TIFF_NS)
            meta.camera = camera_name(tiff.get("Make"), tiff.get("Model"))
        if meta.notes is None:
            description = parse_namespace(raw_packet, DC_NS).get("description")
            meta.notes = _clean(description)

    exif = _exif_values(target)
    if exif:
        meta.sources.append("exif")
        meta.raw["exif"] = exif
        meta.camera = meta.camera or camera_name(exif.get("Make"), exif.get("Model"))
        meta.lens = meta.lens or _clean(exif.get("LensModel"))
        meta.film_iso = meta.film_iso or _int(exif.get("ISOSpeedRatings"))
        meta.capture_date = meta.capture_date or _date(
            exif.get("DateTimeOriginal") or exif.get("DateTimeDigitized") or exif.get("DateTime")
        )
        meta.notes = meta.notes or _clean(exif.get("ImageDescription"))

    parsed = naming.parse(filename or target.name)
    if parsed:
        meta.raw["filename"] = {
            "roll": parsed.roll,
            "frame_number": parsed.frame_number,
            "film": parsed.film,
        }
        if meta.roll is None and parsed.roll:
            meta.roll = parsed.roll
        if meta.frame_number is None and parsed.frame_number is not None:
            meta.frame_number = parsed.frame_number
        if meta.film_stock is None and parsed.film:
            meta.film_stock = parsed.film
        meta.sources.append("filename")

    return meta


# ---------------------------------------------------------------------------
# Matching what was read against the catalog
# ---------------------------------------------------------------------------


def match_roll(db: Session, value: Optional[str]) -> Optional[FilmRoll]:
    """The roll ``negpy:CaptureRoll`` refers to: serial first, then title.

    The serial is the archive's own identifier and is matched exactly (the index
    is case-insensitive). A title is matched case-insensitively and only when it
    is unambiguous — two rolls called "Kyoto" mean the file has to be filed by
    hand, which is better than filing it into the wrong one.
    """
    wanted = (value or "").strip()
    if not wanted:
        return None
    by_serial = serials.find_by_serial(db, wanted)
    if by_serial is not None:
        return by_serial
    matches = (
        db.query(FilmRoll)
        .filter(func.lower(FilmRoll.title) == wanted.lower())
        .order_by(FilmRoll.id.asc())
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def _match_by_name(db: Session, model, value: Optional[str]):
    """A catalog entry whose name matches ``value``, exactly or as a substring."""
    wanted = (value or "").strip()
    if not wanted:
        return None
    exact = db.query(model).filter(func.lower(model.name) == wanted.lower()).first()
    if exact is not None:
        return exact
    # "NIKON F5" in the file, "Nikon F5" plus a serial in the catalog, and the
    # other way round: a scan that says "AF NIKKOR 50mm f/1.8D" against a lens
    # catalogued as "Nikkor 50mm f/1.8".
    lowered = wanted.lower()
    for entry in db.query(model).all():
        name = (entry.name or "").strip().lower()
        if not name:
            continue
        if name in lowered or lowered in name:
            return entry
    return None


def match_camera(db: Session, value: Optional[str]) -> Optional[Camera]:
    return _match_by_name(db, Camera, value)


def match_lens(db: Session, value: Optional[str]) -> Optional[Lens]:
    return _match_by_name(db, Lens, value)


def match_film_stock(db: Session, name: Optional[str], manufacturer: Optional[str] = None) -> Optional[FilmStock]:
    found = _match_by_name(db, FilmStock, name)
    if found is not None:
        return found
    if manufacturer and name:
        return _match_by_name(db, FilmStock, f"{manufacturer} {name}")
    return None


def _create_camera(db: Session, meta: FrameMetadata) -> Optional[Camera]:
    if not meta.camera:
        return None
    entry = Camera(name=meta.camera, notes="Added from a scan's metadata (NegPy/EXIF).")
    db.add(entry)
    db.flush()
    return entry


def _create_lens(db: Session, meta: FrameMetadata) -> Optional[Lens]:
    if not meta.lens:
        return None
    entry = Lens(name=meta.lens, notes="Added from a scan's metadata (NegPy/EXIF).")
    db.add(entry)
    db.flush()
    return entry


def _create_film_stock(db: Session, meta: FrameMetadata) -> Optional[FilmStock]:
    if not meta.film_stock:
        return None
    # ``kind`` cannot be null and the file does not say. Colour negative is the
    # commonest and the least surprising thing to correct in the Gear page.
    entry = FilmStock(
        name=meta.film_stock,
        manufacturer=meta.film_manufacturer,
        iso=meta.film_iso,
        kind=FilmKind.color,
    )
    db.add(entry)
    db.flush()
    return entry


# ---------------------------------------------------------------------------
# Applying it
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """What one ingest actually changed, for the API response and the tests."""

    image_id: Optional[int] = None
    fields: List[str] = field(default_factory=list)
    roll_fields: List[str] = field(default_factory=list)
    matched_roll_id: Optional[int] = None
    sidecar: Optional[str] = None
    #: True when the recipe came from NegPy's edits.db rather than from a sidecar.
    edits_match: bool = False
    sources: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.fields or self.roll_fields or self.sidecar or self.edits_match)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_id": self.image_id,
            "fields": list(self.fields),
            "roll_fields": list(self.roll_fields),
            "matched_roll_id": self.matched_roll_id,
            "sidecar": self.sidecar,
            "edits_match": self.edits_match,
            "sources": list(self.sources),
        }


def apply_to_roll(db: Session, roll: FilmRoll, meta: FrameMetadata, *, create_gear: bool = False) -> List[str]:
    """Fill the roll's empty gear and date fields from a frame's metadata."""
    changed: List[str] = []
    if roll is None:
        return changed

    if roll.camera_id is None and meta.camera:
        camera = match_camera(db, meta.camera) or (_create_camera(db, meta) if create_gear else None)
        if camera is not None:
            roll.camera_id = camera.id
            roll.camera = camera.name
            changed.append("camera")

    if roll.lens_id is None and meta.lens:
        lens = match_lens(db, meta.lens) or (_create_lens(db, meta) if create_gear else None)
        if lens is not None:
            roll.lens_id = lens.id
            roll.lens = lens.name
            changed.append("lens")

    if roll.film_stock_id is None and meta.film_stock:
        stock = match_film_stock(db, meta.film_stock, meta.film_manufacturer) or (
            _create_film_stock(db, meta) if create_gear else None
        )
        if stock is not None:
            roll.film_stock_id = stock.id
            roll.film_type = stock.name
            changed.append("film_stock")

    if meta.capture_date:
        if roll.start_date is None or meta.capture_date < roll.start_date:
            roll.start_date = meta.capture_date
            changed.append("start_date")
        if roll.end_date is None or meta.capture_date > roll.end_date:
            roll.end_date = meta.capture_date
            changed.append("end_date")

    # How it was developed. These have their own columns since 0006; before that
    # ingest appended a line to the roll's notes, which was worse in every way —
    # you could not search it, print it, or correct it without editing prose.
    for column, value in (
        ("developer", meta.developer),
        ("development_dilution", meta.dilution),
        ("push_pull", meta.push_pull),
        ("development_time", meta.development_time),
    ):
        if value and not (getattr(roll, column) or "").strip():
            setattr(roll, column, value)
            changed.append(column)

    return changed


def apply_to_image(image: ImageAsset, meta: FrameMetadata) -> List[str]:
    """Fill the frame's empty fields. Never overwrites one that has a value.

    A contact sheet is never given a frame number, whatever its file says: it is a
    picture *of* the frames, not one of them (M2's rule, kept here).
    """
    changed: List[str] = []
    is_scan = image.type == ImageType.scan
    if is_scan and meta.frame_number is not None and image.frame_number is None:
        image.frame_number = meta.frame_number
        changed.append("frame_number")
    if meta.capture_date is not None and image.capture_date is None:
        image.capture_date = meta.capture_date
        changed.append("capture_date")
    if meta.notes and not (image.notes or "").strip():
        image.notes = meta.notes
        changed.append("notes")
    if meta:
        image.capture_metadata = meta.to_dict()
        changed.append("capture_metadata")
    return changed


def attach_recipe(image: ImageAsset, recipe: "sidecar_mod.Sidecar", source: str) -> None:
    """Record a NegPy recipe on a frame, whatever it was read from.

    One writer for both sources, so a recipe from ``edits.db`` and one from a
    ``.negpy`` file are stored, summarised and shown identically; ``source`` is the
    only difference, and it is there so the UI can say where it came from.
    """
    payload = recipe.to_dict()
    payload["source"] = source
    image.negpy_edited_at = recipe.edited_at
    image.negpy_recipe = payload


def attach_edits(image: ImageAsset, index: Optional["edits_mod.EditsIndex"]) -> bool:
    """Look this frame's content hash up in NegPy's edits.db (M5, "left for later").

    Only when the frame has no sidecar: a ``.negpy`` file travels with the scan and
    is authoritative, while edits.db is one machine's private state. Returns whether
    anything was recorded.
    """
    if index is None or not image.content_hash or image.sidecar_path:
        return False
    recipe = index.lookup(image.content_hash)
    if recipe is None:
        return False
    attach_recipe(image, recipe, "edits.db")
    return True


def attach_sidecar(image: ImageAsset, path: Optional[str | Path] = None) -> Optional[str]:
    """Record the ``.negpy`` sidecar for this frame, if there is one.

    ``path`` overrides where to look, which is what the upload path needs: a
    managed file is stored under a UUID, and its sidecar is stored beside it.
    """
    from ... import paths as app_paths

    target = Path(path) if path else None
    if target is None:
        resolved = app_paths.resolve(image.source_path or image.path)
        target = sidecar_mod.find(resolved) if resolved else None
    if target is None or not Path(target).is_file():
        return None
    parsed = sidecar_mod.read(target)
    if parsed is None:
        return None
    image.sidecar_path = str(target)
    attach_recipe(image, parsed, "sidecar")
    return str(target)


def ingest_settings(db: Session) -> tuple[bool, bool]:
    """``(ingest on?, create gear?)``, read once so a 36-file upload does not
    ask the settings table seventy-two times."""
    return bool(settings_store.get(db, "negpy_ingest")), bool(settings_store.get(db, "negpy_create_gear"))


def ingest_image(
    db: Session,
    image: ImageAsset,
    *,
    roll: Optional[FilmRoll] = None,
    match_unassigned: bool = True,
    enabled: Optional[bool] = None,
    create_gear: Optional[bool] = None,
    sidecar_path: Optional[str | Path] = None,
    edits_index: Optional["edits_mod.EditsIndex"] = None,
) -> IngestResult:
    """Read one frame's file and fill in what the archive does not know yet.

    This is the single entry point every upload path and the library scanner call.
    It is deliberately forgiving: a file with no metadata, a file Pillow cannot
    open and a file that has since been moved all produce an empty result rather
    than an error. Losing a frame because its EXIF is odd would be a much worse
    bug than not reading it.
    """
    from ... import paths as app_paths

    result = IngestResult(image_id=image.id)
    if enabled is None:
        enabled = bool(settings_store.get(db, "negpy_ingest"))
    if not enabled:
        return result
    if create_gear is None:
        create_gear = bool(settings_store.get(db, "negpy_create_gear"))

    resolved = app_paths.resolve(image.source_path or image.path)
    if resolved is None or not Path(resolved).is_file():
        return result

    meta = read(resolved, image.original_filename)
    result.sources = list(meta.sources)

    if roll is None and image.film_roll_id is not None:
        roll = db.get(FilmRoll, image.film_roll_id)
    if roll is None and match_unassigned and meta.roll:
        matched = match_roll(db, meta.roll)
        if matched is not None:
            image.film_roll_id = matched.id
            roll = matched
            result.matched_roll_id = matched.id
            result.fields.append("film_roll_id")

    result.fields.extend(apply_to_image(image, meta))
    # M6.1: a file carrying NegPy's own XMP namespace is a NegPy *export* — the
    # converted positive — because NegPy writes that namespace on export and nowhere
    # else (a scanner's TIFF never has it, and a `.negpy` sidecar beside a scan is
    # not the file's packet). Recorded so the preview shows it as it is instead of
    # printing it a second time. Fills a blank only, like every other field here.
    if image.positive is None and "negpy" in meta.raw:
        image.positive = True
        result.fields.append("positive")
    if roll is not None:
        result.roll_fields.extend(apply_to_roll(db, roll, meta, create_gear=create_gear))

    result.sidecar = attach_sidecar(image, sidecar_path)
    if result.sidecar is None and attach_edits(image, edits_index):
        result.edits_match = True
    return result
