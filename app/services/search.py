"""Search: one grammar and one matcher for every list in the archive (M7).

Before this, the roll list matched each word against nine columns with ``LIKE``
and the frames page matched two; nothing else could be searched at all, and a
typo found nothing. This module is what both of those lists and the global
search palette (``GET /api/search``) run on, so a word means the same thing
wherever it is typed.

**The grammar.** A query is words and quoted phrases, every one of which must
match (``AND``), plus optional qualifiers that pin a word to one field::

    harbour 2024                 both words, anywhere on or in the roll
    "second visit"               the phrase
    camera:nikon film:gold       only rolls shot on a Nikon with a Gold film
    year:2024 status:sleeved     shot in 2024, filed
    location:"binder 3"          anywhere under a location called Binder 3
    serial:0003                  part of the archive serial

**What a roll matches on.** One lower-cased *haystack* per roll, built in SQL:
title, notes, serial, folder, building, the legacy gear names and the catalog
names the ids point at, format, developer, dilution and push/pull, the years
it was shot, and the notes and original filenames of its frames — so "anna"
finds the roll whose frame 12 says "Anna at the harbour". Storage locations
match by their path (``Archive A / Shelf 2 / Binder 3``), so a search for the
binder finds every roll on every page in it, and a status matches by its value
or its label ("sleeved", "at the lab").

**Typos.** When the ``pg_trgm`` extension is installed (the migration tries to
create it and shrugs if it may not), a word of five letters or more also
matches when it is *nearly* in the haystack — ``word_similarity`` at 0.5, so
"harbor" finds "Harbour" and "kodack" finds "Kodak" but "nikon" does not find
"Minolta". A quoted phrase is never fuzzy, and neither is anything with a
digit or punctuation in it (a serial, a filename). Without the extension the
search is exact, and nothing else changes.

**Ranking.** The lists that show search results order by a score computed in
SQL: an exact serial or title first, then a title that starts with the words,
then one that contains them at a word boundary, then anywhere, then a match in
the notes or the rest, with trigram similarity as a tiebreak when available.
Same age, same score: newest first, as before.

The matcher is deliberately unindexed. A home archive has hundreds of rolls,
a large one a few thousand, and a sequential scan over that with a trigram
function per row is milliseconds. An index would need the haystack to be a
stored column, and keeping it in step with edits on five tables is more
machinery than the archive needs today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from sqlalchemy import Integer, String, cast, extract, func, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from ..models import Camera, FilmRoll, FilmStock, ImageAsset, Lens, Location
from . import lifecycle
from . import locations as loc_svc

#: ``word_similarity(word, haystack)`` at or above this counts as a match. Measured
#: on Postgres 14: harbor/harbour 0.63, kodack/kodak 0.57, tokio/tokyo 0.5,
#: light/night 0.5 (the price), potra/portra 0.44 and witner/winter 0.29 (a
#: dropped or swapped letter in a short word is beyond trigrams; not caught).
FUZZY_THRESHOLD = 0.5
#: Shorter words are matched exactly: with six trigrams, one wrong letter in a
#: four-letter word already scores 0.5, and "f5" is mostly padding.
FUZZY_MIN_LENGTH = 5

#: ``camera:nikon`` — the field a qualified word is pinned to. ``in`` is an alias
#: for ``location`` because "in:binder 3" reads the way people say it.
QUALIFIERS = ("camera", "lens", "film", "year", "status", "location", "in", "serial", "format", "frame", "roll")

_TOKEN = re.compile(r'(?:(?P<key>[a-z]+):)?(?:"(?P<phrase>[^"]*)"|(?P<word>\S+))', re.IGNORECASE)
_YEAR = re.compile(r"^(19|20)\d{2}$")
_FRAME = re.compile(r"^#?(\d{1,4})$")


@dataclass
class Query:
    """A parsed search string."""

    raw: str = ""
    #: Free words, lower-cased, every one of which must match (nearly, with pg_trgm).
    terms: List[str] = field(default_factory=list)
    #: Quoted phrases, lower-cased: must appear as written, never fuzzily.
    phrases: List[str] = field(default_factory=list)
    #: ``{"camera": ["nikon"], "year": ["2024"]}``, keys from :data:`QUALIFIERS`.
    qualifiers: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.terms and not self.phrases and not self.qualifiers

    @property
    def needles(self) -> List[tuple]:
        """``(text, exact)`` for every free term and phrase, in the order typed."""
        return [(term, False) for term in self.terms] + [(phrase, True) for phrase in self.phrases]

    @property
    def phrase(self) -> str:
        """All free terms and phrases as one string, for ranking."""
        return " ".join(self.terms + self.phrases)


def parse(raw: Optional[str]) -> Query:
    """Split a search string into terms and qualifiers.

    Quotes keep a phrase together, a known ``key:`` pins the word to one field,
    and an unknown ``key:`` is just a word with a colon in it (``f:2.8`` is a
    thing somebody might write in a note).
    """
    query = Query(raw=(raw or "").strip())
    for match in _TOKEN.finditer(query.raw):
        key = (match.group("key") or "").lower()
        quoted = match.group("phrase") is not None
        value = match.group("phrase") if quoted else match.group("word")
        value = " ".join((value or "").split()).lower()
        if key in QUALIFIERS:
            if key == "in":
                key = "location"
            if value:
                query.qualifiers.setdefault(key, []).append(value)
            continue
        if key:
            value = f"{key}:{value}"
        if not value:
            continue
        if quoted and " " in value:
            query.phrases.append(value)
        else:
            query.terms.append(value)
    return query


# ---------------------------------------------------------------------------
# pg_trgm
# ---------------------------------------------------------------------------

_trigram: Optional[bool] = None


def trigram_available(db: Session) -> bool:
    """Is ``pg_trgm`` installed in this database? Asked once per process."""
    global _trigram
    if _trigram is None:
        try:
            _trigram = bool(db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).scalar())
        except Exception:
            db.rollback()
            _trigram = False
    return _trigram


def forget_trigram_state() -> None:
    """For tests, and for a migration that installs the extension under a running app."""
    global _trigram
    _trigram = None


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def like_pattern(term: str) -> str:
    r"""``%term%`` with LIKE's own metacharacters escaped (``\`` is the escape)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def contains(column: ColumnElement, term: str) -> ColumnElement:
    """``lower(column) LIKE %term%``, null-safe."""
    return func.lower(func.coalesce(column, "")).like(like_pattern(term), escape="\\")


