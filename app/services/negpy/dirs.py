"""Where NegArchive may write files *for* NegPy, and where it may not (M5).

Two of M5's features write to disk outside the database: the gear library
(``gear/cameras.json`` and friends, written into NegPy's user directory) and the
roll handoff (a folder of scans plus ``presets/metadata/<serial>.json``). Both are
triggered by an HTTP request on a LAN where, by default, there is no password —
so "POST me a path and I will write files into it" is not an option. This module
is the one place that turns a configured or requested path into a directory the
app is allowed to write in.

**The default needs no configuration and leaves the machine alone.** With nothing
set, both targets live inside NegArchive's own data directory::

    $DATA_DIR/negpy/user/        gear/, presets/metadata/   ← point NEGPY_USER_DIR here,
                                                              or copy it into NegPy's
    $DATA_DIR/negpy/handoff/     <serial>/ per prepared roll

which is backed up with everything else and can be carried to the machine NegPy
runs on. To write straight into NegPy's real user directory instead, set
``NEGPY_USER_DIR`` (the same variable NegPy itself reads) and/or
``NEGPY_EXPORT_DIR`` in the environment; those two, plus anything listed in
``NEGPY_DIRS_ALLOW`` and the library roots from ``LIBRARY_ROOTS_ALLOW``, are the
bases a *setting* may then point inside. A path outside all of them is refused
with a 403 that names the bases, exactly like M3's library roots.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from ... import paths
from ...errors import ApiError
from .. import settings_store, share, smb

#: Subdirectory of ``DATA_DIR`` used when nothing is configured.
DEFAULT_SUBDIR = "negpy"


def _env_path(name: str) -> Optional[Path]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def default_user_dir() -> Path:
    return paths.data_dir() / DEFAULT_SUBDIR / "user"


def default_handoff_dir() -> Path:
    return paths.data_dir() / DEFAULT_SUBDIR / "handoff"


def allowed_bases() -> List[Path]:
    """Directories a configured path may live in or under.

    Always includes ``$DATA_DIR/negpy``, so the feature works out of the box; adds
    ``NEGPY_USER_DIR``, ``NEGPY_EXPORT_DIR``, every entry of ``NEGPY_DIRS_ALLOW``
    and every entry of ``LIBRARY_ROOTS_ALLOW`` (a folder NegArchive already reads
    scans from is a reasonable place to hand a roll back to).
    """
    bases: List[Path] = [paths.data_dir() / DEFAULT_SUBDIR]
    # M6: the share, while it is mounted. This is what makes live mode work with
    # nothing in the environment — gear/ and presets/ are written onto the share,
    # where the machine running NegPy can see them.
    if smb.is_mounted():
        bases.append(smb.mount_base())
    # M6.2: the archive's own share, always — it is a folder under DATA_DIR.
    bases.append(share.base())
    for name in ("NEGPY_USER_DIR", "NEGPY_EXPORT_DIR"):
        found = _env_path(name)
        if found is not None:
            bases.append(found)
    for name in ("NEGPY_DIRS_ALLOW", "LIBRARY_ROOTS_ALLOW"):
        for part in (os.getenv(name) or "").split(os.pathsep):
            part = part.strip()
            if part:
                bases.append(Path(part).expanduser())
    seen: List[Path] = []
    for base in bases:
        try:
            resolved = base.resolve()
        except OSError:  # pragma: no cover - a path that cannot even be resolved
            continue
        if resolved not in seen:
            seen.append(resolved)
    return seen


def is_allowed(candidate: Path) -> bool:
    try:
        resolved = candidate.expanduser().resolve()
    except OSError:  # pragma: no cover
        return False
    for base in allowed_bases():
        if resolved == base or base in resolved.parents:
            return True
    return False


def validate(path: str, field: str) -> Path:
    """Resolve a configured directory, refusing anything outside :func:`allowed_bases`.

    The directory does not have to exist yet — it is created on first write — but
    its location is checked now, when the person setting it can still see why.
    """
    text = str(path or "").strip()
    if not text:
        raise ApiError("invalid_path", "A folder path is required.", 400, field)
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ApiError(
            "invalid_path",
            "Use an absolute path: a relative one means something different to the "
            "server than it does to you.",
            400,
            field,
        )
    if not is_allowed(candidate):
        raise ApiError(
            "path_not_allowed",
            "That folder is outside the ones NegArchive may write to: "
            + ", ".join(str(base) for base in allowed_bases())
            + ". Set NEGPY_USER_DIR, NEGPY_EXPORT_DIR or NEGPY_DIRS_ALLOW and restart.",
            403,
            field,
        )
    return candidate.resolve()


def _configured(db: Session, key: str, env_name: str, fallback: Path) -> Path:
    """Setting first, then the environment variable, then the default."""
    stored = (settings_store.get(db, key) or "").strip()
    if stored:
        candidate = Path(stored).expanduser()
        if is_allowed(candidate):
            return candidate
        # A path that was allowed when it was saved and is not any more (someone
        # changed the environment) must not silently write somewhere else.
        raise ApiError(
            "path_not_allowed",
            f"The configured folder {stored} is no longer inside the folders NegArchive "
            "may write to. Fix it in Settings, or restore the environment variable.",
            403,
            key,
        )
    from_env = _env_path(env_name)
    if from_env is not None:
        return from_env
    return fallback


def user_dir(db: Session) -> Path:
    """NegPy's user directory: the one holding ``gear/`` and ``presets/``."""
    return _configured(db, "negpy_user_dir", "NEGPY_USER_DIR", default_user_dir())


def handoff_dir(db: Session) -> Path:
    """Where a prepared roll folder is written."""
    return _configured(db, "negpy_handoff_dir", "NEGPY_EXPORT_DIR", default_handoff_dir())


def gear_dir(db: Session) -> Path:
    return user_dir(db) / "gear"


def presets_dir(db: Session) -> Path:
    return user_dir(db) / "presets" / "metadata"


def ensure(directory: Path) -> Path:
    """Create ``directory`` (and its parents) and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory
