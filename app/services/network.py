"""Which address the tablet in the darkroom should type in.

Roadmap M3, "LAN discoverability". Half of self-hosting is remembering that the
machine is at 192.168.1.37 and not .38, so the backend works it out itself, logs
it at startup and hands it to the UI, which draws a QR code next to it.

No network traffic is involved: the UDP "connect" below only asks the kernel's
routing table which source address it *would* use, and never sends a packet.
Everything is wrapped, because an offline machine with no default route is a
completely normal state for an archive.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import urlsplit

if TYPE_CHECKING:  # pragma: no cover - typing only; this module must not need the database
    from sqlalchemy.orm import Session


def _is_useful(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified:
        return False
    return parsed.version == 4


def _routing_address() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Any routable address will do; UDP connect() sends nothing.
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1, never actually reachable
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def lan_ips() -> List[str]:
    """Every IPv4 address this host looks reachable on, best guess first."""
    found: List[str] = []

    primary = _routing_address()
    if primary and _is_useful(primary):
        found.append(primary)

    try:
        _, _, addresses = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        addresses = []
    for address in addresses:
        if _is_useful(address) and address not in found:
            found.append(address)

    return found


def ui_port() -> int:
    """Port the *browser* uses. The container's own port is irrelevant here."""
    try:
        return int(os.getenv("UI_PORT") or 8021)
    except ValueError:
        return 8021


def public_base_url(db: Optional["Session"] = None) -> Optional[str]:
    """The address links are written with, when somebody said so (M6.3).

    The ``public_base_url`` setting first — it can be a full URL, because a web
    UI behind a reverse proxy is ``https://archive.example.com`` with no port —
    then ``NEGARCHIVE_PUBLIC_HOST`` from the environment. A bare host or IP gets
    ``http://`` and the UI port; a URL is kept as typed, minus a trailing slash.
    """
    if db is not None:
        from . import settings_store  # noqa: PLC0415 - optional: this module works without a database

        configured = str(settings_store.get(db, "public_base_url") or "").strip()
        if configured:
            return normalize_base_url(configured)
    value = (os.getenv("NEGARCHIVE_PUBLIC_HOST") or "").strip()
    return normalize_base_url(value) if value else None


def normalize_base_url(value: str) -> str:
    text = value.strip().rstrip("/")
    if "://" in text:
        return text
    return f"http://{text}:{ui_port()}"


def ui_host(db: Optional["Session"] = None) -> str | None:
    """The hostname of the links override, or None. Kept for callers that want a host."""
    url = public_base_url(db)
    if not url:
        return None
    return urlsplit(url).hostname or None


def ui_url(db: Optional["Session"] = None) -> str | None:
    """The URL to print, show in the footer and encode in the QR code."""
    override = public_base_url(db)
    if override:
        return override
    ips = lan_ips()
    return f"http://{ips[0]}:{ui_port()}" if ips else None


def ui_urls(db: Optional["Session"] = None) -> List[str]:
    """Every candidate URL, the override first, so the footer can offer an alternative."""
    port = ui_port()
    override = public_base_url(db)
    host = urlsplit(override).hostname if override else None
    return ([override] if override else []) + [f"http://{ip}:{port}" for ip in lan_ips() if ip != host]
