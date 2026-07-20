"""Authentication: user accounts, password hashing, bearer tokens.

Single-user today, but structured so multi-user is a data change rather than a
rewrite:

  - accounts live in their own table keyed by user_id (not a single "the user"
    record), and every other table carries a user_id foreign key,
  - every request resolves to a user_id, and all data access derives from it
    (see paths.UserData),
  - the token carries the user_id, so nothing downstream has to guess.

Security notes for a learning project:
  - Passwords are stored ONLY as salted hashes (werkzeug's pbkdf2). We never
    keep the plaintext.
  - Tokens are signed with itsdangerous using the app SECRET_KEY, and carry an
    expiry. A signed token means we don't need server-side session storage —
    the signature proves we issued it and that it wasn't tampered with.
  - Both werkzeug and itsdangerous ship WITH Flask, so no new dependencies.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .errors import ApiError
from .paths import UserData, db_file, user_repository

TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


# --- user store --------------------------------------------------------------
class UserStore:
    """Account operations. Storage lives in engine.repository.UserRepository;
    this class owns the POLICY (validation + password hashing) so crypto choices
    never leak into SQL."""

    def __init__(self, repo):
        self.repo = repo

    def by_username(self, username: str) -> dict | None:
        return self.repo.by_username(username)

    def by_id(self, user_id: str) -> dict | None:
        return self.repo.by_id(user_id)

    def create(self, username: str, password: str) -> dict:
        username = username.strip()
        if len(username) < 3:
            raise ApiError(400, "BadRequest", "username must be at least 3 characters")
        if len(password) < 8:
            raise ApiError(400, "BadRequest", "password must be at least 8 characters")
        if self.by_username(username):
            raise ApiError(409, "UserExists", f"username '{username}' is taken")
        user = {
            "id": uuid.uuid4().hex[:12],
            "username": username,
            "password_hash": generate_password_hash(password),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.repo.insert(user)

    def verify(self, username: str, password: str) -> dict | None:
        user = self.by_username(username)
        # Return None for both "no such user" and "wrong password" so we never
        # leak which one it was.
        if not user or not check_password_hash(user["password_hash"], password):
            return None
        return user

    def count(self) -> int:
        return self.repo.count()


def user_store() -> UserStore:
    return UserStore(user_repository(current_app.config["DATA_ROOT"]))


# --- tokens ------------------------------------------------------------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="auth-token")


def make_token(user_id: str) -> str:
    return _serializer().dumps({"uid": user_id})


def read_token(token: str) -> str:
    """Return the user_id inside a valid token, else raise 401."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired:
        raise ApiError(401, "TokenExpired", "session expired — please log in again")
    except BadSignature:
        raise ApiError(401, "InvalidToken", "invalid session token")
    return data["uid"]


def load_or_create_secret(root: str) -> str:
    """Persist a random SECRET_KEY so tokens survive a server restart.

    In production this would come from an env var; for a local tool we generate
    once and keep it in a file (which should never be committed).
    """
    env = os.environ.get("PAPERTRADING_SECRET")
    if env:
        return env
    path = os.path.join(root, "secret.key")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    os.makedirs(root, exist_ok=True)
    key = secrets.token_urlsafe(48)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key


# --- the decorator every protected route uses -------------------------------
def require_auth(fn):
    """Verify the bearer token and stash the user on flask.g.

    Routes then use g.user_id / g.data — they never see a hardcoded user, and
    never open a connection or a file themselves.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise ApiError(401, "Unauthorized", "missing bearer token")
        user_id = read_token(header[len("Bearer "):].strip())

        store = user_store()
        user = store.by_id(user_id)
        if not user:
            # Token was validly signed, but the account is gone.
            raise ApiError(401, "Unauthorized", "account no longer exists")

        g.user_id = user_id
        g.username = user["username"]
        g.data = UserData(db_file(current_app.config["DATA_ROOT"]), user_id)
        return fn(*args, **kwargs)

    return wrapper
