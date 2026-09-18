"""The FastAPI application: migrations at startup, static files, the routers."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from alembic import command

from . import auth, paths
from .db import SessionLocal, engine
from .errors import ApiError, from_exc, validation_error_response
from .routers import api, backup, library, locations, negpy, scan, system
from .routers import smb as smb_router
from .seed import seed_catalog
from .services import network, smb, watcher

REPO_ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger("negarchive")

#: Never served as HTML, whatever the extension says (R#18).
UNSAFE_MEDIA_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "application/xml",
    "text/xml",
    "application/javascript",
    "text/javascript",
}


def run_migrations() -> None:
    """``alembic upgrade head`` in process (roadmap M2, replaces the ALTER hooks).

    The config is built in code rather than read from ``alembic.ini`` alone, so the
    app and the CLI cannot drift apart: both end up on the same script directory and
    the same ``DATABASE_URL``.
    """
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", str(engine.url.render_as_string(hide_password=False)))
    # Reuse the app's engine so a single connection pool does the work.
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def configure_logging() -> None:
    """Make sure NegArchive's own log lines actually come out (M3).

    Two things conspire against them: uvicorn installs its own logging
    configuration, and ``alembic.ini``'s ``fileConfig()`` — which runs during the
    migration above — re-reads logging config with Python's default of
    ``disable_existing_loggers=True``, switching off every logger it does not
    name. So this runs *after* the migrations, re-enables our loggers and gives
    them a handler if nothing else did.

    Worth the dozen lines: the LAN URL printed at startup is how somebody finds
    the archive from their phone in the first place.
    """
    for name in ("negarchive", "negarchive.watch"):
        logger = logging.getLogger(name)
        logger.disabled = False
        logger.setLevel(logging.INFO)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        log.addHandler(handler)
        log.propagate = False


def announce() -> None:
    """Print where the archive can be reached (M3, LAN discoverability)."""
    urls = network.ui_urls()
    log.info("NegArchive data directory: %s", paths.data_dir())
    if urls:
        log.info("NegArchive UI on this network: %s", "  ".join(urls))
        log.info("QR code for the phone: %s/api/system/qr.svg", urls[0])
    else:
        log.info("No LAN address found; set NEGARCHIVE_PUBLIC_HOST to advertise one.")
    if auth.is_enabled():
        log.info("A shared password is set (NEGARCHIVE_PASSWORD); the API is closed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A failure here must stop the app: booting against a half-migrated schema is how
    # the old silent `try/except: pass` migrations produced 500s at runtime (R#23).
    run_migrations()
    configure_logging()  # after the migrations: alembic's fileConfig disables loggers
    paths.ensure_dirs()
    db = SessionLocal()
    try:
        seed_catalog(db)
    finally:
        db.close()
    announce()

    # M6: a mount does not survive the container it was made in, so a restart would
    # otherwise come back with every linked frame pointing into an empty directory.
    # Never fatal: a NAS that boots slower than the server is a Tuesday.
    smb.remount_at_startup()

    # M3: the watch folder. Off unless WATCH_INTERVAL_SECONDS says otherwise, so a
    # bare `uvicorn` never starts a process that walks directories every 30 seconds.
    task: asyncio.Task | None = None
    interval = system.watch_interval_seconds()
    if interval:
        task = asyncio.create_task(watcher.watch_loop(interval))
    else:
        log.info("Watch folder polling is off (WATCH_INTERVAL_SECONDS).")

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - shutdown must not raise
                pass


app = FastAPI(title="NegArchive", lifespan=lifespan)

# Enable CORS for Node/Next.js frontends (local dev and hosted)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# M3 (R#26): one optional shared password in front of everything, /static included.
# Does nothing at all unless NEGARCHIVE_PASSWORD is set.
app.middleware("http")(auth.shared_password_middleware)


@app.exception_handler(ApiError)
async def handle_api_error(request, exc: ApiError):
    """Anything raised below a handler still answers with the structured body."""
    return from_exc(exc)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request, exc: RequestValidationError):
    """Pydantic's 422 in the same ``{"error": {code, message, field}}`` shape (R#16)."""
    return validation_error_response(exc.errors())


class SafeStaticFiles(StaticFiles):
    """Static files that can never be interpreted as a page (R#18).

    An uploaded ``evil.html`` used to be served back with ``text/html``, which is
    stored XSS on the LAN. Uploads are now served as a download with a neutral media
    type, and everything under ``/static`` is marked ``nosniff``.
    """

    def file_response(self, full_path, stat_result, scope, status_code=200) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        path = scope.get("path", "")
        media_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if media_type in UNSAFE_MEDIA_TYPES and not path.startswith("/catalog/"):
            response.headers["content-type"] = "application/octet-stream"
            response.headers["content-disposition"] = "attachment"
        response.headers["x-content-type-options"] = "nosniff"
        return response


# Mount static from DATA_DIR (M3). The URLs are unchanged — `/static/uploads/...`
# still means what it always meant — only the directory behind them left the source
# tree. `check_dir=False` keeps a fresh checkout (no uploads yet) bootable.
paths.ensure_dirs()
app.mount(
    "/static",
    SafeStaticFiles(directory=str(paths.data_dir()), check_dir=False),
    name="static",
)


@app.get("/")
def index():
    return {
        "ok": True,
        "app": "NegArchive API",
        "message": "Frontend runs separately (Next.js). See http://localhost:3000 during development.",
        "ui_url": network.ui_url(),
    }


# Routers
app.include_router(api.router)
app.include_router(library.router)
app.include_router(backup.router)
app.include_router(system.router)
app.include_router(locations.router)
app.include_router(scan.router)
app.include_router(negpy.router)
app.include_router(smb_router.router)
