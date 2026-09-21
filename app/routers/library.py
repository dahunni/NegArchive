"""Library roots: import by reference, and the folders the watcher sweeps.

Roadmap M3. See :mod:`app.services.importer` for the scanning rules and for why a
linked file is never copied, moved or deleted.

    POST   /api/library/roots            register a folder (validated, see below)
    GET    /api/library/roots            list them with their last scan
    PUT    /api/library/roots/{id}       rename it, or turn watching on and off
    DELETE /api/library/roots/{id}       stop tracking it; files and frames stay
    POST   /api/library/roots/{id}/scan  walk it now
    POST   /api/library/scan             walk every root now

**A registered folder is readable through the API**, because previews and
downloads have to work for linked files. That is why a root must sit under an
allowed base — ``LIBRARY_ROOTS_ALLOW``, a mounted NAS share, or the archive's own
share (M6.2): without that rule, a single POST would turn the archive into a
file server for the whole disk.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError, error_response, from_exc, read_json
from ..models import ImageAsset, LibraryRoot
from ..services import importer

router = APIRouter(prefix="/api/library", tags=["library"])


def root_to_dict(root: LibraryRoot, frame_count: Optional[int] = None) -> dict:
    return {
        "id": root.id,
        "path": root.path,
        "label": root.label,
        "watch": bool(root.watch),
        "last_scan_at": root.last_scan_at.isoformat() if root.last_scan_at else None,
        "last_scan_summary": root.last_scan_summary,
        "created_at": root.created_at.isoformat() if root.created_at else None,
        "frame_count": frame_count,
    }


def _under_root(root: LibraryRoot):
    """``source_path LIKE '<root>/%'`` with the root's own ``%``, ``_`` and ``\\`` escaped.

    A folder called ``scans_2024`` must not also match ``scansX2024``: with the
    wildcards unescaped, ``forget_frames`` on one root could take a sibling's
    frames with it.
    """
    prefix = root.path.rstrip("/") + "/"
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return ImageAsset.source_path.like(escaped + "%", escape="\\")


def _frame_count(db: Session, root: LibraryRoot) -> int:
    return db.query(ImageAsset).filter(ImageAsset.storage_mode == "linked", _under_root(root)).count()


@router.get("/roots")
def list_roots(db: Session = Depends(get_db)):
    roots = db.query(LibraryRoot).order_by(LibraryRoot.id.asc()).all()
    return {
        "roots": [root_to_dict(r, _frame_count(db, r)) for r in roots],
        # The UI lists where a root may be. Since M6.2 the archive's own share is
        # always one of them, so the feature is never off; `enabled` stays for
        # older clients.
        "allowed_bases": [str(b) for b in importer.allowed_bases()],
        "enabled": True,
    }


@router.post("/roots")
async def create_root(request: Request, db: Session = Depends(get_db)):
    """Body: ``{"path": "/library/scans", "label": "Scanner", "watch": true}``."""
    try:
        payload = await read_json(request)
        resolved = importer.validate_root(payload.get("path"))
    except ApiError as exc:
        return from_exc(exc)

    existing = db.query(LibraryRoot).filter(LibraryRoot.path == str(resolved)).first()
    if existing:
        return error_response("duplicate_root", "That folder is already registered.", 409)

    root = LibraryRoot(
        path=str(resolved),
        label=(payload.get("label") or None),
        watch=bool(payload.get("watch")),
    )
    db.add(root)
    db.commit()
    return {"ok": True, "root": root_to_dict(root, 0)}


@router.put("/roots/{root_id}")
async def update_root(root_id: int, request: Request, db: Session = Depends(get_db)):
    root = db.get(LibraryRoot, root_id)
    if not root:
        return error_response("not_found", "That library root does not exist.", 404)
    try:
        payload = await read_json(request)
    except ApiError as exc:
        return from_exc(exc)
    if "label" in payload:
        root.label = payload["label"] or None
    if "watch" in payload:
        root.watch = bool(payload["watch"])
    db.commit()
    return {"ok": True, "root": root_to_dict(root, _frame_count(db, root))}


@router.delete("/roots/{root_id}")
def delete_root(root_id: int, forget_frames: bool = False, db: Session = Depends(get_db)):
    """Stop tracking a folder.

    The files are never touched. By default the frame records stay too, so notes
    and frame numbers are not lost by un-registering a folder; ``forget_frames``
    removes the linked records (still not the files).
    """
    root = db.get(LibraryRoot, root_id)
    if not root:
        return error_response("not_found", "That library root does not exist.", 404)
    forgotten = 0
    if forget_frames:
        forgotten = (
            db.query(ImageAsset)
            .filter(ImageAsset.storage_mode == "linked", _under_root(root))
            .delete(synchronize_session=False)
        )
    db.delete(root)
    db.commit()
    return {"ok": True, "forgotten_frames": forgotten}


@router.post("/roots/{root_id}/scan")
def scan_one(root_id: int, db: Session = Depends(get_db)):
    root = db.get(LibraryRoot, root_id)
    if not root:
        return error_response("not_found", "That library root does not exist.", 404)
    result = importer.scan_root(db, root)
    return {"ok": True, "root": root_to_dict(root, _frame_count(db, root)), "result": result.to_dict()}


@router.post("/scan")
def scan_all(db: Session = Depends(get_db)):
    roots = db.query(LibraryRoot).order_by(LibraryRoot.id.asc()).all()
    results = {root.id: importer.scan_root(db, root).to_dict() for root in roots}
    return {"ok": True, "scanned": len(results), "results": results}