def nearly(column: ColumnElement, term: str, fuzzy: bool) -> Optional[ColumnElement]:
    """The trigram clause for a term, or None when it does not apply.

    Only plain words are matched nearly. A serial, a filename or anything else
    with a digit or punctuation in it is matched exactly: typos live in words,
    and ``NEG-2024-0001`` nearly matching ``NEG-2024-0002`` would make a serial
    search useless.
    """
    if not fuzzy or len(term) < FUZZY_MIN_LENGTH or not term.isalpha():
        return None
    return func.word_similarity(term, func.lower(func.coalesce(column, ""))) >= FUZZY_THRESHOLD


def matches(column: ColumnElement, term: str, fuzzy: bool) -> ColumnElement:
    """Exact-substring OR nearly, in one clause."""
    approx = nearly(column, term, fuzzy)
    return or_(contains(column, term), approx) if approx is not None else contains(column, term)


def _camera_name():
    return select(Camera.name).where(Camera.id == FilmRoll.camera_id).correlate(FilmRoll).scalar_subquery()


def _lens_name():
    return select(Lens.name).where(Lens.id == FilmRoll.lens_id).correlate(FilmRoll).scalar_subquery()


def _film_name():
    return select(FilmStock.name).where(FilmStock.id == FilmRoll.film_stock_id).correlate(FilmRoll).scalar_subquery()


