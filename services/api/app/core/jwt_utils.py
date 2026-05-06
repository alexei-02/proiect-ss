"""JWT encoding and decoding helpers."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def encode_access(user_id: str, username: str, roles: list[str]) -> tuple[str, str]:
    """Return (signed_token, jti)."""
    settings = get_settings()
    jti = secrets.token_hex(16)
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "roles": roles,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_access_ttl_seconds),
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def encode_refresh(user_id: str) -> tuple[str, str]:
    """Return (signed_token, jti)."""
    settings = get_settings()
    jti = secrets.token_hex(16)
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": user_id,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
        "type": "refresh",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """Decode, verify signature, audience, issuer, expiry.

    Raises jwt.PyJWTError subclasses on any failure.
    """
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        leeway=10,
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"Expected token type '{expected_type}', got '{payload.get('type')}'"
        )
    return payload
