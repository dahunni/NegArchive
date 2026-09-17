"""The watch folder: an asyncio poller over the registered library roots.

Roadmap M3, the headless equivalent of NegPy's Hot Folder. A scanner writes a new
subfolder per roll and a file per frame; this notices and turns them into a roll
draft and linked frames without anybody opening the UI.

**Polling, not inotify**, on purpose: the interesting case is a network share
(SMB/NFS) on a NAS, where filesystem events either do not exist or are not
delivered to the container. A `stat` sweep every 30 seconds is boring, portable
and cheap next to the scanning itself — and the content hash only samples 6 MiB
per file, so a sweep over an unchanged library costs almost nothing.

Controls:

* ``WATCH_INTERVAL_SECONDS`` — seconds between sweeps. Default 30. Empty, ``0``
  or ``off`` disables the task entirely (it is then never started).
* the ``watch_enabled`` setting — the toggle in the UI. Checked on every tick, so
  it takes effect without a restart.
* ``library_roots.watch`` — per folder.

The task never raises into the event loop: a poller that kills the app because a
NAS was asleep would be worse than one that logs and tries again.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..db import SessionLocal
from ..models import LibraryRoot
from . import importer, settings_store

log = logging.getLogger("negarchive.watch")


def _sweep_once() -> Optional[str]:
    """One pass over the watched roots. Returns a log line, or None if idle."""
    db = SessionLocal()
    try:
        if not settings_store.get(db, "watch_enabled"):
            return None
        roots = db.query(LibraryRoot).filter(LibraryRoot.watch.is_(True)).all()
        if not roots:
            return None
        changed = []
        for root in roots:
            result = importer.scan_root(db, root)
            if result.frames_added or result.rolls_created or result.frames_rehomed:
                changed.append(f"{root.path}: {result.summary()}")
        return "; ".join(changed) if changed else None
    finally:
        db.close()


async def watch_loop(interval_seconds: int) -> None:
    """Sweep every ``interval_seconds`` until the task is cancelled."""
    log.info("watch folder poller started, every %ss", interval_seconds)
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                # The scan is blocking file IO; keep it off the event loop.
                message = await asyncio.to_thread(_sweep_once)
                if message:
                    log.info("watch folder: %s", message)
            except Exception:  # noqa: BLE001 - a bad sweep must not kill the loop
                log.exception("watch folder sweep failed")
    except asyncio.CancelledError:
        log.info("watch folder poller stopped")
        raise
