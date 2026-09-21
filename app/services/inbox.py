"""The inbox: the archive's own share, and the folder that empties itself (M6.2).

The simplest workflow with NegPy is: convert, export a finished JPEG or TIFF, give it
to the archive. Two things made that tedious. The export folder was a network
share the archive *mounted from a NAS* — a second machine, a password, a
capability on the container — and the folder was watched by reference, so every
export stayed where NegPy put it and the folder filled up for ever.

So the stack now **serves** a share of its own (the ``smb`` service in
docker-compose.yml, one folder: ``$DATA_DIR/inbox``), and this module is what
empties it. Every sweep takes each finished file *into* the archive exactly as an
upload would — copied into managed storage, hashed, its EXIF and NegPy XMP read,
filed on the roll its metadata, its name or its folder says, marked as the
finished positive it is — and then deletes it from the inbox. The folder is a
letterbox, not a library: what NegPy drops in it is gone by the next sweep, and
what is left there is a file the archive could not take and says why.

**Everything that lands here is a finished positive.** That is the inbox's
purpose, and it is what makes "drop the export and forget it" safe: nothing in
here is ever printed as a negative. The one exception is a camera raw, which is
never a positive; a raw dropped here is imported as a scan and decided by the
film stock. A negative scan that needs printing belongs on the roll's upload box.

**How a file finds its roll**, in order: a subfolder named after a roll (its
serial, ``NEG-2026-0007``, or its title) files everything inside it on that roll;
otherwise the file's own ``negpy:CaptureRoll`` or its export filename
(``NEG-2026-0007_012_HP5 Plus.jpg``) does; otherwise the frame arrives unassigned
and waits on the Frames page. The inbox never creates a roll.

**What is never deleted.** A file the archive could not accept — not an image, a
truncated write, too large — stays where it is and is listed in the status, so
the mistake is visible instead of silently gone. A file whose bytes the archive
already holds is a duplicate: it is removed and counted, because re-exporting the
same frame twice is the most ordinary thing in the world and should cost nothing.

**Half-written files.** A JPEG arriving over SMB exists on disk before it is
complete. A file whose mtime is younger than :data:`SETTLE_SECONDS` is left for the
next sweep, and the magic-byte sniff catches the rest.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import FilmRoll, ImageAsset, ImageType

# The upload path's own rules — allowlist, sniff, size, the one place that builds
# an ImageAsset — so a file from the inbox is judged exactly like one from the
# browser. Same straight edge app/services/importer.py uses; `routers.api` does
# not import this module.
from ..routers.api import (
    ALLOWED_EXTENSIONS,
    _abs,
    _looks_like_image,
    _new_image,
    max_upload_bytes,
    store_sidecar_bytes,
)
from . import lifecycle, rawdecode, serials, settings_store, share
from .hashing import safe_content_hash
from .importer import parse_folder_name
from .negpy import edits as negpy_edits
from .negpy import metadata as negpy_metadata
from .negpy import sidecar as negpy_sidecar

log = logging.getLogger("negarchive.inbox")

#: Where the inbox is: the `inbox/` folder of the archive's own share
#: (app/services/share.py). Overridable for a laptop or a test.
INBOX_DIR_ENV = "INBOX_DIR"

#: A file younger than this may still be arriving over the network.
SETTLE_SECONDS = 10

#: Names that are never files of yours: Finder's and Windows' droppings, and the
#: ``._name`` AppleDouble twins macOS writes next to every file on an SMB share.
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORED_PREFIXES = (".", "._", "~$")
#: Subfolders left alone entirely.
IGNORED_DIR_PREFIXES = (".", "_", "@")

#: How many waiting files the status lists (the count is always exact).
LISTED_PENDING = 30


# ---------------------------------------------------------------------------
# Where it is, and how to reach it
# ---------------------------------------------------------------------------


def inbox_dir() -> Path:
    raw = (os.getenv(INBOX_DIR_ENV) or "").strip()
    return Path(raw).expanduser().resolve() if raw else share.folder(share.INBOX_DIR)


def ensure() -> Path:
    target = inbox_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


@dataclass
class SweepResult:
    imported: int = 0
    filed: int = 0  # imported *and* on a roll
    unassigned: int = 0
    duplicates: int = 0
    settling: int = 0
    rejected: List[Tuple[str, str]] = field(default_factory=list)
    folders_removed: int = 0
    roll_ids: List[int] = field(default_factory=list)
    image_ids: List[int] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.imported or self.duplicates or self.folders_removed)

    def summary(self) -> str:
        parts = [f"{self.imported} imported"]
        if self.filed:
            parts.append(f"{self.filed} filed on a roll")
        if self.unassigned:
            parts.append(f"{self.unassigned} waiting for a roll")
        if self.duplicates:
            parts.append(f"{self.duplicates} already in the archive")
        if self.settling:
            parts.append(f"{self.settling} still arriving")
        if self.rejected:
            parts.append(f"{len(self.rejected)} could not be taken")
        return ", ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "imported": self.imported,
            "filed": self.filed,
            "unassigned": self.unassigned,
            "duplicates": self.duplicates,
            "settling": self.settling,
            "rejected": [{"name": name, "reason": reason} for name, reason in self.rejected],
            "folders_removed": self.folders_removed,
            "roll_ids": list(self.roll_ids),
            "image_ids": list(self.image_ids),
            "summary": self.summary(),
        }


def _ignored_file(name: str) -> bool:
    return name in IGNORED_NAMES or name.startswith(IGNORED_PREFIXES)


def _walk(base: Path) -> List[Path]:
    """Every candidate file under the inbox, in a stable order, sidecars included."""
    found: List[Path] = []
    for root, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith(IGNORED_DIR_PREFIXES))
        for name in sorted(names):
            if not _ignored_file(name):
                found.append(Path(root) / name)
    return found


def _roll_for_folder(db: Session, folder: Path, base: Path) -> Optional[FilmRoll]:
    """The roll a subfolder is named after, if the archive has it. Never created."""
    if folder == base:
        return None
    title, serial = parse_folder_name(folder.name)
    if serial:
        roll = serials.find_by_serial(db, serial)
        if roll is not None:
            return roll
    return negpy_metadata.match_roll(db, folder.name) or negpy_metadata.match_roll(db, title)


def _remove_quietly(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.warning("inbox: could not remove %s: %s", path, exc)
        return False


def _sweep_apple_doubles(base: Path) -> None:
    """Remove the ``._name`` twins macOS leaves once ``name`` itself is gone.

    Finder writes one next to every file on an SMB share. They are hidden and
    harmless, and they are also precisely the clutter this folder is meant not
    to collect.
    """
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(IGNORED_DIR_PREFIXES)]
        for name in names:
            if name.startswith("._") and not (Path(root) / name[2:]).exists():
                _remove_quietly(Path(root) / name)


def _prune_empty_dirs(base: Path, result: SweepResult) -> None:
    """Drop subfolders the sweep emptied. Bottom-up; the inbox itself stays."""
    for root, dirs, names in os.walk(base, topdown=False):
        current = Path(root)
        if current == base or current.name.startswith(IGNORED_DIR_PREFIXES):
            continue
        leftovers = [n for n in names if not _ignored_file(n)]
        if leftovers or dirs:
            continue
        for stray in names:  # only Finder droppings can be left at this point
            _remove_quietly(current / stray)
        try:
            current.rmdir()
            result.folders_removed += 1
        except OSError:
            pass


def sweep(db: Session, *, settle_seconds: int = SETTLE_SECONDS, now: Optional[float] = None) -> SweepResult:
    """Take every finished file in the inbox into the archive, then delete it there.

    Committed per file, so a sweep that dies halfway keeps what it imported and
    the inbox keeps what it did not; the duplicate check makes a second pass over
    the same file cost nothing but its hash.
    """
    result = SweepResult()
    base = ensure()
    clock = now if now is not None else time.time()
    files = _walk(base)
    if not files:
        _record(db, result)
        return result

    ingest_on, create_gear = negpy_metadata.ingest_settings(db)
    edits_index = negpy_edits.open_index(db) if ingest_on else None
    try:
        for path in files:
            if negpy_sidecar.is_sidecar_name(path.name):
                continue  # travels with its scan, below
            outcome = _take(db, path, base, result, clock, settle_seconds, ingest_on, create_gear, edits_index)
            if outcome:
                log.info("inbox: %s", outcome)
    finally:
        if edits_index is not None:
            edits_index.close()

    _sweep_apple_doubles(base)
    _prune_empty_dirs(base, result)
    _record(db, result)
    return result


def _take(
    db: Session,
    path: Path,
    base: Path,
    result: SweepResult,
    clock: float,
    settle_seconds: int,
    ingest_on: bool,
    create_gear: bool,
    edits_index,
) -> Optional[str]:
    """One file: accept it exactly like an upload, or say why not. Returns a log line."""
    name = path.name
    shown = str(path.relative_to(base))
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        result.rejected.append((shown, "not an accepted image"))
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    if clock - stat.st_mtime < settle_seconds:
        result.settling += 1
        return None
    if stat.st_size > max_upload_bytes():
        result.rejected.append((shown, f"larger than MAX_UPLOAD_MB ({max_upload_bytes() // (1024 * 1024)} MB)"))
        return None
    try:
        with path.open("rb") as handle:
            head = handle.read(16)
    except OSError as exc:
        result.rejected.append((shown, f"could not be read ({exc.strerror or exc})"))
        return None
    if not _looks_like_image(head):
        result.rejected.append((shown, "does not look like an image (still being written?)"))
        return None

    # The `.negpy` beside it, if NegPy wrote one: read now, removed with the scan.
    sidecar_file = negpy_sidecar.find(path)
    payload = None
    if sidecar_file is not None:
        try:
            if sidecar_file.stat().st_size <= negpy_sidecar.MAX_SIDECAR_BYTES:
                payload = sidecar_file.read_bytes()
        except OSError:
            payload = None

    digest = safe_content_hash(path)
    if digest and db.query(ImageAsset.id).filter(ImageAsset.content_hash == digest).first() is not None:
        # Same bytes already in the archive: the ordinary re-export. Gone, counted.
        result.duplicates += 1
        _remove_quietly(path)
        if sidecar_file is not None:
            _remove_quietly(sidecar_file)
        return f"{shown}: already in the archive, removed"

    rel_path = os.path.join("static", "uploads", "scans", f"{uuid4().hex}{ext}")
    destination = _abs(rel_path)
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(path, destination)
        if os.path.getsize(destination) != stat.st_size:
            raise OSError("short copy")
    except OSError as exc:
        _remove_quietly(Path(destination))
        result.rejected.append((shown, f"could not be copied into the archive ({exc})"))
        return None

    # From here on the copy exists: any failure below has to take it away again,
    # or every sweep would leave one more orphan under uploads/ and try again.
    try:
        folder_roll = _roll_for_folder(db, path.parent, base)
        image = _new_image(
            film_roll_id=folder_roll.id if folder_roll else None,
            image_type=ImageType.scan,
            rel_path=rel_path,
            original_filename=name,
            # The inbox holds finished positives (module docstring). A raw never is one.
            positive=None if ext in rawdecode.RAW_EXTENSIONS else True,
        )
        db.add(image)
        db.flush()
        stored_sidecar = store_sidecar_bytes(rel_path, payload) if payload else None
        # `delete_asset_file` is the router's, and its guards (never a linked
        # file, never anything outside static/uploads) are the ones that must
        # apply when a re-export through the inbox supersedes an older one. Same
        # bargain as `importer`'s import of the frame-number parser: one rule,
        # in the one place that has always owned it.
        from ..routers.api import delete_asset_file

        negpy_metadata.ingest_image(
            db,
            image,
            roll=folder_roll,
            match_unassigned=folder_roll is None,
            enabled=ingest_on,
            create_gear=create_gear,
            sidecar_path=stored_sidecar,
            edits_index=edits_index,
            delete_file=delete_asset_file,
        )
        if image.film_roll_id is None:
            # Last resort, the folder rule applied to the name: `NEG-2026-0007_Frame005.ARW`
            # (NegPy's scan mode) starts with a serial even though it is not the export
            # preset, and a file named after a roll belongs to it.
            _, leading = parse_folder_name(path.stem)
            named = serials.find_by_serial(db, leading) if leading else None
            if named is not None:
                image.film_roll_id = named.id
        roll = folder_roll or (db.get(FilmRoll, image.film_roll_id) if image.film_roll_id else None)
        if roll is not None:
            lifecycle.touch_scanned(roll)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - one file must not end the sweep
        log.exception("inbox: could not take %s", shown)
        db.rollback()
        _remove_quietly(Path(destination))
        _remove_quietly(Path(destination + negpy_sidecar.SUFFIX))
        result.rejected.append((shown, f"could not be imported ({exc.__class__.__name__}: {exc})"))
        return None
    if roll is not None:
        result.filed += 1
        if roll.id not in result.roll_ids:
            result.roll_ids.append(roll.id)
    else:
        result.unassigned += 1
    result.imported += 1
    result.image_ids.append(image.id)

    # Only now, with the record committed and the copy verified, does the inbox
    # let go of the file. If this fails, the next sweep sees a duplicate and
    # removes it then.
    _remove_quietly(path)
    if sidecar_file is not None:
        _remove_quietly(sidecar_file)
    where = f"roll {roll.archive_serial or roll.title}" if roll else "no roll yet"
    return f"{shown} → frame {image.id} ({where})"


#: When this process last swept. The database only learns about sweeps that did
#: something: a row written every thirty seconds for "nothing happened" is churn.
_last_sweep_at: Optional[str] = None


def _record(db: Session, result: SweepResult) -> None:
    """Remember the last sweep for the status card. Never fails a sweep."""
    global _last_sweep_at
    _last_sweep_at = datetime.utcnow().isoformat(timespec="seconds")
    if not (result.changed or result.rejected):
        return
    try:
        settings_store.set_value(db, "inbox_last_sweep_at", _last_sweep_at)
        settings_store.set_value(db, "inbox_last_summary", result.summary())
        db.commit()
    except Exception:  # noqa: BLE001 - a status line is not worth a failed sweep
        db.rollback()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def pending(limit: int = LISTED_PENDING) -> Dict[str, Any]:
    """What is sitting in the inbox right now — count exact, names capped."""
    base = inbox_dir()
    if not base.is_dir():
        return {"count": 0, "files": []}
    files = [p for p in _walk(base) if not negpy_sidecar.is_sidecar_name(p.name)]
    listed = []
    now = time.time()
    for path in files[:limit]:
        try:
            stat = path.stat()
        except OSError:
            continue
        listed.append(
            {
                "name": str(path.relative_to(base)),
                "size": stat.st_size,
                "age_seconds": max(0, int(now - stat.st_mtime)),
                "accepted": path.suffix.lower() in ALLOWED_EXTENSIONS,
            }
        )
    return {"count": len(files), "files": listed}


def status(db: Session) -> Dict[str, Any]:
    from ..routers.system import watch_interval_seconds  # a router constant, read-only

    base = inbox_dir()
    return {
        "dir": str(base),
        "exists": base.is_dir(),
        "share": share.info(db),
        "pending": pending(),
        "last_sweep_at": _last_sweep_at or settings_store.get(db, "inbox_last_sweep_at"),
        "last_summary": settings_store.get(db, "inbox_last_summary"),
        "interval_seconds": watch_interval_seconds(),
        "filename_pattern": share.FILENAME_PATTERN,
    }
