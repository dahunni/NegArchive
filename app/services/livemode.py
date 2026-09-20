"""Live mode: one button that wires the share up so NegPy can just be worked in (M6).

The M5 integration exchanges files, and M6's share is where those files live. What
is left is the wiring — five folders, two library roots, two settings and a gear
sync — and every one of them is a thing you can get subtly wrong on your own. So
this does it, and the Settings page explains what it did.

The layout it makes on the share::

    rolls/          scans live here forever. NegArchive *links* them, never copies,
                    and NegPy opens the same folder as a library root
    exports/        what NegPy exports; a watched root too, so finished positives
                    come back into the archive on their own
    negpy-user/     gear/ and presets/metadata/ — NegArchive writes, NegPy reads
    handoff/        a prepared roll, for the times you still want one

**Why this closes the loop.** A frame in ``rolls/`` is linked, so its
``source_path`` is the file on the share. Edit it in NegPy, NegPy writes
``<name>.negpy`` beside it, and the next watcher sweep calls
:func:`app.services.importer._refresh_sidecar`, which looks for exactly that file
beside exactly that path, compares its mtime and attaches the recipe. Nobody
clicks anything. That is the whole trick, and it is why live mode uses import by
reference rather than the roll handoff: a handoff folder holds *hard links*, and a
sidecar written next to a hard link is not next to the frame's ``source_path``.

**What it will not do.** It never touches a folder that already exists, never
un-registers a root, and never turns a setting off. Run it twice and the second
run reports that there was nothing to do.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import FilmRoll, LibraryRoot
from . import settings_store, smb
from .negpy import gear as negpy_gear

log = logging.getLogger("negarchive.livemode")

#: The folders live mode makes on the share. Fixed names on purpose: the point of
#: the button is that there is nothing to decide.
ROLLS_DIR = "rolls"
EXPORTS_DIR = "exports"
USER_DIR = "negpy-user"
HANDOFF_DIR = "handoff"

#: Which of them become watched library roots, and what they are called in the UI.
WATCHED = ((ROLLS_DIR, "Scans (NegPy works here)"), (EXPORTS_DIR, "NegPy exports"))


@dataclass
class Report:
    """What live mode changed, in the order a person would want to read it."""

    mountpoint: str = ""
    folders_created: List[str] = field(default_factory=list)
    folders_existing: List[str] = field(default_factory=list)
    roots_added: List[str] = field(default_factory=list)
    roots_existing: List[str] = field(default_factory=list)
    settings_changed: Dict[str, str] = field(default_factory=dict)
    gear: Dict[str, Any] = field(default_factory=dict)
    watch_enabled: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.folders_created or self.roots_added or self.settings_changed)

    def summary(self) -> str:
        if not self.changed:
            return "Already set up — nothing to change."
        parts = []
        if self.folders_created:
            parts.append(f"{len(self.folders_created)} folders made")
        if self.roots_added:
            parts.append(f"{len(self.roots_added)} folders watched")
        if self.settings_changed:
            parts.append("NegPy folders pointed at the share")
        return ", ".join(parts) + "."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mountpoint": self.mountpoint,
            "folders_created": self.folders_created,
            "folders_existing": self.folders_existing,
            "roots_added": self.roots_added,
            "roots_existing": self.roots_existing,
            "settings_changed": self.settings_changed,
            "gear": self.gear,
            "watch_enabled": self.watch_enabled,
            "changed": self.changed,
            "summary": self.summary(),
            "client": client_steps(self.mountpoint),
        }


def client_steps(mountpoint: str) -> Dict[str, Any]:
    """The half of live mode that happens on the laptop, not the server.

    Returned with the report rather than hard-coded in the frontend, because the
    folder names here are the ones this module just made: if they ever change, the
    instructions change with them instead of quietly becoming wrong.
    """
    return {
        "rolls": f"{mountpoint}/{ROLLS_DIR}",
        "exports": f"{mountpoint}/{EXPORTS_DIR}",
        "user": f"{mountpoint}/{USER_DIR}",
        "filename_pattern": "{{ roll }}_{{ frame|pad(3) }}_{{ film }}",
    }


def scan_plan(db: Session, roll: FilmRoll) -> Dict[str, Any]:
    """What to type into NegPy's *Live View & Scan* so the frames land on *this* roll.

    NegPy's scan mode writes ``<output>/<roll name>/<roll name>_Frame001.ARW``
    (roadmap M6.1). Point its output at the share's ``rolls/`` folder and name the
    roll after the archive's serial, and :func:`app.services.importer.scan_root`
    adopts the folder onto the roll that already carries that serial — film,
    camera and lifecycle included — on the next sweep. Nothing here is remembered:
    the mount, the root and the watcher are checked when asked, like :func:`state`.
    """
    base = smb.mount_base()
    mounted = smb.is_mounted(base)
    rolls_root = str(base / ROLLS_DIR)
    root = db.query(LibraryRoot).filter(LibraryRoot.path == rolls_root).first()
    serial = roll.archive_serial or ""
    watching = bool(root and root.watch) and bool(settings_store.get(db, "watch_enabled"))
    return {
        "roll_id": roll.id,
        # The two things to type into NegPy, in the order its panel asks for them.
        "output_dir": rolls_root,
        "roll_name": serial or None,
        # What will appear, so the page can say it before it happens.
        "folder": f"{rolls_root}/{serial}" if serial else None,
        "example_file": f"{serial}_Frame001.ARW" if serial else None,
        # Whether the folder will be picked up by itself, and how soon.
        "root_id": root.id if root else None,
        "mounted": mounted,
        "watched": watching,
        "interval_seconds": _watch_interval_seconds(),
        "ready": bool(mounted and root is not None and watching and serial),
        # A roll that already has a folder keeps it; the page says so instead of
        # inviting a second one.
        "source_dir": roll.source_dir,
        "already_linked": bool(roll.source_dir),
    }


def _watch_interval_seconds() -> Optional[int]:
    """The watcher's sweep interval, read exactly as ``app.routers.system`` reads it.

    Same rules, same reasons: **unset means off**, an unparseable value means the
    default. A service does not import a router, so the lines are repeated rather
    than the edge reversed; if they drift apart the roll page and Settings would
    disagree about whether the watcher is on, and a test pins them together.
    """
    raw = (os.getenv("WATCH_INTERVAL_SECONDS") or "").strip()
    if not raw or raw.lower() in {"0", "off", "false", "none"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return 30
    return value if value > 0 else None


def _require_share(db: Session) -> Path:
    config = smb.load(db)
    if not smb.is_mounted():
        raise ApiError(
            "not_mounted",
            "Mount the share first: live mode needs a folder both this server and "
            "the machine running NegPy can see.",
            409,
            "smb",
        )
    if config.readonly:
        raise ApiError(
            "share_readonly",
            "The share is mounted read-only, so NegPy's gear and presets cannot be "
            "written to it. Turn off “Read-only” and mount again.",
            409,
            "readonly",
        )
    return smb.mount_base()


def apply(db: Session) -> Report:
    """Make the folders, register the roots, point NegPy's folders at the share."""
    base = _require_share(db)
    report = Report(mountpoint=str(base))

    for name in (ROLLS_DIR, EXPORTS_DIR, USER_DIR, HANDOFF_DIR):
        target = base / name
        if target.is_dir():
            report.folders_existing.append(str(target))
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ApiError(
                "write_failed",
                f"Could not make {target} on the share: {exc}. Does the SMB user have "
                "write access to it?",
                502,
                "smb",
            ) from exc
        report.folders_created.append(str(target))

    for name, label in WATCHED:
        path = str(base / name)
        existing = db.query(LibraryRoot).filter(LibraryRoot.path == path).first()
        if existing is not None:
            # Registered but not swept is the one case worth correcting: it is the
            # difference between live mode working and appearing not to.
            if not existing.watch:
                existing.watch = True
            report.roots_existing.append(path)
            continue
        db.add(LibraryRoot(path=path, label=label, watch=True))
        report.roots_added.append(path)

    user_dir = str(base / USER_DIR)
    handoff_dir = str(base / HANDOFF_DIR)
    if str(settings_store.get(db, "negpy_user_dir") or "") != user_dir:
        settings_store.set_value(db, "negpy_user_dir", user_dir)
        report.settings_changed["negpy_user_dir"] = user_dir
    if str(settings_store.get(db, "negpy_handoff_dir") or "") != handoff_dir:
        settings_store.set_value(db, "negpy_handoff_dir", handoff_dir)
        report.settings_changed["negpy_handoff_dir"] = handoff_dir

    # The sidecar loop *is* the watcher. Live mode without it is a share with no
    # archive attached to it.
    if not settings_store.get(db, "watch_enabled"):
        settings_store.set_value(db, "watch_enabled", True)
        report.settings_changed["watch_enabled"] = "on"
    report.watch_enabled = True

    db.commit()

    # Last, because it writes into a folder the steps above just created.
    try:
        gear_dir = base / USER_DIR / "gear"
        gear_dir.mkdir(parents=True, exist_ok=True)
        result = negpy_gear.sync(db, gear_dir)
        if result.synced_at:
            settings_store.set_value(db, "negpy_gear_synced_at", result.synced_at)
            db.commit()
        report.gear = result.to_dict()
    except (OSError, ApiError) as exc:  # noqa: BLE001 - a gear sync is not worth failing the setup
        log.warning("live mode: gear sync failed: %s", exc)
        report.gear = {"ok": False, "error": str(exc)}

    log.info("live mode applied at %s: %s", base, report.summary())
    return report


