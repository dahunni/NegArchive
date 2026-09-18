"""Mounting the network share NegArchive and NegPy both work in (M6).

NegPy runs on a laptop; NegArchive runs in a container on a server. The live
integration (docs/NEGPY_LIVE.md) needs both to see *the same bytes*: NegPy edits
a scan in place and drops a ``.negpy`` sidecar next to it, and the watcher's
:func:`app.services.importer.scan_root` sweep notices the sidecar's mtime and
attaches the recipe. That only works if the folder NegPy opens is the folder
NegArchive linked from.

So the container mounts the share itself, and this module is the only place that
runs ``mount``. Everything is driven from Settings rather than the environment,
because the whole point is that you can point the archive at your NAS without
editing a Compose file and recreating containers.

**What this needs from the deployment.** ``mount.cifs`` (the ``cifs-utils``
package, in the image since M6) and ``CAP_SYS_ADMIN`` on the container — mounting
a filesystem is a privileged operation and no amount of userspace cleverness
changes that. The Compose file adds the capability with a comment saying why;
:func:`capabilities` checks for it up front so the UI can explain a failure
instead of printing ``mount: permission denied``.

**Where the password lives.** Not in the database and not in an export: it is
written to ``$DATA_DIR/.smb/credentials`` with mode 0600, which is the file
``mount.cifs`` reads. The database keeps the host, the share, the user and the
mount options — everything you would tell a colleague — and never the secret.
:func:`status` never returns it.

**One share.** Not because more would be hard, but because the live setup has one
answer: the folder your scanner writes into and your NegPy opens. A second share
is a second deployment decision, and those live in the environment.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .. import paths
from ..errors import ApiError
from . import settings_store

log = logging.getLogger("negarchive.smb")

#: Where the share is mounted inside the container. Overridable so a test (and a
#: bare `uvicorn` on a laptop) can point it somewhere writable.
MOUNT_BASE_ENV = "SMB_MOUNT_BASE"
DEFAULT_MOUNT_BASE = "/mnt/negarchive"

#: `mount -t cifs` wants seconds; a NAS that is asleep should fail fast and say so
#: rather than hanging the request that asked for it.
MOUNT_TIMEOUT_SECONDS = 25
PROBE_TIMEOUT_SECONDS = 4

#: SMB's own port. 139 (NetBIOS) is not offered: every NAS made this century speaks 445.
SMB_PORT = 445

#: Dialects worth offering. "default" lets mount.cifs negotiate, which is right
#: for a modern NAS and wrong for an old one that needs to be told.
VERSIONS = ("3.1.1", "3.0", "2.1", "default")

#: CAP_SYS_ADMIN. `mount()` needs it; without it the syscall fails with EPERM.
CAP_SYS_ADMIN_BIT = 21

_HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
_SHARE_RE = re.compile(r"^[^/\\:*?\"<>|,\n\r\t]{1,80}$")


# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------


def mount_base() -> Path:
    raw = (os.getenv(MOUNT_BASE_ENV) or "").strip()
    return Path(raw or DEFAULT_MOUNT_BASE)


def credentials_path() -> Path:
    return paths.data_dir() / ".smb" / "credentials"


def is_mounted(target: Optional[Path] = None) -> bool:
    """Is something mounted at the mount point right now?

    Read from ``/proc/self/mounts`` rather than remembered in a variable: the
    share can go away without asking us (the NAS reboots, the network drops), and
    a cached "yes" would make the archive lie about where its files are.
    """
    wanted = str((target or mount_base()))
    try:
        with open("/proc/self/mounts", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and _unescape_mount(parts[1]) == wanted:
                    return True
    except OSError:
        # No procfs (macOS during development): fall back to the mountpoint test,
        # which is right for a real mount and harmlessly false for an empty dir.
        try:
            return (target or mount_base()).is_mount()
        except OSError:
            return False
    return False


def _unescape_mount(field: str) -> str:
    """``/proc/mounts`` octal-escapes spaces and tabs in paths."""
    return re.sub(r"\\0(\d\d)", lambda m: chr(int(m.group(1), 8)), field)


def capabilities() -> Dict[str, Any]:
    """What this container can actually do, checked before anything is attempted."""
    helper = shutil.which("mount.cifs")
    return {
        "cifs_utils": bool(helper),
        "cifs_utils_path": helper,
        "sys_admin": _has_sys_admin(),
        "mount_base": str(mount_base()),
    }


def _has_sys_admin() -> bool:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("CapEff:"):
                    return bool(int(line.split()[1], 16) & (1 << CAP_SYS_ADMIN_BIT))
    except (OSError, ValueError, IndexError):
        return False
    return False


def explain_missing(caps: Dict[str, Any]) -> Optional[str]:
    if not caps["cifs_utils"]:
        return (
            "This image has no mount.cifs. Pull the current negarchive-web image "
            "(cifs-utils is in it since M6) or rebuild with `docker compose build web`."
        )
    if not caps["sys_admin"]:
        return (
            "The container may not mount filesystems. Add the two lines the Compose "
            "file has commented for this — `cap_add: [SYS_ADMIN]` and "
            "`security_opt: [apparmor:unconfined]` on the `web` service — then "
            "`docker compose up -d`."
        )
    return None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """The share, as Settings describes it. Never carries the password."""

    enabled: bool = False
    host: str = ""
    share: str = ""
    subpath: str = ""
    username: str = ""
    domain: str = ""
    version: str = "3.0"
    readonly: bool = False
    automount: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.host and self.share)

    @property
    def unc(self) -> str:
        return f"//{self.host}/{self.share}"

    @property
    def source(self) -> str:
        """What `mount` is pointed at: the share, plus the folder inside it.

        ``mount.cifs`` takes ``//nas/photo/film`` and mounts that subdirectory,
        which is better supported across servers than the ``prefixpath=`` option.
        """
        return f"{self.unc}/{self.subpath}" if self.subpath else self.unc

    @property
    def display(self) -> str:
        """What to show a person: ``//nas.local/photo/film``."""
        tail = f"/{self.subpath}" if self.subpath else ""
        return f"{self.unc}{tail}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "host": self.host,
            "share": self.share,
            "subpath": self.subpath,
            "username": self.username,
            "domain": self.domain,
            "version": self.version,
            "readonly": self.readonly,
            "automount": self.automount,
            "unc": self.unc if self.configured else "",
            "display": self.display if self.configured else "",
        }


