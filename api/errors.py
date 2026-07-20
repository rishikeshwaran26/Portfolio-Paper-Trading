"""Error handling for the API — one consistent JSON error envelope.

What a *good* error response looks like
---------------------------------------
Three things every error here gives the client:

  1. The right HTTP STATUS CODE, so generic tools and the browser understand
     the outcome without reading the body (2xx ok, 4xx your fault, 5xx our fault).
  2. A machine-readable `type`, so the React app can branch on it
     (e.g. show a "top up cash" hint specifically on "InsufficientFunds")
     without string-matching the human message.
  3. A human-readable `message` safe to show a user.

Every error — validation, business-rule, or unexpected — comes back in the SAME
shape, so the frontend has exactly one error format to handle:

    { "error": { "type": "InsufficientFunds", "message": "need ₹... but ..." } }

Status code choices
-------------------
  400 Bad Request  — the request itself is malformed / invalid (missing field,
                     wrong type, confidence out of range). The client must fix
                     the request before retrying.
  404 Not Found    — the strategy in the URL doesn't exist.
  409 Conflict     — the request is well-formed but conflicts with current
                     state: duplicate strategy name, not enough cash, not enough
                     shares. Retrying unchanged won't help until state changes.
  500 Internal     — we broke (storage failure, unexpected bug). Never leak
                     internals; log server-side, return a generic message.
"""

from __future__ import annotations

from flask import Flask, jsonify

from engine.errors import (
    InsufficientFunds,
    InsufficientHoldings,
    InvalidTrade,
    StorageError,
)


class ApiError(Exception):
    """Raised inside routes for HTTP-level problems (bad body, not found,
    duplicate). Carries the status code and a type label."""

    def __init__(self, status: int, type_: str, message: str):
        super().__init__(message)
        self.status = status
        self.type = type_
        self.message = message


def _envelope(type_: str, message: str, status: int):
    return jsonify({"error": {"type": type_, "message": message}}), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(e: ApiError):
        return _envelope(e.type, e.message, e.status)

    # Business-rule violations from the engine: well-formed request, but the
    # current state won't allow it -> 409 Conflict.
    @app.errorhandler(InsufficientFunds)
    def _handle_funds(e):
        return _envelope("InsufficientFunds", str(e), 409)

    @app.errorhandler(InsufficientHoldings)
    def _handle_holdings(e):
        return _envelope("InsufficientHoldings", str(e), 409)

    # Bad inputs the engine rejected -> 400 Bad Request.
    @app.errorhandler(InvalidTrade)
    def _handle_invalid(e):
        return _envelope("InvalidTrade", str(e), 400)

    # Storage problems are our fault -> 500, generic message.
    @app.errorhandler(StorageError)
    def _handle_storage(e):
        app.logger.error("storage error: %s", e)
        return _envelope("StorageError", "a server storage error occurred", 500)

    # Flask's own 404 (unknown route) and 405 (wrong method) in our envelope.
    @app.errorhandler(404)
    def _handle_404(e):
        return _envelope("NotFound", "no such resource", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return _envelope("MethodNotAllowed", "method not allowed on this resource", 405)

    # Last-resort net so a bug never returns an HTML stack trace as an API reply.
    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):  # already handled above, but be safe
            return _envelope(e.type, e.message, e.status)
        app.logger.exception("unexpected error")
        return _envelope("InternalError", "an unexpected error occurred", 500)
