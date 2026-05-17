"""Refresh token storage — issue, rotate, revoke, and clean up expired rows."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from prisma import Prisma


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RefreshTokenStore:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def issue(
        self,
        *,
        user_id: str,
        jti: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> str:
        """Generate a raw token, persist its hash, return the raw token."""
        raw = secrets.token_urlsafe(48)
        await self._db.refreshtoken.create(
            data={
                "userId": user_id,
                "tokenHash": _hash(raw),
                "jti": jti,
                "expiresAt": expires_at,
                "userAgent": user_agent,
                "ipAddress": ip_address,
            }
        )
        return raw

    async def lookup(self, raw: str) -> Any | None:
        """Return the RefreshToken Prisma row (or None) for the given raw token."""
        return await self._db.refreshtoken.find_unique(where={"tokenHash": _hash(raw)})

    async def revoke_by_hash(self, token_hash: str) -> None:
        await self._db.refreshtoken.update_many(
            where={"tokenHash": token_hash, "revokedAt": None},
            data={"revokedAt": datetime.now(tz=UTC)},
        )

    async def revoke_raw(self, raw: str) -> None:
        await self.revoke_by_hash(_hash(raw))

    async def revoke_all_for_user(self, user_id: str) -> None:
        await self._db.refreshtoken.update_many(
            where={"userId": user_id, "revokedAt": None},
            data={"revokedAt": datetime.now(tz=UTC)},
        )

    async def cleanup_expired(self) -> int:
        """Delete rows expired more than 7 days ago. Returns count deleted."""
        cutoff = datetime.now(tz=UTC) - timedelta(days=7)
        result = await self._db.refreshtoken.delete_many(where={"expiresAt": {"lt": cutoff}})
        return result


def hash_token(raw: str) -> str:
    """SHA-256 hash of a raw refresh token — exported for use in auth routes."""
    return _hash(raw)
