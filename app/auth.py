"""One optional shared password for the whole archive (R#26).

NegArchive is a single-user LAN application and stays open by default: a home
network with one person on it does not need a login screen, and adding one would
make the "at the shelf" PWA worse for no gain. But a flat share, a co-working
space or a guest VLAN is a different story, so setting **one** environment
variable turns the whole API into a locked door::

    NEGARCHIVE_PASSWORD=something-long

There are no accounts, no registration and no password reset. The token is
derived from the password, so it survives a restart (nobody is logged out when
the container is updated) and revoking access means changing the variable.

Deliberately not implemented: rate limiting, lockouts, per-user sessions. This is
a door latch for a trusted network, not an authentication system, and pretending
otherwise would be worse than saying so. Run behind the Next.js proxy so the
browser, the `<img>` tags and the service worker are all same-origin and the
session cookie is sent with every one of them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse

#: Cookie the browser stores the token in. Not ``httponly``: the upload path uses
#: XMLHttpRequest and the service worker needs to see it too.
COOKIE_NAME = "negarchive_token"

#: Paths that stay open even with a password set, so a phone can discover the
#: archive, show the "locked" screen and let a monitor poll health.
OPEN_PATHS = ("/api/health", "/api/system/info", "/api/system/login", "/openapi.json", "/docs", "/redoc")


def configured_password() -> str:
    """The shared password, or ``""`` when authentication is off."""
    return (os.getenv("NEGARCHIVE_PASSWORD") or "").strip()


def is_enabled() -> bool:
    return bool(configured_password())


def token_for(password: str) -> str:
    """The session token a given password yields.

    A plain salted SHA-256: deterministic (restart-safe), and useless to anyone
    who does not already know the password. It is not a password *store* — the
    real password is in the environment either way — so a slow KDF would buy
    nothing here.
    """
    return hashlib.sha256(f"negarchive-session:{password}".encode("utf-8")).hexdigest()


def expected_token() -> str:
    return token_for(configured_password())


def token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    cookie = request.cookies.get(COOKIE_NAME)
    return cookie.strip() if cookie else None


def check_password(candidate: str | None) -> bool:
    if not is_enabled():
        return True
    return hmac.compare_digest((candidate or "").strip(), configured_password())


def is_authorized(request: Request) -> bool:
    if not is_enabled():
        return True
    presented = token_from_request(request)
    if not presented:
        return False
    return hmac.compare_digest(presented, expected_token())


def is_open_path(path: str, open_paths: Iterable[str] = OPEN_PATHS) -> bool:
    return path == "/" or any(path == p or path.startswith(p + "/") for p in open_paths)


def unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "unauthorized",
                "message": "This archive is password protected. Sign in to continue.",
            }
        },
    )


async def shared_password_middleware(request: Request, call_next):
    """ASGI middleware: everything but :data:`OPEN_PATHS` needs the token.

    ``/static`` is guarded as well — a photo archive whose pictures are readable
    without the password is not protected at all.
    """
    if not is_enabled() or is_open_path(request.url.path) or request.method == "OPTIONS":
        return await call_next(request)
    if is_authorized(request):
        return await call_next(request)
    return unauthorized()
