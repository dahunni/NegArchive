"""SQLAlchemy models.

Postgres only: native ``Boolean``, ``Date`` and ``JSONB`` where needed, no
``with_variant`` branches for a second dialect (M2, roadmap decision 2).

The schema is owned by Alembic (``alembic/versions``); ``create_all`` is not called
anywhere any more. Change a model *and* write a revision.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from .db import Base


class ImageType(enum.Enum):
    contact_sheet = "contact_sheet"
    scan = "scan"


class FilmKind(enum.Enum):
    black_and_white = "black_and_white"
    color = "color"
    slide = "slide"
    motion_picture = "motion_picture"


#: Film formats a roll or a stock can have (R#21). Plain strings rather than a
#: Postgres enum, so adding "110" or "127" later is a column-free migration.
FILM_FORMATS = ("35mm", "120", "4x5", "8x10", "other")

#: How the file behind an image asset is owned. ``managed`` files live under
#: ``static/uploads`` and are deleted with their row; ``linked`` files belong to
#: someone else (M3's import-by-reference) and are never touched.
STORAGE_MODES = ("managed", "linked")

#: M4: the kinds a node of the location tree can be. Any depth is allowed; two
#: kinds carry behaviour: a ``binder`` orders its ``sleeve`` children as pages and a
#: ``sleeve`` holds exactly one roll and has a layout (rows x frames per row).
LOCATION_KINDS = ("building", "room", "shelf", "row", "box", "binder", "envelope", "sleeve", "other")

#: M4: the roll lifecycle, in order. ``scanned`` is set by the first scan, ``sleeved``
#: by the first move into a sleeve; everything else is set by hand or by a scanner
#: command card.
ROLL_STATUSES = ("loaded", "shot", "at_lab", "back", "scanned", "sleeved")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    image_path: Mapped[str | None] = mapped_column(String(500))
    mount: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FilmStock(Base):
    __tablename__ = "film_stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    format: Mapped[str | None] = mapped_column(String(20))
    iso: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[FilmKind] = mapped_column(Enum(FilmKind))
    expired: Mapped[bool | None] = mapped_column(Boolean)  # True expired, False not, None unknown
    expiration_date: Mapped[date | None] = mapped_column(Date)
    image_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lens(Base):
    __tablename__ = "lenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    mount: Mapped[str | None] = mapped_column(String(100))
    image_path: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FilmRoll(Base):
    __tablename__ = "film_rolls"
    __table_args__ = (
        # M4: serials are unique, case-insensitively; rolls without one are not compared.
        Index(
            "ux_film_rolls_archive_serial",
            text("upper(archive_serial)"),
            unique=True,
            postgresql_where=text("archive_serial IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # R#14: gear is referenced by id. The name columns below are kept for one release
    # (older clients still send and read them) and are written from the catalog entry
    # whenever an id is set, so they never go stale on their own.
    camera_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    lens_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lenses.id", ondelete="SET NULL"), index=True
    )
    film_stock_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("film_stocks.id", ondelete="SET NULL"), index=True
    )

    #: Deprecated free-text gear names, superseded by the three ids above.
    camera: Mapped[str | None] = mapped_column(String(200))
    lens: Mapped[str | None] = mapped_column(String(200))
    film_type: Mapped[str | None] = mapped_column(String(200))

    format: Mapped[str | None] = mapped_column(String(20))  # one of FILM_FORMATS
    notes: Mapped[str | None] = mapped_column(Text)

    # --- M5: how the roll was developed ----------------------------------------
    #: Free text on purpose. A developer is "Rodinal" or "Xtol" or "the lab down the
    #: road"; a dilution is "1+50" or "stock"; a push is "+1" or "pulled one stop";
    #: a time is "9:30" or "9 min at 20 °C". Every one of those is what somebody
    #: wrote on the envelope, and an enum would only make them type it somewhere
    #: else. They are filled from NegPy's ``negpy:Developer``,
    #: ``DevelopmentDilution``, ``PushPull`` and ``DevelopmentTime`` on ingest.
    developer: Mapped[str | None] = mapped_column(String(200))
    development_dilution: Mapped[str | None] = mapped_column(String(100))
    push_pull: Mapped[str | None] = mapped_column(String(50))
    development_time: Mapped[str | None] = mapped_column(String(50))

    # Shoot date range (optional)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    # Physical storage location
    building: Mapped[str | None] = mapped_column(String(200))
    folder: Mapped[str | None] = mapped_column(String(200))
    archive_serial: Mapped[str | None] = mapped_column(String(200))

    # --- M4: where the negatives are, and where the roll is in its life ----------
    #: The sleeve, envelope or box the strips are in. NULL = not filed yet.
    location_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    #: Strip lengths overriding the sleeve layout, e.g. ``[5,5,5,5,5,5,6]`` for a roll
    #: doubled up on an old 5-per-row page. NULL = the layout's default.
    strips: Mapped[list | None] = mapped_column(JSONB)
    #: One of ROLL_STATUSES.
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="back", default="back")
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    shot_at: Mapped[datetime | None] = mapped_column(DateTime)
    lab_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    lab_back_at: Mapped[datetime | None] = mapped_column(DateTime)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime)
    sleeved_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: The camera this roll is (or was) loaded in; blocks a second roll in the same camera.
    loaded_camera_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    #: When a label or cover sheet was last printed; the serial is frozen after that,
    #: and a move after it puts the roll back into the print queue.
    label_printed_at: Mapped[datetime | None] = mapped_column(DateTime)

    #: M3: the folder this roll was imported from by reference, so a rescan knows
    #: which roll a directory already maps to. NULL for rolls created in the UI.
    source_dir: Mapped[str | None] = mapped_column(String(1000), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["ImageAsset"]] = relationship(
        "ImageAsset", back_populates="film_roll", cascade="all, delete-orphan"
    )

    # Loaded with the roll: the API answers with the catalog entry's *current* name,
    # so renaming a camera updates every roll that points at it.
    camera_ref: Mapped["Camera | None"] = relationship("Camera", lazy="joined", foreign_keys=[camera_id])
    lens_ref: Mapped["Lens | None"] = relationship("Lens", lazy="joined")
    film_stock_ref: Mapped["FilmStock | None"] = relationship("FilmStock", lazy="joined")
    location_ref: Mapped["Location | None"] = relationship("Location", lazy="joined", foreign_keys=[location_id])
    loaded_camera_ref: Mapped["Camera | None"] = relationship("Camera", foreign_keys=[loaded_camera_id])

    @property
    def camera_name(self) -> str | None:
        return self.camera_ref.name if self.camera_ref else self.camera

    @property
    def lens_name(self) -> str | None:
        return self.lens_ref.name if self.lens_ref else self.lens

    @property
    def film_type_name(self) -> str | None:
        return self.film_stock_ref.name if self.film_stock_ref else self.film_type


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Optional: an image can exist before it is assigned to a roll
    film_roll_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("film_rolls.id"), index=True, nullable=True
    )
    type: Mapped[ImageType] = mapped_column(Enum(ImageType), index=True)
    path: Mapped[str] = mapped_column(String(500))
    #: R#7/R#24: the name the scanner gave the file. The only link between a physical
    #: frame and its file once the upload renames it to a UUID.
    original_filename: Mapped[str | None] = mapped_column(String(500))
    #: 'managed' (NegArchive owns the file) or 'linked' (M3's import-by-reference).
    storage_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="managed", default="managed"
    )
    #: M3: absolute path of a linked original. NULL for managed files, which live
    #: under DATA_DIR and are found through `path`.
    source_path: Mapped[str | None] = mapped_column(String(1000), index=True)
    #: M3: NegPy-compatible sampled SHA-256 (app/services/hashing.py). Indexed,
    #: because rescans and imports look files up by it.
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    frame_number: Mapped[int | None] = mapped_column(Integer, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    capture_date: Mapped[date | None] = mapped_column(Date)

    # --- M5: what the file itself said, and what NegPy has done to it -----------
    #: Everything read out of the file on ingest (EXIF, the ``negpy:`` XMP
    #: namespace, the filename), verbatim. Kept even when it changed nothing: it is
    #: the evidence behind an automatically filled frame number or date.
    capture_metadata: Mapped[dict | None] = mapped_column(JSONB)
    #: The ``.negpy`` sidecar next to this file, when there is one.
    sidecar_path: Mapped[str | None] = mapped_column(String(1000))
    #: When that sidecar was last written — i.e. when the scan was last edited.
    negpy_edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: The parsed sidecar plus a one-line summary of it (services/negpy/sidecar.py).
    negpy_recipe: Mapped[dict | None] = mapped_column(JSONB)
    #: M6.1: is this file already a positive? NULL = decide from the film stock (the
    #: old behaviour); True = a finished positive — a NegPy export, a scan of a print —
    #: shown as it is and never printed a second time; False = a negative even when
    #: the roll's film is unknown. Set from NegPy's XMP on ingest, or by hand.
    positive: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    film_roll: Mapped["FilmRoll | None"] = relationship("FilmRoll", back_populates="images")


class LibraryRoot(Base):
    """A folder registered for import by reference and, optionally, watching (M3).

    One row per tree the user pointed NegArchive at. Each direct subfolder of it
    becomes a roll; the files inside become linked frames. The path is validated
    against ``LIBRARY_ROOTS_ALLOW`` before it is ever stored.
    """

    __tablename__ = "library_roots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(200))
    #: Included in the background poller's sweep.
    watch: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: Human-readable result of the last scan, shown in Settings.
    last_scan_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Key/value settings that outlive a container restart (M3).

    Deliberately schemaless: the archive is single-user and the settings page is
    a handful of toggles. Anything that needs validation gets its own column.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# M4: the physical archive
# ---------------------------------------------------------------------------


class SleeveLayout(Base):
    """How a sleeve page is cut: rows of strips, frames per strip (M4).

    PrintFile 35-7B is 7 rows of 6; the owner's older pages take 5 per row. A roll
    can override the layout with its own ``strips`` list.
    """

    __tablename__ = "sleeve_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    rows: Mapped[int] = mapped_column(Integer, nullable=False)
    frames_per_row: Mapped[int] = mapped_column(Integer, nullable=False)
    film_format: Mapped[str | None] = mapped_column(String(20))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Location(Base):
    """One node of the storage tree: building, shelf, row, binder, sleeve… (M4).

    ``code`` is the short printable identifier (``A``, ``S2``, ``B03``, ``P12``); the
    full path (``Archive A / Shelf 2 / Binder 03 / Page 12``) is derived. A sleeve
    holds exactly one roll; a binder orders its sleeves by ``sort_order`` as pages.
    """

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # one of LOCATION_KINDS
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    #: Sleeves: the page geometry. Binders: the default for pages created inside.
    sleeve_layout_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sleeve_layouts.id", ondelete="SET NULL")
    )
    #: Binders: how many pages fit. Boxes: how many rolls. NULL = unlimited.
    capacity: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent: Mapped["Location | None"] = relationship("Location", remote_side=[id], back_populates="children")
    children: Mapped[list["Location"]] = relationship(
        "Location", back_populates="parent", cascade="all, delete-orphan", order_by="Location.sort_order"
    )
    sleeve_layout: Mapped["SleeveLayout | None"] = relationship("SleeveLayout", lazy="joined")
    rolls: Mapped[list["FilmRoll"]] = relationship("FilmRoll", foreign_keys=[FilmRoll.location_id], viewonly=True)


class LocationMove(Base):
    """Every move of a roll, so the roll page can say where it has been (M4)."""

    __tablename__ = "location_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    roll_id: Mapped[int] = mapped_column(Integer, ForeignKey("film_rolls.id", ondelete="CASCADE"), index=True)
    from_location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("locations.id", ondelete="SET NULL"))
    to_location_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("locations.id", ondelete="SET NULL"))
    moved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


#: When the roll was last moved, loaded with the roll. A label printed before the
#: last move points at the wrong shelf, so ``needs_label`` (app/routers/api.py)
#: and the print queue both ask this one question.
FilmRoll.last_moved_at = column_property(
    select(func.max(LocationMove.moved_at))
    .where(LocationMove.roll_id == FilmRoll.id)
    .correlate_except(LocationMove)
    .scalar_subquery(),
    deferred=False,
)


def needs_label(roll: "FilmRoll") -> bool:
    """Never printed, or moved since the last print."""
    if roll.label_printed_at is None:
        return True
    last = roll.last_moved_at
    return last is not None and last > roll.label_printed_at
