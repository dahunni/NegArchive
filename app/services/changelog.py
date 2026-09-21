"""Read ``CHANGELOG.md`` into something the UI can show (M7).

The file is the source of truth: a release adds an entry at the top and bumps
:data:`app.version.__version__`, and the frontend shows whatever is here. The
parser understands exactly the Keep-a-Changelog shape the file uses::

    ## [0.10.0] - 2026-09-21
    ### Added
    - one bullet, possibly
      wrapped onto the next line
    ### Fixed
    - another

Anything above the first ``## [`` heading is the preamble and is skipped. A
missing or unreadable file yields an empty list rather than an error, because a
version endpoint that 500s over a Markdown file would be worse than one that
says nothing about what changed.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

_ENTRY = re.compile(r"^##\s+\[?(?P<version>[^\]\s]+)\]?(?:\s*-\s*(?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
_SECTION = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(?P<text>.*)$")
_CONTINUATION = re.compile(r"^\s{2,}(?P<text>\S.*)$")


def parse(text: str) -> List[dict]:
    """``[{"version", "date", "sections": [{"title", "items": [...]}]}, ...]``, newest first
    (the file's own order)."""
    entries: List[dict] = []
    entry: Optional[dict] = None
    section: Optional[dict] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _ENTRY.match(line)
        if heading:
            entry = {"version": heading.group("version"), "date": heading.group("date"), "sections": []}
            entries.append(entry)
            section = None
            continue
        if entry is None:
            continue  # the preamble
        sub = _SECTION.match(line)
        if sub:
            section = {"title": sub.group("title"), "items": []}
            entry["sections"].append(section)
            continue
        bullet = _BULLET.match(line)
        if bullet:
            if section is None:
                section = {"title": "Changes", "items": []}
                entry["sections"].append(section)
            section["items"].append(bullet.group("text").strip())
            continue
        wrapped = _CONTINUATION.match(raw)
        if wrapped and section is not None and section["items"]:
            section["items"][-1] = f"{section['items'][-1]} {wrapped.group('text').strip()}"
    return entries


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


@lru_cache(maxsize=4)
def _cached(path: str, mtime: float) -> List[dict]:
    return parse(_read(Path(path)))


def entries(path: Path = CHANGELOG_PATH) -> List[dict]:
    """The parsed changelog, re-read when the file changes (a dev server edits it live)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    return _cached(str(path), mtime)


def version_key(version: str) -> Tuple[int, ...]:
    """``"0.10.0"`` → ``(0, 10, 0)`` so versions compare numerically, not as strings.

    A pre-release suffix (``1.0.0-rc1``) sorts below the release it precedes;
    anything unparseable sorts below everything.
    """
    match = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-.+)?$", (version or "").strip())
    if not match:
        return (-1,)
    parts = tuple(int(group) if group else 0 for group in match.groups()[:3])
    return parts + ((0,) if match.group(4) else (1,))


def since(entries_list: List[dict], seen: Optional[str]) -> List[dict]:
    """The entries newer than ``seen``; all of them when nothing has been seen."""
    if not seen:
        return list(entries_list)
    floor = version_key(seen)
    return [entry for entry in entries_list if version_key(entry["version"]) > floor]
