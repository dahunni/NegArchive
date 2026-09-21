"""The storage tree, sleeve layouts and moving rolls (roadmap M4)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..errors import ApiError, error_response, from_exc, not_found, parse_int
from ..models import FilmRoll, ImageAsset, ImageType, Location, LocationMove, SleeveLayout
from ..services import locations as svc
from ..services import strips as strips_svc

router = APIRouter(prefix="/api", tags=["locations"])


def _roll_brief(roll: FilmRoll, image_count: int = 0) -> dict:
    return {
        "id": roll.id,
        "title": roll.title,
        "archive_serial": roll.archive_serial,
        "status": roll.status,
        "film_type": roll.film_type_name,
        "camera": roll.camera_name,
        "start_date": roll.start_date.isoformat() if roll.start_date else None,
        "end_date": roll.end_date.isoformat() if roll.end_date else None,
        "location_id": roll.location_id,
        "image_count": image_count,
        "label_printed_at": roll.label_printed_at.isoformat() if roll.label_printed_at else None,
    }


def _image_counts(db: Session, roll_ids: List[int]) -> dict:
    if not roll_ids:
        return {}
    rows = (
        db.query(ImageAsset.film_roll_id, func.count(ImageAsset.id))
        .filter(ImageAsset.film_roll_id.in_(roll_ids), ImageAsset.type == ImageType.scan)
        .group_by(ImageAsset.film_roll_id)
        .all()
    )
    return dict(rows)


# --- sleeve layouts ------------------------------------------------------------


@router.get("/sleeve_layouts")
def list_layouts(db: Session = Depends(get_db)):
    items = db.query(SleeveLayout).order_by(SleeveLayout.is_default.desc(), SleeveLayout.id.asc()).all()
    return [_layout_dict(l) for l in items]


@router.post("/sleeve_layouts")
def create_layout(body: schemas.SleeveLayoutWrite, db: Session = Depends(get_db)):
    try:
        name = (body.name or "").strip()
        if not name:
            raise ApiError("invalid_name", "Name is required.", 400, "name")
        rows = parse_int(body.rows, "rows", minimum=1)
        per_row = parse_int(body.frames_per_row, "frames_per_row", minimum=1)
        if rows is None or per_row is None:
            raise ApiError("invalid_number", "Rows and frames per row are required.", 400, "rows")
        layout = SleeveLayout(name=name, rows=rows, frames_per_row=per_row, film_format=body.film_format, is_default=bool(body.is_default))
        if layout.is_default:
            db.query(SleeveLayout).update({SleeveLayout.is_default: False})
        db.add(layout)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ApiError("duplicate_name", f"A sleeve layout named “{name}” already exists.", 409, "name") from exc
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "layout": _layout_dict(layout)}


def _layout_dict(layout: SleeveLayout) -> dict:
    return {
        "id": layout.id,
        "name": layout.name,
        "rows": layout.rows,
        "frames_per_row": layout.frames_per_row,
        "film_format": layout.film_format,
        "is_default": bool(layout.is_default),
        "capacity": layout.rows * layout.frames_per_row,
    }


# --- the tree ------------------------------------------------------------------


@router.get("/locations")
def list_locations(db: Session = Depends(get_db)):
    """Every node, flat, with its path and counts. The UI builds the tree from ``parent_id``."""
    nodes = db.query(Location).order_by(Location.parent_id.asc().nulls_first(), Location.sort_order.asc(), Location.id.asc()).all()
    direct = svc.roll_counts(db)
    totals = svc.subtree_counts(nodes, direct)
    return {"locations": [svc.to_dict(n, direct=direct, totals=totals) for n in nodes]}


@router.get("/locations/{location_id}")
def get_location(location_id: int, db: Session = Depends(get_db)):
    node = db.get(Location, location_id)
    if not node:
        return not_found("Location")
    direct = svc.roll_counts(db)
    all_nodes = db.query(Location).all()
    totals = svc.subtree_counts(all_nodes, direct)
    children = sorted(node.children, key=lambda c: (c.sort_order, c.id))
    child_ids = [c.id for c in children]
    rolls_by_location = {}
    if child_ids:
        for roll in db.query(FilmRoll).filter(FilmRoll.location_id.in_(child_ids)).all():
            rolls_by_location.setdefault(roll.location_id, []).append(roll)
    held = db.query(FilmRoll).filter(FilmRoll.location_id == node.id).order_by(FilmRoll.archive_serial.asc()).all()
    counts = _image_counts(db, [r.id for r in held] + [r.id for rs in rolls_by_location.values() for r in rs])
    layout = svc.layout_for(db, node)
    return {
        "location": svc.to_dict(node, direct=direct, totals=totals),
        "ancestors": [svc.to_dict(a) for a in svc.ancestors(node)[:-1]],
        "children": [
            {
                **svc.to_dict(c, direct=direct, totals=totals),
                "rolls": [_roll_brief(r, counts.get(r.id, 0)) for r in rolls_by_location.get(c.id, [])],
            }
            for c in children
        ],
        "rolls": [_roll_brief(r, counts.get(r.id, 0)) for r in held],
        "effective_layout": (
            {"id": layout.id, "name": layout.name, "rows": layout.rows, "frames_per_row": layout.frames_per_row}
            if layout
            else None
        ),
        "next_free_sleeve_id": _next_free_id(db, node) if node.kind == "binder" else None,
        "discrepancies": svc.discrepancies(db, node),
    }


def _next_free_id(db: Session, binder: Location) -> Optional[int]:
    page = svc.next_free_sleeve(db, binder)
    return page.id if page is not None else None


def _apply(body: schemas.LocationWrite, node: Location, db: Session, creating: bool) -> None:
    given = (lambda f: creating or body.given(f)) if hasattr(body, "given") else (lambda f: True)
    if given("kind") and (creating or body.kind is not None):
        node.kind = svc.parse_kind(body.kind)
    if given("name"):
        name = (body.name or "").strip()
        if not name:
            raise ApiError("invalid_name", "Name is required.", 400, "name")
        node.name = name
    if given("code"):
        node.code = (body.code or "").strip() or None
    if given("notes"):
        node.notes = (body.notes or "").strip() or None
    if given("sort_order") and body.sort_order is not None:
        node.sort_order = parse_int(body.sort_order, "sort_order", minimum=0) or 0
    if given("capacity"):
        node.capacity = parse_int(body.capacity, "capacity", minimum=1)
    if given("sleeve_layout_id"):
        if body.sleeve_layout_id in (None, ""):
            node.sleeve_layout_id = None
        else:
            layout_id = parse_int(body.sleeve_layout_id, "sleeve_layout_id", minimum=1)
            if not db.get(SleeveLayout, layout_id):
                raise ApiError("unknown_layout", "That sleeve layout does not exist.", 404, "sleeve_layout_id")
            node.sleeve_layout_id = layout_id
    if given("parent_id"):
        if body.parent_id in (None, ""):
            node.parent_id = None
        else:
            parent_id = parse_int(body.parent_id, "parent_id", minimum=1)
            parent = db.get(Location, parent_id)
            if parent is None:
                raise ApiError("unknown_parent", "That parent location does not exist.", 404, "parent_id")
            if not creating and (parent.id == node.id or node.id in svc.path_ids(parent)):
                raise ApiError("invalid_parent", "A location cannot be moved inside itself.", 400, "parent_id")
            node.parent_id = parent.id


@router.post("/locations")
def create_location(body: schemas.LocationCreate, db: Session = Depends(get_db)):
    try:
        node = Location(kind="other", name="", sort_order=0)
        _apply(body, node, db, creating=True)
        if node.sort_order == 0 and node.parent_id is not None:
            siblings = db.query(func.max(Location.sort_order)).filter(Location.parent_id == node.parent_id).scalar() or 0
            node.sort_order = siblings + 1
        db.add(node)
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(node)
    return {"ok": True, "location": svc.to_dict(node)}


@router.put("/locations/{location_id}")
def update_location(location_id: int, body: schemas.LocationUpdate, db: Session = Depends(get_db)):
    node = db.get(Location, location_id)
    if not node:
        return not_found("Location")
    try:
        _apply(body, node, db, creating=False)
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(node)
    return {"ok": True, "location": svc.to_dict(node)}


@router.delete("/locations/{location_id}")
def delete_location(location_id: int, force: bool = False, db: Session = Depends(get_db)):
    node = db.get(Location, location_id)
    if not node:
        return not_found("Location")
    ids = [n.id for n in db.query(Location).all() if node.id in svc.path_ids(n)]
    held = db.query(func.count(FilmRoll.id)).filter(FilmRoll.location_id.in_(ids)).scalar() or 0
    if (held or len(ids) > 1) and not force:
        return error_response(
            "location_in_use",
            f"“{svc.label(node)}” holds {held} roll{'s' if held != 1 else ''} and {len(ids) - 1} sub-location"
            f"{'s' if len(ids) - 1 != 1 else ''}. Delete it anyway with ?force=true; the rolls become unfiled.",
            409,
        )
    db.query(FilmRoll).filter(FilmRoll.location_id.in_(ids)).update({FilmRoll.location_id: None}, synchronize_session=False)
    db.delete(node)
    db.commit()
    return {"ok": True, "rolls_unfiled": held}


@router.post("/locations/{location_id}/pages")
def add_pages(location_id: int, body: schemas.AddPages, db: Session = Depends(get_db)):
    node = db.get(Location, location_id)
    if not node:
        return not_found("Location")
    try:
        layout = None
        if body.sleeve_layout_id:
            layout = db.get(SleeveLayout, body.sleeve_layout_id)
            if layout is None:
                raise ApiError("unknown_layout", "That sleeve layout does not exist.", 404, "sleeve_layout_id")
        created = svc.add_pages(db, node, parse_int(body.count, "count", minimum=1) or 0, layout)
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "pages": [svc.to_dict(p) for p in created]}


@router.get("/locations/{location_id}/next_free")
def next_free(location_id: int, db: Session = Depends(get_db)):
    node = db.get(Location, location_id)
    if not node:
        return not_found("Location")
    page = svc.next_free_sleeve(db, node)
    return {"location": svc.to_dict(page) if page else None}


# --- moving rolls --------------------------------------------------------------


def _target(db: Session, location_id) -> Optional[Location]:
    if location_id in (None, "", "none"):
        return None
    parsed = parse_int(location_id, "location_id", minimum=1)
    node = db.get(Location, parsed)
    if node is None:
        raise ApiError("unknown_location", "That location does not exist.", 404, "location_id")
    return node


@router.post("/films/{film_id}/move")
def move_roll(film_id: int, body: schemas.MoveRoll, db: Session = Depends(get_db)):
    """File a roll somewhere. A binder target resolves to its next free page."""
    roll = db.get(FilmRoll, film_id)
    if not roll:
        return not_found("Roll")
    try:
        target = _target(db, body.location_id)
        destination = svc.move_roll(db, roll, target, note=(body.note or None))
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    db.refresh(roll)
    return {
        "ok": True,
        "roll": _roll_brief(roll),
        "location": svc.to_dict(destination) if destination else None,
        "path": svc.path_string(destination),
    }


@router.post("/films/bulk_move")
def bulk_move(body: schemas.BulkMove, db: Session = Depends(get_db)):
    try:
        if not body.ids:
            raise ApiError("invalid_ids", "Select at least one roll.", 400, "ids")
        target = _target(db, body.location_id)
        moved = []
        for raw in body.ids:
            roll_id = parse_int(raw, "ids", minimum=1)
            roll = db.get(FilmRoll, roll_id)
            if roll is None:
                raise ApiError("unknown_roll", f"Roll {roll_id} does not exist.", 404, "ids")
            destination = svc.move_roll(db, roll, target, note=body.note or None)
            db.flush()
            moved.append(
                {
                    "roll": _roll_brief(roll),
                    "location": svc.to_dict(destination) if destination else None,
                    "path": svc.path_string(destination),
                }
            )
        db.commit()
    except ApiError as exc:
        db.rollback()
        return from_exc(exc)
    return {"ok": True, "moved": moved}


@router.get("/films/{film_id}/moves")
def roll_moves(film_id: int, db: Session = Depends(get_db)):
    roll = db.get(FilmRoll, film_id)
    if not roll:
        return not_found("Roll")
    moves = db.query(LocationMove).filter(LocationMove.roll_id == roll.id).order_by(LocationMove.moved_at.desc(), LocationMove.id.desc()).all()
    return {
        "moves": [
            {
                "id": m.id,
                "moved_at": m.moved_at.isoformat(),
                "from": svc.path_string(db.get(Location, m.from_location_id)) if m.from_location_id else None,
                "to": svc.path_string(db.get(Location, m.to_location_id)) if m.to_location_id else None,
                "note": m.note,
            }
            for m in moves
        ]
    }


@router.get("/films/{film_id}/layout")
def roll_layout(film_id: int, db: Session = Depends(get_db)):
    """The sleeve grid of a roll: rows of frames, for the cover sheet and the viewer."""
    from .api import preview_version

    roll = db.get(FilmRoll, film_id)
    if not roll:
        return not_found("Roll")
    layout = svc.layout_for(db, roll.location_ref)
    strips = strips_svc.effective_strips(roll.strips, layout.rows if layout else None, layout.frames_per_row if layout else None)
    frames = [
        {
            "id": i.id,
            "frame_number": i.frame_number,
            "notes": i.notes,
            "capture_date": i.capture_date.isoformat() if i.capture_date else None,
            # Which of a frame's two files the sleeve grid shows; see
            # `strips.better_for_paper`.
            "positive": i.positive,
            # The cover sheet's thumbnails are served immutable; see image_to_dict.
            "preview_version": preview_version(i),
        }
        for i in db.query(ImageAsset)
        .filter(ImageAsset.film_roll_id == roll.id, ImageAsset.type == ImageType.scan)
        .order_by(ImageAsset.frame_number.asc().nulls_last(), ImageAsset.id.asc())
        .all()
    ]
    rows = strips_svc.grid(frames, strips)
    # By *number*, not by id: a frame whose sibling took the cell — the raw
    # negative behind the positive on the grid — is on the sleeve, and listing it
    # under "not on the sleeve grid" would say the opposite for every frame of a
    # roll that went through NegPy.
    placed = {cell["frame_number"] for row in rows for cell in row if cell}
    return {
        "strips": strips,
        "layout": {"id": layout.id, "name": layout.name} if layout else None,
        "capacity": strips_svc.capacity(strips),
        "rows": rows,
        "unplaced": [f for f in frames if f["frame_number"] not in placed],
    }