def load(db: Session) -> Config:
    return Config(
        enabled=bool(settings_store.get(db, "smb_enabled")),
        host=str(settings_store.get(db, "smb_host") or ""),
        share=str(settings_store.get(db, "smb_share") or ""),
        subpath=str(settings_store.get(db, "smb_subpath") or ""),
        username=str(settings_store.get(db, "smb_username") or ""),
        domain=str(settings_store.get(db, "smb_domain") or ""),
        version=str(settings_store.get(db, "smb_version") or "3.0"),
        readonly=bool(settings_store.get(db, "smb_readonly")),
        automount=bool(settings_store.get(db, "smb_automount")),
    )


def validate_host(value: str) -> str:
    text = str(value or "").strip().strip("/")
    if not text:
        raise ApiError("invalid_host", "The NAS address is required.", 400, "host")
    if not _HOST_RE.match(text):
        raise ApiError(
            "invalid_host",
            "Use the NAS's hostname or IP address on its own — no scheme, no slashes "
            "(nas.local, or 192.168.1.10).",
            400,
            "host",
        )
    return text


def validate_share(value: str) -> str:
    """The top-level share name, the part right after the host in ``//nas/photo``.

    Commas are refused along with the path separators: a comma in a share name
    would end the option it is interpolated into and start another one, which is
    how a mount option string turns into an injection.
    """
    text = str(value or "").strip().strip("/")
    if not text:
        raise ApiError("invalid_share", "The share name is required.", 400, "share")
    if not _SHARE_RE.match(text):
        raise ApiError(
            "invalid_share",
            "That is not a share name. Use just the share, without slashes or commas "
            "(photo, not //nas/photo/film).",
            400,
            "share",
        )
    return text


def validate_subpath(value: str) -> str:
    """An optional folder *inside* the share, so the mount can be narrowed.

    Leading and trailing slashes are forgiving — ``/film/`` and ``film`` mean the
    same folder and typing either is reasonable. ``..`` is not: a share mounted one
    level up from the one that was configured is not what anybody asked for.
    """
    text = str(value or "").strip().strip("/")
    if not text:
        return ""
    if ".." in Path(text).parts or "\\" in text:
        raise ApiError(
            "invalid_subpath",
            "The folder inside the share must be a plain relative path (film/negatives), "
            "with no .. in it.",
            400,
            "subpath",
        )
    if "," in text:
        raise ApiError("invalid_subpath", "A folder inside the share may not contain a comma.", 400, "subpath")
    return text


def validate_version(value: str) -> str:
    text = str(value or "").strip() or "3.0"
    if text not in VERSIONS:
        raise ApiError("invalid_version", f"The SMB version must be one of: {', '.join(VERSIONS)}.", 400, "version")
    return text


def validate_credential(value: str, field: str) -> str:
    """A username, domain or password that is safe to put in a credentials file.

    ``mount.cifs`` parses that file line by line, so a newline in a value would
    forge a second line. Refuse rather than strip: silently changing somebody's
    password to something that does not work is a worse afternoon than an error.
    """
    text = str(value or "")
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ApiError("invalid_credential", "That value may not contain a line break.", 400, field)
    return text.strip() if field != "password" else text


