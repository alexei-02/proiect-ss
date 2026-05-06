"""Audit log response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    id: int
    occurred_at: datetime
    user_id: str | None
    username: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    user_agent: str | None
    outcome: str
    metadata: dict[str, Any] | None


class AuditLogPage(BaseModel):
    entries: list[AuditLogEntry]
    next_cursor: int | None  # pass as ?cursor= on the next request
