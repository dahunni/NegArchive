"""M7: the pg_trgm extension, for a search that forgives a typo

Revision ID: 0008_m7_search_trgm
Revises: 0007_m6_positive
Create Date: 2026-09-21 09:00:00

``pg_trgm`` ships with every Postgres (it is in contrib, which the official
image and every distribution package include) and is a *trusted* extension
since Postgres 13, so the database owner may create it without being a
superuser. ``app/services/search.py`` uses ``word_similarity`` and
``similarity`` from it when it is there and matches exactly when it is not.

The CREATE runs inside a savepoint and a failure is logged, not raised: an
archive on a managed Postgres whose owner may not create extensions must still
migrate and start. What it loses is "harbor" finding "Harbour", nothing else.
The downgrade leaves the extension alone — other things might use it by then,
and an extension is not schema.
"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008_m7_search_trgm"
down_revision: Union[str, None] = "0007_m6_positive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger("negarchive")


def upgrade() -> None:
    bind = op.get_bind()
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception as exc:  # pragma: no cover - depends on the server's privileges
        log.warning(
            "Could not install the pg_trgm extension (%s). Search will match exactly, without "
            "typo tolerance; a superuser can run `CREATE EXTENSION pg_trgm` on the database later.",
            exc,
        )


def downgrade() -> None:
    pass
