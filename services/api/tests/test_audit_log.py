"""Tests for audit logging: middleware, sink, and audit-log endpoint."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.audit import (
    AuditEvent,
    AuditMiddleware,
    PHI_TOUCHING_PATHS,
    PrismaAuditSink,
    _client_ip,
    _path_to_action,
    _path_to_resource,
)


# ─── unit helpers ─────────────────────────────────────────────────────────────


def test_phi_touching_paths_contains_expected() -> None:
    assert "/api/v1/documents" in PHI_TOUCHING_PATHS
    assert "/api/v1/review-queue" in PHI_TOUCHING_PATHS


def test_path_to_action_document_post() -> None:
    assert _path_to_action("POST", "/api/v1/documents") == "document.upload"


def test_path_to_action_document_get() -> None:
    assert _path_to_action("GET", "/api/v1/documents/abc") == "document.read"


def test_path_to_action_review_get() -> None:
    assert _path_to_action("GET", "/api/v1/review-queue") == "review.list"


def test_path_to_action_review_post() -> None:
    assert _path_to_action("POST", "/api/v1/review-queue/abc/resolve") == "review.resolve"


def test_path_to_resource_document() -> None:
    assert _path_to_resource("/api/v1/documents/abc") == "document"


def test_path_to_resource_review() -> None:
    assert _path_to_resource("/api/v1/review-queue") == "review_item"


def test_client_ip_xff() -> None:
    req = MagicMock()
    req.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1"}
    req.client = None
    assert _client_ip(req) == "10.0.0.1"


def test_client_ip_remote_addr() -> None:
    req = MagicMock()
    req.headers = {}
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    assert _client_ip(req) == "127.0.0.1"


def test_client_ip_none() -> None:
    req = MagicMock()
    req.headers = {}
    req.client = None
    assert _client_ip(req) is None


# ─── AuditEvent dataclass ─────────────────────────────────────────────────────


def test_audit_event_defaults() -> None:
    event = AuditEvent(action="document.read", outcome="success")
    assert event.user_id is None
    assert event.metadata is None
    assert event.occurred_at is not None


# ─── PrismaAuditSink ──────────────────────────────────────────────────────────


async def test_prisma_audit_sink_write() -> None:
    db = MagicMock()
    db.auditlog = MagicMock()
    db.auditlog.create = AsyncMock()

    sink = PrismaAuditSink(db)
    event = AuditEvent(
        action="document.read",
        outcome="success",
        user_id="u1",
        username="alice",
        resource_type="document",
        resource_id="doc-1",
    )
    await sink.write(event)
    db.auditlog.create.assert_called_once()
    call_data = db.auditlog.create.call_args[1]["data"]
    assert call_data["action"] == "document.read"
    assert call_data["outcome"] == "success"
    assert call_data["userId"] == "u1"


# ─── Audit-log endpoint ───────────────────────────────────────────────────────


def _make_audit_log_row(row_id: int = 1, ip: str = "192.168.1.100") -> MagicMock:
    row = MagicMock()
    row.id = row_id
    row.occurredAt = datetime.now(tz=timezone.utc)
    row.userId = str(uuid4())
    row.username = "alice"
    row.action = "document.read"
    row.resourceType = "document"
    row.resourceId = str(uuid4())
    row.ipAddress = ip
    row.userAgent = "test-agent"
    row.outcome = "success"
    row.metadata = None
    return row


def test_audit_log_admin_sees_full_ip(
    client: TestClient, mock_db: MagicMock, auth_as
) -> None:
    mock_db.auditlog.find_many.return_value = [_make_audit_log_row(ip="192.168.1.100")]
    resp = client.get("/api/v1/audit-log", headers=auth_as(["admin"]))
    assert resp.status_code == 200
    entry = resp.json()["entries"][0]
    assert entry["ip_address"] == "192.168.1.100"


def test_audit_log_auditor_sees_masked_ip(
    client: TestClient, mock_db: MagicMock, auth_as
) -> None:
    mock_db.auditlog.find_many.return_value = [_make_audit_log_row(ip="192.168.1.100")]
    resp = client.get("/api/v1/audit-log", headers=auth_as(["auditor"]))
    assert resp.status_code == 200
    entry = resp.json()["entries"][0]
    assert entry["ip_address"] == "192.168.1.0/24"


def test_audit_log_doctor_forbidden(client: TestClient, auth_as) -> None:
    resp = client.get("/api/v1/audit-log", headers=auth_as(["doctor"]))
    assert resp.status_code == 403


def test_audit_log_health_endpoint_not_audited(
    client: TestClient, in_memory_audit_sink
) -> None:
    """Hits to /health must NOT produce audit rows."""
    client.app.state.audit_sink = in_memory_audit_sink
    client.get("/health")
    assert len(in_memory_audit_sink.events) == 0


def test_audit_log_next_cursor_pagination(
    client: TestClient, mock_db: MagicMock, auth_as
) -> None:
    # Return limit+1 rows so pagination kicks in
    rows = [_make_audit_log_row(row_id=i) for i in range(51, 0, -1)]
    mock_db.auditlog.find_many.return_value = rows
    resp = client.get("/api/v1/audit-log?limit=50", headers=auth_as(["admin"]))
    body = resp.json()
    assert len(body["entries"]) == 50
    assert body["next_cursor"] is not None
