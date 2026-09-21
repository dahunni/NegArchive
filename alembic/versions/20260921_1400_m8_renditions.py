"""M8: a NegPy export is a rendition of a frame, not a second frame

Revision ID: 0009_m8_renditions
Revises: 0008_m7_search_trgm
Create Date: 2026-09-21 14:00:00

A roll that goes through NegPy comes back with two files per frame — the raw
negative the scanner made and the positive NegPy exported from it. Stored as two
rows they were counted as two frames: a 33-frame roll listed 66, every frame
appeared twice, and a re-export added a third rather than replacing the second.

``derived_from_id`` hangs the export off the negative it came from. The column
only makes the shape possible; nothing is paired up by this migration, because
matching an export to its negative means reading what the archive knows about
each file and that is a decision, not a schema change. Run
``scripts/repair_negpy_archive.py`` to pair up an archive that already holds
both halves — dry run by default, so it can be looked at first.

The FK is ``ON DELETE CASCADE``: deleting a frame takes its renditions, which is
the only sensible reading of "delete this frame".
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0009_m8_renditions"
down_revision: Union[str, None] = "0008_m7_search_trgm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("image_assets", sa.Column("derived_from_id", sa.Integer(), nullable=True))
    op.create_index("ix_image_assets_derived_from_id", "image_assets", ["derived_from_id"])
    op.create_foreign_key(
        "fk_image_assets_derived_from_id",
        "image_assets",
        "image_assets",
        ["derived_from_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_image_assets_derived_from_id", "image_assets", type_="foreignkey")
    op.drop_index("ix_image_assets_derived_from_id", table_name="image_assets")
    op.drop_column("image_assets", "derived_from_id")
