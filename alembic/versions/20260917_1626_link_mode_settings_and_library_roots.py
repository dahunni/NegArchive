"""M3: link mode, library roots and settings

Revision ID: 0003_m3_offline_first
Revises: 0002_m2_archive_integrity
Create Date: 2026-09-17 16:26:32.123158

Roadmap M3 — import by reference, the watch folder and the settings page.

* ``image_assets.source_path``  absolute path of a file NegArchive links instead of
  owning. NULL for managed files.
* ``image_assets.content_hash`` the sampled SHA-256 from ``app/services/hashing.py``.
  Indexed, because every rescan and every import looks files up by it.
* ``film_rolls.source_dir``     the folder a linked roll came from, unique, so a
  rescan knows which roll a directory already maps to.
* ``library_roots``             one row per registered folder tree.
* ``settings``                  key/value settings that survive a restart.

``image_assets.original_filename`` and ``image_assets.storage_mode`` belong to **M2**
and arrive in ``0002_m2_archive_integrity``, which this revision follows. The guarded
adds for them are kept rather than deleted: they are no-ops against any database that
has run M2's revision, and they are what let this file be applied to an archive whose
history took a different route (a restore from an older dump, say).

Every step is guarded the same way, so the whole revision is safe to re-run.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_m3_offline_first"
down_revision: Union[str, None] = "0002_m2_archive_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has_table("library_roots"):
        op.create_table(
            "library_roots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("path", sa.String(length=1000), nullable=False),
            sa.Column("label", sa.String(length=200), nullable=True),
            sa.Column("watch", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("last_scan_at", sa.DateTime(), nullable=True),
            sa.Column("last_scan_summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_library_roots_id"), "library_roots", ["id"], unique=False)
        op.create_index(op.f("ix_library_roots_path"), "library_roots", ["path"], unique=True)

    if not _has_table("settings"):
        op.create_table(
            "settings",
            sa.Column("key", sa.String(length=100), nullable=False),
            sa.Column("value", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("key"),
        )

    roll_columns = _columns("film_rolls")
    if "source_dir" not in roll_columns:
        op.add_column("film_rolls", sa.Column("source_dir", sa.String(length=1000), nullable=True))
    if "ix_film_rolls_source_dir" not in _indexes("film_rolls"):
        op.create_index(op.f("ix_film_rolls_source_dir"), "film_rolls", ["source_dir"], unique=True)

    image_columns = _columns("image_assets")
    # --- M2's two columns, added only if M2 has not landed yet ----------------
    if "original_filename" not in image_columns:
        op.add_column("image_assets", sa.Column("original_filename", sa.String(length=500), nullable=True))
    if "storage_mode" not in image_columns:
        op.add_column(
            "image_assets",
            sa.Column("storage_mode", sa.String(length=16), server_default="managed", nullable=False),
        )
    # --- M3's own ------------------------------------------------------------
    if "source_path" not in image_columns:
        op.add_column("image_assets", sa.Column("source_path", sa.String(length=1000), nullable=True))
    if "content_hash" not in image_columns:
        op.add_column("image_assets", sa.Column("content_hash", sa.String(length=64), nullable=True))

    image_indexes = _indexes("image_assets")
    if "ix_image_assets_content_hash" not in image_indexes:
        op.create_index(op.f("ix_image_assets_content_hash"), "image_assets", ["content_hash"], unique=False)
    if "ix_image_assets_source_path" not in image_indexes:
        op.create_index(op.f("ix_image_assets_source_path"), "image_assets", ["source_path"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_image_assets_source_path"), table_name="image_assets")
    op.drop_index(op.f("ix_image_assets_content_hash"), table_name="image_assets")
    op.drop_column("image_assets", "content_hash")
    op.drop_column("image_assets", "source_path")
    # original_filename / storage_mode are M2's; leave them alone.
    op.drop_index(op.f("ix_film_rolls_source_dir"), table_name="film_rolls")
    op.drop_column("film_rolls", "source_dir")
    op.drop_table("settings")
    op.drop_index(op.f("ix_library_roots_path"), table_name="library_roots")
    op.drop_index(op.f("ix_library_roots_id"), table_name="library_roots")
    op.drop_table("library_roots")
