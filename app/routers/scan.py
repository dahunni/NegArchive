"""Scanning: resolve a code to a thing, render codes, serve the print queue (M4).

* ``POST /api/scan/resolve``   the one grammar for QR contents, Code128 tokens and
  typed serials; answers with the roll, the location or the command it names.
* ``GET  /api/codes/qr.svg``   and ``code128.svg`` render any text.
* ``GET  /api/rolls/by-serial/{serial}``   what ``/s/{serial}`` uses.
* ``GET  /api/print/queue`` / ``POST /api/print/mark``   what still needs a label.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..errors import ApiError, error_response, from_exc, not_found, parse_int
from ..models import FilmRoll, Location, LocationMove
from ..services import codes, network, serials, settings_store
from ..services import locations as loc_svc

router = APIRouter(prefix="/api", tags=["scan"])


def public_base(db: Session) -> str:
    """Where a QR code should point: the setting, else the LAN URL the backend found."""
    configured = (settings_store.get(db, "public_base_url") or "").strip()
    return configured.rstrip("/") if configured else (network.ui_url() or "")


def _roll_payload(db: Session, roll: FilmRoll) -> dict:
    from .api import film_to_dict, roll_summaries

    count, strip = roll_summaries(db, [roll.id]).get(roll.id, (0, []))
    return film_to_dict(roll, count, strip)


@router.post("/scan/resolve")
def resolve(body: schemas.ScanToken, db: Session = Depends(get_db)):
    parsed = codes.parse_token(body.code or "")
    if parsed["kind"] == "command":
        return {
            "kind": "command",
            "command": parsed["command"],
            "known": parsed["known"],
            "description": codes.COMMANDS.get(parsed["command"]),
            "input": body.code,
        }
    if parsed["kind"] == "location":
        node = db.get(Location, parsed["id"])
        if node is None:
            return error_response("unknown_location", f"No location has the code LOC-{parsed['id']}.", 404)
        return {"kind": "location", "location": loc_svc.to_dict(node), "url": f"/locations/{node.id}", "input": body.code}
    if parsed["kind"] == "roll":
        roll = serials.find_by_serial(db, parsed["serial"])
        if roll is None and parsed.get("loose"):
            # A typed word rather than a serial: try the title.
            roll = db.query(FilmRoll).filter(FilmRoll.title.ilike(parsed["serial"])).first()
        if roll is None:
            return error_response("unknown_serial", f"No roll carries the serial {parsed['serial']}.", 404)
        return {
            "kind": "roll",
            "roll": _roll_payload(db, roll),
            "url": f"/films/{roll.id}",
            "input": body.code,
        }
    return error_response("unknown_code", "That code is not something the archive knows.", 404)


@router.get("/rolls/by-serial/{serial}")
def roll_by_serial(serial: str, db: Session = Depends(get_db)):
    roll = serials.find_by_serial(db, serial)
    if roll is None:
        return not_found("Roll")
    return {"roll": _roll_payload(db, roll), "url": f"/films/{roll.id}"}


@router.get("/scan/commands")
def list_commands():
    return {"commands": [{"code": f"CMD-{verb}", "verb": verb, "description": text} for verb, text in codes.COMMANDS.items()]}


# --- codes ---------------------------------------------------------------------


@router.get("/codes/qr.svg")
def qr(text: str = Query(..., min_length=1, max_length=500), scale: int = 4):
    svg = codes.qr_svg(text, scale=max(1, min(scale, 12)))
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/codes/code128.svg")
def code128(text: str = Query(..., min_length=1, max_length=60), height: float = 12.0, label: bool = True):
    try:
        svg = codes.code128_svg(text, module_height=max(4.0, min(height, 60.0)), show_text=label)
    except Exception as exc:  # noqa: BLE001 - a bad character set is a client error
        return error_response("invalid_barcode", f"Cannot encode that text as Code128: {exc}", 400, "text")
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/codes/for_roll/{film_id}")
def codes_for_roll(film_id: int, db: Session = Depends(get_db)):
    roll = db.get(FilmRoll, film_id)
    if not roll:
        return not_found("Roll")
    if not roll.archive_serial:
        return error_response("no_serial", "This roll has no serial yet.", 409)
    base = public_base(db)
    return {
        "serial": roll.archive_serial,
        "qr_text": codes.roll_url(base, roll.archive_serial),
        "barcode_text": roll.archive_serial,
        "qr_svg_url": f"/api/codes/qr.svg?text={codes.roll_url(base, roll.archive_serial)}",
        "barcode_svg_url": f"/api/codes/code128.svg?text={roll.archive_serial}",
        "public_base": base,
    }


@router.get("/codes/for_location/{location_id}")
def codes_for_location(location_id: int, db: Session = Depends(get_db)):
    node = db.get(Location, location_id)
    if not node:
        return not_found("Location")
    base = public_base(db)
    return {
        "code": f"LOC-{node.id}",
        "qr_text": codes.location_url(base, node.id),
        "barcode_text": f"LOC-{node.id}",
        "qr_svg_url": f"/api/codes/qr.svg?text={codes.location_url(base, node.id)}",
        "barcode_svg_url": f"/api/codes/code128.svg?text=LOC-{node.id}",
        "public_base": base,
    }


# --- print queue ---------------------------------------------------------------


#: A page of the queue. An archive's *whole* backlog is not a screenful, and it is
#: not something to hold in memory either.
QUEUE_PAGE = 50
QUEUE_MAX_PAGE = 500


@router.get("/print/queue")
def print_queue(
    limit: int = Query(QUEUE_PAGE, ge=1, le=QUEUE_MAX_PAGE),
    offset: int = Query(0, ge=0),
    reason: Optional[str] = Query(None, description="never_printed | moved_since_print"),
    db: Session = Depends(get_db),
):
    """Rolls that never had a label, or moved since the last one was printed.

    Paged like every other list since M3 (R#20): an archive that has never printed
    a label has its entire catalogue in here, and sending all of it — with a
    thumbnail strip per roll — is how the page became something you scroll past
    rather than work through.

    The "moved since the last print" test is done in SQL against the latest move
    per roll; it used to read every row of ``location_moves`` into a dict, which is
    every move the archive has ever recorded.
    """
    from .api import film_to_dict, roll_summaries

    latest_move = (
        db.query(LocationMove.roll_id.label("roll_id"), func.max(LocationMove.moved_at).label("moved_at"))
        .group_by(LocationMove.roll_id)
        .subquery()
    )
    never_printed = FilmRoll.label_printed_at.is_(None)
    moved_since = and_(
        FilmRoll.label_printed_at.isnot(None),
        latest_move.c.moved_at.isnot(None),
        latest_move.c.moved_at > FilmRoll.label_printed_at,
    )

    query = db.query(FilmRoll, latest_move.c.moved_at).outerjoin(
        latest_move, latest_move.c.roll_id == FilmRoll.id
    )
    wanted = (reason or "").strip().lower()
    if wanted == "never_printed":
        query = query.filter(never_printed)
    elif wanted == "moved_since_print":
        query = query.filter(moved_since)
    elif wanted:
        return error_response(
            "invalid_reason",
            "Reason must be never_printed or moved_since_print.",
            400,
            "reason",
        )
    else:
        query = query.filter(or_(never_printed, moved_since))

    total = query.order_by(None).count()
    rows = query.order_by(FilmRoll.created_at.desc(), FilmRoll.id.desc()).limit(limit).offset(offset).all()

    summaries = roll_summaries(db, [roll.id for roll, _ in rows])
    items = [
        {
            **film_to_dict(roll, *summaries.get(roll.id, (0, []))),
            "reason": "never_printed" if roll.label_printed_at is None else "moved_since_print",
        }
        for roll, _ in rows
    ]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.post("/print/mark")
def mark_printed(body: schemas.MarkPrinted, db: Session = Depends(get_db)):
    try:
        if not body.roll_ids:
            raise ApiError("invalid_ids", "Select at least one roll.", 400, "roll_ids")
        now = datetime.utcnow()
        updated = 0
        for raw in body.roll_ids:
            roll = db.get(FilmRoll, parse_int(raw, "roll_ids", minimum=1))
            if roll is None:
                continue
            roll.label_printed_at = now
            updated += 1
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "marked": updated}
