"""“Open in NegPy”: a roll folder and a metadata preset, ready to work on (M5).

NegPy has no CLI, no URL scheme and no IPC (docs/NEGPY_INTEGRATION.md), so
"open this roll in NegPy" cannot mean launching anything. What it can mean — and
what this does — is putting the roll somewhere NegPy is already looking, in a
shape that needs no typing:

``<handoff dir>/<serial>/``
    every scan of the roll, named with the recommended export preset
    (``NEG-2026-0007_012_HP5 Plus.tif``), plus any ``.negpy`` sidecar that was
    already next to it, plus a ``README.txt`` with the three steps.

``<user dir>/presets/metadata/<serial>.json``
    a metadata preset carrying the roll's camera, lens and film as the ``na-…``
    ids that :mod:`app.services.negpy.gear` wrote into NegPy's gear library, the
    roll serial as ``capture_roll``, and the capture date.

The user then adds the folder as a library root or Hot Folder and applies the
preset. Two clicks, and every frame comes out of NegPy carrying the serial that
is printed on the sleeve the negatives are in.

**Nothing is moved and nothing original is renamed.** The default mode is a hard
link, so a 40 GB roll costs no disk and edits in NegPy work on the same bytes;
where hard links are impossible (a different filesystem, an SMB share) it falls
back to a copy and says so. ``mode="copy"`` asks for copies outright — the right
choice when the handoff folder is a USB stick going to another machine.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ... import paths as app_paths
from ...errors import ApiError
from ...models import FilmRoll, ImageAsset, ImageType
from . import naming
from . import sidecar as sidecar_mod

#: How a scan gets into the handoff folder.
MODES = ("link", "copy")


def _safe(text: str) -> str:
    """A filename component that survives every filesystem the archive may sit on."""
    cleaned = "".join(character for character in str(text or "") if character not in '/\\:*?"<>|\n\r\t')
    return cleaned.strip().strip(".") or "untitled"


def folder_name(roll: FilmRoll) -> str:
    """``NEG-2026-0007``, or ``roll-12`` for a roll that somehow has no serial."""
    return _safe(roll.archive_serial or f"roll-{roll.id}")


def frame_filename(roll: FilmRoll, image: ImageAsset, extension: str) -> str:
    """The recommended preset's name for this frame.

    ``{{ roll }}_{{ frame|pad(3) }}_{{ film }}`` — see
    :data:`app.services.negpy.naming.FILENAME_PATTERN`. A frame with no number
    keeps its original stem instead of being given one it has not earned.
    """
    serial = _safe(roll.archive_serial or f"roll-{roll.id}")
    film = _safe(roll.film_type_name) if roll.film_type_name else None
    if image.frame_number is None:
        stem = Path(image.original_filename or f"frame-{image.id}").stem
        return f"{serial}_{_safe(stem)}{extension}"
    parts = [serial, f"{int(image.frame_number):03d}"]
    if film:
        parts.append(film)
    return "_".join(parts) + extension


@dataclass
class HandoffResult:
    """What was prepared, and what to do with it."""

    roll_id: int = 0
    serial: Optional[str] = None
    folder: str = ""
    preset_path: Optional[str] = None
    mode: str = "link"
    linked: int = 0
    copied: int = 0
    sidecars: int = 0
    skipped: List[str] = field(default_factory=list)
    #: Files from an earlier prepare that no frame corresponds to any more.
    removed: int = 0
    prepared_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "roll_id": self.roll_id,
            "serial": self.serial,
            "folder": self.folder,
            "preset_path": self.preset_path,
            "mode": self.mode,
            "linked": self.linked,
            "copied": self.copied,
            "sidecars": self.sidecars,
            "skipped": list(self.skipped),
            "removed": self.removed,
            "frames": self.linked + self.copied,
            "prepared_at": self.prepared_at,
            "filename_pattern": naming.FILENAME_PATTERN,
        }


def preset_payload(roll: FilmRoll) -> Dict[str, Any]:
    """NegPy metadata preset for a roll, in the ``na-…`` id space gear sync writes."""
    when = roll.start_date or roll.end_date
    return {
        "name": roll.archive_serial or roll.title,
        "description": f"NegArchive roll {roll.archive_serial or roll.id} — {roll.title}",
        "capture_roll": roll.archive_serial or roll.title,
        "capture_date": when.isoformat() if when else None,
        "camera_id": f"na-cam-{roll.camera_id}" if roll.camera_id else None,
        "lens_id": f"na-lens-{roll.lens_id}" if roll.lens_id else None,
        "film_stock_id": f"na-film-{roll.film_stock_id}" if roll.film_stock_id else None,
        "camera": roll.camera_name,
        "lens": roll.lens_name,
        "film_stock": roll.film_type_name,
        "film_iso": roll.film_stock_ref.iso if roll.film_stock_ref else None,
        "format": roll.format,
        "notes": roll.notes,
        "source": "NegArchive",
        "written_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


README = """This folder was prepared by NegArchive for NegPy.

