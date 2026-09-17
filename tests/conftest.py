"""Test setup.

The suite runs against Postgres, which is the target database (roadmap decision 2).
Point ``DATABASE_URL`` at a throwaway database before running it, e.g.::

    docker run -d --name negarchive-test-db -p 55433:5432 \\
        -e POSTGRES_USER=negarchive -e POSTGRES_PASSWORD=negarchive \\
        -e POSTGRES_DB=negarchive postgres:16
    DEEPFACE_ENABLED=false \\
    DATABASE_URL=postgresql+psycopg2://negarchive:negarchive@localhost:55433/negarchive \\
        pytest

Without ``DATABASE_URL`` every test is skipped rather than silently falling back
to SQLite, which is where the Postgres-only bugs used to hide.
"""

import os

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SKIP_REASON = "DATABASE_URL is not set; these tests need a Postgres database"


def pytest_collection_modifyitems(config, items):
    if DATABASE_URL:
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def client():
    """A TestClient against a freshly created schema."""
    os.environ.setdefault("DEEPFACE_ENABLED", "false")
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    with TestClient(app) as test_client:  # runs the startup hook (create_all + migrations)
        yield test_client
