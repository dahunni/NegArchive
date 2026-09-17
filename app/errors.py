"""Structured error bodies.

Every endpoint answers a failure the same way (R#16, R#17):

    {"error": {"code": "duplicate_name",
               "message": "A camera named “Nikon F5” already exists.",
               "field": "name"}}

``field`` is new in M2 and is what the forms in ``frontend/lib/api.ts`` attach the
message to; it is ``null`` when the failure does not belong to one input. The status
code is a real 4xx: 400/422 for bad input, 404 for a missing record, 409 for a
conflict, 415 for a file type that is not allowed.
"""

from datetime import date
from typing import Any, Iterable, Optional, Sequence

from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raised anywhere below a handler; turned into :func:`error_response`."""

    def __init__(self, code: str, message: str, status: int = 400, field: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.field = field


def error_response(
    code: str, message: str, status: int = 400, field: Optional[str] = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "field": field}},
    )


def from_exc(exc: ApiError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.status, exc.field)


def not_found(what: str, field: Optional[str] = None) -> JSONResponse:
    """404 for a record that does not exist."""
    return error_response("not_found", f"{what} not found.", 404, field)


def _label(field: str) -> str:
    return field.replace("_", " ").capitalize()


def _field_name(location: Sequence[Any]) -> Optional[str]:
    """The input a Pydantic error belongs to, e.g. ``("body", "title") -> "title"``."""
    parts = [part for part in location if isinstance(part, str) and part not in {"body", "query", "path"}]
    return parts[-1] if parts else None


def validation_error_response(errors: Iterable[dict]) -> JSONResponse:
    """FastAPI's 422 in our shape, reporting the first offending field."""
    first = next(iter(errors), None)
    if first is None:  # pragma: no cover - FastAPI always sends at least one
        return error_response("invalid_request", "The request could not be validated.", 422)
    field = _field_name(first.get("loc", ()))
    message = str(first.get("msg", "Invalid value")).removeprefix("Value error, ")
    if field:
        message = f"{_label(field)}: {message}"
    return error_response("invalid_request", message, 422, field)


def require_text(value, field: str, label: Optional[str] = None) -> str:
    label = label or field.replace("_", " ")
    if value is None or not str(value).strip():
        raise ApiError("invalid_" + field, f"{label.capitalize()} is required.", 400, field)
    return str(value).strip()


def parse_date(value, field: str) -> Optional[date]:
    """ISO date or None; anything else is a 400 instead of a bare 500 (R#16)."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise ApiError(
            "invalid_date",
            f"{_label(field)} must be a date like 2024-07-01.",
            400,
            field,
        )


def parse_int(value, field: str, minimum: Optional[int] = None) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        raise ApiError("invalid_number", f"{_label(field)} must be a whole number.", 400, field)
    if minimum is not None and parsed < minimum:
        raise ApiError(
            "invalid_number", f"{_label(field)} must be {minimum} or greater.", 400, field
        )
    return parsed


def parse_choice(value, field: str, allowed: Sequence[str]) -> Optional[str]:
    """One of ``allowed``, or a 400 that lists them."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text not in allowed:
        raise ApiError(
            "invalid_choice",
            f"{_label(field)} must be one of: {', '.join(allowed)}.",
            400,
            field,
        )
    return text


async def read_json(request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        raise ApiError("invalid_json", "The request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("invalid_json", "The request body must be a JSON object.")
    return payload