def save(db: Session, payload: Dict[str, Any]) -> Config:
    """Write the configuration, and the password to its own 0600 file.

    The password is *optional in the payload*: a request that omits the key keeps
    the stored one, so the UI can save a changed folder without asking for the
    NAS password again. Passing an empty string clears it (a guest share).
    """
    host = validate_host(payload.get("host", ""))
    share = validate_share(payload.get("share", ""))
    subpath = validate_subpath(payload.get("subpath", ""))
    username = validate_credential(payload.get("username", ""), "username")
    domain = validate_credential(payload.get("domain", ""), "domain")
    version = validate_version(payload.get("version", "3.0"))

    settings_store.set_value(db, "smb_host", host)
    settings_store.set_value(db, "smb_share", share)
    settings_store.set_value(db, "smb_subpath", subpath)
    settings_store.set_value(db, "smb_username", username)
    settings_store.set_value(db, "smb_domain", domain)
    settings_store.set_value(db, "smb_version", version)
    settings_store.set_value(db, "smb_readonly", bool(payload.get("readonly", False)))
    settings_store.set_value(db, "smb_automount", bool(payload.get("automount", True)))
    settings_store.set_value(db, "smb_enabled", bool(payload.get("enabled", True)))

    if "password" in payload:
        write_credentials(username, validate_credential(payload.get("password") or "", "password"), domain)
    db.commit()
    return load(db)


def write_credentials(username: str, password: str, domain: str = "") -> Optional[Path]:
    """The file ``mount.cifs`` reads instead of taking the password on its command line.

    A password in ``-o password=…`` is in the process table, which on a box with
    more than one user is the same as printing it. Mode 0600 in a 0700 directory,
    and the whole thing is skipped for a guest share.
    """
    target = credentials_path()
    if not username and not password:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    # Create with the right mode from the start: writing then chmod-ing leaves a
    # window where the secret is world-readable.
    handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(f"username={username}\n")
        stream.write(f"password={password}\n")
        if domain:
            stream.write(f"domain={domain}\n")
    os.chmod(target, 0o600)
    return target


def has_credentials() -> bool:
    return credentials_path().is_file()


def forget_credentials() -> None:
    try:
        credentials_path().unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


def mount_options(config: Config) -> List[str]:
    """The ``-o`` list, built from validated pieces only.

    ``uid``/``gid``/``file_mode``/``dir_mode`` because a CIFS server does not send
    usable ownership: without them every file arrives owned by root and unreadable
    by the app. ``nobrl`` because byte-range locks over SMB are the thing that
    corrupts SQLite, and something on the share will eventually be a SQLite file.
    """
    options = [
        f"credentials={credentials_path()}" if has_credentials() else "guest",
        f"uid={os.getuid()}",
        f"gid={os.getgid()}",
        "file_mode=0664",
        "dir_mode=0775",
        "iocharset=utf8",
        "nobrl",
        # A share that goes away should fail the one call that touched it rather
        # than parking the request forever in uninterruptible sleep.
        "soft",
    ]
    if config.version != "default":
        options.append(f"vers={config.version}")
    options.append("ro" if config.readonly else "rw")
    return options


def mount_command(config: Config) -> List[str]:
    """The exact argv. Split out so a test can assert on it without root."""
    return [
        "mount",
        "-t",
        "cifs",
        config.source,
        str(mount_base()),
        "-o",
        ",".join(mount_options(config)),
    ]


def probe(config: Config) -> Dict[str, Any]:
    """Can we even reach the NAS? A TCP connect, before anything privileged.

    Worth its own step: "no route to host" and "wrong password" are different
    problems with different fixes, and ``mount`` reports both as a failure.
    """
    if not config.configured:
        raise ApiError("not_configured", "Set the NAS address and the share name first.", 400, "host")
    try:
        with socket.create_connection((config.host, SMB_PORT), timeout=PROBE_TIMEOUT_SECONDS):
            return {"ok": True, "reachable": True, "host": config.host, "port": SMB_PORT}
    except socket.gaierror:
        return {
            "ok": False,
            "reachable": False,
            "error": f"No machine called {config.host} could be found. Check the name, or use the IP address.",
        }
    except (OSError, socket.timeout) as exc:
        return {
            "ok": False,
            "reachable": False,
            "error": f"{config.host} did not answer on port {SMB_PORT} ({exc}). Is the NAS awake, and is SMB on?",
        }


