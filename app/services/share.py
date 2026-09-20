"""The archive's own share: one folder the stack serves over SMB (M6.2, M6.3).

NegArchive is a container on a server; NegPy is a desktop app on a laptop. M6
closed that gap by mounting *somebody else's* share — a NAS — into the container.
The owner did not want a NAS in the loop, so the stack now serves a share itself:
the ``smb`` service in docker-compose.yml exports ``$DATA_DIR/share``, and this
module is the one place that knows its layout and its address.

The layout, all of it on the one share::

    share/
      inbox/        NegPy's finished exports land here and are taken into the
                    archive and deleted (app/services/inbox.py)
      rolls/        camera scans, one folder per roll named after its serial; the
                    archive *links* them and NegPy edits them in place
      negpy-user/   gear/ and presets/metadata/ — the archive writes, NegPy reads
      handoff/      a prepared roll, for the times you still want one

Nothing privileged is involved: the share is a normal container on one port, and
the folders are ordinary directories under ``DATA_DIR``, in every backup.

**Permissions.** Samba writes as its own user (uid 1000 by default), the API
runs as root, and NegPy has to be able to create folders in ``rolls/`` and files
in ``inbox/``. So the layout is made world-writable by :func:`ensure_layout`. It
is a letterbox on a home LAN, not a filing cabinet with locks, and the archive's
own copies of everything live elsewhere under ``DATA_DIR``.

**The address.** ``smb://<host>[:port]/<name>``. The host is, in order: the
``share_host`` setting (M6.3 — an IP or a hostname; Finder connects here), the
``SHARE_HOST`` environment variable, the hostname of the links override
(``public_base_url``), and finally the LAN addresses this machine looks
reachable on. The links override and the share override are deliberately two
settings: the web UI may sit behind a proxy on a name, while SMB wants the box's
own address.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from .. import paths
from . import network, settings_store

log = logging.getLogger("negarchive.share")

#: Where the served folder is, inside the container. Overridable for a laptop or a test.
SHARE_DIR_ENV = "SHARE_DIR"

#: The folders on it. Fixed names on purpose: there is nothing to decide.
INBOX_DIR = "inbox"
ROLLS_DIR = "rolls"
USER_DIR = "negpy-user"
HANDOFF_DIR = "handoff"
LAYOUT = (INBOX_DIR, ROLLS_DIR, USER_DIR, HANDOFF_DIR)

#: How the `smb` service is reachable. The password is that service's alone.
SHARE_NAME_ENV = "SHARE_NAME"
SHARE_USER_ENV = "SHARE_USER"
SHARE_PORT_ENV = "SHARE_PORT"
SHARE_HOST_ENV = "SHARE_HOST"
DEFAULT_SHARE_NAME = "negarchive"
DEFAULT_SHARE_USER = "negarchive"
DEFAULT_SHARE_PORT = 445

#: NegPy's export filename pattern that puts roll, frame and film in the name.
FILENAME_PATTERN = "{{ roll }}_{{ frame|pad(3) }}_{{ film }}"


# ---------------------------------------------------------------------------
# Where it is
# ---------------------------------------------------------------------------


def base() -> Path:
    raw = (os.getenv(SHARE_DIR_ENV) or "").strip()
    return Path(raw).expanduser().resolve() if raw else paths.data_dir() / "share"


def folder(name: str) -> Path:
    return base() / name


def ensure_layout() -> Path:
    """Make the folders and make them writable by the share's user. Idempotent."""
    root = base()
    for target in (root, *(root / name for name in LAYOUT)):
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(target, 0o777)
        except OSError as exc:  # pragma: no cover - a read-only or foreign filesystem
            log.warning("share: could not open %s to the share's user: %s", target, exc)
    return root


# ---------------------------------------------------------------------------
# How to reach it
# ---------------------------------------------------------------------------


def name() -> str:
    return (os.getenv(SHARE_NAME_ENV) or "").strip() or DEFAULT_SHARE_NAME


def user() -> str:
    return (os.getenv(SHARE_USER_ENV) or "").strip() or DEFAULT_SHARE_USER


def port() -> int:
    try:
        return int((os.getenv(SHARE_PORT_ENV) or "").strip() or DEFAULT_SHARE_PORT)
    except ValueError:
        return DEFAULT_SHARE_PORT


def host_override(db: Optional[Session] = None) -> Optional[str]:
    """The address Finder should connect to, when somebody said so.

    A bare host or IP; a pasted ``smb://host/whatever`` or ``host:445`` is
    forgiven and reduced to the host. Falls back to the links override's
    hostname, because a box that is called ``archive.local`` for the browser is
    usually called that for SMB too — until it is not, which is why the setting
    exists on its own.
    """
    candidates = []
    if db is not None:
        candidates.append(settings_store.get(db, "share_host"))
    candidates.append(os.getenv(SHARE_HOST_ENV))
    for raw in candidates:
        text = str(raw or "").strip()
        if text:
            return _host_only(text)
    links = network.ui_host(db)
    return links or None


def _host_only(text: str) -> str:
    if "://" in text:
        return urlsplit(text).hostname or text
    return text.split("/", 1)[0].rsplit(":", 1)[0] if ":" in text and not text.startswith("[") else text.split("/", 1)[0]


def urls(db: Optional[Session] = None) -> List[str]:
    """``smb://`` addresses a Mac can paste into Finder, best first."""
    override = host_override(db)
    hosts = ([override] if override else []) + [ip for ip in network.lan_ips() if ip != override]
    suffix = "" if port() == DEFAULT_SHARE_PORT else f":{port()}"
    return [f"smb://{host}{suffix}/{name()}" for host in hosts]


def mac_root() -> str:
    """What Finder mounts the share as."""
    return f"/Volumes/{name()}"


def mac_path(sub: str = "") -> str:
    return f"{mac_root()}/{sub}" if sub else mac_root()


def info(db: Optional[Session] = None) -> Dict[str, Any]:
    all_urls = urls(db)
    return {
        "name": name(),
        "user": user(),
        "port": port(),
        "host_override": host_override(db),
        "urls": all_urls,
        "url": all_urls[0] if all_urls else None,
        "mac_root": mac_root(),
        # Kept for the card that predates the layout: the inbox is NegPy's export folder.
        "mac_path": mac_path(INBOX_DIR),
        "dir": str(base()),
        "folders": {sub: str(folder(sub)) for sub in LAYOUT},
        "mac_folders": {sub: mac_path(sub) for sub in LAYOUT},
        "filename_pattern": FILENAME_PATTERN,
    }
