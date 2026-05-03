"""
Authentication & RBAC.

THIS IS A STUB. The Auth epic owner replaces the body of these functions
with real JWT verification, but the public interface (function names,
arguments, return types, exceptions raised) MUST stay the same so the
route handlers don't change.

Contract for the Auth epic implementer:
---------------------------------------
1. `get_current_user(request)`:
     - Read the Authorization header (Bearer <token>).
     - Verify JWT signature with the configured public key / secret.
     - Decode claims, raise HTTPException(401) on any failure.
     - Return a User object populated from the JWT claims.

2. `require_role(role)`:
     - Returns a FastAPI dependency.
     - The dependency calls get_current_user, then raises HTTPException(403)
       if `role` is not in user.roles.

Roles in use (from the RBAC matrix in docs/RBAC.md):
    - admin        — full access, system management
    - doctor       — read/write patient data, resolve review queue
    - receptionist — upload documents, read patient data
    - auditor      — read-only access to anonymized data + metrics
"""

from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException, Request, status


@dataclass
class User:
    id: str
    username: str
    roles: list[str] = field(default_factory=list)


# ─── Stub: returns a fake user for development only ────────────────────
# Auth epic: REPLACE THIS with real JWT verification.
async def get_current_user(request: Request) -> User:
    """Stub auth — returns a hardcoded admin in development.

    In production this MUST verify the JWT and extract the real claims.
    """
    # TODO(auth-epic): replace with real JWT verification.
    if request.app.state.settings.env != "development":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth not implemented for non-dev environments",
        )
    return User(id="dev-user", username="dev", roles=["admin", "doctor"])


def require_role(role: str) -> Callable:
    """Dependency factory — enforces that the current user has `role`."""

    async def dependency(request: Request) -> User:
        user = await get_current_user(request)
        if role not in user.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return user

    return dependency
