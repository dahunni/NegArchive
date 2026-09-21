"""Reading NegPy's ``edits.db`` — read-only, defensively, and never required.

Roadmap M5 (the "left for later" item). NegPy keeps every edit in
``<user dir>/edits.db``, an SQLite database whose ``file_settings`` table is keyed
by the **content hash** of the source file (`negpy/kernel/image/logic.py`), not by
its path. NegArchive computes the same hash for every frame it has
(:mod:`app.services.hashing`), so when both programs sit on the same machine the
two can be matched exactly — without a sidecar, and without either side changing
anything.

That is the whole feature: "this negative has been worked on, and here is roughly
what was done to it", for an archive whose owner never turned sidecars on.

**Three rules, and they are not negotiable.**

1. **Read-only, always.** The connection is opened with SQLite's
   ``mode=ro&immutable=1`` URI, so the driver will not write, will not create the
   file, and will not touch a journal or WAL beside it. NegPy's edits are NegPy's;
   a bug here must not be able to cost somebody their work.
2. **Never required.** No edits.db, an edits.db with a schema this does not
   recognise, a locked or corrupt file — all of them mean "no extra information",
   never an error. Everything in M5 keeps working; this only ever adds.
3. **A sidecar wins.** A ``.negpy`` file sits next to the scan and travels with it;
   edits.db is one machine's private state. Where both exist, the sidecar is what
   the archive records, and this is the fallback.

Reading a data file is not linking against a program: nothing of NegPy is imported
here, and the schema below is treated as an observation that may be wrong, not as
an interface that must hold. Hence the column sniffing — if a future NegPy renames
``settings_json``, this degrades to "no information" instead of raising.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from . import dirs
from .sidecar import Sidecar

#: What NegPy calls the file, inside its user directory.
DEFAULT_FILENAME = "edits.db"

#: The table observed in NegPy 0.59, and the alternatives worth trying.
TABLE_CANDIDATES = ("file_settings", "settings", "edits")

#: Column names, in preference order, for the three things we need.
HASH_COLUMNS = ("file_hash", "hash", "content_hash")
SETTINGS_COLUMNS = ("settings_json", "settings", "json", "data")
PATH_COLUMNS = ("file_path", "path", "source_path", "filename")
TIME_COLUMNS = ("updated_at", "modified_at", "saved_at", "timestamp", "mtime")

#: Hashes per ``IN`` clause. SQLite's default limit is 999 parameters.
CHUNK = 400


@dataclass(frozen=True)
class Layout:
    """Which columns of which table hold what, in this particular edits.db."""

    table: str
    hash_column: str
    settings_column: str
    path_column: Optional[str] = None
    time_column: Optional[str] = None


def database_path(db: Session) -> Optional[Path]:
    """Where ``edits.db`` would be, for this archive's configured user directory."""
    try:
        return dirs.user_dir(db) / DEFAULT_FILENAME
    except Exception:  # noqa: BLE001 - a misconfigured directory is not an error here
        return None


def connect(path: str | Path) -> Optional[sqlite3.Connection]:
    """An immutable, read-only connection, or ``None`` if that is not possible."""
    target = Path(path)
    try:
        if not target.is_file():
            return None
        # immutable=1 also promises SQLite that nothing else is changing the file,
        # so it takes no locks at all — a NegPy that happens to be running is not
        # disturbed, and neither is its WAL.
        # `as_uri()` percent-encodes the path, so a user directory with a `?`,
        # `#` or `%` in it does not turn into a different (nonexistent) file.
        connection = sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro&immutable=1", uri=True, timeout=2.0)
        connection.row_factory = sqlite3.Row
        return connection
    except (sqlite3.Error, OSError, ValueError):
        return None


def _tables(connection: sqlite3.Connection) -> List[str]:
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    except sqlite3.Error:
        return []
    return [str(row[0]) for row in rows]


def _columns(connection: sqlite3.Connection, table: str) -> List[str]:
    try:
        rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    except sqlite3.Error:
        return []
    return [str(row[1]) for row in rows]


def _pick(available: Iterable[str], wanted: Iterable[str]) -> Optional[str]:
    lowered = {name.lower(): name for name in available}
    for candidate in wanted:
        if candidate in lowered:
            return lowered[candidate]
    return None


def detect_layout(connection: sqlite3.Connection) -> Optional[Layout]:
    """Work out where the hashes and the settings are, or give up quietly."""
    tables = _tables(connection)
    ordered = [name for name in TABLE_CANDIDATES if name in tables] + [
        name for name in tables if name not in TABLE_CANDIDATES
    ]
    for table in ordered:
        columns = _columns(connection, table)
        hash_column = _pick(columns, HASH_COLUMNS)
        settings_column = _pick(columns, SETTINGS_COLUMNS)
        if hash_column and settings_column:
            return Layout(
                table=table,
                hash_column=hash_column,
                settings_column=settings_column,
                path_column=_pick(columns, PATH_COLUMNS),
                time_column=_pick(columns, TIME_COLUMNS),
            )
    return None


