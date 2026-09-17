"""Test setup.

The suite runs against Postgres, which is the *only* database NegArchive supports
(roadmap decision 2, M2). Point ``DATABASE_URL`` at a throwaway database before
running it, e.g.::

    docker run -d --rm --name negarchive-test-db -p 55440:5432 \\
        -e POSTGRES_USER=negarchive -e POSTGRES_PASSWORD=negarchive \\
        -e POSTGRES_DB=negarchive postgres:16
    DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:55440/negarchive \\
        pytest

Without ``DATABASE_URL`` every test is skipped rather than silently falling back to
SQLite, which is where the Postgres-only bugs used to hide. A ``DATABASE_URL`` that
is *not* Postgres is an error, not a skip.

The fixture drops the whole schema, including ``alembic_version``, so every run
migrates a genuinely empty database from the first revision to head: the test suite
exercises the migration chain as a side effect.
"""

import os

import pytest
from sqlalchemy import text

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SKIP_REASON = "DATABASE_URL is not set; these tests need a Postgres database"


def pytest_collection_modifyitems(config, items):
    if DATABASE_URL.startswith(("postgresql://", "postgresql+", "postgres://")):
        return
    if DATABASE_URL:
        raise pytest.UsageError(
            f"DATABASE_URL must point at Postgres, got {DATABASE_URL.split(':', 1)[0]!r}. "
            "SQLite support was removed in M2."
        )
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def client():
    """A TestClient against a database built by ``alembic upgrade head``."""
    from fastapi.testclient import TestClient

    from app.db import engine
    from app.main import app

    with engine.begin() as connection:
        # Faster and more thorough than drop_all: it also removes alembic_version and
        # the enum types, so the migrations start from nothing.
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    with TestClient(app) as test_client:  # the lifespan runs the migrations and the seed
        yield test_client
