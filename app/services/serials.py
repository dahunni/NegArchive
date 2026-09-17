"""Archive serials: ``NEG-YYYY-NNNN`` (roadmap M4).

The serial is what goes on every label, in every QR and barcode and into NegPy's
roll field, so it has three properties the rest of the app relies on:

* **allocated, not typed**: a roll without one gets the next number for its year;
* **unique**, case-insensitively, enforced by a partial unique index;
* **frozen once printed**: after ``label_printed_at`` is set the API refuses to
  change it unless asked to with ``?force=true`` — a label already on a sleeve
  must keep pointing at the roll it was printed for.

The prefix is a setting (``serial_prefix``, default ``NEG``) so an archive can
carry its own scheme; the year and the counter are not negotiable.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import FilmRoll
from . import settings_store

#: Digits in the counter. Grows on its own past 9999 (``f"{n:04d}"`` widens).
COUNTER_WIDTH = 4

_SERIAL = re.compile(r"^(?P<prefix>[A-Z0-9]{1,10})-(?P<year>\d{4})-(?P<number>\d{1,6})$")


def prefix(db: Session) -> str:
    value = (settings_store.get(db, "serial_prefix") or "NEG").strip().upper()
    return re.sub(r"[^A-Z0-9]", "", value)[:10] or "NEG"


def normalize(value: Optional[str]) -> Optional[str]:
    """Trim and upper-case; an empty value is None."""
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def parse(serial: str) -> Optional[tuple[str, int, int]]:
    """``("NEG", 2024, 11)`` for ``NEG-2024-0011``; None for a foreign scheme."""
    match = _SERIAL.match(normalize(serial) or "")
    if not match:
        return None
    return match.group("prefix"), int(match.group("year")), int(match.group("number"))


def year_for(roll: FilmRoll) -> int:
    """The year the serial should carry: when the roll was shot, else when it was created."""
    when = roll.start_date or roll.end_date
    if when is None:
        created = roll.created_at or datetime.utcnow()
        when = created.date() if isinstance(created, datetime) else created
    return when.year


def next_serial(db: Session, year: int, serial_prefix: Optional[str] = None) -> str:
    """The next free ``PREFIX-YEAR-NNNN``, scanning what is already in the table."""
    prefix_value = serial_prefix or prefix(db)
    pattern = f"{prefix_value}-{year}-%"
    highest = 0
    for (existing,) in db.query(FilmRoll.archive_serial).filter(
        func.upper(FilmRoll.archive_serial).like(pattern)
    ):
        parsed = parse(existing or "")
        if parsed and parsed[0] == prefix_value and parsed[1] == year:
            highest = max(highest, parsed[2])
    return f"{prefix_value}-{year}-{highest + 1:0{COUNTER_WIDTH}d}"


def is_taken(db: Session, serial: str, except_roll_id: Optional[int] = None) -> bool:
    query = db.query(FilmRoll.id).filter(func.upper(FilmRoll.archive_serial) == normalize(serial))
    if except_roll_id is not None:
        query = query.filter(FilmRoll.id != except_roll_id)
    return db.query(query.exists()).scalar() is True


def assign(db: Session, roll: FilmRoll, requested: Optional[str], *, force: bool = False) -> None:
    """Set ``roll.archive_serial`` from a request value, allocating when it is empty.

    Raises :class:`ApiError` (409) for a duplicate, or for a change after a label has
    been printed unless ``force``.
    """
    wanted = normalize(requested)
    current = normalize(roll.archive_serial)

    if wanted is None:
        if current is not None:
            return  # nothing requested, nothing to change
        roll.archive_serial = next_serial(db, year_for(roll))
        return

    if wanted == current:
        return
    if current is not None and roll.label_printed_at is not None and not force:
        raise ApiError(
            "serial_frozen",
            f"The serial {current} has been printed on a label. Change it anyway with ?force=true.",
            409,
            "archive_serial",
        )
    if is_taken(db, wanted, except_roll_id=roll.id):
        raise ApiError("duplicate_serial", f"Another roll already carries the serial {wanted}.", 409, "archive_serial")
    roll.archive_serial = wanted


def find_by_serial(db: Session, serial: str) -> Optional[FilmRoll]:
    wanted = normalize(serial)
    if not wanted:
        return None
    return db.query(FilmRoll).filter(func.upper(FilmRoll.archive_serial) == wanted).first()