class EditsIndex:
    """One open, read-only look at an edits.db.

    Built once per request and closed afterwards: a bulk upload of 36 frames does
    one `connect` and 36 indexed lookups, not 36 connections.
    """

    def __init__(self, path: Path, connection: sqlite3.Connection, layout: Layout) -> None:
        self.path = path
        self._connection = connection
        self.layout = layout

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error:  # pragma: no cover - closing twice is harmless
            pass

    def __enter__(self) -> "EditsIndex":
        return self

    def __exit__(self, *exception) -> None:
        self.close()

    # -- reading -----------------------------------------------------------
    def row_count(self) -> Optional[int]:
        try:
            return int(self._connection.execute(f'SELECT count(*) FROM "{self.layout.table}"').fetchone()[0])
        except (sqlite3.Error, TypeError, ValueError):
            return None

    def lookup_many(self, hashes: Iterable[str]) -> Dict[str, Sidecar]:
        """``{content hash: recipe}`` for the hashes this database knows."""
        wanted = [h for h in {str(h).strip() for h in hashes if h} if h]
        found: Dict[str, Sidecar] = {}
        layout = self.layout
        for start in range(0, len(wanted), CHUNK):
            chunk = wanted[start : start + CHUNK]
            placeholders = ",".join("?" * len(chunk))
            columns = [layout.hash_column, layout.settings_column]
            if layout.path_column:
                columns.append(layout.path_column)
            if layout.time_column:
                columns.append(layout.time_column)
            selected = ", ".join(f'"{name}"' for name in columns)
            query = (
                f'SELECT {selected} FROM "{layout.table}" '
                f'WHERE "{layout.hash_column}" IN ({placeholders})'
            )
            try:
                rows = self._connection.execute(query, chunk).fetchall()
            except sqlite3.Error:
                return found
            for row in rows:
                recipe = self._to_sidecar(row)
                if recipe is not None:
                    found[str(row[layout.hash_column])] = recipe
        return found

    def lookup(self, content_hash: Optional[str]) -> Optional[Sidecar]:
        if not content_hash:
            return None
        return self.lookup_many([content_hash]).get(str(content_hash).strip())

    def _to_sidecar(self, row: sqlite3.Row) -> Optional[Sidecar]:
        """One row as the same object a ``.negpy`` sidecar produces.

        Reusing :class:`~app.services.negpy.sidecar.Sidecar` is the point: the
        viewer, the API and the tests then cannot tell — and must not care —
        whether a recipe came from a file beside the scan or from this database.
        """
        layout = self.layout
        raw = row[layout.settings_column]
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None

        edited_at = None
        if layout.time_column:
            edited_at = _as_datetime(row[layout.time_column])
        if edited_at is None:
            edited_at = _file_mtime(self.path)

        payload: Dict[str, Any] = {"settings": data, "file_hash": row[layout.hash_column]}
        if layout.path_column:
            payload["file_path"] = row[layout.path_column]
        return Sidecar(path=str(self.path), edited_at=edited_at, data=payload)


def _as_datetime(value: Any):
    from datetime import datetime

    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value))
        except (OverflowError, OSError, ValueError):
            return None
    from .sidecar import parse_utc

    return parse_utc(str(value))


def _file_mtime(path: Path):
    from datetime import datetime

    try:
        return datetime.utcfromtimestamp(path.stat().st_mtime)
    except OSError:  # pragma: no cover
        return None


def open_index(db: Session, path: Optional[str | Path] = None) -> Optional[EditsIndex]:
    """The archive's edits.db, ready to query — or ``None``, which is not an error."""
    target = Path(path) if path else database_path(db)
    if target is None:
        return None
    connection = connect(target)
    if connection is None:
        return None
    layout = detect_layout(connection)
    if layout is None:
        connection.close()
        return None
    return EditsIndex(target, connection, layout)


def describe(db: Session) -> Dict[str, Any]:
    """What Settings says about edits.db: where it is, and whether it is readable."""
    target = database_path(db)
    report: Dict[str, Any] = {
        "path": str(target) if target else None,
        "exists": bool(target and target.is_file()),
        "readable": False,
        "table": None,
        "rows": None,
    }
    if not report["exists"]:
        return report
    index = open_index(db, target)
    if index is None:
        return report
    try:
        report["readable"] = True
        report["table"] = index.layout.table
        report["rows"] = index.row_count()
    finally:
        index.close()
    return report
