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
    # --- M4 ---
    location_id: Optional[Any] = None
    strips: Optional[Any] = None
    status: Optional[str] = None
    loaded_camera_id: Optional[Any] = None


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
    # --- M4: where it is, and where it is in its life ---
    location_id: Optional[int] = None
    location_path: Optional[str] = None
    location_kind: Optional[str] = None
    strips: Optional[List[int]] = None
    effective_strips: List[int] = Field(default_factory=list)
    status: str = "back"
    status_label: Optional[str] = None
    loaded_at: Optional[datetime] = None
    shot_at: Optional[datetime] = None
    lab_sent_at: Optional[datetime] = None
    lab_back_at: Optional[datetime] = None
    scanned_at: Optional[datetime] = None
    sleeved_at: Optional[datetime] = None
    loaded_camera_id: Optional[int] = None
    label_printed_at: Optional[datetime] = None
    needs_label: bool = False


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
    #: M3, import by reference: where a linked original really is (NULL for a
    #: managed file), and the sampled hash that identifies it across a move.
    source_path: Optional[str] = None
    content_hash: Optional[str] = None
    frame_number: Optional[int] = None
    notes: Optional[str] = None
    capture_date: Optional[date] = None
    #: M5, NegPy: what the file said about itself when it was ingested, and the
    #: ``.negpy`` sidecar next to it, if any.
    capture_metadata: Optional[Dict[str, Any]] = None
    sidecar_path: Optional[str] = None
    negpy_edited_at: Optional[datetime] = None
    negpy_recipe: Optional[Dict[str, Any]] = None
    negpy_summary: Optional[str] = None
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


# --- M4: locations, scanning, printing -----------------------------------------


class SleeveLayoutWrite(Model):
    name: Optional[str] = None
    rows: Optional[Any] = None
    frames_per_row: Optional[Any] = None
    film_format: Optional[str] = None
    is_default: Optional[bool] = False


class LocationWrite(Model):
    parent_id: Optional[Any] = None
    kind: Optional[str] = None
    name: Optional[str] = None
    code: Optional[str] = None
    sort_order: Optional[Any] = None
    notes: Optional[str] = None
    capacity: Optional[Any] = None
    sleeve_layout_id: Optional[Any] = None


class LocationCreate(LocationWrite):
    pass


class LocationUpdate(LocationWrite, Update):
    pass


class AddPages(Model):
    count: Any = 1
    sleeve_layout_id: Optional[int] = None


class MoveRoll(Model):
    location_id: Optional[Any] = None
    note: Optional[str] = None


class BulkMove(Model):
    ids: List[Any] = Field(default_factory=list)
    location_id: Optional[Any] = None
    note: Optional[str] = None


class ScanToken(Model):
    code: str


class MarkPrinted(Model):
    roll_ids: List[Any] = Field(default_factory=list)


class StatusChange(Model):
    status: str
    at: Optional[str] = None


class LoadFilm(Model):
    title: Optional[str] = None
    film_stock_id: Optional[Any] = None
    lens_id: Optional[Any] = None
    format: Optional[FilmFormat] = None
    notes: Optional[str] = None
    force: Optional[bool] = False
