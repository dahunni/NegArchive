"""M6.1: a frame that is already a positive

Revision ID: 0007_m6_positive
Revises: 0006_m5_development
Create Date: 2026-09-20 13:00:00

One nullable boolean on ``image_assets``. NULL is what every existing frame gets
and means "decide from the film stock", which is exactly what happened before;
TRUE means the file is a finished positive — a NegPy export, a scan of a print —
and the preview shows it as it is, never printing it a second time; FALSE means
"this is a negative even though the roll's film is unknown".

Nothing is backfilled. ``POST /api/negpy/ingest`` sets it from the files
themselves for frames that carry NegPy's XMP.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007_m6_positive"
down_revision: Union[str, None] = "0006_m5_development"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "positive" not in _columns("image_assets"):
        op.add_column("image_assets", sa.Column("positive", sa.Boolean(), nullable=True))


def downgrade() -> None:
    if "positive" in _columns("image_assets"):
        op.drop_column("image_assets", "positive")
