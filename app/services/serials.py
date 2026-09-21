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

#: The same grammar at the *head of a filename*, with either separator and the
#: prefix optional. Two things write it there: NegPy's camera-scan mode
#: (``NEG-2026-0001_Frame001.ARW``) and its export templating, which renders
#: ``{{ roll }}`` through a slug step that turns the hyphens into underscores —
#: so the roll the archive calls ``NEG-2026-0001`` comes back as
#: ``NEG_2026_0001_001.jpg``. A prefix has to start with a letter, or ``img_0007``
#: and every other ``word_number`` scanner name would read as a serial.
_SERIAL_IN_NAME = re.compile(
    r"^(?:(?P<prefix>[A-Za-z][A-Za-z0-9]{0,9})[-_])?(?P<year>\d{4})[-_](?P<number>\d{1,6})(?![0-9])"
)


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


def serial_in_filename(filename: Optional[str]) -> Optional[str]:
    """``"NEG-2026-0001"`` for ``NEG_2026_0001_001.jpg``: the serial a file claims.

    Only a serial at the *head* of the name counts — a number further in is a
    frame, a date or an ISO — and it is spelled back with hyphens whichever
    separator the file used.

    This is a claim, not a fact. It is worth nothing until
    :func:`find_by_serial_loose` matches it against a roll that actually exists,
    which is the whole safety property: a camera's ``IMG_2026_0001_001.jpg`` parses
    just as happily and then matches nothing.
    """
    if not filename:
        return None
    stem = str(filename).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    match = _SERIAL_IN_NAME.match(stem.strip())
    if not match:
        return None
    prefix_value = (match.group("prefix") or "").upper()
    body = f"{match.group('year')}-{match.group('number')}"
    return f"{prefix_value}-{body}" if prefix_value else body


def find_by_serial_loose(db: Session, serial: str) -> Optional[FilmRoll]:
    """:func:`find_by_serial`, but on what a serial *means* rather than how it is spelled.

    ``NEG_2026_0001``, ``NEG-2026-0001`` and ``NEG-2026-1`` are one roll. A file
    that came back from NegPy has been through a templating engine that eats
    hyphens, and a serial written by hand is rarely padded to four digits.
    """
    exact = find_by_serial(db, serial)
    if exact is not None:
        return exact
    wanted = parse((normalize(serial) or "").replace("_", "-"))
    if wanted is None:
        return None
    prefix_value, year, _number = wanted
    for roll in db.query(FilmRoll).filter(
        func.upper(FilmRoll.archive_serial).like(f"{prefix_value}-{year}-%")
    ):
        if parse(roll.archive_serial or "") == wanted:
            return roll
    return None
