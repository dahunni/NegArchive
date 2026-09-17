"""m2 archive integrity

The M2 schema change (docs/ROADMAP.md, R#7, R#10, R#14, R#15, R#21, R#24):

* ``image_assets.original_filename`` — the scanner's name for the file, the only link
  between a physical frame and its scan once the upload renames it to a UUID
* ``image_assets.storage_mode`` — ``managed`` (default, NegArchive owns the file) or
  ``linked``; M3's import-by-reference sets the latter and file deletion respects it
* ``film_rolls.camera_id / lens_id / film_stock_id`` — real foreign keys with
  ``ON DELETE SET NULL``, **backfilled from the existing name columns**. The name
  columns stay for one release so older clients keep working
* ``film_rolls.format``, ``film_stocks.manufacturer``, ``film_stocks.format``
* ``faces`` and ``persons`` are dropped: the DeepFace code was dead and people
  detection comes from Immich in M6

Downgrading restores the empty ``faces``/``persons`` tables and drops the new columns;
the ids backfilled here are not migrated back into the name columns because the name
columns were never removed.

Revision ID: 0002_m2_archive_integrity
Revises: 0001_baseline
Create Date: 2026-09-17 16:22:21.929153

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_m2_archive_integrity'
down_revision: Union[str, None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- faces and persons: dead code since M1, gone for good (R#10, R#15) --------
    # faces.person_id references persons, so faces goes first.
    op.drop_index('ix_faces_id', table_name='faces')
    op.drop_index('ix_faces_image_id', table_name='faces')
    op.drop_index('ix_faces_person_id', table_name='faces')
    op.drop_table('faces')
    op.drop_index('ix_persons_id', table_name='persons')
    op.drop_index('ix_persons_name', table_name='persons')
    op.drop_table('persons')

    # --- gear by id instead of by name (R#14) ------------------------------------
    op.add_column('film_rolls', sa.Column('camera_id', sa.Integer(), nullable=True))
    op.add_column('film_rolls', sa.Column('lens_id', sa.Integer(), nullable=True))
    op.add_column('film_rolls', sa.Column('film_stock_id', sa.Integer(), nullable=True))
    op.add_column('film_rolls', sa.Column('format', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_film_rolls_camera_id'), 'film_rolls', ['camera_id'], unique=False)
    op.create_index(op.f('ix_film_rolls_film_stock_id'), 'film_rolls', ['film_stock_id'], unique=False)
    op.create_index(op.f('ix_film_rolls_lens_id'), 'film_rolls', ['lens_id'], unique=False)

    # Backfill by name before the constraints go on, so an archive that has been in
    # use since M0 comes out of this migration already wired up. Names that match no
    # catalog entry simply stay NULL and keep their free-text name.
    for column, table in (
        ('camera_id', 'cameras'),
        ('lens_id', 'lenses'),
        ('film_stock_id', 'film_stocks'),
    ):
        name_column = {'camera_id': 'camera', 'lens_id': 'lens', 'film_stock_id': 'film_type'}[column]
        op.execute(
            sa.text(
                f"UPDATE film_rolls r SET {column} = c.id "
                f"FROM {table} c "
                f"WHERE r.{column} IS NULL AND r.{name_column} IS NOT NULL "
                f"AND lower(btrim(r.{name_column})) = lower(btrim(c.name))"
            )
        )

    op.create_foreign_key(
        'fk_film_rolls_camera_id_cameras', 'film_rolls', 'cameras',
        ['camera_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_film_rolls_lens_id_lenses', 'film_rolls', 'lenses',
        ['lens_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_film_rolls_film_stock_id_film_stocks', 'film_rolls', 'film_stocks',
        ['film_stock_id'], ['id'], ondelete='SET NULL',
    )

    # --- film stock detail (R#21) -------------------------------------------------
    op.add_column('film_stocks', sa.Column('manufacturer', sa.String(length=200), nullable=True))
    op.add_column('film_stocks', sa.Column('format', sa.String(length=20), nullable=True))

    # --- the file behind a frame (R#7, R#24) --------------------------------------
    op.add_column('image_assets', sa.Column('original_filename', sa.String(length=500), nullable=True))
    op.add_column(
        'image_assets',
        sa.Column('storage_mode', sa.String(length=20), server_default='managed', nullable=False),
    )
    # Frames are listed in frame-number order everywhere now, so the sort has an index.
    op.create_index(op.f('ix_image_assets_frame_number'), 'image_assets', ['frame_number'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_image_assets_frame_number'), table_name='image_assets')
    op.drop_column('image_assets', 'storage_mode')
    op.drop_column('image_assets', 'original_filename')
    op.drop_column('film_stocks', 'format')
    op.drop_column('film_stocks', 'manufacturer')
    op.drop_constraint('fk_film_rolls_film_stock_id_film_stocks', 'film_rolls', type_='foreignkey')
    op.drop_constraint('fk_film_rolls_lens_id_lenses', 'film_rolls', type_='foreignkey')
    op.drop_constraint('fk_film_rolls_camera_id_cameras', 'film_rolls', type_='foreignkey')
    op.drop_index(op.f('ix_film_rolls_lens_id'), table_name='film_rolls')
    op.drop_index(op.f('ix_film_rolls_film_stock_id'), table_name='film_rolls')
    op.drop_index(op.f('ix_film_rolls_camera_id'), table_name='film_rolls')
    op.drop_column('film_rolls', 'format')
    op.drop_column('film_rolls', 'film_stock_id')
    op.drop_column('film_rolls', 'lens_id')
    op.drop_column('film_rolls', 'camera_id')

    op.create_table(
        'persons',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('name', sa.VARCHAR(length=200), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint('id', name='persons_pkey'),
    )
    op.create_index('ix_persons_name', 'persons', ['name'], unique=True)
    op.create_index('ix_persons_id', 'persons', ['id'], unique=False)
    op.create_table(
        'faces',
        sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column('image_id', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('bbox_x', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('bbox_y', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('bbox_w', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('bbox_h', sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column('embedding', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('person_id', sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['image_id'], ['image_assets.id'], name='faces_image_id_fkey'),
        sa.ForeignKeyConstraint(['person_id'], ['persons.id'], name='faces_person_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='faces_pkey'),
    )
    op.create_index('ix_faces_person_id', 'faces', ['person_id'], unique=False)
    op.create_index('ix_faces_image_id', 'faces', ['image_id'], unique=False)
    op.create_index('ix_faces_id', 'faces', ['id'], unique=False)