1. In NegPy, add this folder as a library root (or as the Hot Folder).
2. Apply the metadata preset called "{serial}" — NegArchive wrote it to
   {preset}
   It fills in the roll, the capture date and the gear for every frame.
3. Export with the filename pattern
   {pattern}
   into a folder NegArchive watches, and the edited scans come back with their
   roll and frame numbers intact.

The files here are {mode_note}. NegArchive never writes to, renames or deletes
the originals; delete this folder whenever you are done with it.
"""


def _place(source: Path, target: Path, mode: str) -> str:
    """Put ``source`` at ``target``. Returns the mode that was actually used."""
    if target.exists():
        try:
            if target.samefile(source):
                return "link"
        except OSError:
            pass
        target.unlink(missing_ok=True)
    if mode == "link":
        try:
            os.link(source, target)
            return "link"
        except OSError:
            # Different filesystem, or a share that has no hard links: copy.
            pass
    shutil.copy2(source, target)
    return "copy"


def prepare(
    db: Session,
    roll: FilmRoll,
    *,
    handoff_root: Path,
    presets_root: Optional[Path] = None,
    mode: str = "link",
) -> HandoffResult:
    """Build the roll folder and the preset. Raises :class:`ApiError` on a bad mode."""
    import json

    if mode not in MODES:
        raise ApiError("invalid_mode", f"Mode must be one of: {', '.join(MODES)}.", 400, "mode")

    scans: List[ImageAsset] = (
        db.query(ImageAsset)
        .filter(ImageAsset.film_roll_id == roll.id, ImageAsset.type == ImageType.scan)
        .order_by(ImageAsset.frame_number.asc().nulls_last(), ImageAsset.id.asc())
        .all()
    )
    if not scans:
        raise ApiError(
            "no_frames",
            "This roll has no scans yet, so there is nothing to open in NegPy.",
            400,
        )

    folder = Path(handoff_root) / folder_name(roll)
    folder.mkdir(parents=True, exist_ok=True)
    result = HandoffResult(roll_id=roll.id, serial=roll.archive_serial, folder=str(folder), mode=mode)

    used_names: set[str] = set()
    for image in scans:
        source = app_paths.resolve(image.source_path or image.path)
        if source is None or not source.is_file():
            result.skipped.append(image.original_filename or str(image.id))
            continue
        extension = Path(image.original_filename or source.name).suffix.lower() or source.suffix.lower()
        name = frame_filename(roll, image, extension)
        if name in used_names:  # two frames with the same number: keep both
            name = f"{Path(name).stem}-{image.id}{extension}"
        used_names.add(name)
        try:
            placed = _place(source, folder / name, mode)
        except OSError:
            result.skipped.append(image.original_filename or str(image.id))
            continue
        if placed == "link":
            result.linked += 1
        else:
            result.copied += 1

        found = sidecar_mod.find(source)
        if found is not None:
            try:
                _place(found, folder / (name + sidecar_mod.SUFFIX), mode)
                result.sidecars += 1
            except OSError:
                pass

    # A frame renumbered or deleted since the last prepare left its old file
    # here; NegPy would open both. Everything this run did not place goes.
    keep = set(used_names) | {name + sidecar_mod.SUFFIX for name in used_names} | {"README.txt"}
    for stale in folder.iterdir():
        if stale.is_file() and stale.name not in keep and not stale.name.startswith("."):
            try:
                stale.unlink()
                result.removed += 1
            except OSError:
                pass

    preset_path: Optional[Path] = None
    if presets_root is not None:
        preset_path = Path(presets_root) / f"{folder_name(roll)}.json"
        preset_path.parent.mkdir(parents=True, exist_ok=True)
        preset_path.write_text(
            json.dumps(preset_payload(roll), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        result.preset_path = str(preset_path)

    mode_note = (
        "hard links to the archive's own files — they cost no disk space"
        if result.linked and not result.copied
        else "copies of the archive's own files"
        if result.copied and not result.linked
        else "hard links where that was possible, copies everywhere else"
    )
    (folder / "README.txt").write_text(
        README.format(
            serial=roll.archive_serial or roll.title,
            preset=result.preset_path or "(no preset written: no NegPy user directory configured)",
            pattern=naming.FILENAME_PATTERN,
            mode_note=mode_note,
        ),
        encoding="utf-8",
    )
    result.prepared_at = datetime.utcnow().isoformat(timespec="seconds")
    return result
