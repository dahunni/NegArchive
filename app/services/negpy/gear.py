"""NegArchive's catalog, written as NegPy gear files (M5).

NegPy keeps its cameras, lenses and film stocks as JSON under ``<user dir>/gear/``
and reloads them when the file's mtime changes; there is no import UI, because
"the JSON files *are* the interface" (docs/NEGPY_INTEGRATION.md). So the whole of
"gear sync" is: write three files, in NegPy's camelCase schema, without standing
on anything that is not ours.

**Ids carry the ownership.** Every entry this writes is
``na-cam-<id>`` / ``na-lens-<id>`` / ``na-film-<id>``, built from the NegArchive
row id. Two things follow, and they are the reason the prefix exists:

* an entry whose id does **not** start with ``na-`` is NegPy's own — bundled or
  hand-written — and is read, kept and written back untouched, in its original
  order;
* an ``na-`` entry that no longer has a row behind it was deleted in NegArchive,
  so it is dropped. A sync is therefore a mirror of the catalog, not an
  append-only pile.

NegPy's bundled entries win on an id collision, which the prefix makes impossible
anyway.

Both file shapes are handled, because it costs four lines and guessing wrong
would quietly destroy somebody's gear library: a bare JSON array, and an object
wrapping one (``{"cameras": [...]}``). Whatever shape the existing file has is
the shape it keeps.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from ...models import Camera, FilmKind, FilmStock, Lens

#: One file per kind, and the id prefix that marks our rows inside it.
FILES = {
    "cameras": ("cameras.json", "na-cam-"),
    "lenses": ("lenses.json", "na-lens-"),
    "film_stocks": ("film_stocks.json", "na-film-"),
}

#: NegArchive's film kinds in NegPy's spelling.
COLOR_TYPES = {
    FilmKind.color: "ColorNegative",
    FilmKind.black_and_white: "B&W Negative",
    FilmKind.slide: "ColorSlide",
    FilmKind.motion_picture: "Other",
}

#: ``50mm f/1.8``, ``AF-S 24-70mm f/2.8G``: the numbers NegPy has fields for. A
#: zoom reports its short end. The aperture's ``f`` must not be the tail of a
#: word (``EF 50mm``, ``AF 50mm``) and must not be followed by ``mm``.
_FOCAL = re.compile(r"(\d{1,4}(?:\.\d+)?)(?:\s*-\s*\d{1,4}(?:\.\d+)?)?\s*mm", re.IGNORECASE)
_APERTURE = re.compile(r"(?<![A-Za-z])f\s*/?\s*(\d{1,2}(?:\.\d+)?)(?!\s*mm)", re.IGNORECASE)


def split_name(name: str) -> Tuple[Optional[str], str]:
    """``"Nikon F5"`` → ``("Nikon", "F5")``; a one-word name has no make.

    Only the first space is used, and only when what follows it is not empty:
    NegPy shows ``displayName``, so a wrong split costs nothing but a slightly
    odd ``make`` field, while refusing to split at all would leave the field
    empty for every camera that has one.
    """
    cleaned = (name or "").strip()
    head, _, rest = cleaned.partition(" ")
    if head and rest.strip():
        return head, rest.strip()
    return None, cleaned


def camera_entry(camera: Camera) -> Dict[str, Any]:
    make, model = split_name(camera.name)
    notes = [camera.notes or ""]
    if camera.mount:
        # NegPy has no mount field; the mapping table puts it in notes.
        notes.append(f"Mount: {camera.mount}")
    return {
        "id": f"na-cam-{camera.id}",
        "displayName": camera.name,
        "make": make,
        "model": model,
        "notes": "\n".join(part for part in notes if part.strip()) or None,
        "source": "NegArchive",
    }


def lens_entry(lens: Lens) -> Dict[str, Any]:
    make, model = split_name(lens.name)
    focal = _FOCAL.search(lens.name or "")
    aperture = _APERTURE.search(lens.name or "")
    notes = [lens.notes or ""]
    if lens.mount:
        notes.append(f"Mount: {lens.mount}")
    return {
        "id": f"na-lens-{lens.id}",
        "displayName": lens.name,
        "make": make,
        "model": model,
        "lensModel": lens.name,
        "focalLength": float(focal.group(1)) if focal else None,
        "maxAperture": float(aperture.group(1)) if aperture else None,
        "notes": "\n".join(part for part in notes if part.strip()) or None,
        "source": "NegArchive",
    }


def film_entry(stock: FilmStock) -> Dict[str, Any]:
    kind = stock.kind if isinstance(stock.kind, FilmKind) else None
    return {
        "id": f"na-film-{stock.id}",
        "displayName": stock.name,
        "manufacturer": stock.manufacturer,
        "stockName": stock.name,
        "iso": stock.iso,
        "colorType": COLOR_TYPES.get(kind, "Other"),
        "format": stock.format,
        "expired": bool(stock.expired),
        "source": "NegArchive",
    }


# ---------------------------------------------------------------------------
# Reading and writing the files
# ---------------------------------------------------------------------------


@dataclass
class GearFile:
    """An existing gear file: its entries, and the shape to write it back in."""

    entries: List[dict] = field(default_factory=list)
    #: The key the list sits under (``{"cameras": [...]}``), or None for a bare array.
    wrapper: Optional[str] = None
    #: Every other top-level key of a wrapped file, written back untouched.
    extra: Dict[str, Any] = field(default_factory=dict)


def _load(path: Path) -> Optional[GearFile]:
    """The existing gear file, an empty one if there is none — or **None** when the
    file is there but cannot be read.

    That last case is the important one: a file NegPy is halfway through writing,
    or a share that hiccups, must not be replaced by a file holding only the
    archive's entries. The caller skips the file and reports it.
    """
    if not path.exists():
        return GearFile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if isinstance(raw, list):
        return GearFile(entries=[entry for entry in raw if isinstance(entry, dict)])
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, list):
                extra = {k: v for k, v in raw.items() if k != key}
                return GearFile(entries=[entry for entry in value if isinstance(entry, dict)], wrapper=key, extra=extra)
        return GearFile(extra=dict(raw))
    return None


def merge(existing: List[dict], ours: List[dict], prefix: str) -> List[dict]:
    """Our entries on top of theirs, in place, keeping everything that is not ours.

    Entries we wrote before keep their position in the file, so a diff of two
    syncs is readable; new ones are appended.
    """
    by_id = {str(entry.get("id")): entry for entry in ours}
    merged: List[dict] = []
    seen: set[str] = set()
    for entry in existing:
        entry_id = str(entry.get("id") or "")
        if not entry_id.startswith(prefix):
            merged.append(entry)  # NegPy's own, or somebody else's: untouched
            continue
        replacement = by_id.get(entry_id)
        if replacement is not None:  # ours, still in the catalog: updated in place
            merged.append(replacement)
            seen.add(entry_id)
        # ours, no longer in the catalog: dropped
    for entry in ours:
        entry_id = str(entry.get("id"))
        if entry_id not in seen:
            merged.append(entry)
    return merged


def _write(path: Path, entries: List[dict], existing: GearFile) -> None:
    """Write the file atomically: NegPy watches mtimes and may read at any moment."""
    payload: Any = entries
    if existing.wrapper or existing.extra:
        payload = dict(existing.extra)
        payload[existing.wrapper or "entries"] = entries
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temp name: two syncs at once (live mode and the button) must not
    # rename each other's half-written file into place.
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class SyncResult:
    """What one gear sync wrote."""

    directory: str = ""
    dry_run: bool = False
    files: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    synced_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "directory": self.directory,
            "dry_run": self.dry_run,
            "files": self.files,
            "synced_at": self.synced_at,
            "total": sum(item["ours"] for item in self.files.values()),
        }


def sync(db: Session, directory: Path, *, dry_run: bool = False) -> SyncResult:
    """Write (or, with ``dry_run``, only report) the three gear files."""
    ours: Dict[str, List[dict]] = {
        "cameras": [camera_entry(c) for c in db.query(Camera).order_by(Camera.id.asc()).all()],
        "lenses": [lens_entry(l) for l in db.query(Lens).order_by(Lens.id.asc()).all()],
        "film_stocks": [film_entry(s) for s in db.query(FilmStock).order_by(FilmStock.id.asc()).all()],
    }

    result = SyncResult(directory=str(directory), dry_run=dry_run)
    for kind, entries in ours.items():
        filename, prefix = FILES[kind]
        path = directory / filename
        current = _load(path)
        if current is None:
            # Unreadable: leave it exactly as it is rather than overwrite NegPy's
            # own entries with ours. The report says so; the next sync retries.
            result.files[kind] = {
                "path": str(path),
                "ours": len(entries),
                "kept": 0,
                "removed": 0,
                "total": 0,
                "skipped": True,
                "error": "the existing file could not be read as JSON; left untouched",
            }
            continue
        existing = current.entries
        merged = merge(existing, entries, prefix)
        result.files[kind] = {
            "path": str(path),
            "ours": len(entries),
            "kept": sum(1 for entry in merged if not str(entry.get("id") or "").startswith(prefix)),
            "removed": sum(
                1
                for entry in existing
                if str(entry.get("id") or "").startswith(prefix)
                and str(entry.get("id")) not in {str(e["id"]) for e in entries}
            ),
            "total": len(merged),
        }
        if not dry_run:
            _write(path, merged, current)

    if not dry_run:
        result.synced_at = datetime.utcnow().isoformat(timespec="seconds")
    return result
