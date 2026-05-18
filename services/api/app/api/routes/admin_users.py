"""Admin user management endpoints — admin role only.

POST  /api/v1/admin/users              — create a new user
GET   /api/v1/admin/users              — list all users (paginated)
GET   /api/v1/admin/users/{user_id}    — get a single user
PATCH /api/v1/admin/users/{user_id}    — update roles, active status, or password

Security constraints enforced here:
  - All routes require the "admin" role.
  - An admin cannot deactivate their own account (self-lockout prevention).
  - An admin cannot remove the "admin" role from their own account.
  - Deactivating a user immediately revokes all their refresh tokens.
  - All mutating operations are written to the audit log.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.audit import AuditEvent
from app.core.limiter import limiter
from app.core.security import User, require_role
from app.schemas.users import (
    CreateUserRequest,
    UpdateUserRequest,
    UserListResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])

_ADMIN_DEP = Depends(require_role("admin"))


def _to_response(row: dict) -> UserResponse:
    return UserResponse(
        id=row["id"],
        username=row["username"],
        roles=row["roles"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def _ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_user(
    request: Request,
    body: CreateUserRequest,
    actor: User = _ADMIN_DEP,
) -> UserResponse:
    user_store = request.app.state.user_store
    audit_sink = getattr(request.app.state, "audit_sink", None)

    if await user_store.get_by_username(body.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    row = await user_store.create_user(body.username, body.password, body.roles)

    if audit_sink is not None:
        await audit_sink.write(
            AuditEvent(
                action="admin.user.create",
                outcome="success",
                user_id=actor.id,
                username=actor.username,
                resource_type="user",
                resource_id=row["id"],
                ip_address=_ip(request),
                user_agent=request.headers.get("user-agent"),
                metadata={"created_username": body.username, "roles": body.roles},
            )
        )

    return _to_response(row)


@router.get("", response_model=UserListResponse)
@limiter.limit("60/minute")
async def list_users(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _actor: User = _ADMIN_DEP,
) -> UserListResponse:
    user_store = request.app.state.user_store
    rows, total = await user_store.list_users(limit=limit, offset=offset)
    return UserListResponse(users=[_to_response(r) for r in rows], total=total)


@router.get("/{user_id}", response_model=UserResponse)
@limiter.limit("60/minute")
async def get_user(
    request: Request,
    user_id: str,
    _actor: User = _ADMIN_DEP,
) -> UserResponse:
    user_store = request.app.state.user_store
    row = await user_store.get_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_response(row)


@router.patch("/{user_id}", response_model=UserResponse)
@limiter.limit("20/minute")
async def update_user(
    request: Request,
    user_id: str,
    body: UpdateUserRequest,
    actor: User = _ADMIN_DEP,
) -> UserResponse:
    user_store = request.app.state.user_store
    rt_store = request.app.state.rt_store
    audit_sink = getattr(request.app.state, "audit_sink", None)

    existing = await user_store.get_by_id(user_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Self-protection: prevent admins from locking themselves out.
    if user_id == actor.id:
        if body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot deactivate their own account",
            )
        if body.roles is not None and "admin" not in body.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot remove the admin role from their own account",
            )

    updated = await user_store.update_user(
        user_id,
        roles=body.roles,
        is_active=body.is_active,
        password=body.password,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Immediately revoke all sessions when deactivating a user.
    if body.is_active is False:
        await rt_store.revoke_all_for_user(user_id)

    if audit_sink is not None:
        changes: dict = {}
        if body.roles is not None:
            changes["roles"] = body.roles
        if body.is_active is not None:
            changes["is_active"] = body.is_active
        if body.password is not None:
            changes["password"] = "<reset>"  # noqa: S105
        await audit_sink.write(
            AuditEvent(
                action="admin.user.update",
                outcome="success",
                user_id=actor.id,
                username=actor.username,
                resource_type="user",
                resource_id=user_id,
                ip_address=_ip(request),
                user_agent=request.headers.get("user-agent"),
                metadata={"target_username": existing["username"], "changes": changes},
            )
        )

    return _to_response(updated)
