"""A NegPy export is a rendition of a frame, not a second frame (M8).

A roll that goes through the NegPy flow comes back with **two files per frame**:
the raw negative the scanner made (``NEG-2026-0001_Frame007.ARW``) and the
positive NegPy exported from it (``NEG_2026_0001_007.jpg``). They are two
pictures of one piece of film. Stored as two rows they were counted as two
frames — a 33-frame roll listed 66, every frame appeared twice in every grid,
and a re-export added a third row rather than replacing the second.

So the **negative is the frame** and the export hangs off it through
``ImageAsset.derived_from_id``. The export keeps everything that makes it a real
file in an archive meant to outlive its software — its own path, content hash,
original filename and provenance, and its own download URL — but it is not a
frame: it is never counted, listed, renumbered, placed on a sleeve or handed to
NegPy as one.

Which negative an export belongs to
-----------------------------------
NegPy writes the answer into the export itself. Its XMP carries
``negpy:CaptureRoll`` and ``negpy:CaptureFrame`` — "this is roll NEG-2026-0001,
frame 7" — which :mod:`app.services.negpy.metadata` has already read into
``capture_metadata`` by the time anything here runs. That is an authoritative
statement from the program that made the file, so it is used first; the
filename's roll and frame are the fallback, and the record's own
``film_roll_id`` and ``frame_number`` the fallback after that.

Nothing is ever guessed. A positive that names no roll, or names a frame the
roll does not have, stays a frame in its own right — which is the right answer
for a scan of a print, or for an export whose negative was never imported.

A fresher export replaces the one before it
-------------------------------------------
Re-exporting a frame from NegPy after another edit is the normal case, not the
exception, and the archive should end up with the newest one, not a pile. The
newest export becomes the frame's rendition and the row before it is retired,
taking its file with it — but only when NegArchive owns it (``storage_mode ==
"managed"``). A linked file on somebody's share is never touched: this module
may unlink a record from a file, never a file from a disk it does not own.
Notes typed on the old rendition are carried forward; they were written about
this frame's positive, and that is still what this is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import FilmRoll, ImageAsset, ImageType
from . import serials

# `negpy.naming` is imported where it is used, not here: the negpy package reads
# this module (the handoff must not hand NegPy its own exports), and importing it
# at the top would have the two halves importing each other half-built.

#: What the roll of an export is read from, in order of how much it is worth.
#: ``negpy:CaptureRoll`` is NegPy saying so; a filename is an inference.
ROLL_SOURCES = ("xmp", "filename", "record")


def _claimed(image: ImageAsset) -> tuple[Optional[str], Optional[int]]:
    """``(roll, frame)`` this export says it is, best source first."""
    meta = image.capture_metadata if isinstance(image.capture_metadata, dict) else {}
    raw = meta.get("raw") if isinstance(meta.get("raw"), dict) else {}
    negpy = raw.get("negpy") if isinstance(raw.get("negpy"), dict) else {}

    roll = (negpy.get("CaptureRoll") or "").strip() or None
    frame: Optional[int] = None
    try:
        frame = int(str(negpy.get("CaptureFrame")).strip())
    except (TypeError, ValueError):
        frame = None

    if roll is None or frame is None:
        from .negpy import naming

        parsed = naming.parse(image.original_filename)
        roll = roll or parsed.roll
        frame = frame if frame is not None else parsed.frame_number
    if roll is None:
        roll = serials.serial_in_filename(image.original_filename)
    if frame is None:
        frame = image.frame_number
    return roll, frame


def _roll_of(db: Session, image: ImageAsset, claimed_roll: Optional[str]) -> Optional[FilmRoll]:
    """The roll this export belongs to: the one it is already filed on, else the
    one it names. A file that is on a roll is not moved by this module."""
    if image.film_roll_id is not None:
        return db.get(FilmRoll, image.film_roll_id)
    if not claimed_roll:
        return None
    return serials.find_by_serial_loose(db, claimed_roll)


def negative_for(db: Session, image: ImageAsset) -> Optional[ImageAsset]:
    """The frame ``image`` is an export of, or None to leave it a frame of its own.

    Only a *positive* is ever a rendition, and only of a negative on the same roll
    carrying the same frame number. Where a roll has two negatives for one number
    — two scans of the same piece of film, which this archive allows — the oldest
    wins, because that is the one the rest of the app already shows as the frame.
    """
    if not image.positive or image.derived_from_id is not None:
        return None
    if image.type != ImageType.scan:
        return None

    claimed_roll, frame = _claimed(image)
    if frame is None:
        return None
    roll = _roll_of(db, image, claimed_roll)
    if roll is None:
        return None

    return (
        db.query(ImageAsset)
        .filter(
            ImageAsset.film_roll_id == roll.id,
            ImageAsset.type == ImageType.scan,
            ImageAsset.frame_number == frame,
            ImageAsset.derived_from_id.is_(None),
            ImageAsset.id != image.id,
            # A negative, or a file that has not said either way. Never another
            # export: two positives of one frame are a re-export, handled below.
            func.coalesce(ImageAsset.positive, False).is_(False),
        )
        .order_by(ImageAsset.id.asc())
        .first()
    )


def existing_rendition(db: Session, negative: ImageAsset) -> Optional[ImageAsset]:
    found = _renditions_of(db, negative)
    return found[0] if found else None


@dataclass(frozen=True)
class Superseded:
    """The file a re-export replaced, shaped like the record that pointed at it.

    ``delete_asset_file`` takes a row and reads ``path`` and ``storage_mode`` off
    it, and it holds the guards that matter (never a linked file, never anything
    outside ``static/uploads``). Handing it this rather than a bare string keeps
    those guards in the one place that has always owned them.
    """

    path: str
    storage_mode: str


def attach(db: Session, image: ImageAsset, *, delete_file=None) -> Optional[ImageAsset]:
    """Make ``image`` the rendition of the frame it names. Returns that frame.

    When the frame already had one this is a **re-export**, and the newest wins:
    ``image`` becomes the rendition and the previous row is retired, taking its
    file with it when the archive owns it. Notes typed on the old rendition are
    carried forward.

    The *new* row is the survivor rather than the old one on purpose. It is the
    row the caller has just created and still holds — an upload handler is about
    to answer with it, and on the first ingest it has not even been flushed yet,
    so it has no id to delete by. Retiring the older row instead needs neither.
    """
    negative = negative_for(db, image)
    if negative is None:
        return None

    image.derived_from_id = negative.id
    # A rendition is reached through its frame and never listed beside it, so the
    # frame number is the frame's to keep.
    image.frame_number = negative.frame_number

    for previous in _renditions_of(db, negative):
        if previous is image or (image.id is not None and previous.id == image.id):
            continue
        if previous.notes and not image.notes:
            image.notes = previous.notes
        superseded = (
            None
            if previous.path == image.path
            else Superseded(previous.path, previous.storage_mode or "managed")
        )
        db.delete(previous)
        if delete_file is not None and superseded is not None:
            delete_file(superseded)
    return negative


def _renditions_of(db: Session, negative: ImageAsset):
    return (
        db.query(ImageAsset)
        .filter(ImageAsset.derived_from_id == negative.id)
        .order_by(ImageAsset.id.asc())
        .all()
    )


def is_frame(image: ImageAsset) -> bool:
    """A frame in its own right — what every count, list and grid means by "frame"."""
    return image.derived_from_id is None


# ---------------------------------------------------------------------------
# What the rest of the app asks this module
# ---------------------------------------------------------------------------


def only_frames(query):
    """Narrow a query on :class:`ImageAsset` to frames. A rendition is not a frame.

    Every count, list, grid, search result, contact sheet and handoff goes
    through this, which is the whole point of having it: "how many frames does
    this roll have" must have one answer, and before M8 it was the number of
    files.
    """
    return query.filter(ImageAsset.derived_from_id.is_(None))


def by_frame(db: Session, frame_ids) -> dict:
    """``{frame_id: rendition}`` for the frames given, in one query.

    A roll page asks this once for all 36 frames rather than once per frame.
    """
    ids = [i for i in frame_ids if i is not None]
    if not ids:
        return {}
    found: dict = {}
    for rendition in (
        db.query(ImageAsset)
        .filter(ImageAsset.derived_from_id.in_(ids))
        .order_by(ImageAsset.id.asc())
    ):
        found.setdefault(rendition.derived_from_id, rendition)
    return found


def shown_for(frame: ImageAsset, rendition: Optional[ImageAsset], render: str = "auto"):
    """The file to actually show for a frame, and whether it still needs rendering.

    Returns ``(image, render_as_positive)``.

    * ``raw`` — the frame's own file, as stored. Always.
    * ``auto`` / ``positive`` — NegPy's export when there is one, shown as it is
      because it already *is* the picture; otherwise the frame's own file put
      through :mod:`app.services.preview`, which is an approximation and says so.

    A real export beats an approximation of one, which is the whole reason the
    export is kept rather than recomputed.
    """
    if render == "raw" or rendition is None:
        return frame, render != "raw"
    return rendition, False
