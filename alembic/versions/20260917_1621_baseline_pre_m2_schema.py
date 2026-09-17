"""baseline: the schema as it stood before M2

This is where the Alembic chain starts (roadmap M2, R#23). It reproduces exactly what
``Base.metadata.create_all`` plus the old startup ``ALTER TABLE`` hooks in
``app/main.py`` used to build, so:

* on an empty database it creates the pre-M2 schema and the next revision migrates it;
* on a database that already has those tables (anybody who ran a pre-M2 NegArchive),
  it does nothing and only records the revision, so ``alembic upgrade head`` is the
  one upgrade path for new and existing installs alike.

``create_all`` is no longer called anywhere; this file and its successors own the schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-17 16:21:45.528970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _already_built() -> bool:
    """True when this database predates Alembic and already has the M1 tables."""
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table("film_rolls")


def upgrade() -> None:
    if _already_built():
        # An existing install: the tables are there, only the version stamp is missing.
        return
    op.create_table('cameras',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('image_path', sa.String(length=500), nullable=True),
    sa.Column('mount', sa.String(length=100), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cameras_id'), 'cameras', ['id'], unique=False)
    op.create_index(op.f('ix_cameras_name'), 'cameras', ['name'], unique=True)
    op.create_table('film_rolls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('camera', sa.String(length=200), nullable=True),
    sa.Column('lens', sa.String(length=200), nullable=True),
    sa.Column('film_type', sa.String(length=200), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('building', sa.String(length=200), nullable=True),
    sa.Column('folder', sa.String(length=200), nullable=True),
    sa.Column('archive_serial', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_film_rolls_id'), 'film_rolls', ['id'], unique=False)
    op.create_table('film_stocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('iso', sa.Integer(), nullable=True),
    sa.Column('kind', sa.Enum('black_and_white', 'color', 'slide', 'motion_picture', name='filmkind'), nullable=False),
    sa.Column('expired', sa.Boolean(), nullable=True),
    sa.Column('expiration_date', sa.Date(), nullable=True),
    sa.Column('image_path', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_film_stocks_id'), 'film_stocks', ['id'], unique=False)
    op.create_index(op.f('ix_film_stocks_name'), 'film_stocks', ['name'], unique=True)
    op.create_table('lenses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('mount', sa.String(length=100), nullable=True),
    sa.Column('image_path', sa.String(length=500), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lenses_id'), 'lenses', ['id'], unique=False)
    op.create_index(op.f('ix_lenses_name'), 'lenses', ['name'], unique=True)
    op.create_table('persons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_persons_id'), 'persons', ['id'], unique=False)
    op.create_index(op.f('ix_persons_name'), 'persons', ['name'], unique=True)
    op.create_table('image_assets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('film_roll_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.Enum('contact_sheet', 'scan', name='imagetype'), nullable=False),
    sa.Column('path', sa.String(length=500), nullable=False),
    sa.Column('frame_number', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('capture_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['film_roll_id'], ['film_rolls.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_image_assets_film_roll_id'), 'image_assets', ['film_roll_id'], unique=False)
    op.create_index(op.f('ix_image_assets_id'), 'image_assets', ['id'], unique=False)
    op.create_index(op.f('ix_image_assets_type'), 'image_assets', ['type'], unique=False)
    op.create_table('faces',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=False),
    sa.Column('bbox_x', sa.Integer(), nullable=False),
    sa.Column('bbox_y', sa.Integer(), nullable=False),
    sa.Column('bbox_w', sa.Integer(), nullable=False),
    sa.Column('bbox_h', sa.Integer(), nullable=False),
    sa.Column('embedding', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['image_id'], ['image_assets.id'], ),
    sa.ForeignKeyConstraint(['person_id'], ['persons.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_faces_id'), 'faces', ['id'], unique=False)
    op.create_index(op.f('ix_faces_image_id'), 'faces', ['image_id'], unique=False)
    op.create_index(op.f('ix_faces_person_id'), 'faces', ['person_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_faces_person_id'), table_name='faces')
    op.drop_index(op.f('ix_faces_image_id'), table_name='faces')
    op.drop_index(op.f('ix_faces_id'), table_name='faces')
    op.drop_table('faces')
    op.drop_index(op.f('ix_image_assets_type'), table_name='image_assets')
    op.drop_index(op.f('ix_image_assets_id'), table_name='image_assets')
    op.drop_index(op.f('ix_image_assets_film_roll_id'), table_name='image_assets')
    op.drop_table('image_assets')
    op.drop_index(op.f('ix_persons_name'), table_name='persons')
    op.drop_index(op.f('ix_persons_id'), table_name='persons')
    op.drop_table('persons')
    op.drop_index(op.f('ix_lenses_name'), table_name='lenses')
    op.drop_index(op.f('ix_lenses_id'), table_name='lenses')
    op.drop_table('lenses')
    op.drop_index(op.f('ix_film_stocks_name'), table_name='film_stocks')
    op.drop_index(op.f('ix_film_stocks_id'), table_name='film_stocks')
    op.drop_table('film_stocks')
    op.drop_index(op.f('ix_film_rolls_id'), table_name='film_rolls')
    op.drop_table('film_rolls')
    op.drop_index(op.f('ix_cameras_name'), table_name='cameras')
    op.drop_index(op.f('ix_cameras_id'), table_name='cameras')
    op.drop_table('cameras')
    # Postgres keeps an enum type after its table is dropped; without this a
    # `downgrade base` followed by `upgrade head` would fail on "type already exists".
    sa.Enum(name="imagetype").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="filmkind").drop(op.get_bind(), checkfirst=True)
