"""M5: how a roll was developed — developer, dilution, push/pull, time

Revision ID: 0006_m5_development
Revises: 0005_m5_negpy
Create Date: 2026-09-18 09:00:00

The four fields NegPy already writes into XMP (``negpy:Developer``,
``DevelopmentDilution``, ``PushPull``, ``DevelopmentTime``) and that M5's ingest had
nowhere to put but the roll's notes. They are free text, because a developer is
"Rodinal" or "the lab down the road" and a time is "9:30" or "9 min at 20 °C";
an enum would only make somebody type it somewhere else.

Nothing is backfilled and nothing is parsed out of existing notes: a migration that
rewrites what a person typed is a bad trade for four fields that
``POST /api/negpy/ingest`` fills from the files themselves.

Every step is guarded, so the revision can be re-run.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006_m5_development"
down_revision: Union[str, None] = "0005_m5_negpy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


NEW_COLUMNS = (
    ("developer", lambda: sa.Column("developer", sa.String(length=200), nullable=True)),
    ("development_dilution", lambda: sa.Column("development_dilution", sa.String(length=100), nullable=True)),
    ("push_pull", lambda: sa.Column("push_pull", sa.String(length=50), nullable=True)),
    ("development_time", lambda: sa.Column("development_time", sa.String(length=50), nullable=True)),
)


def upgrade() -> None:
    existing = _columns("film_rolls")
    for name, column in NEW_COLUMNS:
        if name not in existing:
            op.add_column("film_rolls", column())


def downgrade() -> None:
    existing = _columns("film_rolls")
    for name, _ in reversed(NEW_COLUMNS):
        if name in existing:
            op.drop_column("film_rolls", name)
