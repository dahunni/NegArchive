"""Export, import and the CSV roll index.

Roadmap M3. See :mod:`app.services.backup` for the format and the merge rules.

    GET  /api/export            streamed ZIP: export.json + the managed files
    GET  /api/export.json       just the JSON, for a quick look or a diff
    GET  /api/export/rolls.csv  one line per roll, for a spreadsheet
    POST /api/import            multipart "file"; ?dry_run=true reports only
    GET  /api/backups           what scripts/backup.sh has produced so far
"""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from .. import paths
from ..db import get_db
from ..errors import error_response
from ..services import backup as backup_service

router = APIRouter(prefix="/api", tags=["backup"])
log = logging.getLogger("negarchive.backup")


@router.get("/export")
def export_archive(db: Session = Depends(get_db)):
    filename = backup_service.export_filename()
    return StreamingResponse(
        backup_service.iter_export_zip(db),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Nothing about an export is cacheable.
            "Cache-Control": "no-store",
        },
    )


@router.get("/export.json")
def export_json(db: Session = Depends(get_db)):
    """The tables only. Handy for `curl … | jq` and for diffing two archives."""
    return JSONResponse(backup_service.table_payload(db))


@router.get("/export/rolls.csv")
def export_rolls_csv(db: Session = Depends(get_db)):
    body = backup_service.rolls_csv(db)
    filename = f"negarchive-rolls-{datetime.utcnow():%Y%m%d}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_archive(
    file: UploadFile = File(...),
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """Merge an export ZIP into this archive. Never overwrites; see the service."""
    handle, temp_path = tempfile.mkstemp(suffix=".zip")
    try:
        with os.fdopen(handle, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        try:
            report = backup_service.import_archive(db, temp_path, dry_run=dry_run)
        except ValueError as exc:
            db.rollback()
            return error_response("invalid_export", str(exc), 400)
        except zipfile.BadZipFile:
            db.rollback()
            return error_response("invalid_export", "That file could not be read as a ZIP.", 400)
        except Exception as exc:  # noqa: BLE001 - but never silently: the cause is logged
            db.rollback()
            log.exception("import failed")
            return error_response("import_failed", f"The import failed: {exc}", 500)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
    return {"ok": True, "report": report}


@router.get("/backups")
def list_backups():
    """What ``scripts/backup.sh`` has written into ``DATA_DIR/backups``."""
    directory = paths.backups_dir()
    entries = []
    try:
        for item in sorted(directory.glob("*.tar.gz"), key=lambda p: p.name, reverse=True):
            stat = item.stat()
            entries.append(
                {
                    "name": item.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                }
            )
    except OSError:
        pass
    return {"directory": str(directory), "backups": entries}
