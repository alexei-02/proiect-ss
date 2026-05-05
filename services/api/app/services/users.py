"""User management — thin Prisma wrapper.

Kept separate from PostgresStore so the Document interface contract stays clean.
"""

from datetime import datetime, timezone
from typing import Any

from prisma import Prisma

from app.core.passwords import hash_password


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

    async def create_user(
        self, username: str, password: str, roles: list[str]
    ) -> dict[str, Any]:
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
            data={"lastLoginAt": datetime.now(tz=timezone.utc)},
        )

    async def exists_with_role(self, role: str) -> bool:
        count = await self._db.user.count(where={"roles": {"has": role}})
        return count > 0
