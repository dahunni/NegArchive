"""Request and response models for every endpoint (R#16).

Two rules keep this readable:

* **Requests** are deliberately permissive about scalar *types* — ``iso`` may arrive
  as ``"400"``, ``expired`` as ``"yes"``, a date as a string — and the handler runs
  the value through the parsers in :mod:`app.errors`, which produce a 400 with a
  precise code and the offending ``field``. Shape errors Pydantic catches itself
  (a list where an object belongs, an unknown film format) come back as a 422 in the
  same body, via the handler in :mod:`app.main`.
* **Responses** are strict: each route declares a ``response_model``, so a field that
  the API promises and the code forgets is a test failure rather than a silent
  ``undefined`` in the UI.

``PATCH``-style updates need to tell "key absent" from "key set to null"
(``film_roll_id: null`` unassigns a frame, R#12). Pydantic's ``model_fields_set``
does that, wrapped in :meth:`Update.given`.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import FILM_FORMATS, STORAGE_MODES

FilmFormat = Literal["35mm", "120", "4x5", "8x10", "other"]
StorageMode = Literal["managed", "linked"]
FilmKindName = Literal["black_and_white", "color", "slide", "motion_picture"]
ImageTypeName = Literal["scan", "contact_sheet"]

assert set(FILM_FORMATS) == set(FilmFormat.__args__)  # keep the two definitions honest
assert set(STORAGE_MODES) == set(StorageMode.__args__)


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class Update(Model):
    """A partial update: only the keys the client actually sent are applied."""

    def given(self, name: str) -> bool:
        return name in self.model_fields_set


# --- errors ------------------------------------------------------------------


class ErrorDetail(Model):
    code: str
    message: str
    field: Optional[str] = None


class ErrorOut(Model):
    error: ErrorDetail


# --- film rolls ---------------------------------------------------------------


class FilmRollWrite(Model):
    """Shared body of create and update.

    Gear can be given as an id (preferred, R#14) or as a name (older clients); a name
    that matches a catalog entry is resolved to its id, one that does not is kept as
    free text.
    """

    title: Optional[str] = None
    camera_id: Optional[int] = None
    lens_id: Optional[int] = None
    film_stock_id: Optional[int] = None
    camera: Optional[str] = None
    lens: Optional[str] = None
    film_type: Optional[str] = None
    format: Optional[FilmFormat] = None
    notes: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    building: Optional[str] = None
    folder: Optional[str] = None
    archive_serial: Optional[str] = None


class FilmRollCreate(FilmRollWrite):
    pass


class FilmRollUpdate(FilmRollWrite, Update):
    pass


class FilmRollOut(Model):
    id: int
    title: str
    camera_id: Optional[int] = None
    lens_id: Optional[int] = None
    film_stock_id: Optional[int] = None
    camera: Optional[str] = None
    lens: Optional[str] = None
    film_type: Optional[str] = None
    format: Optional[str] = None
    notes: Optional[str] = None
    building: Optional[str] = None
    folder: Optional[str] = None
    archive_serial: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_at: datetime
    image_count: int = 0
    cover_image_id: Optional[int] = None
    cover_image_ids: List[int] = Field(default_factory=list)


class FilmRollEnvelope(Model):
    ok: bool = True
    film: FilmRollOut


# --- images -------------------------------------------------------------------


class ImageWrite(Model):
    film_roll_id: Optional[int] = None
    type: Optional[ImageTypeName] = None
    path: Optional[str] = None
    original_filename: Optional[str] = None
    storage_mode: Optional[StorageMode] = None
    frame_number: Optional[Any] = None
    notes: Optional[str] = None
    capture_date: Optional[str] = None


class ImageCreate(ImageWrite):
    pass


class ImageUpdate(ImageWrite, Update):
    pass


class ImageOut(Model):
    id: int
    film_roll_id: Optional[int] = None
    type: ImageTypeName
    path: str
    url: str
    original_filename: Optional[str] = None
    storage_mode: str
    frame_number: Optional[int] = None
    notes: Optional[str] = None
    capture_date: Optional[date] = None
    created_at: datetime


class ImageEnvelope(Model):
    ok: bool = True
    image: ImageOut


class ImageListEnvelope(Model):
    ok: bool = True
    images: List[ImageOut] = Field(default_factory=list)


class FilmDetailOut(Model):
    film: FilmRollOut
    images: List[ImageOut] = Field(default_factory=list)
    contact_sheets: List[ImageOut] = Field(default_factory=list)


class BulkImageUpdate(Model):
    ids: List[Any] = Field(default_factory=list)
    film_roll_id: Optional[Any] = None
    capture_date: Optional[str] = None
    frame_number: Optional[Any] = None

    def given(self, name: str) -> bool:
        return name in self.model_fields_set


class BulkImageDelete(Model):
    ids: List[Any] = Field(default_factory=list)
    #: M2 deletes managed files with the record; send ``keep_files`` to opt out (R#9).
    keep_files: Optional[bool] = None
    #: The M1 spelling, still honoured so an older client keeps its behaviour.
    delete_file: Optional[bool] = None


class BulkUpdateResult(Model):
    ok: bool = True
    updated: int
    images: List[ImageOut] = Field(default_factory=list)


class DeleteResult(Model):
    ok: bool = True
    #: Files actually removed from disk with this call.
    files_deleted: int = 0


class BulkDeleteResult(DeleteResult):
    deleted: int


# --- catalog ------------------------------------------------------------------


class CameraWrite(Model):
    name: Optional[str] = None
    mount: Optional[str] = None
    image_path: Optional[str] = None
    notes: Optional[str] = None


class CameraCreate(CameraWrite):
    pass


class CameraUpdate(CameraWrite, Update):
    pass


class CameraOut(Model):
    id: int
    name: str
    mount: Optional[str] = None
    image_path: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None


class CameraEnvelope(Model):
    ok: bool = True
    camera: CameraOut


class LensCreate(CameraWrite):
    pass


class LensUpdate(CameraWrite, Update):
    pass


class LensOut(CameraOut):
    pass


class LensEnvelope(Model):
    ok: bool = True
    lens: LensOut


class FilmStockWrite(Model):
    name: Optional[str] = None
    manufacturer: Optional[str] = None
    format: Optional[FilmFormat] = None
    iso: Optional[Any] = None
    kind: Optional[Any] = None
    expired: Optional[Any] = None
    expiration_date: Optional[str] = None
    image_path: Optional[str] = None


class FilmStockCreate(FilmStockWrite):
    pass


class FilmStockUpdate(FilmStockWrite, Update):
    pass


class FilmStockOut(Model):
    id: int
    name: str
    manufacturer: Optional[str] = None
    format: Optional[str] = None
    iso: Optional[int] = None
    kind: str
    expired: bool
    expiration_date: Optional[date] = None
    image_path: Optional[str] = None
    url: Optional[str] = None


class FilmStockEnvelope(Model):
    ok: bool = True
    filmstock: FilmStockOut


# --- maintenance ---------------------------------------------------------------


class SeedResult(Model):
    ok: bool = True
    added: Dict[str, int]


class MissingFile(Model):
    image_id: int
    path: str
    film_roll_id: Optional[int] = None
    original_filename: Optional[str] = None


class SweepResult(Model):
    ok: bool = True
    #: False for the default dry run; True when the orphans were actually deleted.
    applied: bool = False
    #: Files under static/uploads that no image row points at.
    orphan_files: List[str] = Field(default_factory=list)
    #: Image rows whose file is gone from disk.
    missing_files: List[MissingFile] = Field(default_factory=list)
    deleted_files: int = 0
    bytes_reclaimed: int = 0
