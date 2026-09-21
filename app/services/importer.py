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
      NEG-2026-0007/          → M6.1: the roll that already HAS this serial, if it
        NEG-2026-0007_Frame001.ARW   has no folder yet (NegPy's scan mode, told
                                      to name its roll after the archive's serial)
      NEG-2026-0008_Frame001.ARW   → the same roll-by-serial rule read out of the
      NEG-2026-0008_Frame002.ARW     *file* names, for a scanner pointed straight
                                      at the watch folder with no subfolder at all

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
import threading
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
from ..routers.api import delete_asset_file as _delete_asset_file
from . import lifecycle, serials, share, smb
from .hashing import safe_content_hash
from .negpy import edits as negpy_edits
from .negpy import metadata as negpy_metadata
from .negpy import sidecar as negpy_sidecar

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


#: "2024-0007", "NEG-2024-0007", "AB-2024-12": the same grammar as
#: :mod:`app.services.serials`, with the prefix optional. A bare year is not a serial.
_SERIAL = re.compile(r"^(?:[A-Za-z0-9]{1,10}-)?\d{4}-\d{1,6}$")


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
    """Directories a library root may live under.

    ``LIBRARY_ROOTS_ALLOW`` (colon-separated, ``os.pathsep``), plus the network
    share when one is mounted (M6), plus — always — the archive's own share
    (M6.2). Nothing outside these can be registered: the API is on a LAN with no
    authentication by default, and "POST me any path" would otherwise let a
    visitor enumerate and read the whole filesystem through ``/download``.
    """
    raw = os.getenv("LIBRARY_ROOTS_ALLOW", "")
    bases = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            bases.append(Path(part).expanduser().resolve())
    # M6: the share mounted from Settings counts, but only while it is actually
    # mounted. An unmounted mount point is an empty directory, and registering a
    # root inside one would produce a folder that imports nothing and looks broken.
    mounted = smb.mount_base()
    if smb.is_mounted(mounted) and mounted not in bases:
        bases.append(mounted)
    # M6.2: the archive's own share — a folder under DATA_DIR the stack serves.
    served = share.base()
    if served not in bases:
        bases.append(served)
    return bases


def validate_root(path: str) -> Path:
    """Resolve ``path`` and check it is an existing directory under an allowed base."""
    bases = allowed_bases()
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
        "That folder is outside the folders NegArchive may link from ("
        + ", ".join(str(b) for b in bases)
        + "). Add its parent to LIBRARY_ROOTS_ALLOW and restart.",
        403,
    )


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """What one sweep of a root did, for the API response and the settings page."""

    rolls_created: int = 0

    rolls_adopted: int = 0  # M6.1: existing rolls a serial-named folder attached to
    frames_added: int = 0
    frames_rehomed: int = 0
    #: Frames a move put under a folder or a filename naming a *different* roll
    #: by serial, and which followed the file onto it.
    frames_refiled: int = 0
    frames_updated: int = 0
    frames_unchanged: int = 0
    files_skipped: int = 0
    #: M5: how many frames picked up a NegPy `.negpy` sidecar in this sweep.
    sidecars_seen: int = 0
    roll_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        sidecars = f", {self.sidecars_seen} NegPy sidecars" if self.sidecars_seen else ""
        return (
            f"{self.frames_added} new, {self.frames_rehomed} re-homed"
            + (f" ({self.frames_refiled} onto the roll they name)" if self.frames_refiled else "")
            + ", "
            f"{self.frames_updated} updated, {self.frames_unchanged} unchanged, "
            f"{self.rolls_created} new rolls"
            + (f", {self.rolls_adopted} adopted" if self.rolls_adopted else "")
            + f"{sidecars}"
        )

    def to_dict(self) -> dict:
        return {
            "rolls_created": self.rolls_created,
            "rolls_adopted": self.rolls_adopted,
            "frames_added": self.frames_added,
            "frames_rehomed": self.frames_rehomed,
            "frames_refiled": self.frames_refiled,
            "frames_updated": self.frames_updated,
            "frames_unchanged": self.frames_unchanged,
            "files_skipped": self.files_skipped,
            "sidecars_seen": self.sidecars_seen,
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
    # M6.1: a folder carrying the serial of a roll the archive already has *is* that
    # roll — the one you are scanning, named the way the roll page told you to name
    # it in NegPy — provided the roll has no source folder yet. The frames land on
    # the record that already knows the film, the camera and where the roll is in
    # its life, instead of on a draft with a fresh serial sitting next to it. A roll
    # that already has a folder is left alone: two folders are not one roll.
    if serial:
        existing = serials.find_by_serial_loose(db, serial)
        if existing is not None and not existing.source_dir:
            existing.source_dir = key
            result.rolls_adopted += 1
            result.roll_ids.append(existing.id)
            return existing
    roll = FilmRoll(title=title, source_dir=key)
    # M4: the folder's serial if it carries one and it is free, else a fresh one.
    if serial and not serials.is_taken(db, serial):
        roll.archive_serial = serials.normalize(serial)
    else:
        serials.assign(db, roll, None)
    db.add(roll)
    db.flush()  # we need the id for the frames below
    result.rolls_created += 1
    result.roll_ids.append(roll.id)
    return roll


def _same_serial(roll: FilmRoll, claimed: Optional[str]) -> bool:
    """Does ``roll`` actually carry the serial a folder or a filename named?

    Compared by meaning, not by spelling, so ``NEG_2026_0001`` and ``NEG-2026-1``
    both answer yes for ``NEG-2026-0001``. False whenever the roll was invented
    rather than found — that is what keeps a move between two ordinary folders
    from dragging frames off the roll they are on.
    """
    if not claimed or not roll.archive_serial:
        return False
    wanted = serials.parse(claimed.replace("_", "-"))
    held = serials.parse(roll.archive_serial)
    if wanted is not None and held is not None:
        return wanted == held
    return serials.normalize(claimed) == serials.normalize(roll.archive_serial)


def _rolls_for_files(
    db: Session, folder: Path, files: list[Path], result: ScanResult
) -> list[tuple[FilmRoll, list[Path], bool]]:
    """``[(roll, files, named_by_serial)]`` — which roll each file belongs to.

    The third element says the roll was found *by its serial* rather than invented
    from a folder name, which is what lets :func:`_link_file` re-file a frame that
    moved (see there).

    Normally the answer is one pair: a folder is a roll. But NegPy's scan mode can
    be pointed straight at the watch folder, and then the roll's name is not in a
    folder name at all — it is in every *file* name, because that is what the roll
    page told you to call the roll::

        /mnt/share/rolls/NEG-2026-0001_Frame001.ARW
        /mnt/share/rolls/NEG-2026-0001_Frame002.ARW

    Read by folder alone those are 33 loose files in a directory called ``rolls``,
    so the archive invented a roll called "rolls" with a fresh serial and the real
    roll — the one that knows the camera, the film and where the negatives live —
    sat next to it with nothing in it. The same roll, in the archive twice.

    So when the folder's own name says nothing about a serial, the filenames are
    asked instead, and a file naming a roll the archive **already has** goes to
    that roll. Everything else falls back to the folder's roll exactly as before.

    Two guards make this safe to do by default:

    * the serial has to resolve to an existing roll (:func:`serials.find_by_serial_loose`),
      so a camera's ``IMG_2026_0001_0007.jpg`` matches nothing and changes nothing;
    * a folder that *does* name a serial keeps M6.1's behaviour untouched — the
      folder is the more deliberate statement of the two.

    Unlike the folder rule this does not claim ``source_dir``. A watch folder is
    not one roll's folder; the next roll scanned into it must be free to find its
    own record, and a file that names no roll must still land on the folder's.
    """
    _title, serial = parse_folder_name(folder.name)
    if serial is not None:
        roll = _roll_for_folder(db, folder, result)
        return [(roll, files, _same_serial(roll, serial))]

    by_roll: dict[int, tuple[FilmRoll, list[Path]]] = {}
    leftover: list[Path] = []
    for file_path in files:
        claimed = serials.serial_in_filename(file_path.name)
        roll = serials.find_by_serial_loose(db, claimed) if claimed else None
        if roll is None:
            leftover.append(file_path)
            continue
        by_roll.setdefault(roll.id, (roll, []))[1].append(file_path)

    groups = [(roll, group, True) for roll, group in by_roll.values()]  # matched on its serial
    if leftover or not groups:
        # `not groups` keeps an empty watch folder answering as it always did: a
        # draft roll for the folder, which is what the settings page shows.
        groups.append((_roll_for_folder(db, folder, result), leftover, False))  # the folder's own roll
    return groups


def _refresh_sidecar(image: ImageAsset) -> bool:
    """Pick up a ``.negpy`` sidecar that appeared or was written again (M5).

    Editing a scan in NegPy does not touch the scan, so a rescan that only
    compares image bytes would never notice. Comparing the sidecar's mtime with
    what the frame recorded costs one `stat` per file and is what makes "edited in
    NegPy" show up in the archive after the edit.
    """
    source = image.source_path or image.path
    found = negpy_sidecar.find(source)
    if found is None:
        return False
    try:
        mtime = datetime.utcfromtimestamp(found.stat().st_mtime)
    except OSError:
        return False
    if image.sidecar_path == str(found) and image.negpy_edited_at is not None:
        if mtime <= image.negpy_edited_at:
            return False
    return negpy_metadata.attach_sidecar(image, found) is not None


def _link_file(
    db: Session,
    file_path: Path,
    roll: FilmRoll,
    result: ScanResult,
    ingest: tuple[bool, bool] = (True, False),
    edits_index=None,
    by_serial: bool = False,
) -> None:
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
        changed = False
        if existing.content_hash != digest:
            # Re-scanned or re-exported in place: same path, different bytes.
            existing.content_hash = digest
            changed = True
        if _refresh_sidecar(existing):
            result.sidecars_seen += 1
            changed = True
        if changed:
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
            elif by_serial and candidate.film_roll_id != roll.id:
                # The file moved somewhere that names a roll by its *serial*: a
                # folder called NEG-2026-0001, or a filename that starts with it.
                # That is a deliberate statement about where the frame belongs,
                # and it is how somebody repairs a misfiled roll by hand — so the
                # record follows the file. A move between two ordinary folders
                # still leaves the roll alone (`by_serial` is false there), which
                # is what keeps a reorganisation from shuffling the archive.
                candidate.film_roll_id = roll.id
                result.frames_refiled += 1
            result.frames_rehomed += 1
            return

    image = ImageAsset(
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
    db.add(image)
    # M5: a linked file is read exactly like an uploaded one — EXIF, the `negpy:`
    # XMP namespace, the filename preset and any `.negpy` sidecar beside it. The
    # file itself is never written to; only the record learns something.
    enabled, create_gear = ingest
    ingested = negpy_metadata.ingest_image(
        db,
        image,
        roll=roll,
        match_unassigned=False,
        enabled=enabled,
        create_gear=create_gear,
        edits_index=edits_index,
        # A linked file is never deleted by this — `delete_asset_file` refuses
        # one. It is here for the case where a linked re-export supersedes a
        # *managed* one that had been uploaded through the browser earlier.
        delete_file=_delete_asset_file,
    )
    if ingested.sidecar or ingested.edits_match:
        result.sidecars_seen += 1
    result.frames_added += 1
    lifecycle.touch_scanned(roll)


#: One scan at a time. The watcher's thread and a manual ``POST /api/library/scan``
#: could otherwise both create a roll for the same new folder, and the loser would
#: die on the ``source_dir`` unique index.
_SCAN_LOCK = threading.Lock()


def scan_root(db: Session, root: LibraryRoot, commit: bool = True) -> ScanResult:
    """Walk one registered root and link everything under it."""
    with _SCAN_LOCK:
        return _scan_root_locked(db, root, commit)


def _scan_root_locked(db: Session, root: LibraryRoot, commit: bool) -> ScanResult:
    result = ScanResult()
    ingest = negpy_metadata.ingest_settings(db)  # M5, read once per sweep
    base = Path(root.path)
    if not base.is_dir():
        root.last_scan_at = datetime.utcnow()
        root.last_scan_summary = "folder is not reachable"
        if commit:
            db.commit()
        return result

    # NegPy's edits.db, opened once for the whole sweep — after the check above, so
    # an unreachable share does not leave a connection open behind the early return.
    edits_index = negpy_edits.open_index(db) if ingest[0] else None
    try:
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
            for roll, group, by_serial in _rolls_for_files(db, folder, files, result):
                before = result.frames_added
                for file_path in group:
                    _link_file(db, file_path, roll, result, ingest, edits_index, by_serial)
                # A roll found by its *filenames* is only adopted on the sweep that
                # actually puts frames on it: there is no `source_dir` to mark it
                # with, so without this a rescan would report the adoption forever.
                # `_roll_for_folder` has already counted a roll it resolved from a
                # folder name and put its id in `roll_ids`, which is what keeps the
                # two paths from counting the same roll twice.
                if by_serial and result.frames_added > before and roll.id not in result.roll_ids:
                    result.rolls_adopted += 1
                    result.roll_ids.append(roll.id)
    finally:
        if edits_index is not None:
            edits_index.close()

    root.last_scan_at = datetime.utcnow()
    root.last_scan_summary = result.summary()
    if commit:
        db.commit()
    return result


def scan_roots(db: Session, roots: Iterable[LibraryRoot]) -> dict[int, ScanResult]:
    return {root.id: scan_root(db, root) for root in roots}
