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
* ``GET /api/system/version``  — the version, the build and the changelog (M7).

``/api/system/info`` deliberately reports no filesystem contents, no versions of
anything and no error detail: it is the one endpoint an unauthenticated visitor
can always reach.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import auth, paths, version
from ..db import get_db
from ..errors import ApiError, error_response, from_exc, read_json
from ..models import FilmRoll, ImageAsset, LibraryRoot
from ..services import changelog, network, settings_store
from ..services import smb as smb_service
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
    try:
        urls = network.ui_urls(db)  # reads the public_base_url setting
        counts = {
            "rolls": db.query(func.count(FilmRoll.id)).scalar() or 0,
            "frames": db.query(func.count(ImageAsset.id)).scalar() or 0,
        }
        watch = _watch_state(db)
    except Exception:
        # Before the first migration, or with the database down, this endpoint
        # must still answer: it is how the phone finds the box in the first place.
        db.rollback()
        urls = network.ui_urls()
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


def _validate_setting(key: str, value) -> Any:
    """The settings that are more than a string, checked before they are stored.

    They are checked here rather than in the store, because the store's job is to
    keep values: "may NegArchive write there" belongs to M5's
    :mod:`app.services.negpy.dirs`, and the shape of a mount option belongs to
    :mod:`app.services.smb` — the same validators ``PUT /api/smb/config`` runs, so
    this endpoint cannot be used to slip an unchecked value past them.

    Returns the value to store (validators normalise, e.g. strip slashes).
    """
    text = str(value or "").strip()
    if key in {"negpy_user_dir", "negpy_handoff_dir"} and text:
        negpy_dirs.validate(value, key)
        return value
    if key == "negpy_handoff_mode":
        if text not in negpy_handoff.MODES:
            raise ApiError(
                "invalid_mode",
                f"The handoff mode must be one of: {', '.join(negpy_handoff.MODES)}.",
                400,
                key,
            )
        return text
    if key == "preview_render":
        if text not in PREVIEW_RENDER_MODES:
            raise ApiError(
                "invalid_choice",
                f"preview_render must be one of: {', '.join(PREVIEW_RENDER_MODES)}.",
                400,
                key,
            )
        return text
    if key == "smb_host":
        return smb_service.validate_host(text) if text else ""
    if key == "smb_share":
        return smb_service.validate_share(text) if text else ""
    if key == "smb_subpath":
        return smb_service.validate_subpath(text)
    if key == "smb_version":
        return smb_service.validate_version(text)
    if key in {"smb_username", "smb_domain"}:
        return smb_service.validate_credential(text, key)
    return value


#: What ``preview_render`` may be (app/routers/api.py, ``render_plan``).
PREVIEW_RENDER_MODES = ("auto", "raw", "positive")


@router.put("/system/settings")
async def put_settings(request: Request, db: Session = Depends(get_db)):
    """Body: any subset of the allowlisted keys, e.g. ``{"watch_enabled": false}``."""
    try:
        payload = await read_json(request)
        unknown = sorted(set(payload) - set(settings_store.KNOWN_SETTINGS))
        if unknown:
            raise ApiError("unknown_setting", f"Unknown setting(s): {', '.join(unknown)}.")
        for key, value in payload.items():
            settings_store.set_value(db, key, _validate_setting(key, value))
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.commit()
    return {"ok": True, "settings": settings_store.get_all(db), "watch": _watch_state(db)}


# ---------------------------------------------------------------------------
# Version and changelog (M7)
# ---------------------------------------------------------------------------


@router.get("/system/version")
def system_version(since: Optional[str] = None):
    """Which NegArchive this is, and what changed.

    ``version`` is :data:`app.version.__version__`; ``git_sha`` and ``built_at``
    are what the published image was built from, or null for a checkout run
    from source. ``changelog`` is ``CHANGELOG.md`` parsed, newest first, and
    ``since=<version>`` trims it to the entries newer than that — which is what
    the UI asks for on the first load after an update, so the "what's new"
    dialog shows exactly the releases you skipped.

    Unlike ``/api/system/info`` this endpoint is *not* on the open list: with a
    password set, the version is behind it like everything else.
    """
    entries = changelog.entries()
    return {
        "app": "NegArchive",
        "version": version.__version__,
        "git_sha": version.git_sha(),
        "built_at": version.build_date(),
        "changelog": changelog.since(entries, since) if since else entries,
        "changelog_total": len(entries),
        "release_url": f"https://github.com/dahunni/NegArchive/releases/tag/v{version.__version__}",
    }
