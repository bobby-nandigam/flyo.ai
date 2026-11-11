"""Password hashing and JWT issuance/verification.

Passwords use PBKDF2-HMAC-SHA256 from the standard library (no native bcrypt
dependency to break across Python versions). Tokens are signed HS256 JWTs with a
short-lived access token and a longer refresh token, each tagged with its type so
a refresh token can never be used as an access token.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import os
from typing import Any

import jwt

from app.core.config import get_settings

_PBKDF2_ROUNDS = 200_000
_ALGO = "pbkdf2_sha256"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"{_ALGO}${_PBKDF2_ROUNDS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_s, dk_s = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt_s), int(rounds_s))
        return hmac.compare_digest(dk, _unb64(dk_s))
    except (ValueError, TypeError):
        return False


def _issue(sub: str, *, token_type: str, ttl: int, extra: dict[str, Any]) -> str:
    settings = get_settings()
    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "sub": sub,
        "type": token_type,
        "iat": now,
        "exp": now + _dt.timedelta(seconds=ttl),
        **extra,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, tenant_id: str, role: str) -> str:
    settings = get_settings()
    return _issue(
        user_id,
        token_type="access",
        ttl=settings.access_token_ttl_seconds,
        extra={"tenant_id": tenant_id, "role": role},
    )


def create_refresh_token(user_id: str, tenant_id: str) -> str:
    settings = get_settings()
    return _issue(
        user_id,
        token_type="refresh",
        ttl=settings.refresh_token_ttl_seconds,
        extra={"tenant_id": tenant_id},
    )


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Decode and validate a token; raises ``jwt.PyJWTError`` on any problem."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload
