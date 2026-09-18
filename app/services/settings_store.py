"""The handful of settings that must survive a container restart.

Anything that describes *this deployment* (ports, paths, passwords) is an
environment variable. Anything the person using the archive toggles in the UI
lives here, in the database, so it is part of a backup and comes back with a
restore: the watch folder toggle, the serial prefix, the NegPy folders and — since
M6 — the network share those folders usually live on.

One thing deliberately does *not* live here: the SMB password. Settings are
exported, and an export ZIP that carries the NAS password is a copy of the NAS
password on every machine the archive was ever restored to. It is written to
``$DATA_DIR/.smb/credentials`` (mode 0600) instead; see
:mod:`app.services.smb`.

Keys are allowlisted on purpose: a settings table that takes any key is an
untyped column of mystery strings a year later.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from ..models import Setting

TRUE_VALUES = {"1", "true", "yes", "on"}

#: key → (kind, default). ``kind`` is "bool" or "text".
KNOWN_SETTINGS: Dict[str, tuple[str, Any]] = {
    # Master switch for the background poller. The interval itself is
    # WATCH_INTERVAL_SECONDS, because how often a machine may hit the disk is a
    # deployment decision, not a user preference.
    "watch_enabled": ("bool", True),
    # M4: the serial prefix (NEG-2024-0011) and where printed QR codes point. The
    # base URL is a setting rather than an env var because the QR on a binder has to
    # outlive whatever the LAN happens to hand this box today.
    "serial_prefix": ("text", "NEG"),
    "public_base_url": ("text", ""),
    # Label sizes in millimetres, "width x height". Plain-paper cut-outs (M4_PAPER.md).
    "label_spine_mm": ("text", "50x200"),
    "label_sticker_mm": ("text", "50x25"),
    # M5, NegPy. Reading a file's own metadata on upload is on by default: it only
    # ever fills a field that is empty, and a scan that already knows its roll and
    # frame number is the whole reason the integration exists.
    "negpy_ingest": ("bool", True),
    # Creating catalog entries for gear a scan names but the archive does not have
    # is off by default: the Gear page is a catalog somebody curated, and filling it
    # from EXIF strings produces "NIKON CORPORATION NIKON F5" next to "Nikon F5".
    "negpy_create_gear": ("bool", False),
    # Where NegPy's user directory is, and where prepared roll folders go. Empty
    # means "NEGPY_USER_DIR / NEGPY_EXPORT_DIR, else inside DATA_DIR"; a value has
    # to sit inside an allowed base (app/services/negpy/dirs.py).
    "negpy_user_dir": ("text", ""),
    "negpy_handoff_dir": ("text", ""),
    # "link" (hard links, no disk cost) or "copy".
    "negpy_handoff_mode": ("text", "link"),
    # Set by the last successful gear sync, so Settings can say when it last ran.
    "negpy_gear_synced_at": ("text", ""),
    # M6: the network share NegArchive and NegPy both work in
    # (app/services/smb.py). These describe a share the way you would describe it
    # to a colleague — the password is *not* here: it lives in
    # $DATA_DIR/.smb/credentials with mode 0600, so it is neither in the database
    # nor in an export ZIP.
    "smb_enabled": ("bool", False),
    "smb_host": ("text", ""),
    "smb_share": ("text", ""),
    "smb_subpath": ("text", ""),
    "smb_username": ("text", ""),
    "smb_domain": ("text", ""),
    "smb_version": ("text", "3.0"),
    # A read-only mount cannot hold NegPy's gear and presets, so live mode needs
    # this off; it is offered for an archive that only ever reads a scanner's share.
    "smb_readonly": ("bool", False),
    # A mount does not survive the container, so the default is to make it again
    # at startup.
    "smb_automount": ("bool", True),
    # M5: how previews are rendered — "auto" prints a frame the archive knows is
    # a negative (its film stock says so, or NegPy has an edit for it) as a
    # positive and leaves everything else alone; "raw" always shows the scan as
    # stored; "positive" always prints. The scan itself is never changed: a
    # rendering lives in the disposable preview cache.
    "preview_render": ("text", "auto"),
}


def _coerce(kind: str, raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    if kind == "bool":
        return str(raw).strip().lower() in TRUE_VALUES
    return raw


def get_all(db: Session) -> Dict[str, Any]:
    stored = {row.key: row.value for row in db.query(Setting).all()}
    return {
        key: _coerce(kind, stored.get(key), default)
        for key, (kind, default) in KNOWN_SETTINGS.items()
    }


def get(db: Session, key: str) -> Any:
    kind, default = KNOWN_SETTINGS[key]
    row = db.get(Setting, key)
    return _coerce(kind, row.value if row else None, default)


def set_value(db: Session, key: str, value: Any) -> Any:
    """Write one allowlisted setting. The caller commits."""
    kind, default = KNOWN_SETTINGS[key]
    if kind == "bool":
        if isinstance(value, bool):
            stored = "true" if value else "false"
        else:
            stored = "true" if str(value).strip().lower() in TRUE_VALUES else "false"
    else:
        stored = None if value is None else str(value)

    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=stored)
        db.add(row)
    else:
        row.value = stored
    return _coerce(kind, stored, default)
