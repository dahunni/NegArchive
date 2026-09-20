"""The archive's own share (M6.2, M6.3).

    GET  /api/share          address, layout, live-mode state, what is in the inbox
    POST /api/share/setup    live mode: the watched folder, NegPy's folders, gear

The legacy ``/api/smb/live`` routes point at the same functions and stay for
the page that predates this one; ``/api/inbox`` keeps the sweep.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError, from_exc
from ..services import inbox, livemode
from ..services import share as share_service

router = APIRouter(prefix="/api/share", tags=["share"])


@router.get("")
def status(db: Session = Depends(get_db)):
    return {
        "ok": True,
        "share": share_service.info(db),
        "live": livemode.state(db),
        "inbox": inbox.status(db),
    }


@router.post("/setup")
def setup(db: Session = Depends(get_db)):
    """Safe to run twice: it creates nothing that exists and turns nothing off."""
    try:
        report = livemode.apply(db)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "report": report.to_dict(), "live": livemode.state(db), "share": share_service.info(db)}
