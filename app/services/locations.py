"""The storage tree (roadmap M4): paths, counts, pages, moves.

One table, any depth. Two kinds carry behaviour: a **sleeve** holds exactly one
roll and has a layout; a **binder** orders its sleeves by ``sort_order`` as pages
and knows which pages are empty or missing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import LOCATION_KINDS, FilmRoll, Location, LocationMove, SleeveLayout
from . import lifecycle

#: Kinds that hold rolls directly. Anything else is a container of containers, but
#: a roll may still be filed there loosely (a box of envelopes, say).
HOLDS_ONE_ROLL = {"sleeve"}


def parse_kind(value) -> str:
    text = str(value or "").strip().lower()
    if text not in LOCATION_KINDS:
        raise ApiError("invalid_kind", f"Kind must be one of: {', '.join(LOCATION_KINDS)}.", 400, "kind")
    return text


def ancestors(node: Location) -> List[Location]:
    """Root first, ``node`` last."""
    chain: List[Location] = []
    current: Optional[Location] = node
    guard = 0
    while current is not None and guard < 64:
        chain.append(current)
        current = current.parent
        guard += 1
    chain.reverse()
    return chain


def label(node: Location) -> str:
    """``B03 Binder 3`` when there is a code, else the name."""
    if node.code and node.code.strip() and node.code.strip().lower() != node.name.strip().lower():
        return f"{node.code.strip()} · {node.name.strip()}"
    return node.name.strip()


def path_string(node: Optional[Location]) -> Optional[str]:
    if node is None:
        return None
    return " / ".join(label(n) for n in ancestors(node))


def path_ids(node: Optional[Location]) -> List[int]:
    return [n.id for n in ancestors(node)] if node else []


def default_layout(db: Session) -> Optional[SleeveLayout]:
    return (
        db.query(SleeveLayout).filter(SleeveLayout.is_default.is_(True)).first()
        or db.query(SleeveLayout).order_by(SleeveLayout.id.asc()).first()
    )


def layout_for(db: Session, node: Optional[Location]) -> Optional[SleeveLayout]:
    """The sleeve layout that applies to a node: its own, else the nearest ancestor's, else the default."""
    current = node
    while current is not None:
        if current.sleeve_layout is not None:
            return current.sleeve_layout
        current = current.parent
    return default_layout(db)


def roll_counts(db: Session) -> Dict[int, int]:
    """``{location_id: rolls filed directly there}``."""
    rows = (
        db.query(FilmRoll.location_id, func.count(FilmRoll.id))
        .filter(FilmRoll.location_id.isnot(None))
        .group_by(FilmRoll.location_id)
        .all()
    )
    return dict(rows)


def subtree_counts(nodes: Iterable[Location], direct: Dict[int, int]) -> Dict[int, int]:
    """Direct counts rolled up into every ancestor."""
    by_id = {n.id: n for n in nodes}
    totals: Dict[int, int] = {}
    for node_id, count in direct.items():
        current = by_id.get(node_id)
        while current is not None:
            totals[current.id] = totals.get(current.id, 0) + count
            current = by_id.get(current.parent_id) if current.parent_id else None
    return totals


def to_dict(node: Location, *, direct: Optional[Dict[int, int]] = None, totals: Optional[Dict[int, int]] = None) -> dict:
    layout = node.sleeve_layout
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "kind": node.kind,
        "name": node.name,
        "code": node.code,
        "label": label(node),
        "path": path_string(node),
        "path_ids": path_ids(node),
        "sort_order": node.sort_order,
        "notes": node.notes,
        "capacity": node.capacity,
        "sleeve_layout_id": node.sleeve_layout_id,
        "sleeve_layout": (
            {"id": layout.id, "name": layout.name, "rows": layout.rows, "frames_per_row": layout.frames_per_row}
            if layout
            else None
        ),
        "roll_count": (direct or {}).get(node.id, 0),
        "rolls_in_subtree": (totals or {}).get(node.id, 0),
        "scan_code": f"LOC-{node.id}",
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


def occupant(db: Session, sleeve: Location, except_roll_id: Optional[int] = None) -> Optional[FilmRoll]:
    query = db.query(FilmRoll).filter(FilmRoll.location_id == sleeve.id)
    if except_roll_id is not None:
        query = query.filter(FilmRoll.id != except_roll_id)
    return query.first()


def next_free_sleeve(db: Session, container: Location) -> Optional[Location]:
    """The first empty sleeve page under a binder (or any container), in page order.

    Queried, not read off ``container.children``: pages added a moment ago in the
    same session are not in the loaded relationship yet.
    """
    taken = {roll_id for (roll_id,) in db.query(FilmRoll.location_id).filter(FilmRoll.location_id.isnot(None))}
    pages = (
        db.query(Location)
        .filter(Location.parent_id == container.id, Location.kind == "sleeve")
        .order_by(Location.sort_order.asc(), Location.id.asc())
        .all()
    )
    for page in pages:
        if page.id not in taken:
            return page
    return None


