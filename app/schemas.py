from pydantic import BaseModel, Field
from typing import Optional, List
from .models import ImageType


class FilmRollCreate(BaseModel):
    title: str
    camera: Optional[str] = None
    lens: Optional[str] = None
    film_type: Optional[str] = None
    notes: Optional[str] = None
    building: Optional[str] = None
    folder: Optional[str] = None
    archive_serial: Optional[str] = None


class FilmRollOut(BaseModel):
    id: int
    title: str
    camera: Optional[str]
    lens: Optional[str]
    film_type: Optional[str]
    notes: Optional[str]
    building: Optional[str]
    folder: Optional[str]
    archive_serial: Optional[str]

    class Config:
        from_attributes = True


class ImageUpload(BaseModel):
    film_roll_id: int
    type: ImageType
    frame_number: Optional[int] = None
    notes: Optional[str] = None


class PersonOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True