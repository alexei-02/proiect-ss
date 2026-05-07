from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class ReportType(StrEnum):
    OCR_SUMMARY = "ocr_summary"
    AUDIT_EXPORT = "audit_export"
    COMPLIANCE = "compliance"
    ANONYMISED_EXPORT = "anonymised_export"


class ReportRequest(BaseModel):
    report_type: ReportType
    params: dict[str, Any] = {}


class ReportStatusResponse(BaseModel):
    id: UUID
    report_type: ReportType
    status: Literal["queued", "running", "ready", "failed"]
    created_at: datetime
    completed_at: datetime | None = None
    error_msg: str | None = None
    download_url: str | None = None  # populated when status == "ready"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertResponse(BaseModel):
    id: int
    alert_type: str
    severity: AlertSeverity
    document_id: str | None = None
    message: str
    expires_on: datetime | None = None
    acknowledged: bool
    created_at: datetime
