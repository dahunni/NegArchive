"""Import by reference: register a folder tree, link its files, never copy them.

Roadmap M3. A 36-exposure roll at 4000 dpi is several gigabytes; NegPy already has
it on disk, and an Immich external library may want the same bytes. Copying them
into ``DATA_DIR`` a second time is the wrong default for an archive that is meant
to outlive its software, so a *linked* frame stores the path and a
:mod:`~app.services.hashing` content hash and leaves the file exactly where it is.

Folder layout the scanner expects — the one everybody's scanner software produces:

    <root>/
      2024-0007 Harbour/      → one roll, serial 2024-0007, title "Harbour"
        harbour_001.tif       → frame 1
        harbour_002.tif       → frame 2
      Kyoto rain/             → one roll, title "Kyoto rain", no serial
        ...
      loose_scan.tif          → goes into a roll named after <root> itself

**Rescans are idempotent.** A file is identified first by its absolute path and
then by its content hash, so scanning twice changes nothing, a file edited in
place updates its hash, and a file that *moved* is re-homed onto its existing
record instead of being imported a second time.

Frame numbers and the accepted extensions come from M2's upload path, so a linked
file and an uploaded one are read by exactly the same rules.

Nothing here ever writes to, moves or deletes a file under a library root.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import FilmRoll, ImageAsset, ImageType, LibraryRoot

# The upload allowlist and the frame-number parser are M2's, and there is exactly
# one of each: a file linked from a library root has to be judged by the same rules
# as one uploaded through the browser, or the two halves of the archive disagree
# about what a frame is called. (Importing a router from a service is the wrong
# direction; `routers.api` does not import this module, so it is a straight edge,
# not a cycle. If it ever needs to, both belong in a service of their own.)
from ..routers.api import ALLOWED_EXTENSIONS, frame_number_from_filename
from .hashing import safe_content_hash

#: The same allowlist the upload endpoints use (roadmap M2, R#18).
IMAGE_EXTENSIONS = ALLOWED_EXTENSIONS

#: Folders a scan never descends into.
SKIP_DIRS = {".git", "__pycache__", ".Trash", "@eaDir", ".DS_Store", "node_modules"}


# ---------------------------------------------------------------------------
# Folder parsing
#
# Frame numbers come from M2's `frame_number_from_filename`, imported above. M3
# briefly carried a copy of it so link mode could be built before M2 landed; that
# copy is gone.
# ---------------------------------------------------------------------------


#: "2024-0007", "NEG-2024-0007", "AB-2024-12". A bare year is not a serial.
_SERIAL = re.compile(r"^(?:[A-Za-z]{1,6}-)?\d{4}-\d{2,6}$")


def parse_folder_name(name: str) -> tuple[str, Optional[str]]:
    """``("Harbour", "2024-0007")`` for a folder called ``2024-0007 Harbour``.

    Only a *leading* token that looks like an archive serial is taken; everything
    else becomes the title. A folder whose whole name is a serial keeps it as the
    title too, because a roll must have one.
    """
    cleaned = name.strip()
    head, _, rest = cleaned.partition(" ")
    if not rest:
        head, _, rest = cleaned.partition("_")
    if head and _SERIAL.match(head):
        title = rest.strip(" _-") or head
        return title, head
    return cleaned, None


# ---------------------------------------------------------------------------
# Root registration
# ---------------------------------------------------------------------------


def allowed_bases() -> list[Path]:
    """Directories a library root may live under, from ``LIBRARY_ROOTS_ALLOW``.

    Colon-separated (``os.pathsep``), empty by default: with nothing configured
    **no** folder can be registered. The API is on a LAN with no authentication by
    default, and "POST me any path" would otherwise let a visitor enumerate and
    read the whole filesystem through ``/download``.
    """
    raw = os.getenv("LIBRARY_ROOTS_ALLOW", "")
    bases = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            bases.append(Path(part).expanduser().resolve())
    return bases


def validate_root(path: str) -> Path:
    """Resolve ``path`` and check it is an existing directory under an allowed base."""
    bases = allowed_bases()
    if not bases:
        raise ApiError(
            "library_roots_disabled",
            "Import by reference is off. Set LIBRARY_ROOTS_ALLOW to the folder(s) "
            "NegArchive may link files from, then restart.",
            403,
        )
    if not str(path or "").strip():
        raise ApiError("invalid_path", "A folder path is required.")
    try:
        candidate = Path(str(path)).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ApiError("unknown_path", "That folder does not exist.", 404) from exc
    if not candidate.is_dir():
        raise ApiError("not_a_directory", "That path is not a folder.")
    for base in bases:
        if candidate == base or base in candidate.parents:
            return candidate
    raise ApiError(
        "path_not_allowed",
        "That folder is outside LIBRARY_ROOTS_ALLOW: "
        + ", ".join(str(b) for b in bases)
        + ".",
        403,
    )


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """What one sweep of a root did, for the API response and the settings page."""

    rolls_created: int = 0
    frames_added: int = 0
    frames_rehomed: int = 0
    frames_updated: int = 0
    frames_unchanged: int = 0
    files_skipped: int = 0
    roll_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.frames_added} new, {self.frames_rehomed} re-homed, "
            f"{self.frames_updated} updated, {self.frames_unchanged} unchanged, "
            f"{self.rolls_created} new rolls"
        )

    def to_dict(self) -> dict:
        return {
            "rolls_created": self.rolls_created,
            "frames_added": self.frames_added,
            "frames_rehomed": self.frames_rehomed,
            "frames_updated": self.frames_updated,
            "frames_unchanged": self.frames_unchanged,
            "files_skipped": self.files_skipped,
            "roll_ids": self.roll_ids,
            "summary": self.summary(),
        }


def _image_files(folder: Path) -> list[Path]:
    """Image files directly inside ``folder``, sorted by name."""
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [
        entry
        for entry in entries
        if entry.is_file()
        and not entry.name.startswith(".")
        and entry.suffix.lower() in IMAGE_EXTENSIONS
    ]


def _subfolders(folder: Path) -> list[Path]:
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [
        entry
        for entry in entries
        if entry.is_dir() and not entry.name.startswith(".") and entry.name not in SKIP_DIRS
    ]


def _roll_for_folder(db: Session, folder: Path, result: ScanResult) -> FilmRoll:
    """The roll this folder maps to, created as a draft the first time it is seen."""
    key = str(folder)
    roll = db.query(FilmRoll).filter(FilmRoll.source_dir == key).first()
    if roll:
        return roll
    title, serial = parse_folder_name(folder.name)
    roll = FilmRoll(title=title, archive_serial=serial, source_dir=key)
    db.add(roll)
    db.flush()  # we need the id for the frames below
    result.rolls_created += 1
    result.roll_ids.append(roll.id)
    return roll


def _link_file(db: Session, file_path: Path, roll: FilmRoll, result: ScanResult) -> None:
    absolute = str(file_path)
    digest = safe_content_hash(file_path)
    if digest is None:
        result.files_skipped += 1
        return

    existing = (
        db.query(ImageAsset)
        .filter(ImageAsset.source_path == absolute, ImageAsset.storage_mode == "linked")
        .first()
    )
    if existing is not None:
        if existing.content_hash != digest:
            # Re-scanned or re-exported in place: same path, different bytes.
            existing.content_hash = digest
            result.frames_updated += 1
        else:
            result.frames_unchanged += 1
        return

    # Same bytes somewhere else: the file moved. Re-home the record rather than
    # importing a duplicate, so frame numbers and notes survive a reorganisation.
    moved = (
        db.query(ImageAsset)
        .filter(ImageAsset.content_hash == digest, ImageAsset.storage_mode == "linked")
        .all()
    )
    for candidate in moved:
        if candidate.source_path and not os.path.exists(candidate.source_path):
            candidate.source_path = absolute
            candidate.path = absolute
            candidate.original_filename = file_path.name
            if candidate.film_roll_id is None:
                candidate.film_roll_id = roll.id
            result.frames_rehomed += 1
            return

    db.add(
        ImageAsset(
            film_roll_id=roll.id,
            type=ImageType.scan,
            # `path` keeps pointing at the original for every consumer that only
            # knows `path`; `source_path` is what marks it as not ours to touch.
            path=absolute,
            source_path=absolute,
            content_hash=digest,
            original_filename=file_path.name,
            storage_mode="linked",
            frame_number=frame_number_from_filename(file_path.name),
        )
    )
    result.frames_added += 1


def scan_root(db: Session, root: LibraryRoot, commit: bool = True) -> ScanResult:
    """Walk one registered root and link everything under it."""
    result = ScanResult()
    base = Path(root.path)
    if not base.is_dir():
        root.last_scan_at = datetime.utcnow()
        root.last_scan_summary = "folder is not reachable"
        if commit:
            db.commit()
        return result

    folders: list[Path] = []
    loose = _image_files(base)
    if loose:
        # Files dropped straight into the root still belong somewhere.
        folders.append(base)
    folders.extend(_subfolders(base))

    for folder in folders:
        files = _image_files(folder)
        if not files and folder != base:
            # An empty subfolder is a roll the scanner has not filled yet: the
            # watch folder is supposed to show it as a draft immediately.
            _roll_for_folder(db, folder, result)
            continue
        roll = _roll_for_folder(db, folder, result)
        for file_path in files:
            _link_file(db, file_path, roll, result)

    root.last_scan_at = datetime.utcnow()
    root.last_scan_summary = result.summary()
    if commit:
        db.commit()
    return result


def scan_roots(db: Session, roots: Iterable[LibraryRoot]) -> dict[int, ScanResult]:
    return {root.id: scan_root(db, root) for root in roots}
