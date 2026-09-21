"""The network share, and the live-mode setup built on it (M6).

    GET    /api/smb/status        the share, the mount, what the container can do
    PUT    /api/smb/config        save it (the password goes to its own 0600 file)
    POST   /api/smb/test          can we reach the NAS at all? no privileges needed
    POST   /api/smb/mount         mount it
    POST   /api/smb/unmount       unmount it
    DELETE /api/smb/credentials   forget the password
    GET    /api/smb/live          is live mode set up? every part checked, not remembered
    POST   /api/smb/live          set it up: folders, watched roots, NegPy folders, gear

**These endpoints mount filesystems, so they are exactly as protected as the rest
of the API** — which, with no ``NEGARCHIVE_PASSWORD`` set, is not at all. That is
the same bargain M3 made for library roots, with the same reasoning (a home LAN,
one user), and it is why :mod:`app.services.smb` validates every piece of a mount
option instead of trusting the caller. If the archive is reachable from anywhere
you do not control, set a password; the README says so in two places.

Nothing here ever returns the SMB password, and it is not in the settings export.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError, error_response, from_exc, read_json
from ..services import livemode
from ..services import smb as smb_service

router = APIRouter(prefix="/api/smb", tags=["smb"])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Everything the Settings card draws, including why it might be unavailable."""
    return {"ok": True, **smb_service.status(db)}


@router.put("/config")
async def save_config(request: Request, db: Session = Depends(get_db)):
    """Body: ``{host, share, subpath?, username?, password?, domain?, version?, ...}``.

    Omitting ``password`` keeps the stored one, so changing the folder does not
    mean typing the NAS password again; sending ``""`` clears it for a guest share.
    """
    try:
        payload = await read_json(request)
        config = smb_service.save(db, payload)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    except OSError as exc:
        db.rollback()
        return error_response("write_failed", f"Could not store the credentials: {exc}", 500)
    return {"ok": True, **smb_service.status(db), "saved": config.to_dict()}


@router.post("/test")
async def test(request: Request, db: Session = Depends(get_db)):
    """Is the NAS there? A TCP connect to 445, so it answers in seconds.

    Deliberately separate from mounting: "the NAS is asleep" and "the password is
    wrong" have different fixes, and a failed mount cannot tell you which it was.
    A body may carry a host and share that have not been saved yet, so the form
    can be tested before it is committed.
    """
    try:
        payload = await read_json(request, required=False) or {}
    except ApiError as exc:
        return from_exc(exc)

    config = smb_service.load(db)
    try:
        if payload.get("host"):
            config.host = smb_service.validate_host(payload["host"])
        if payload.get("share"):
            config.share = smb_service.validate_share(payload["share"])
        result = smb_service.probe(config)
    except ApiError as exc:
        return from_exc(exc)

    caps = smb_service.capabilities()
    return {
        "ok": bool(result.get("ok")),
        **result,
        "capabilities": caps,
        "unavailable_reason": smb_service.explain_missing(caps),
    }


@router.post("/mount")
def mount(db: Session = Depends(get_db)):
    try:
        result = smb_service.mount(db)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {**result, **smb_service.status(db)}


@router.post("/unmount")
def unmount(lazy: bool = False, db: Session = Depends(get_db)):
    """Unmount. ``lazy`` detaches a share whose NAS has already gone away."""
    try:
        result = smb_service.unmount(lazy=lazy)
    except ApiError as exc:
        return from_exc(exc)
    return {**result, **smb_service.status(db)}


@router.delete("/credentials")
def forget_credentials(db: Session = Depends(get_db)):
    """Delete the stored password. The share stays configured, as a guest share."""
    smb_service.forget_credentials()
    return {"ok": True, **smb_service.status(db)}


@router.get("/live")
def live_state(db: Session = Depends(get_db)):
    return {"ok": True, "live": livemode.state(db)}


@router.post("/live")
def live_apply(db: Session = Depends(get_db)):
    """Make the folders, watch them, point NegPy's folders at the share, sync gear.

    Safe to run twice: it creates nothing that exists and turns nothing off.
    """
    try:
        report = livemode.apply(db)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "report": report.to_dict(), "live": livemode.state(db)}
