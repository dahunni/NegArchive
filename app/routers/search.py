"""``GET /api/search`` — everything in the archive that matches, grouped (M7).

One request, one answer with a group per kind of thing:

    GET /api/search?q=harbour&limit=5
    {
      "query": "harbour",
      "parsed": {"terms": ["harbour"], "qualifiers": {}},
      "total": 7,
      "groups": [
        {"kind": "roll",       "label": "Rolls",      "total": 2, "items": [...]},
        {"kind": "frame",      "label": "Frames",     "total": 5, "items": [...]},
        {"kind": "camera",     "label": "Cameras",    "total": 0, "items": []},
        ...
      ]
    }

Every item carries ``kind``, ``id``, ``title``, ``url`` and enough to draw one
line under the title; the palette in the frontend renders them and ``Enter``
follows ``url``. ``total`` per group is the count in the database, so "3 of 12"
and a "see all" link are possible without a second request. ``kinds`` narrows
the groups (``kinds=roll,frame``). The grammar, the matching and the ranking
live in :mod:`app.services.search`, shared with the roll list and the frames
page, so the palette and the filter bars agree on what a word means.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import error_response
from ..models import Camera, FilmRoll, FilmStock, ImageAsset, ImageType, Lens
from ..services import lifecycle
from ..services import locations as loc_svc
from ..services import search as search_svc

router = APIRouter(prefix="/api", tags=["search"])

KINDS = ("roll", "frame", "camera", "lens", "film_stock", "location")
LABELS = {
    "roll": "Rolls",
    "frame": "Frames",
    "camera": "Cameras",
    "lens": "Lenses",
    "film_stock": "Film stocks",
    "location": "Locations",
}
#: Per group, unless the caller asks for more. Capped so the palette stays a palette.
DEFAULT_LIMIT = 5
MAX_LIMIT = 50

LOCATION_KIND_LABELS = {
    "building": "Building",
    "room": "Room",
    "shelf": "Shelf",
    "row": "Row",
    "box": "Box",
    "binder": "Binder",
    "envelope": "Envelope",
    "sleeve": "Sleeve",
    "other": "Location",
}


def _rolls(db: Session, query: search_svc.Query, limit: int) -> dict:
    from .api import NO_SCANS, roll_summaries

    base = db.query(FilmRoll).filter(*search_svc.roll_filters(db, None, query))
    total = base.order_by(None).count()
    rolls = (
        base.order_by(search_svc.roll_score(db, query).desc(), FilmRoll.created_at.desc(), FilmRoll.id.desc())
        .limit(limit)
        .all()
    )
    summaries = roll_summaries(db, [r.id for r in rolls])
    items = []
    for roll in rolls:
        count, covers, versions = summaries.get(roll.id, NO_SCANS)
        items.append(
            {
                "kind": "roll",
                "id": roll.id,
                "title": roll.title,
                "url": f"/films/{roll.id}",
                "serial": roll.archive_serial,
                "status": roll.status or "back",
                "status_label": lifecycle.STATUS_LABELS.get(roll.status or "back"),
                "film_type": roll.film_type_name,
                "camera": roll.camera_name,
                "start_date": roll.start_date.isoformat() if roll.start_date else None,
                "end_date": roll.end_date.isoformat() if roll.end_date else None,
                "location_path": loc_svc.path_string(roll.location_ref),
                "image_count": count,
                "cover_image_id": covers[0] if covers else None,
                "cover_version": versions[0] if versions else None,
            }
        )
    return {"kind": "roll", "label": LABELS["roll"], "total": total, "items": items}


def _frames(db: Session, query: search_svc.Query, limit: int) -> dict:
    from .api import preview_version

    base = (
        db.query(ImageAsset)
        .filter(ImageAsset.type == ImageType.scan)
        .filter(*search_svc.frame_filters(db, None, query))
    )
    total = base.order_by(None).count()
    frames = (
        base.order_by(
            search_svc.frame_score(db, query).desc(),
            ImageAsset.film_roll_id.asc().nulls_last(),
            ImageAsset.frame_number.asc().nulls_last(),
            ImageAsset.id.asc(),
        )
        .limit(limit)
        .all()
    )
    roll_ids = {f.film_roll_id for f in frames if f.film_roll_id}
    rolls: Dict[int, FilmRoll] = (
        {r.id: r for r in db.query(FilmRoll).filter(FilmRoll.id.in_(roll_ids)).all()} if roll_ids else {}
    )
    items = []
    for frame in frames:
        roll = rolls.get(frame.film_roll_id) if frame.film_roll_id else None
        number = f"Frame {frame.frame_number}" if frame.frame_number is not None else "Unnumbered frame"
        items.append(
            {
                "kind": "frame",
                "id": frame.id,
                "title": f"{number} · {roll.title}" if roll else number,
                "url": f"/images/{frame.id}",
                "frame_number": frame.frame_number,
                "roll_id": frame.film_roll_id,
                "roll_title": roll.title if roll else None,
                "roll_serial": roll.archive_serial if roll else None,
                "notes": frame.notes,
                "original_filename": frame.original_filename,
                "capture_date": frame.capture_date.isoformat() if frame.capture_date else None,
                "preview_version": preview_version(frame),
            }
        )
    return {"kind": "frame", "label": LABELS["frame"], "total": total, "items": items}


def _gear(db: Session, query: search_svc.Query, limit: int, kind: str) -> dict:
    from .api import catalog_url

    if kind == "camera":
        model, extras, tab = Camera, [Camera.mount, Camera.notes], "cameras"
    elif kind == "lens":
        model, extras, tab = Lens, [Lens.mount, Lens.notes], "lenses"
    else:
        model, extras, tab = FilmStock, [FilmStock.manufacturer, FilmStock.format], "filmstocks"

    filters = search_svc.name_filters(db, model.name, extras, query)
    if not filters:
        return {"kind": kind, "label": LABELS[kind], "total": 0, "items": []}
    base = db.query(model).filter(*filters)
    total = base.order_by(None).count()
    rows = base.order_by(search_svc.name_score(db, model.name, query).desc(), model.name.asc()).limit(limit).all()
    items = []
    for row in rows:
        if kind == "camera":
            subtitle = row.mount
        elif kind == "lens":
            subtitle = row.mount
        else:
            bits = [row.manufacturer, f"ISO {row.iso}" if row.iso else None, row.format]
            subtitle = " · ".join(b for b in bits if b) or None
        items.append(
            {
                "kind": kind,
                "id": row.id,
                "title": row.name,
                "url": f"/gear?tab={tab}&highlight={row.id}",
                "subtitle": subtitle,
                "image_url": catalog_url(row.image_path),
            }
        )
    return {"kind": kind, "label": LABELS[kind], "total": total, "items": items}


def _locations(db: Session, query: search_svc.Query, limit: int) -> dict:
    nodes = search_svc.location_matches(db, query)
    counts = loc_svc.roll_counts(db) if nodes else {}
    items = [
        {
            "kind": "location",
            "id": node.id,
            "title": loc_svc.label(node),
            "url": f"/locations/{node.id}",
            "location_kind": node.kind,
            "kind_label": LOCATION_KIND_LABELS.get(node.kind, "Location"),
            "path": loc_svc.path_string(node),
            "code": node.code,
            "roll_count": counts.get(node.id, 0),
        }
        for node in nodes[:limit]
    ]
    return {"kind": "location", "label": LABELS["location"], "total": len(nodes), "items": items}


@router.get("/search")
def search(
    q: Optional[str] = Query(None, description="Words, quoted phrases and key:value qualifiers."),
    kinds: Optional[str] = Query(None, description="Comma-separated subset of roll,frame,camera,lens,film_stock,location."),
    limit: Optional[int] = Query(None, ge=1, le=MAX_LIMIT, description="Per group."),
    db: Session = Depends(get_db),
):
    query = search_svc.parse(q)
    wanted: List[str] = list(KINDS)
    if kinds:
        wanted = [k.strip() for k in kinds.split(",") if k.strip()]
        unknown = [k for k in wanted if k not in KINDS]
        if unknown:
            return error_response("invalid_kind", f"Unknown kind(s): {', '.join(unknown)}. Use {', '.join(KINDS)}.", 400, "kinds")
    per_group = limit or DEFAULT_LIMIT

    parsed = {"terms": query.terms, "phrases": query.phrases, "qualifiers": query.qualifiers}
    if query.empty:
        return {"query": query.raw, "parsed": parsed, "total": 0, "groups": [], "fuzzy": search_svc.trigram_available(db)}

    groups = []
    for kind in wanted:
        if kind == "roll":
            groups.append(_rolls(db, query, per_group))
        elif kind == "frame":
            groups.append(_frames(db, query, per_group))
        elif kind in ("camera", "lens", "film_stock"):
            groups.append(_gear(db, query, per_group, kind))
        elif kind == "location":
            groups.append(_locations(db, query, per_group))

    return {
        "query": query.raw,
        "parsed": parsed,
        "total": sum(group["total"] for group in groups),
        "groups": groups,
        # Whether a typo can still find something: the UI says so in its hint line.
        "fuzzy": search_svc.trigram_available(db),
    }
