"""Audit logging infrastructure.

Two writers:
  - AuditMiddleware: logs every PHI-touching HTTP request after auth resolves.
  - PrismaAuditSink: persists AuditEvent rows to the append-only audit_logs table.

The sink is also called by PostgresStore for phi.decrypt events.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from prisma import Json, Prisma

logger = logging.getLogger(__name__)

# Paths whose responses touch PHI — middleware writes an audit row for these.
PHI_TOUCHING_PATHS = frozenset(
    {
        "/api/v1/documents",
        "/api/v1/review-queue",
    }
)


@dataclass
class AuditEvent:
    action: str
    outcome: str  # "success" | "denied" | "error"
    user_id: str | None = None
    username: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class PrismaAuditSink:
    """Writes AuditEvent rows to PostgreSQL via Prisma."""

    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def write(self, event: AuditEvent) -> None:
        try:
            await self._db.auditlog.create(
                data={
                    "userId": event.user_id,
                    "username": event.username,
                    "action": event.action,
                    "resourceType": event.resource_type,
                    "resourceId": event.resource_id,
                    "ipAddress": event.ip_address,
                    "userAgent": event.user_agent,
                    "outcome": event.outcome,
                    "metadata": Json(event.metadata) if event.metadata else None,
                }
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Audit sink write failed: %s", exc)


class AuditMiddleware(BaseHTTPMiddleware):
    """Writes one audit row per PHI-touching request that has an authenticated user.

    The sink is resolved at dispatch time from request.app.state.audit_sink so
    this middleware can be registered at create_app() time before the DB connects.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        path = request.url.path
        if not any(path.startswith(p) for p in PHI_TOUCHING_PATHS):
            return response

        sink: PrismaAuditSink | None = getattr(getattr(request, "app", None), "state", None)
        if sink is not None:
            sink = getattr(sink, "audit_sink", None)
        if sink is None:
            return response

        user = getattr(getattr(request, "state", None), "user", None)
        if user is None:
            return response

        status_code = response.status_code
        if status_code < 400:
            outcome = "success"
        elif status_code == 403:
            outcome = "denied"
        else:
            outcome = "error"

        resource_id = _extract_resource_id(path)

        event = AuditEvent(
            action=_path_to_action(request.method, path),
            outcome=outcome,
            user_id=user.id,
            username=user.username,
            resource_type=_path_to_resource(path),
            resource_id=resource_id,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        try:
            await sink.write(event)
        except Exception as exc:  # pragma: no cover
            logger.error("AuditMiddleware write failed: %s", exc)

        return response


def _extract_resource_id(path: str) -> str | None:
    parts = path.strip("/").split("/")
    # /api/v1/documents/{id}  → parts[3] = id
    if len(parts) >= 4 and parts[3] not in ("", "resolve"):
        return parts[3]
    return None


def _path_to_action(method: str, path: str) -> str:
    if "/documents" in path:
        return "document.upload" if method == "POST" else "document.read"
    if "/review-queue" in path:
        return "review.resolve" if method == "POST" else "review.list"
    return f"{method.lower()}.unknown"


def _path_to_resource(path: str) -> str:
    if "/documents" in path:
        return "document"
    if "/review-queue" in path:
        return "review_item"
    return "unknown"


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None
