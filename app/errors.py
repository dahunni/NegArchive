"""Structured error bodies for the validation failures the UI can actually hit.

Roadmap M2 makes *every* endpoint answer this way (with Pydantic models behind it).
M1 only needs the cases the new dialogs run into, so that a form can show the real
reason instead of "Failed to save":

    {"error": {"code": "duplicate_name", "message": "A camera named … already exists."}}

The status code is a real 4xx, so ``res.ok`` in ``lib/api.ts`` is meaningful.
"""

from datetime import date
from typing import Optional

from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raised inside a handler; the handler turns it into :func:`error_response`."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def error_response(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def from_exc(exc: ApiError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.status)


def not_found(what: str) -> JSONResponse:
    """404 with the legacy ``error`` key kept readable for older clients."""
    return error_response("not_found", f"{what} not found.", 404)


def require_text(value, field: str, label: Optional[str] = None) -> str:
    label = label or field.replace("_", " ")
    if value is None or not str(value).strip():
        raise ApiError("invalid_" + field, f"{label.capitalize()} is required.")
    return str(value).strip()


def parse_date(value, field: str) -> Optional[date]:
    """ISO date or None; anything else is a 400 instead of a bare 500 (R#16)."""
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ApiError(
            "invalid_date",
            f"{field.replace('_', ' ').capitalize()} must be a date like 2024-07-01.",
        )


def parse_int(value, field: str, minimum: Optional[int] = None) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        raise ApiError(
            "invalid_number",
            f"{field.replace('_', ' ').capitalize()} must be a whole number.",
        )
    if minimum is not None and parsed < minimum:
        raise ApiError(
            "invalid_number",
            f"{field.replace('_', ' ').capitalize()} must be {minimum} or greater.",
        )
    return parsed


async def read_json(request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        raise ApiError("invalid_json", "The request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("invalid_json", "The request body must be a JSON object.")
    return payload
