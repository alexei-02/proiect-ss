"""User management — thin Prisma wrapper.

Kept separate from PostgresStore so the Document interface contract stays clean.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.passwords import hash_password
from prisma import Prisma


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "username": row.username,
        "password_hash": row.passwordHash,
        "roles": list(row.roles),
        "is_active": row.isActive,
        "created_at": row.createdAt,
        "last_login_at": row.lastLoginAt,
    }


class UserStore:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def get_by_username(self, username: str) -> dict[str, Any] | None:
        row = await self._db.user.find_unique(where={"username": username})
        return _row_to_dict(row) if row is not None else None

    async def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        row = await self._db.user.find_unique(where={"id": user_id})
        return _row_to_dict(row) if row is not None else None

    async def create_user(self, username: str, password: str, roles: list[str]) -> dict[str, Any]:
        row = await self._db.user.create(
            data={
                "username": username,
                "passwordHash": hash_password(password),
                "roles": roles,
            }
        )
        return _row_to_dict(row)

    async def set_active(self, user_id: str, *, is_active: bool) -> None:
        await self._db.user.update(
            where={"id": user_id},
            data={"isActive": is_active},
        )

    async def record_login(self, user_id: str) -> None:
        await self._db.user.update(
            where={"id": user_id},
            data={"lastLoginAt": datetime.now(tz=UTC)},
        )

    async def exists_with_role(self, role: str) -> bool:
        count = await self._db.user.count(where={"roles": {"has": role}})
        return count > 0

    async def list_users(self, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        rows, total = await asyncio.gather(
            self._db.user.find_many(order={"createdAt": "desc"}, take=limit, skip=offset),
            self._db.user.count(),
        )
        return [_row_to_dict(r) for r in rows], total

    async def update_user(
        self,
        user_id: str,
        *,
        roles: list[str] | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> dict[str, Any] | None:
        data: dict[str, Any] = {}
        if roles is not None:
            data["roles"] = roles
        if is_active is not None:
            data["isActive"] = is_active
        if password is not None:
            data["passwordHash"] = hash_password(password)
        if not data:
            return await self.get_by_id(user_id)
        try:
            row = await self._db.user.update(where={"id": user_id}, data=data)
            return _row_to_dict(row)
        except Exception:
            return None