def move_roll(db: Session, roll: FilmRoll, target: Optional[Location], note: Optional[str] = None) -> Location | None:
    """File a roll in ``target`` (a binder resolves to its next free page). Returns where it went.

    Raises 409 ``sleeve_occupied`` when the sleeve already holds another roll, and
    409 ``no_free_page`` when a binder has no empty sleeve left.
    """
    destination = target
    if target is not None and target.kind == "binder":
        destination = next_free_sleeve(db, target)
        if destination is None:
            raise ApiError(
                "no_free_page",
                f"“{label(target)}” has no empty page. Add pages to the binder first.",
                409,
                "location_id",
            )
    if destination is not None and destination.kind in HOLDS_ONE_ROLL:
        other = occupant(db, destination, except_roll_id=roll.id)
        if other is not None:
            raise ApiError(
                "sleeve_occupied",
                f"“{path_string(destination)}” already holds {other.archive_serial or other.title}.",
                409,
                "location_id",
            )
    if destination is not None and destination.capacity is not None and destination.kind not in HOLDS_ONE_ROLL:
        held = db.query(func.count(FilmRoll.id)).filter(FilmRoll.location_id == destination.id, FilmRoll.id != roll.id).scalar() or 0
        if held >= destination.capacity:
            raise ApiError(
                "location_full",
                f"“{label(destination)}” is full ({destination.capacity}).",
                409,
                "location_id",
            )

    previous_id = roll.location_id
    if previous_id == (destination.id if destination else None):
        return destination
    roll.location_id = destination.id if destination else None
    db.add(
        LocationMove(
            roll_id=roll.id,
            from_location_id=previous_id,
            to_location_id=roll.location_id,
            moved_at=datetime.utcnow(),
            note=note,
        )
    )
    if destination is not None and destination.kind == "sleeve":
        lifecycle.touch_sleeved(roll)
    elif roll.status == "sleeved" and (destination is None or destination.kind != "sleeve"):
        # Taken out of its sleeve: it is scanned (or back), not sleeved any more.
        roll.status = "scanned" if roll.scanned_at else "back"
    return destination


def add_pages(db: Session, binder: Location, count: int, layout: Optional[SleeveLayout] = None) -> List[Location]:
    """Append ``count`` sleeve pages to a binder, numbered on from the last page."""
    if count < 1 or count > 500:
        raise ApiError("invalid_count", "Add between 1 and 500 pages at a time.", 400, "count")
    existing = db.query(Location).filter(Location.parent_id == binder.id, Location.kind == "sleeve").all()
    highest = max((c.sort_order for c in existing), default=0)
    if binder.capacity is not None and len(existing) + count > binder.capacity:
        raise ApiError(
            "binder_full",
            f"“{label(binder)}” holds {binder.capacity} pages; it has {len(existing)}.",
            409,
            "count",
        )
    created: List[Location] = []
    for offset in range(1, count + 1):
        number = highest + offset
        page = Location(
            parent_id=binder.id,
            kind="sleeve",
            name=f"Page {number}",
            code=f"P{number:02d}",
            sort_order=number,
            sleeve_layout_id=(layout.id if layout else None),
        )
        db.add(page)
        created.append(page)
    db.flush()
    db.expire(binder, ["children"])
    return created


def discrepancies(db: Session, node: Location) -> List[dict]:
    """What is wrong under a node: rolls that say ``sleeved`` but sit outside a sleeve,
    sleeves holding more than one roll, and pages missing from a numbered binder."""
    problems: List[dict] = []
    if node.kind == "binder":
        pages = sorted((c for c in node.children if c.kind == "sleeve"), key=lambda c: (c.sort_order, c.id))
        numbers = [p.sort_order for p in pages]
        if numbers:
            for expected in range(1, max(numbers) + 1):
                if expected not in numbers:
                    problems.append({"kind": "missing_page", "message": f"Page {expected} is missing."})
        for page in pages:
            held = db.query(FilmRoll).filter(FilmRoll.location_id == page.id).all()
            if len(held) > 1:
                problems.append(
                    {
                        "kind": "sleeve_overfull",
                        "location_id": page.id,
                        "message": f"{label(page)} holds {len(held)} rolls: "
                        + ", ".join(r.archive_serial or r.title for r in held),
                    }
                )
    for roll in db.query(FilmRoll).filter(FilmRoll.location_id == node.id).all():
        if roll.status == "sleeved" and node.kind != "sleeve":
            problems.append(
                {
                    "kind": "status_mismatch",
                    "roll_id": roll.id,
                    "message": f"{roll.archive_serial or roll.title} is marked sleeved but is filed in a {node.kind}.",
                }
            )
    return problems
