"""The roll lifecycle: loaded → shot → at lab → back → scanned → sleeved (M4).

Each step has a timestamp. ``scanned`` and ``sleeved`` are set automatically (first
scan, first move into a sleeve); the rest by hand, by the wizard's "Load film", or
by a scanner command card. Steps may be skipped; going backwards is allowed too,
because a roll does come back from the lab uncut sometimes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import ROLL_STATUSES, Camera, FilmRoll

STATUS_TIMESTAMP = {
    "loaded": "loaded_at",
    "shot": "shot_at",
    "at_lab": "lab_sent_at",
    "back": "lab_back_at",
    "scanned": "scanned_at",
    "sleeved": "sleeved_at",
}

STATUS_LABELS = {
    "loaded": "In camera",
    "shot": "Shot",
    "at_lab": "At the lab",
    "back": "Back from the lab",
    "scanned": "Scanned",
    "sleeved": "Sleeved",
}


def rank(status: str) -> int:
    return ROLL_STATUSES.index(status) if status in ROLL_STATUSES else -1


def parse_status(value) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text == "atlab":
        text = "at_lab"
    if text not in ROLL_STATUSES:
        raise ApiError("invalid_status", f"Status must be one of: {', '.join(ROLL_STATUSES)}.", 400, "status")
    return text


def set_status(roll: FilmRoll, status: str, at: Optional[datetime] = None) -> None:
    """Set the status and stamp its timestamp (only if not already stamped, unless ``at`` is given)."""
    status = parse_status(status)
    roll.status = status
    column = STATUS_TIMESTAMP[status]
    if at is not None or getattr(roll, column) is None:
        setattr(roll, column, at or datetime.utcnow())
    if roll.loaded_camera_id is not None and rank(status) >= rank("at_lab"):
        # Once the roll left for the lab the camera is free again.
        roll.loaded_camera_id = None


def touch_scanned(roll: FilmRoll) -> None:
    """The first scan arrives: a roll not yet past ``scanned`` becomes ``scanned``."""
    if rank(roll.status) < rank("scanned"):
        set_status(roll, "scanned")
    elif roll.scanned_at is None:
        roll.scanned_at = datetime.utcnow()


def touch_sleeved(roll: FilmRoll) -> None:
    if roll.status != "sleeved":
        set_status(roll, "sleeved")


def load_into_camera(db: Session, camera: Camera, roll: FilmRoll, *, force: bool = False) -> None:
    """Mark a roll as loaded in a camera; refuse while another roll is still in it."""
    other = (
        db.query(FilmRoll)
        .filter(FilmRoll.loaded_camera_id == camera.id, FilmRoll.status.in_(("loaded", "shot")), FilmRoll.id != roll.id)
        .first()
    )
    if other is not None and not force:
        raise ApiError(
            "camera_occupied",
            f"“{camera.name}” still has {other.archive_serial or other.title} loaded. "
            "Mark that roll as shot or sent to the lab first, or pass ?force=true.",
            409,
            "loaded_camera_id",
        )
    roll.loaded_camera_id = camera.id
    if roll.camera_id is None:
        roll.camera_id = camera.id
        roll.camera = camera.name
    set_status(roll, "loaded")


def work_bucket(roll: FilmRoll) -> Optional[str]:
    """Which home-page work list a roll belongs to, or None when it is filed."""
    if roll.status in ("loaded", "shot"):
        return "in_cameras"
    if roll.status == "at_lab":
        return "at_lab"
    if roll.status == "back":
        return "to_scan"
    if roll.status == "scanned":
        return "to_sleeve"
    return None
