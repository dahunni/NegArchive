"""Live mode: one button that wires the archive's own share up for NegPy (M6, M6.3).

The M5 integration exchanges files; the share (:mod:`app.services.share`) is
where those files live. What is left is the wiring — a watched folder, two
settings and a gear sync — and every one of them is a thing you can get subtly
wrong on your own. So this does it, and the Settings page explains what it did.

The layout it wires up, all on the one share the stack serves::

    inbox/          NegPy's exports; taken into the archive and deleted
                    (app/services/inbox.py — swept whether or not this ran)
    rolls/          camera scans, a folder per roll. NegArchive *links* them,
                    never copies, and NegPy opens the same folder
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

Until M6.3 this targeted a NAS share mounted *into* the container. The owner did
not want a NAS in the loop, so the base is now the folder the stack serves
itself; nothing has to be mounted before this can run, and the old
``exports/`` root is gone — the inbox is where exports go, and it empties itself.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import FilmRoll, LibraryRoot
from . import settings_store, share
from .negpy import gear as negpy_gear

log = logging.getLogger("negarchive.livemode")

#: Names kept as module constants for the code and tests that import them.
ROLLS_DIR = share.ROLLS_DIR
INBOX_DIR = share.INBOX_DIR
USER_DIR = share.USER_DIR
HANDOFF_DIR = share.HANDOFF_DIR

#: The one folder that becomes a watched library root, and what it is called in the UI.
#: The inbox is not a root — it is emptied, not indexed.
WATCHED = ((ROLLS_DIR, "Scans (NegPy works here)"),)


@dataclass
class Report:
    """What live mode changed, in the order a person would want to read it."""

    base: str = ""
    folders_created: List[str] = field(default_factory=list)
    folders_existing: List[str] = field(default_factory=list)
    roots_added: List[str] = field(default_factory=list)
    roots_existing: List[str] = field(default_factory=list)
    settings_changed: Dict[str, str] = field(default_factory=dict)
    gear: Dict[str, Any] = field(default_factory=dict)
    watch_enabled: bool = False
    client: Dict[str, Any] = field(default_factory=dict)

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
            parts.append(f"{len(self.roots_added)} folder watched")
        if self.settings_changed:
            parts.append("NegPy folders pointed at the share")
        return ", ".join(parts) + "."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base": self.base,
            "mountpoint": self.base,  # the name the first frontend used
            "folders_created": self.folders_created,
            "folders_existing": self.folders_existing,
            "roots_added": self.roots_added,
            "roots_existing": self.roots_existing,
            "settings_changed": self.settings_changed,
            "gear": self.gear,
            "watch_enabled": self.watch_enabled,
            "changed": self.changed,
            "summary": self.summary(),
            "client": self.client,
        }


def client_steps(db: Optional[Session] = None) -> Dict[str, Any]:
    """The half of live mode that happens on the laptop, not the server.

    Returned by the backend rather than hard-coded in the frontend, because the
    folder names here are the ones this module makes: if they ever change, the
    instructions change with them instead of quietly becoming wrong. Paths are
    the Mac's — ``/Volumes/<share>/…`` — since that is where they get pasted.
    """
    info = share.info(db)
    return {
        "urls": info["urls"],
        "url": info["url"],
        "user": info["user"],
        "mac_root": info["mac_root"],
        "rolls": share.mac_path(ROLLS_DIR),
        "inbox": share.mac_path(INBOX_DIR),
        "exports": share.mac_path(INBOX_DIR),  # the old name for the same step
        "user_dir": share.mac_path(USER_DIR),
        "handoff": share.mac_path(HANDOFF_DIR),
        "filename_pattern": share.FILENAME_PATTERN,
    }


def scan_plan(db: Session, roll: FilmRoll) -> Dict[str, Any]:
    """What to type into NegPy's *Live View & Scan* so the frames land on *this* roll.

    NegPy's scan mode writes ``<output>/<roll name>/<roll name>_Frame001.ARW``
    (roadmap M6.1). Point its output at the share's ``rolls/`` folder and name the
    roll after the archive's serial, and :func:`app.services.importer.scan_root`
    adopts the folder onto the roll that already carries that serial — film,
    camera and lifecycle included — on the next sweep. Nothing here is remembered:
    the folder, the root and the watcher are checked when asked, like :func:`state`.
    """
    rolls_dir = share.folder(ROLLS_DIR)
    rolls_root = str(rolls_dir)
    root = db.query(LibraryRoot).filter(LibraryRoot.path == rolls_root).first()
    serial = roll.archive_serial or ""
    watching = bool(root and root.watch) and bool(settings_store.get(db, "watch_enabled"))
    return {
        "roll_id": roll.id,
        # The two things to type into NegPy, in the order its panel asks for them —
        # as the Mac sees them, which is where they get typed.
        "output_dir": rolls_root,
        "mac_output_dir": share.mac_path(ROLLS_DIR),
        "roll_name": serial or None,
        # What will appear, so the page can say it before it happens.
        "folder": f"{rolls_root}/{serial}" if serial else None,
        "example_file": f"{serial}_Frame001.ARW" if serial else None,
        # Whether the folder will be picked up by itself, and how soon.
        "root_id": root.id if root else None,
        "served": rolls_dir.is_dir(),
        "mounted": rolls_dir.is_dir(),  # the first frontend's name for it
        "watched": watching,
        "interval_seconds": _watch_interval_seconds(),
        "ready": bool(rolls_dir.is_dir() and root is not None and watching and serial),
        # A roll that already has a folder keeps it; the page says so instead of
        # inviting a second one.
        "source_dir": roll.source_dir,
        "already_linked": bool(roll.source_dir),
        "share": share.info(db),
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


def apply(db: Session) -> Report:
    """Make the folders, register the root, point NegPy's folders at the share."""
    # Looked at *before* ensure_layout makes them, so the report can tell "made
    # just now" from "was already there". (Startup makes them too, so after a
    # restart every folder is, truthfully, already there.)
    existed = {name: (share.base() / name).is_dir() for name in share.LAYOUT}
    try:
        base = share.ensure_layout()
    except OSError as exc:
        raise ApiError("write_failed", f"Could not make the share's folders under {share.base()}: {exc}", 500) from exc
    report = Report(base=str(base))

    for name in share.LAYOUT:
        target = base / name
        (report.folders_existing if existed[name] else report.folders_created).append(str(target))

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

    report.client = client_steps(db)
    log.info("live mode applied at %s: %s", base, report.summary())
    return report


