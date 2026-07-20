"""Layer-1 (syntactic) request validation, shared by every blueprint.

These guard the door: is the body JSON, are required fields present and the
right type. Business rules (enough cash, valid confidence) stay in the engine —
see the note at the top of routes.py.
"""

from __future__ import annotations

from flask import request

from .errors import ApiError


def json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "BadRequest", "request body must be a JSON object")
    return body


def req_str(body: dict, field: str) -> str:
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise ApiError(400, "BadRequest", f"'{field}' is required and must be a non-empty string")
    return val.strip()


def req_int(body: dict, field: str) -> int:
    val = body.get(field)
    # bool is a subclass of int in Python, so reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(400, "BadRequest", f"'{field}' is required and must be a whole number")
    return val


def req_num(body: dict, field: str) -> float:
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError(400, "BadRequest", f"'{field}' is required and must be a number")
    return float(val)


def opt_str(body: dict, field: str, default: str = "") -> str:
    val = body.get(field, default)
    return val.strip() if isinstance(val, str) else default


def opt_tags(body: dict) -> list[str]:
    val = body.get("tags", [])
    if val in (None, ""):
        return []
    if not isinstance(val, list) or not all(isinstance(t, str) for t in val):
        raise ApiError(400, "BadRequest", "'tags' must be a list of strings")
    return [t.strip() for t in val if t.strip()]
