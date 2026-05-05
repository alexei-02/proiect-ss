"""Audit log endpoint — admin and auditor only.

GET /api/v1/audit-log
  Cursor-paginated (descending id).
  Auditor role sees IP addresses masked to /24.
"""

from fastapi import APIRouter, Depends, Query, Request

from app.core.security import User, require_any_role
from app.schemas.audit import AuditLogEntry, AuditLogPage

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit"])


@router.get("", response_model=AuditLogPage)
async def get_audit_log(
    request: Request,
    cursor: int | None = Query(None, ge=1, description="Fetch entries with id < cursor"),
    limit: int = Query(50, ge=1, le=200),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    _user: User = Depends(require_any_role("admin", "auditor")),
) -> AuditLogPage:
    db = request.app.state.db
    is_auditor_only = "admin" not in _user.roles

    where: dict = {}
    if cursor is not None:
        where["id"] = {"lt": cursor}
    if user_id is not None:
        where["userId"] = user_id
    if action is not None:
        where["action"] = action

    rows = await db.auditlog.find_many(
        where=where if where else None,
        order={"id": "desc"},
        take=limit + 1,  # fetch one extra to detect next page
    )

    has_more = len(rows) > limit
    rows = rows[:limit]

    entries: list[AuditLogEntry] = []
    for row in rows:
        ip = row.ipAddress
        # Auditors see only the /24 prefix, not the full IP.
        if is_auditor_only and ip:
            parts = ip.split(".")
            if len(parts) == 4:  # IPv4 only
                ip = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

        entries.append(
            AuditLogEntry(
                id=row.id,
                occurred_at=row.occurredAt,
                user_id=row.userId,
                username=row.username,
                action=row.action,
                resource_type=row.resourceType,
                resource_id=row.resourceId,
                ip_address=ip,
                user_agent=row.userAgent,
                outcome=row.outcome,
                metadata=row.metadata,
            )
        )

    next_cursor = rows[-1].id if has_more and rows else None
    return AuditLogPage(entries=entries, next_cursor=next_cursor)