def state(db: Session) -> Dict[str, Any]:
    """Is live mode actually on? Checked, not remembered.

    Every part is verified against the world — the mount, the folders, the roots,
    the settings — so a share that went away or a root somebody removed shows up
    as "not set up" instead of a stale yes.
    """
    base = smb.mount_base()
    mounted = smb.is_mounted(base)
    roots = {root.path: root for root in db.query(LibraryRoot).all()}
    checks = []
    for name, _label in WATCHED:
        path = str(base / name)
        root = roots.get(path)
        checks.append(
            {
                "path": path,
                "exists": (base / name).is_dir() if mounted else False,
                "registered": root is not None,
                "watched": bool(root and root.watch),
            }
        )
    user_dir = str(base / USER_DIR)
    return {
        "mounted": mounted,
        "mountpoint": str(base),
        "folders": checks,
        "negpy_user_dir_on_share": str(settings_store.get(db, "negpy_user_dir") or "") == user_dir,
        "watch_enabled": bool(settings_store.get(db, "watch_enabled")),
        "ready": bool(
            mounted
            and all(check["exists"] and check["watched"] for check in checks)
            and str(settings_store.get(db, "negpy_user_dir") or "") == user_dir
            and settings_store.get(db, "watch_enabled")
        ),
        "client": client_steps(str(base)),
    }
