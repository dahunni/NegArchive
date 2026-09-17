"""The handful of settings that must survive a container restart.

Anything that describes *this deployment* (ports, paths, passwords) is an
environment variable. Anything the person using the archive toggles in the UI
lives here, in the database, so it is part of a backup and comes back with a
restore. Today that is exactly one thing — whether the watch folder poller runs —
but the table is the seam for the M4/M6 settings that will follow.

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
