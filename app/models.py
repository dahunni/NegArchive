from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSON
import enum

from .db import Base


class ImageType(enum.Enum):
    contact_sheet = "contact_sheet"
    scan = "scan"


class FilmKind(enum.Enum):
    black_and_white = "black_and_white"
    color = "color"
    slide = "slide"
    motion_picture = "motion_picture"


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
    iso: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[FilmKind] = mapped_column(Enum(FilmKind))
    expired: Mapped[int | None] = mapped_column(Integer)  # 1 for expired, 0 for not, None unknown
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
    # Camera and film stock managed via catalogs; stored by name for compatibility
    camera: Mapped[str | None] = mapped_column(String(200))
    lens: Mapped[str | None] = mapped_column(String(200))
    film_type: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)

    # Shoot date range (optional)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    # Physical storage location
    building: Mapped[str | None] = mapped_column(String(200))
    folder: Mapped[str | None] = mapped_column(String(200))
    archive_serial: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["ImageAsset"]] = relationship("ImageAsset", back_populates="film_roll", cascade="all, delete-orphan")


class ImageAsset(Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    film_roll_id: Mapped[int] = mapped_column(Integer, ForeignKey("film_rolls.id"), index=True)
    type: Mapped[ImageType] = mapped_column(Enum(ImageType), index=True)
    path: Mapped[str] = mapped_column(String(500))
    frame_number: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    capture_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    film_roll: Mapped[FilmRoll] = relationship("FilmRoll", back_populates="images")
    faces: Mapped[list["Face"]] = relationship("Face", back_populates="image", cascade="all, delete-orphan")


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    faces: Mapped[list["Face"]] = relationship("Face", back_populates="person")


class Face(Base):
    __tablename__ = "faces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    image_id: Mapped[int] = mapped_column(Integer, ForeignKey("image_assets.id"), index=True)
    bbox_x: Mapped[int] = mapped_column(Integer)
    bbox_y: Mapped[int] = mapped_column(Integer)
    bbox_w: Mapped[int] = mapped_column(Integer)
    bbox_h: Mapped[int] = mapped_column(Integer)

    # Store embedding as JSON for portability across DBs
    embedding: Mapped[dict | None] = mapped_column(JSON().with_variant(Text(), "sqlite"))

    person_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("persons.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    image: Mapped[ImageAsset] = relationship("ImageAsset", back_populates="faces")
    person: Mapped[Person | None] = relationship("Person", back_populates="faces")