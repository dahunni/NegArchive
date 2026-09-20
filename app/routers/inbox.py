"""The inbox: the archive's own share, and what has landed in it (M6.2).

    GET  /api/inbox          where the share is, what is waiting, the last sweep
    POST /api/inbox/sweep    take everything in it now, instead of at the next tick

Both are local file work and neither takes a path from the client: the inbox is
one fixed folder under ``DATA_DIR``. See :mod:`app.services.inbox`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import inbox as inbox_service

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("")
def status(db: Session = Depends(get_db)):
    return {"ok": True, **inbox_service.status(db)}


@router.post("/sweep")
def sweep(db: Session = Depends(get_db)):
    """Import now. Also what the watcher does every ``WATCH_INTERVAL_SECONDS``."""
    result = inbox_service.sweep(db)
    return {"ok": True, "result": result.to_dict(), **inbox_service.status(db)}
