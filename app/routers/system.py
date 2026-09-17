"""Health, LAN discovery, the optional password and the settings page.

Roadmap M3. Three separate small jobs that all answer "what is this machine and
can I reach it":

* ``GET /api/health``       — the Compose healthcheck and any monitor. Always open.
* ``GET /api/system/info``  — LAN addresses, the UI URL, whether a password is set,
  the data directory and the watch-folder state. Always open, because the phone
  needs it *before* it can sign in.
* ``GET /api/system/qr.svg``— that URL as a QR code, rendered server-side so the
  frontend needs no QR dependency and works offline.
* ``POST /api/system/login`` / ``logout`` — the shared password (R#26).
* ``GET|PUT /api/system/settings`` — the allowlisted toggles.

``/api/system/info`` deliberately reports no filesystem contents, no versions of
anything and no error detail: it is the one endpoint an unauthenticated visitor
can always reach.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import auth, paths
from ..db import get_db
from ..errors import ApiError, error_response, from_exc, read_json
from ..models import FilmRoll, ImageAsset, LibraryRoot
from ..services import network, settings_store
from ..services.negpy import dirs as negpy_dirs
from ..services.negpy import handoff as negpy_handoff

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """Is the app up *and* is the database answering?

    The Compose healthcheck uses this, so it has to touch the database: a web
    process that cannot reach Postgres is not healthy, however cheerfully it
    answers HTTP.
    """
    try:
        db.execute(func.now())
        database = "ok"
    except Exception:
        return error_response("database_unavailable", "The database is not reachable.", 503)
    return {"status": "ok", "database": database}


def _watch_state(db: Session) -> dict:
    roots = db.query(LibraryRoot).order_by(LibraryRoot.id.asc()).all()
    watched = [r for r in roots if r.watch]
    last = max((r.last_scan_at for r in roots if r.last_scan_at), default=None)
    return {
        "enabled": bool(settings_store.get(db, "watch_enabled")),
        "interval_seconds": watch_interval_seconds(),
        "roots_total": len(roots),
        "roots_watched": len(watched),
        "last_scan_at": last.isoformat() if last else None,
    }


#: What the Compose stack and `.env.example` set, and what to use if you want one.
DEFAULT_WATCH_INTERVAL_SECONDS = 30


def watch_interval_seconds() -> Optional[int]:
    """Poll interval, or ``None`` when the watch folder is switched off.

    **Unset means off.** A process that walks directories every thirty seconds is
    not something an archive should start doing because somebody ran `uvicorn`;
    the Compose stack sets `WATCH_INTERVAL_SECONDS=30` explicitly, so the feature
    is on where it was installed on purpose and off where it was not. An
    unparseable value falls back to the default rather than to silence, because
    a typo should not quietly disable a feature you asked for.
    """
    raw = (os.getenv("WATCH_INTERVAL_SECONDS") or "").strip()
    if not raw or raw.lower() in {"0", "off", "false", "none"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WATCH_INTERVAL_SECONDS
    return value if value > 0 else None


@router.get("/system/info")
def system_info(db: Session = Depends(get_db)):
    """Everything a phone at the shelf needs in order to find and trust this box."""
    urls = network.ui_urls()
    try:
        counts = {
            "rolls": db.query(func.count(FilmRoll.id)).scalar() or 0,
            "frames": db.query(func.count(ImageAsset.id)).scalar() or 0,
        }
        watch = _watch_state(db)
    except Exception:
        # Before the first migration this endpoint must still answer.
        counts = {"rolls": 0, "frames": 0}
        watch = {"enabled": False, "interval_seconds": watch_interval_seconds()}
    return {
        "app": "NegArchive",
        "lan_ips": network.lan_ips(),
        "ui_url": urls[0] if urls else None,
        "ui_urls": urls,
        "ui_port": network.ui_port(),
        "qr_url": "/api/system/qr.svg",
        "data_dir": str(paths.data_dir()),
        "auth_required": auth.is_enabled(),
        "counts": counts,
        "watch": watch,
        "server_time": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/system/qr.svg")
def system_qr(url: Optional[str] = None):
    """The LAN URL as an SVG QR code.

    Rendered here rather than in the browser so the frontend keeps zero runtime
    dependencies and the code still appears with no internet at all. `segno` is
    ~60 kB of pure Python and pulls nothing in.
    """
    target = url or network.ui_url()
    if not target:
        return error_response("no_lan_address", "This machine has no usable LAN address.", 404)
    from ..services.codes import qr_svg

    # One renderer for every QR in the app (M4). It keeps the xmlns attribute, which
    # `<img>` needs, and swaps the stroke for `currentColor` so the footer follows
    # the light/dark theme.
    svg = qr_svg(target, scale=4, border=2)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store", "X-QR-Target": target},
    )


# ---------------------------------------------------------------------------
# Optional shared password (R#26)
# ---------------------------------------------------------------------------


@router.post("/system/login")
async def login(request: Request):
    try:
        payload = await read_json(request)
    except ApiError as exc:
        return from_exc(exc)
    if not auth.is_enabled():
        return {"ok": True, "auth_required": False, "token": None}
    if not auth.check_password(payload.get("password")):
        return error_response("invalid_password", "That password is not right.", 401)

    token = auth.expected_token()
    response = Response(
        content=f'{{"ok":true,"auth_required":true,"token":"{token}"}}',
        media_type="application/json",
    )
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=60 * 60 * 24 * 365,
        httponly=False,  # the upload XHR and the service worker read it too
        samesite="lax",
        path="/",
    )
    return response


@router.post("/system/logout")
def logout():
    response = Response(content='{"ok":true}', media_type="application/json")
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/system/settings")
def get_settings(db: Session = Depends(get_db)):
    return {"settings": settings_store.get_all(db), "watch": _watch_state(db)}


def _validate_setting(key: str, value) -> None:
    """The two settings that are more than a string: a writable folder and a mode.

    They are checked here rather than in the store, because the store's job is to
    keep values and the answer to "may NegArchive write there" belongs to M5's
    :mod:`app.services.negpy.dirs` (roadmap M5).
    """
    if key in {"negpy_user_dir", "negpy_handoff_dir"} and str(value or "").strip():
        negpy_dirs.validate(value, key)
    if key == "negpy_handoff_mode" and str(value or "").strip() not in negpy_handoff.MODES:
        raise ApiError(
            "invalid_mode",
            f"The handoff mode must be one of: {', '.join(negpy_handoff.MODES)}.",
            400,
            key,
        )


@router.put("/system/settings")
async def put_settings(request: Request, db: Session = Depends(get_db)):
    """Body: any subset of the allowlisted keys, e.g. ``{"watch_enabled": false}``."""
    try:
        payload = await read_json(request)
        unknown = sorted(set(payload) - set(settings_store.KNOWN_SETTINGS))
        if unknown:
            raise ApiError("unknown_setting", f"Unknown setting(s): {', '.join(unknown)}.")
        for key, value in payload.items():
            _validate_setting(key, value)
            settings_store.set_value(db, key, value)
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.commit()
    return {"ok": True, "settings": settings_store.get_all(db), "watch": _watch_state(db)}
