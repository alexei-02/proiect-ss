"""
Authentication & RBAC.

Public interface (signatures are fixed — routes depend on them):
  - User dataclass
  - get_current_user(request) -> User
  - require_role(role)        -> FastAPI dependency (single-role back-compat alias)
  - require_any_role(*roles)  -> FastAPI dependency (passes if user has ANY of the roles)

Behaviour:
  - Reads Authorization: Bearer <token> header.
  - Verifies JWT (HS256 in dev, RS256 in prod — algorithm from settings).
  - Checks per-user is_active kill switch (cached 30 s in process memory).
  - Dev bypass: when env != "production" AND dev_auth_bypass=true AND no Authorization
    header, returns a fake admin+doctor user so local dev works without tokens.

Roles: admin | doctor | receptionist | auditor  (see docs/RBAC.md)
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

import jwt
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# Per-user is_active cache: user_id -> (is_active, cached_at_monotonic)
_ACTIVE_CACHE: dict[str, tuple[bool, float]] = {}
_CACHE_TTL = 30.0  # seconds


@dataclass
class User:
    id: str
    username: str
    roles: list[str] = field(default_factory=list)


async def get_current_user(request: Request) -> User:
    from app.core.config import get_settings
    from app.core.jwt_utils import decode_token

    settings = get_settings()

    # Dev/test bypass — never allowed in production.
    if (
        settings.env != "production"
        and settings.dev_auth_bypass
        and "Authorization" not in request.headers
    ):
        user = User(id="dev-user", username="dev", roles=["admin", "doctor"])
        request.state.user = user
        return user

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[7:]
    try:
        payload = decode_token(token, "access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id: str = payload["sub"]

    # is_active kill switch (30 s cache)
    now = monotonic()
    cached = _ACTIVE_CACHE.get(user_id)
    if cached is None or now - cached[1] > _CACHE_TTL:
        is_active = await _fetch_is_active(request, user_id)
        _ACTIVE_CACHE[user_id] = (is_active, now)
    else:
        is_active = cached[0]

    if not is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account deactivated",
        )

    user = User(
        id=user_id,
        username=payload.get("username", ""),
        roles=payload.get("roles", []),
    )
    request.state.user = user
    return user


async def _fetch_is_active(request: Request, user_id: str) -> bool:
    app_state = getattr(getattr(request, "app", None), "state", None)
    if app_state is None:
        return True
    user_store = getattr(app_state, "user_store", None)
    if user_store is None:
        return True
    try:
        row = await user_store.get_by_id(user_id)
        return row is not None and row["is_active"]
    except Exception as exc:
        logger.warning("is_active check failed for %s: %s", user_id, exc)
        return True  # fail open to avoid locking out users on DB hiccup


def require_any_role(*roles: str) -> Callable:
    """Dependency factory — passes if the current user has ANY of the listed roles."""

    async def dependency(request: Request) -> User:
        user = await get_current_user(request)
        if not any(r in user.roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of roles {list(roles)} required",
            )
        return user

    return dependency


def require_role(role: str) -> Callable:
    """Single-role dependency factory — back-compat alias for require_any_role."""
    return require_any_role(role)
