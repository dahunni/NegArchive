"""Engine and session.

Postgres only (roadmap decision 2). SQLite used to be the default and hid two
Postgres-only bugs (R#1, R#10) behind a second code path, so there is no fallback
any more: ``DATABASE_URL`` is required and must point at Postgres.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


class DatabaseNotConfigured(RuntimeError):
    """Raised at import time when ``DATABASE_URL`` is missing or not Postgres."""


def database_url() -> str:
    """The configured Postgres URL, or a loud error explaining how to set one."""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. NegArchive needs Postgres, for example:\n"
            "  DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:5432/negarchive\n"
            "Start one with `docker compose up -d db`. SQLite is no longer supported; "
            "see scripts/migrate_sqlite_to_pg.py to move an old negarchive.db across."
        )
    if not url.startswith(("postgresql://", "postgresql+", "postgres://")):
        raise DatabaseNotConfigured(
            f"DATABASE_URL must be a Postgres URL, got {url.split(':', 1)[0]!r}. "
            "SQLite support was removed in M2; see scripts/migrate_sqlite_to_pg.py."
        )
    return url


DATABASE_URL = database_url()

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
