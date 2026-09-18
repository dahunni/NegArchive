"""M5: NegPy integration — ingested metadata and .negpy sidecars

Revision ID: 0005_m5_negpy
Revises: 0004_m4_paper
Create Date: 2026-09-17 22:00:00

Roadmap M5 (docs/NEGPY_INTEGRATION.md). Four columns on ``image_assets``, and
nothing else: the rest of M5 is files on disk, which is the whole point of the
integration.

* ``capture_metadata``  JSONB — everything the file said about itself on ingest
                        (EXIF, the ``negpy:`` XMP namespace, the filename).
* ``sidecar_path``      the ``.negpy`` sidecar next to the file, if there is one.
* ``negpy_edited_at``   when that sidecar was last written.
* ``negpy_recipe``      JSONB — the parsed sidecar and a one-line summary.

Nothing is backfilled here: reading every file in an existing archive is a job
for ``POST /api/negpy/ingest``, which the Settings page offers, not for a
migration that has to finish before the app can start.

Every step is guarded, so the revision can be re-run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_m5_negpy"
down_revision: Union[str, None] = "0004_m4_paper"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


NEW_COLUMNS = (
    ("capture_metadata", lambda: sa.Column("capture_metadata", postgresql.JSONB(), nullable=True)),
    ("sidecar_path", lambda: sa.Column("sidecar_path", sa.String(length=1000), nullable=True)),
    ("negpy_edited_at", lambda: sa.Column("negpy_edited_at", sa.DateTime(), nullable=True)),
    ("negpy_recipe", lambda: sa.Column("negpy_recipe", postgresql.JSONB(), nullable=True)),
)


def upgrade() -> None:
    existing = _columns("image_assets")
    for name, column in NEW_COLUMNS:
        if name not in existing:
            op.add_column("image_assets", column())


def downgrade() -> None:
    existing = _columns("image_assets")
    for name, _ in reversed(NEW_COLUMNS):
        if name in existing:
            op.drop_column("image_assets", name)