def state(db: Session) -> Dict[str, Any]:
    """Is live mode actually on? Checked, not remembered.

    Every part is verified against the world — the folders, the root, the
    settings — so a root somebody removed shows up as "not set up" instead of a
    stale yes.
    """
    base = share.base()
    served = base.is_dir()
    roots = {root.path: root for root in db.query(LibraryRoot).all()}
    checks = []
    for name, _label in WATCHED:
        path = str(base / name)
        root = roots.get(path)
        checks.append(
            {
                "path": path,
                "exists": (base / name).is_dir(),
                "registered": root is not None,
                "watched": bool(root and root.watch),
            }
        )
    folders = {name: (base / name).is_dir() for name in share.LAYOUT}
    user_dir = str(base / USER_DIR)
    on_share = str(settings_store.get(db, "negpy_user_dir") or "") == user_dir
    watch_on = bool(settings_store.get(db, "watch_enabled"))
    return {
        "served": served,
        "mounted": served,  # the first frontend's name for it
        "base": str(base),
        "mountpoint": str(base),
        "layout": folders,
        "folders": checks,
        "negpy_user_dir_on_share": on_share,
        "watch_enabled": watch_on,
        "ready": bool(served and all(folders.values()) and all(c["exists"] and c["watched"] for c in checks) and on_share and watch_on),
        "client": client_steps(db),
    }
