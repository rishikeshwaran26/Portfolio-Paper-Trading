"""Auth endpoints: register, login, me.

Kept in their own blueprint because they're the only routes that must work
WITHOUT a token — everything else is behind @require_auth.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from .auth import make_token, require_auth, user_store
from .errors import ApiError
from .validation import json_body, req_str

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _public(user: dict) -> dict:
    """Never leak the password hash to the client."""
    return {"id": user["id"], "username": user["username"], "created_at": user["created_at"]}


@auth_bp.post("/register")
def register():
    body = json_body()
    username = req_str(body, "username")
    password = req_str(body, "password")
    store = user_store()
    user = store.create(username, password)  # raises 409 if taken, 400 if weak
    return (
        jsonify({"user": _public(user), "token": make_token(user["id"])}),
        201,
    )


@auth_bp.post("/login")
def login():
    body = json_body()
    username = req_str(body, "username")
    password = req_str(body, "password")
    user = user_store().verify(username, password)
    if not user:
        # Deliberately vague: don't reveal whether the username exists.
        raise ApiError(401, "InvalidCredentials", "incorrect username or password")
    return jsonify({"user": _public(user), "token": make_token(user["id"])})


@auth_bp.get("/me")
@require_auth
def me():
    """Lets the frontend validate a stored token on page load."""
    return jsonify({"user": {"id": g.user_id, "username": g.username}})


@auth_bp.get("/status")
def status():
    """Unauthenticated: tells the login screen whether any account exists yet,
    so a fresh install can show 'create your account' instead of 'log in'."""
    return jsonify({"has_users": user_store().count() > 0})