def mount(db: Session) -> Dict[str, Any]:
    """Mount the configured share. Idempotent: already mounted is success."""
    config = load(db)
    if not config.configured:
        raise ApiError("not_configured", "Set the NAS address and the share name first.", 400, "host")

    caps = capabilities()
    missing = explain_missing(caps)
    if missing:
        raise ApiError("mount_unavailable", missing, 503)

    target = mount_base()
    if is_mounted(target):
        return {"ok": True, "mounted": True, "already": True, "mountpoint": str(target)}

    target.mkdir(parents=True, exist_ok=True)
    command = mount_command(config)
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, every element validated above
            command,
            capture_output=True,
            text=True,
            timeout=MOUNT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ApiError(
            "mount_timeout",
            f"{config.host} did not answer within {MOUNT_TIMEOUT_SECONDS} seconds. "
            "Is the NAS asleep?",
            504,
        ) from exc
    except OSError as exc:  # pragma: no cover - no `mount` binary at all
        raise ApiError("mount_unavailable", f"Could not run mount: {exc}", 503) from exc

    if completed.returncode != 0:
        raise ApiError("mount_failed", _explain_failure(completed, config), 502)

    settings_store.set_value(db, "smb_enabled", True)
    db.commit()
    log.info("mounted %s at %s", config.display, target)
    return {"ok": True, "mounted": True, "already": False, "mountpoint": str(target)}


def _explain_failure(completed: subprocess.CompletedProcess, config: Config) -> str:
    """Turn mount.cifs's output into something with a next step in it."""
    text = " ".join(part for part in (completed.stderr or "", completed.stdout or "") if part).strip()
    lowered = text.lower()
    if "permission denied" in lowered or "mount error(13)" in lowered:
        who = config.username or "guest"
        return (
            f"The NAS refused the login for {who!r}. Check the user name and password, "
            "and that this user may reach the share."
        )
    if "no such file or directory" in lowered or "mount error(2)" in lowered:
        return (
            f"The NAS has no share called {config.share!r}"
            + (f" with a folder {config.subpath!r} in it" if config.subpath else "")
            + ". Check the spelling in the NAS's own sharing settings."
        )
    if "host is down" in lowered or "mount error(112)" in lowered:
        return f"{config.host} did not answer. Is it awake, and is SMB switched on?"
    if "invalid argument" in lowered or "mount error(22)" in lowered:
        return (
            "The NAS refused the connection settings — usually the SMB version. "
            "Try 3.0, or 2.1 for an older NAS."
        )
    if "operation not permitted" in lowered:
        return (
            "The container may not mount filesystems. Add `cap_add: [SYS_ADMIN]` to the "
            "`web` service in docker-compose.yml and run `docker compose up -d`."
        )
    return text or "mount failed without saying why. Check the container log."


def unmount(db: Optional[Session] = None, lazy: bool = False) -> Dict[str, Any]:
    """Unmount the share. Not mounted is success, not an error."""
    target = mount_base()
    if not is_mounted(target):
        return {"ok": True, "mounted": False, "already": True, "mountpoint": str(target)}
    command = ["umount"] + (["-l"] if lazy else []) + [str(target)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=MOUNT_TIMEOUT_SECONDS)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApiError("unmount_failed", f"Could not unmount: {exc}", 502) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if "target is busy" in detail.lower():
            raise ApiError(
                "unmount_busy",
                "Something is still reading the share. Wait for any running scan to "
                "finish and try again.",
                409,
            )
        raise ApiError("unmount_failed", detail or "umount failed without saying why.", 502)
    log.info("unmounted %s", target)
    return {"ok": True, "mounted": False, "already": False, "mountpoint": str(target)}


def remount_at_startup() -> None:
    """Mount the configured share when the container comes up.

    A mount does not survive the container it was made in, so without this the
    archive would come back from a restart with every linked frame pointing at an
    empty directory. Failure is logged, never fatal: a NAS that is slower to boot
    than the server is a Tuesday, not a reason to refuse to start.
    """
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        config = load(db)
        if not (config.enabled and config.configured and config.automount):
            return
        if is_mounted():
            return
        try:
            mount(db)
        except ApiError as exc:
            log.warning("could not mount %s at startup: %s", config.display, exc.message)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def free_space(target: Path) -> Optional[Dict[str, int]]:
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return None
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def status(db: Session) -> Dict[str, Any]:
    """Everything Settings needs to draw the share card — and never the password."""
    config = load(db)
    target = mount_base()
    mounted = is_mounted(target)
    caps = capabilities()
    return {
        "config": config.to_dict(),
        "mountpoint": str(target),
        "mounted": mounted,
        "has_credentials": has_credentials(),
        "capabilities": caps,
        "unavailable_reason": explain_missing(caps),
        "space": free_space(target) if mounted else None,
        "versions": list(VERSIONS),
    }
