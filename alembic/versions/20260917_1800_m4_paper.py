"""M4: the physical archive — locations, serials, lifecycle, strips

Revision ID: 0004_m4_paper
Revises: 0003_m3_offline_first
Create Date: 2026-09-17 18:00:00

Roadmap M4 (docs/M4_PAPER.md).

* ``sleeve_layouts``   rows x frames per row; four seeded, PrintFile 35-7B default.
* ``locations``        one tree of any depth (building, shelf, row, binder, sleeve…).
* ``location_moves``   every move of a roll.
* ``film_rolls``       ``location_id``, ``strips``, the lifecycle ``status`` and its
                       six timestamps, ``loaded_camera_id``, ``label_printed_at``.
* ``archive_serial``   unique (partial index, NULLs excluded), then backfilled as
                       ``NEG-YYYY-NNNN`` for every roll that has none.
* ``building`` / ``folder`` are migrated into location nodes (building → binder)
  and the roll is filed there. The two text columns stay for one release, read-only.

Every step is guarded so the revision can be re-run.
"""

from datetime import date, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_m4_paper"
down_revision: Union[str, None] = "0003_m3_offline_first"
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


SEED_LAYOUTS = [
    ("PrintFile 35-7B (7 × 6)", 7, 6, "35mm", True),
    ("5 per row (7 × 5)", 7, 5, "35mm", False),
    ("120 — 3 per row (4 × 3)", 4, 3, "120", False),
    ("120 — 4 per row (3 × 4)", 3, 4, "120", False),
]


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table("sleeve_layouts"):
        op.create_table(
            "sleeve_layouts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("rows", sa.Integer(), nullable=False),
            sa.Column("frames_per_row", sa.Integer(), nullable=False),
            sa.Column("film_format", sa.String(length=20), nullable=True),
            sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(op.f("ix_sleeve_layouts_id"), "sleeve_layouts", ["id"], unique=False)

    if not _has_table("locations"):
        op.create_table(
            "locations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("code", sa.String(length=50), nullable=True),
            sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("sleeve_layout_id", sa.Integer(), nullable=True),
            sa.Column("capacity", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["parent_id"], ["locations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["sleeve_layout_id"], ["sleeve_layouts.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_locations_id"), "locations", ["id"], unique=False)
        op.create_index(op.f("ix_locations_parent_id"), "locations", ["parent_id"], unique=False)

    roll_columns = _columns("film_rolls")
    if "location_id" not in roll_columns:
        op.add_column("film_rolls", sa.Column("location_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_film_rolls_location_id", "film_rolls", "locations", ["location_id"], ["id"], ondelete="SET NULL"
        )
        op.create_index(op.f("ix_film_rolls_location_id"), "film_rolls", ["location_id"], unique=False)
    if "strips" not in roll_columns:
        op.add_column("film_rolls", sa.Column("strips", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "status" not in roll_columns:
        op.add_column("film_rolls", sa.Column("status", sa.String(length=20), server_default="back", nullable=False))
    for column in ("loaded_at", "shot_at", "lab_sent_at", "lab_back_at", "scanned_at", "sleeved_at", "label_printed_at"):
        if column not in roll_columns:
            op.add_column("film_rolls", sa.Column(column, sa.DateTime(), nullable=True))
    if "loaded_camera_id" not in roll_columns:
        op.add_column("film_rolls", sa.Column("loaded_camera_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_film_rolls_loaded_camera_id", "film_rolls", "cameras", ["loaded_camera_id"], ["id"], ondelete="SET NULL"
        )
        op.create_index(op.f("ix_film_rolls_loaded_camera_id"), "film_rolls", ["loaded_camera_id"], unique=False)

    if not _has_table("location_moves"):
        op.create_table(
            "location_moves",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("roll_id", sa.Integer(), nullable=False),
            sa.Column("from_location_id", sa.Integer(), nullable=True),
            sa.Column("to_location_id", sa.Integer(), nullable=True),
            sa.Column("moved_at", sa.DateTime(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["roll_id"], ["film_rolls.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["from_location_id"], ["locations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["to_location_id"], ["locations.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_location_moves_id"), "location_moves", ["id"], unique=False)
        op.create_index(op.f("ix_location_moves_roll_id"), "location_moves", ["roll_id"], unique=False)

    # --- seed the sleeve layouts ---------------------------------------------
    existing_layouts = {row[0] for row in bind.execute(sa.text("SELECT name FROM sleeve_layouts")).fetchall()}
    for name, rows, per_row, fmt, is_default in SEED_LAYOUTS:
        if name not in existing_layouts:
            bind.execute(
                sa.text(
                    "INSERT INTO sleeve_layouts (name, rows, frames_per_row, film_format, is_default, created_at) "
                    "VALUES (:name, :rows, :per_row, :fmt, :is_default, :now)"
                ),
                {"name": name, "rows": rows, "per_row": per_row, "fmt": fmt, "is_default": is_default, "now": datetime.utcnow()},
            )

    # --- status backfill: a roll with scans is `scanned`, otherwise `back` ------
    bind.execute(
        sa.text(
            "UPDATE film_rolls SET status = 'scanned', scanned_at = COALESCE(scanned_at, created_at) "
            "WHERE status = 'back' AND id IN (SELECT DISTINCT film_roll_id FROM image_assets "
            "WHERE film_roll_id IS NOT NULL AND type = 'scan')"
        )
    )

    # --- serial backfill and uniqueness ---------------------------------------
    rows = bind.execute(
        sa.text(
            "SELECT id, archive_serial, start_date, created_at FROM film_rolls ORDER BY created_at ASC, id ASC"
        )
    ).fetchall()
    taken: dict[str, int] = {}
    import re

    pattern = re.compile(r"^NEG-(\d{4})-(\d+)$")
    for _, serial, _, _ in rows:
        if serial:
            match = pattern.match(serial.strip().upper())
            if match:
                year, number = match.group(1), int(match.group(2))
                taken[year] = max(taken.get(year, 0), number)
    seen: set[str] = set()
    for roll_id, serial, start_date, created_at in rows:
        clean = (serial or "").strip()
        if clean and clean.upper() not in seen:
            seen.add(clean.upper())
            if clean != serial:
                bind.execute(sa.text("UPDATE film_rolls SET archive_serial = :s WHERE id = :id"), {"s": clean, "id": roll_id})
            continue
        # Missing, or a duplicate of one already seen: allocate a fresh one.
        when = start_date or (created_at.date() if isinstance(created_at, datetime) else created_at) or date.today()
        year = str(when.year)
        taken[year] = taken.get(year, 0) + 1
        fresh = f"NEG-{year}-{taken[year]:04d}"
        while fresh.upper() in seen:
            taken[year] += 1
            fresh = f"NEG-{year}-{taken[year]:04d}"
        seen.add(fresh.upper())
        bind.execute(sa.text("UPDATE film_rolls SET archive_serial = :s WHERE id = :id"), {"s": fresh, "id": roll_id})

    if "ux_film_rolls_archive_serial" not in _indexes("film_rolls"):
        op.create_index(
            "ux_film_rolls_archive_serial",
            "film_rolls",
            [sa.text("upper(archive_serial)")],
            unique=True,
            postgresql_where=sa.text("archive_serial IS NOT NULL"),
        )

    # --- building / folder → location nodes ----------------------------------
    rolls = bind.execute(
        sa.text("SELECT id, building, folder FROM film_rolls WHERE location_id IS NULL AND (building IS NOT NULL OR folder IS NOT NULL)")
    ).fetchall()
    if rolls:
        node_ids: dict[tuple, int] = {}
        for row in bind.execute(sa.text("SELECT id, parent_id, kind, name FROM locations")).fetchall():
            node_ids[(row[1], row[3].strip().lower())] = row[0]

        def ensure(parent_id, kind, name) -> int:
            key = (parent_id, name.strip().lower())
            if key in node_ids:
                return node_ids[key]
            result = bind.execute(
                sa.text(
                    "INSERT INTO locations (parent_id, kind, name, code, sort_order, created_at) "
                    "VALUES (:parent, :kind, :name, NULL, 0, :now) RETURNING id"
                ),
                {"parent": parent_id, "kind": kind, "name": name.strip(), "now": datetime.utcnow()},
            )
            node_ids[key] = result.scalar_one()
            return node_ids[key]

        for roll_id, building, folder in rolls:
            target = None
            if building and building.strip():
                target = ensure(None, "building", building)
            if folder and folder.strip():
                target = ensure(target, "binder", folder)
            if target is not None:
                bind.execute(
                    sa.text("UPDATE film_rolls SET location_id = :loc WHERE id = :id"),
                    {"loc": target, "id": roll_id},
                )


def downgrade() -> None:
    op.drop_index("ux_film_rolls_archive_serial", table_name="film_rolls")
    op.drop_table("location_moves")
    op.drop_index(op.f("ix_film_rolls_loaded_camera_id"), table_name="film_rolls")
    op.drop_constraint("fk_film_rolls_loaded_camera_id", "film_rolls", type_="foreignkey")
    op.drop_column("film_rolls", "loaded_camera_id")
    for column in ("label_printed_at", "sleeved_at", "scanned_at", "lab_back_at", "lab_sent_at", "shot_at", "loaded_at"):
        op.drop_column("film_rolls", column)
    op.drop_column("film_rolls", "status")
    op.drop_column("film_rolls", "strips")
    op.drop_index(op.f("ix_film_rolls_location_id"), table_name="film_rolls")
    op.drop_constraint("fk_film_rolls_location_id", "film_rolls", type_="foreignkey")
    op.drop_column("film_rolls", "location_id")
    op.drop_table("locations")
    op.drop_table("sleeve_layouts")
