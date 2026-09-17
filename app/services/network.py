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
from typing import List


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


def ui_host() -> str | None:
    """Explicit override for setups where the container cannot see the LAN.

    In Docker the backend only knows its bridge address (172.x), which is useless
    to a phone. ``NEGARCHIVE_PUBLIC_HOST=192.168.1.37`` (or a hostname) fixes it.
    """
    value = (os.getenv("NEGARCHIVE_PUBLIC_HOST") or "").strip()
    return value or None


def ui_url() -> str | None:
    """The URL to print, show in the footer and encode in the QR code."""
    host = ui_host() or (lan_ips()[0] if lan_ips() else None)
    if not host:
        return None
    return f"http://{host}:{ui_port()}"


def ui_urls() -> List[str]:
    """Every candidate URL, so the footer can offer an alternative."""
    port = ui_port()
    override = ui_host()
    hosts = ([override] if override else []) + [ip for ip in lan_ips() if ip != override]
    return [f"http://{host}:{port}" for host in hosts]
