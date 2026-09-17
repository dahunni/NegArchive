"""SQLAlchemy models.

Postgres only: native ``Boolean``, ``Date`` and ``JSONB`` where needed, no
``with_variant`` branches for a second dialect (M2, roadmap decision 2).

The schema is owned by Alembic (``alembic/versions``); ``create_all`` is not called
anywhere any more. Change a model *and* write a revision.
"""

from datetime import date, datetime
import enum

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    # Shoot date range (optional)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    # Physical storage location
    building: Mapped[str | None] = mapped_column(String(200))
    folder: Mapped[str | None] = mapped_column(String(200))
    archive_serial: Mapped[str | None] = mapped_column(String(200))

    #: M3: the folder this roll was imported from by reference, so a rescan knows
    #: which roll a directory already maps to. NULL for rolls created in the UI.
    source_dir: Mapped[str | None] = mapped_column(String(1000), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["ImageAsset"]] = relationship(
        "ImageAsset", back_populates="film_roll", cascade="all, delete-orphan"
    )

    # Loaded with the roll: the API answers with the catalog entry's *current* name,
    # so renaming a camera updates every roll that points at it.
    camera_ref: Mapped["Camera | None"] = relationship("Camera", lazy="joined")
    lens_ref: Mapped["Lens | None"] = relationship("Lens", lazy="joined")
    film_stock_ref: Mapped["FilmStock | None"] = relationship("FilmStock", lazy="joined")

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
