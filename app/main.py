"""The FastAPI application: migrations at startup, static files, one router."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from .db import SessionLocal, engine
from .errors import ApiError, from_exc, validation_error_response
from .routers import api
from .seed import seed_catalog

REPO_ROOT = Path(__file__).resolve().parent.parent

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A failure here must stop the app: booting against a half-migrated schema is how
    # the old silent `try/except: pass` migrations produced 500s at runtime (R#23).
    run_migrations()
    db = SessionLocal()
    try:
        seed_catalog(db)
    finally:
        db.close()
    yield


app = FastAPI(title="NegArchive", lifespan=lifespan)

# Enable CORS for Node/Next.js frontends (local dev and hosted)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# Mount static. `check_dir=False` keeps a fresh checkout (no uploads yet) bootable.
os.makedirs("static", exist_ok=True)
app.mount("/static", SafeStaticFiles(directory="static", check_dir=False), name="static")


@app.get("/")
def index():
    return {
        "ok": True,
        "app": "NegArchive API",
        "message": "Frontend runs separately (Next.js). See http://localhost:3000 during development.",
    }


# Routers
app.include_router(api.router)
