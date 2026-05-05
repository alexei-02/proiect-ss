"""Authentication endpoints.

POST /api/v1/auth/login    — exchange credentials for token pair
POST /api/v1/auth/refresh  — rotate refresh token
POST /api/v1/auth/logout   — revoke token(s)
GET  /api/v1/auth/me       — return current user info
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.core.jwt_utils import decode_token, encode_access, encode_refresh
from app.core.limiter import limiter
from app.core.passwords import verify_password
from app.core.security import User, get_current_user
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse, UserMe
from app.services.refresh_tokens import hash_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _ua(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest) -> TokenResponse:
    settings = get_settings()
    user_store = request.app.state.user_store
    rt_store = request.app.state.rt_store

    user_row = await user_store.get_by_username(body.username)

    # Constant-time: always run argon2 verify (dummy hash on unknown user).
    is_valid = verify_password(body.password, user_row["password_hash"] if user_row else None)

    if not is_valid or user_row is None or not user_row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    access_token, _ = encode_access(user_row["id"], user_row["username"], user_row["roles"])
    refresh_raw, refresh_jti = encode_refresh(user_row["id"])
    expires_at = datetime.now(tz=timezone.utc) + timedelta(
        seconds=settings.jwt_refresh_ttl_seconds
    )
    await rt_store.issue(
        user_id=user_row["id"],
        jti=refresh_jti,
        expires_at=expires_at,
        user_agent=_ua(request),
        ip_address=_ip(request),
    )
    await user_store.record_login(user_row["id"])

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_raw,
        expires_in=settings.jwt_access_ttl_seconds,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(request: Request, body: RefreshRequest) -> TokenResponse:
    settings = get_settings()
    rt_store = request.app.state.rt_store
    user_store = request.app.state.user_store
    audit_sink = getattr(request.app.state, "audit_sink", None)

    try:
        decode_token(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    row = await rt_store.lookup(body.refresh_token)
    now_utc = datetime.now(tz=timezone.utc)

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Replay detection — token was already revoked → revoke the whole family.
    if row.revokedAt is not None:
        await rt_store.revoke_all_for_user(row.userId)
        if audit_sink is not None:
            from app.core.audit import AuditEvent

            await audit_sink.write(
                AuditEvent(
                    action="auth.refresh.replay",
                    outcome="denied",
                    user_id=row.userId,
                    ip_address=_ip(request),
                )
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    expires_at = row.expiresAt
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    # Rotate — revoke old, issue new pair.
    await rt_store.revoke_by_hash(hash_token(body.refresh_token))

    user_row = await user_store.get_by_id(row.userId)
    if user_row is None or not user_row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account deactivated",
        )

    access_token, _ = encode_access(user_row["id"], user_row["username"], user_row["roles"])
    new_refresh_raw, new_jti = encode_refresh(user_row["id"])
    new_expires_at = now_utc + timedelta(seconds=settings.jwt_refresh_ttl_seconds)
    await rt_store.issue(
        user_id=user_row["id"],
        jti=new_jti,
        expires_at=new_expires_at,
        user_agent=_ua(request),
        ip_address=_ip(request),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_raw,
        expires_in=settings.jwt_access_ttl_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    body: LogoutRequest,
    user: User = Depends(get_current_user),
) -> None:
    rt_store = request.app.state.rt_store
    if body.refresh_token is not None:
        await rt_store.revoke_raw(body.refresh_token)
    else:
        await rt_store.revoke_all_for_user(user.id)


@router.get("/me", response_model=UserMe)
async def me(user: User = Depends(get_current_user)) -> UserMe:
    return UserMe(id=user.id, username=user.username, roles=user.roles)