def _frame_text():
    """Everything written on a roll's frames, as one string."""
    return (
        select(func.string_agg(func.concat_ws(" ", ImageAsset.notes, ImageAsset.original_filename), " "))
        .where(ImageAsset.film_roll_id == FilmRoll.id)
        .correlate(FilmRoll)
        .scalar_subquery()
    )


def roll_haystack() -> ColumnElement:
    """The one lower-cased string a roll is searched in (see the module docstring)."""
    return func.lower(
        func.concat_ws(
            " ",
            FilmRoll.title,
            FilmRoll.notes,
            FilmRoll.archive_serial,
            FilmRoll.folder,
            FilmRoll.building,
            FilmRoll.camera,
            FilmRoll.lens,
            FilmRoll.film_type,
            FilmRoll.format,
            FilmRoll.developer,
            FilmRoll.development_dilution,
            FilmRoll.push_pull,
            _camera_name(),
            _lens_name(),
            _film_name(),
            cast(extract("year", FilmRoll.start_date), String),
            cast(extract("year", FilmRoll.end_date), String),
            _frame_text(),
        )
    )


def frame_haystack() -> ColumnElement:
    """A frame: its note, the scanner's filename, its number, and its roll's title and serial."""
    roll_title = select(FilmRoll.title).where(FilmRoll.id == ImageAsset.film_roll_id).correlate(ImageAsset).scalar_subquery()
    roll_serial = (
        select(FilmRoll.archive_serial).where(FilmRoll.id == ImageAsset.film_roll_id).correlate(ImageAsset).scalar_subquery()
    )
    return func.lower(
        func.concat_ws(
            " ",
            ImageAsset.notes,
            ImageAsset.original_filename,
            cast(ImageAsset.frame_number, String),
            roll_title,
            roll_serial,
        )
    )


def _location_ids_matching(db: Session, term: str) -> List[int]:
    """Locations whose *path* contains the term — so a binder's name finds its pages.

    In Python rather than SQL: the storage tree is a few dozen to a few hundred
    nodes, and the path is already computed by :func:`locations.path_string`.
    """
    needle = term.lower()
    found: List[int] = []
    for node in db.query(Location).all():
        path = (loc_svc.path_string(node) or "").lower()
        code = (node.code or "").lower()
        if needle in path or (code and needle in code):
            found.append(node.id)
    return found


def _statuses_matching(term: str) -> List[str]:
    """Lifecycle steps whose value or label contains the term ("lab" → at_lab)."""
    needle = term.lower().replace("-", "_")
    return [
        value
        for value, label in lifecycle.STATUS_LABELS.items()
        if needle in value or needle in value.replace("_", " ") or needle in label.lower()
    ]


def _year_clause(term: str) -> Optional[ColumnElement]:
    if not _YEAR.match(term):
        return None
    year = int(term)
    return or_(extract("year", FilmRoll.start_date) == year, extract("year", FilmRoll.end_date) == year)


# ---------------------------------------------------------------------------
# Rolls
# ---------------------------------------------------------------------------


def _roll_term(db: Session, hay: ColumnElement, term: str, fuzzy: bool) -> ColumnElement:
    """Every way one free word can match a roll."""
    clauses: List[ColumnElement] = [matches(hay, term, fuzzy)]
    location_ids = _location_ids_matching(db, term)
    if location_ids:
        clauses.append(FilmRoll.location_id.in_(location_ids))
    statuses = _statuses_matching(term)
    if statuses and len(term) >= 3:
        clauses.append(FilmRoll.status.in_(statuses))
    year = _year_clause(term)
    if year is not None:
        clauses.append(year)
    return or_(*clauses)


