"""Every file NegArchive owns lives under one directory: ``DATA_DIR``.

Roadmap M3. Before this module the backend wrote into ``static/uploads``,
``static/catalog`` and ``static/cache`` *inside the source tree*, which meant the
Compose stack needed three bind mounts, a backup had to know all three, and a
`git clean` could wipe an archive. Now there is exactly one directory to mount,
back up and carry to another machine::

    data/
      postgres/     the database cluster (bind-mounted by the db service)
      uploads/      scans/ and contact_sheets/ — managed copies of your files
      catalog/      camera, lens and film stock pictures
      cache/        rendered previews, safe to delete at any time
      backups/      scripts/backup.sh writes here

``DATA_DIR`` defaults to ``./data`` and is read on every call rather than cached,
so a test can point it somewhere else with ``monkeypatch.setenv``.

**Path strings in the database are public paths**, not filesystem paths: an
``image_assets.path`` of ``static/uploads/scans/ab12.jpg`` is served at
``/static/uploads/scans/ab12.jpg`` and lives on disk at
``$DATA_DIR/uploads/scans/ab12.jpg``. Keeping that string stable is what lets an
archive created before M3 keep working — :func:`resolve` maps the old prefix onto
the new directory, and falls back to the legacy in-tree location if the file is
still sitting there.

A *linked* frame (import by reference, M3) stores an absolute ``source_path``
instead and is never copied, moved or deleted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

#: Subdirectories created on startup. ``postgres`` is created by the db container.
SUBDIRS = ("uploads/scans", "uploads/contact_sheets", "catalog/cameras", "catalog/lenses", "catalog/films", "cache", "backups")

#: Prefixes a stored path may carry before the part that is relative to DATA_DIR.
_PUBLIC_PREFIXES = ("static/", "data/", "./static/", "./data/")


def data_dir() -> Path:
    """The one directory. Absolute, so a chdir cannot move the archive."""
    return Path(os.getenv("DATA_DIR") or "data").expanduser().resolve()


def uploads_dir() -> Path:
    return data_dir() / "uploads"


def catalog_dir() -> Path:
    return data_dir() / "catalog"


def cache_dir() -> Path:
    return data_dir() / "cache"


def backups_dir() -> Path:
    return data_dir() / "backups"


def ensure_dirs(extra: Iterable[str] = ()) -> Path:
    """Create the layout if it is not there yet and return ``DATA_DIR``."""
    root = data_dir()
    for sub in (*SUBDIRS, *extra):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def public_path(*parts: str) -> str:
    """The string stored in the database for a managed file.

    ``public_path("uploads", "scans", "ab12.jpg")`` →
    ``"static/uploads/scans/ab12.jpg"``, which is both the ``/static`` URL and,
    through :func:`resolve`, a real file under ``DATA_DIR``. Always forward
    slashes: the value ends up in a URL and in an export, not only on this OS.
    """
    return "static/" + "/".join(str(p).strip("/") for p in parts if str(p).strip("/"))


def relative_part(stored: str) -> str:
    """Strip the ``static/`` (or ``data/``) prefix off a stored path."""
    value = str(stored).replace("\\", "/").lstrip("/")
    for prefix in _PUBLIC_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def resolve(stored: str | None) -> Path | None:
    """Absolute filesystem path for whatever is stored in a ``path`` column.

    Absolute values (linked files) are returned untouched. Everything else is
    resolved under ``DATA_DIR``; if that file does not exist but the pre-M3
    in-tree location does, the in-tree one wins, so an archive that has not been
    moved into ``data/`` yet keeps rendering.
    """
    if not stored:
        return None
    raw = str(stored)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate

    under_data = data_dir() / relative_part(raw)
    if under_data.exists():
        return under_data
    legacy = Path(os.getcwd()) / raw
    if legacy.exists():
        return legacy
    return under_data


def is_inside_data_dir(path: Path) -> bool:
    """True when ``path`` is a managed file, i.e. one we may delete or move."""
    try:
        path.resolve().relative_to(data_dir())
        return True
    except (ValueError, OSError):
        return False