def _roll_qualifier(db: Session, key: str, value: str, fuzzy: bool) -> ColumnElement:
    if key == "camera":
        return or_(matches(FilmRoll.camera, value, fuzzy), matches(_camera_name(), value, fuzzy))
    if key == "lens":
        return or_(matches(FilmRoll.lens, value, fuzzy), matches(_lens_name(), value, fuzzy))
    if key == "film":
        return or_(matches(FilmRoll.film_type, value, fuzzy), matches(_film_name(), value, fuzzy))
    if key == "serial":
        return contains(FilmRoll.archive_serial, value)
    if key == "format":
        return contains(FilmRoll.format, value)
    if key == "year":
        clause = _year_clause(value)
        return clause if clause is not None else text("false")
    if key == "status":
        statuses = _statuses_matching(value)
        return FilmRoll.status.in_(statuses) if statuses else text("false")
    if key == "location":
        ids = _location_ids_matching(db, value)
        return FilmRoll.location_id.in_(ids) if ids else text("false")
    if key == "roll":
        return or_(matches(FilmRoll.title, value, fuzzy), contains(FilmRoll.archive_serial, value))
    if key == "frame":
        number = _FRAME.match(value)
        if not number:
            return text("false")
        return FilmRoll.id.in_(select(ImageAsset.film_roll_id).where(ImageAsset.frame_number == int(number.group(1))))
    return text("true")


def roll_filters(db: Session, raw: Optional[str], query: Optional[Query] = None) -> List[ColumnElement]:
    """The WHERE clauses for a roll search; empty for an empty query."""
    query = query or parse(raw)
    if query.empty:
        return []
    fuzzy = trigram_available(db)
    hay = roll_haystack()
    clauses = [_roll_term(db, hay, term, fuzzy and not exact) for term, exact in query.needles]
    for key, values in query.qualifiers.items():
        for value in values:
            clauses.append(_roll_qualifier(db, key, value, fuzzy))
    return clauses


def roll_score(db: Session, query: Query) -> ColumnElement:
    """How well a roll matches, for ``ORDER BY ... DESC``."""
    phrase = query.phrase or " ".join(v for values in query.qualifiers.values() for v in values)
    title = func.lower(func.coalesce(FilmRoll.title, ""))
    serial = func.lower(func.coalesce(FilmRoll.archive_serial, ""))
    pattern = like_pattern(phrase)
    score = func.coalesce(
        # `case` via a chain of CASE WHENs would be the idiom; a sum of weighted
        # booleans reads the same and composes better with the trigram term.
        (serial == phrase).cast(Integer) * 1000
        + (title == phrase).cast(Integer) * 900
        + title.like(f"{like_pattern(phrase)[1:]}", escape="\\").cast(Integer) * 300  # starts with
        + title.like(f"% {like_pattern(phrase)[1:]}", escape="\\").cast(Integer) * 150  # a word starts with
        + title.like(pattern, escape="\\").cast(Integer) * 100
        + serial.like(pattern, escape="\\").cast(Integer) * 80
        + func.lower(func.coalesce(FilmRoll.notes, "")).like(pattern, escape="\\").cast(Integer) * 40,
        0,
    )
    if trigram_available(db) and phrase:
        score = score + func.similarity(title, phrase) * 100
    return score


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def _frame_term(hay: ColumnElement, term: str, fuzzy: bool) -> ColumnElement:
    clauses: List[ColumnElement] = [matches(hay, term, fuzzy)]
    number = _FRAME.match(term)
    if number:
        clauses.append(ImageAsset.frame_number == int(number.group(1)))
    return or_(*clauses)


def _frame_qualifier(db: Session, key: str, value: str, fuzzy: bool) -> ColumnElement:
    if key == "frame":
        number = _FRAME.match(value)
        return ImageAsset.frame_number == int(number.group(1)) if number else text("false")
    if key == "roll":
        roll_ids = select(FilmRoll.id).where(
            or_(matches(FilmRoll.title, value, fuzzy), contains(FilmRoll.archive_serial, value))
        )
        return ImageAsset.film_roll_id.in_(roll_ids)
    # A roll-level qualifier on frames selects the frames of the rolls it selects.
    return ImageAsset.film_roll_id.in_(select(FilmRoll.id).where(_roll_qualifier(db, key, value, fuzzy)))


def frame_filters(db: Session, raw: Optional[str], query: Optional[Query] = None) -> List[ColumnElement]:
    """The WHERE clauses for a frame search; empty for an empty query."""
    query = query or parse(raw)
    if query.empty:
        return []
    fuzzy = trigram_available(db)
    hay = frame_haystack()
    clauses = [_frame_term(hay, term, fuzzy and not exact) for term, exact in query.needles]
    for key, values in query.qualifiers.items():
        for value in values:
            clauses.append(_frame_qualifier(db, key, value, fuzzy))
    return clauses


def frame_score(db: Session, query: Query) -> ColumnElement:
    phrase = query.phrase
    notes = func.lower(func.coalesce(ImageAsset.notes, ""))
    filename = func.lower(func.coalesce(ImageAsset.original_filename, ""))
    pattern = like_pattern(phrase)
    number = _FRAME.match(phrase) if phrase else None
    score = func.coalesce(
        (filename == phrase).cast(Integer) * 1000
        + (notes == phrase).cast(Integer) * 900
        + notes.like(f"{like_pattern(phrase)[1:]}", escape="\\").cast(Integer) * 300
        + notes.like(pattern, escape="\\").cast(Integer) * 200
        + filename.like(pattern, escape="\\").cast(Integer) * 100,
        0,
    )
    if number:
        score = score + (ImageAsset.frame_number == int(number.group(1))).cast(Integer) * 500
    if trigram_available(db) and phrase:
        score = score + func.similarity(notes, phrase) * 100
    return score


# ---------------------------------------------------------------------------
# Gear and locations
# ---------------------------------------------------------------------------


def name_filters(db: Session, name: ColumnElement, extras: Sequence[ColumnElement], query: Query) -> List[ColumnElement]:
    """Terms against a name plus a few other columns (mount, manufacturer, notes)."""
    if not query.needles:
        return []
    fuzzy = trigram_available(db)
    hay = func.lower(func.concat_ws(" ", name, *extras))
    return [matches(hay, term, fuzzy and not exact) for term, exact in query.needles]


def name_score(db: Session, name: ColumnElement, query: Query) -> ColumnElement:
    phrase = query.phrase
    lowered = func.lower(func.coalesce(name, ""))
    pattern = like_pattern(phrase)
    score = func.coalesce(
        (lowered == phrase).cast(Integer) * 1000
        + lowered.like(f"{like_pattern(phrase)[1:]}", escape="\\").cast(Integer) * 300
        + lowered.like(f"% {like_pattern(phrase)[1:]}", escape="\\").cast(Integer) * 150
        + lowered.like(pattern, escape="\\").cast(Integer) * 100,
        0,
    )
    if trigram_available(db) and phrase:
        score = score + func.similarity(lowered, phrase) * 100
    return score


def location_matches(db: Session, query: Query) -> List[Location]:
    """Locations whose path, code or notes contain every term, best first."""
    if not query.needles:
        return []
    phrase = query.phrase
    found: List[tuple] = []
    for node in db.query(Location).all():
        path = (loc_svc.path_string(node) or "").lower()
        name = (node.name or "").lower()
        code = (node.code or "").lower()
        notes = (node.notes or "").lower()
        hay = " ".join((path, code, notes))
        if not all(term in hay for term, _ in query.needles):
            continue
        score = 0
        if name == phrase or code == phrase:
            score += 1000
        elif name.startswith(phrase):
            score += 300
        elif phrase in name:
            score += 100
        found.append((-score, path, node))
    found.sort(key=lambda item: (item[0], item[1]))
    return [node for _, _, node in found]


__all__ = [
    "FUZZY_THRESHOLD",
    "QUALIFIERS",
    "Query",
    "parse",
    "trigram_available",
    "forget_trigram_state",
    "roll_filters",
    "roll_score",
    "frame_filters",
    "frame_score",
    "name_filters",
    "name_score",
    "location_matches",
]
