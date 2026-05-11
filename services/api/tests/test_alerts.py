"""Tests for the alerts endpoints and alert generator (T18/T19)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _make_alert_row(
    alert_id=1,
    alert_type="expiry_warning",
    severity="warning",
    document_id=None,
    message="Test alert",
    acknowledged=False,
):
    row = MagicMock()
    row.id = alert_id
    row.alertType = alert_type
    row.severity = severity
    row.documentId = document_id or str(uuid4())
    row.message = message
    row.expiresOn = None
    row.acknowledged = acknowledged
    row.createdAt = datetime.now(tz=timezone.utc)
    return row


@pytest.fixture
def client_with_alert_db(mock_db):
    """Client with alert-table mock wired in."""
    from unittest.mock import patch

    mock_db.alert = MagicMock()
    mock_db.alert.find_many = AsyncMock(return_value=[])
    mock_db.alert.find_unique = AsyncMock(return_value=None)
    mock_db.alert.update = AsyncMock(return_value=_make_alert_row(acknowledged=True))
    mock_db.alert.create = AsyncMock(return_value=_make_alert_row())
    mock_db.document.count = AsyncMock(return_value=0)
    mock_db.query_raw = AsyncMock(return_value=[{"p50": 0.0, "p95": 0.0, "total": 0}])

    with patch("app.main.Prisma", return_value=mock_db):
        from app.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


# ─── alert_generator unit tests ───────────────────────────────────────────────


async def test_scan_expiry_alerts_creates_alerts_for_near_expiry():
    """scan_expiry_alerts creates alerts when documents expire within 30 days."""
    from app.services.alert_generator import scan_expiry_alerts

    db = MagicMock()
    doc_id = str(uuid4())
    soon = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")

    db.query_raw = AsyncMock(
        return_value=[{"id": doc_id, "expiry_str": soon}]
    )
    db.alert = MagicMock()
    db.alert.find_many = AsyncMock(return_value=[])  # no existing alerts
    db.alert.create = AsyncMock(return_value=MagicMock())

    count = await scan_expiry_alerts(db)

    assert count == 1
    db.alert.create.assert_called_once()
    call_data = db.alert.create.call_args[1]["data"]
    assert call_data["alertType"] == "expiry_warning"
    assert call_data["documentId"] == doc_id


async def test_scan_expiry_alerts_skips_already_alerted():
    """scan_expiry_alerts skips documents with existing unacknowledged alerts."""
    from app.services.alert_generator import scan_expiry_alerts

    db = MagicMock()
    doc_id = str(uuid4())
    soon = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")

    db.query_raw = AsyncMock(
        return_value=[{"id": doc_id, "expiry_str": soon}]
    )
    existing = MagicMock()
    existing.documentId = doc_id
    db.alert = MagicMock()
    db.alert.find_many = AsyncMock(return_value=[existing])
    db.alert.create = AsyncMock()

    count = await scan_expiry_alerts(db)

    assert count == 0
    db.alert.create.assert_not_called()


async def test_scan_expiry_alerts_skips_far_future():
    """scan_expiry_alerts does not create alerts for documents expiring beyond 30 days."""
    from app.services.alert_generator import scan_expiry_alerts

    db = MagicMock()
    doc_id = str(uuid4())
    far = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")

    db.query_raw = AsyncMock(
        return_value=[{"id": doc_id, "expiry_str": far}]
    )
    db.alert = MagicMock()
    db.alert.find_many = AsyncMock(return_value=[])
    db.alert.create = AsyncMock()

    count = await scan_expiry_alerts(db)

    assert count == 0
    db.alert.create.assert_not_called()


async def test_scan_expiry_alerts_critical_severity_within_7_days():
    """Alerts within 7 days should have 'critical' severity."""
    from app.services.alert_generator import scan_expiry_alerts

    db = MagicMock()
    doc_id = str(uuid4())
    very_soon = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")

    db.query_raw = AsyncMock(
        return_value=[{"id": doc_id, "expiry_str": very_soon}]
    )
    db.alert = MagicMock()
    db.alert.find_many = AsyncMock(return_value=[])
    db.alert.create = AsyncMock(return_value=MagicMock())

    await scan_expiry_alerts(db)

    call_data = db.alert.create.call_args[1]["data"]
    assert call_data["severity"] == "critical"


# ─── HTTP endpoint tests ───────────────────────────────────────────────────────


def test_list_alerts_returns_unacknowledged_by_default(
    client_with_alert_db, auth_as, mock_db
):
    """GET /alerts returns unacknowledged alerts by default."""
    alert = _make_alert_row(acknowledged=False)
    mock_db.alert.find_many.return_value = [alert]

    resp = client_with_alert_db.get(
        "/api/v1/alerts",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["acknowledged"] is False


def test_list_alerts_doctor_allowed(client_with_alert_db, auth_as, mock_db):
    """Doctor role can list alerts."""
    mock_db.alert.find_many.return_value = []
    resp = client_with_alert_db.get(
        "/api/v1/alerts",
        headers=auth_as(["doctor"]),
    )
    assert resp.status_code == 200


def test_list_alerts_receptionist_forbidden(client_with_alert_db, auth_as):
    """Receptionist cannot list alerts."""
    resp = client_with_alert_db.get(
        "/api/v1/alerts",
        headers=auth_as(["receptionist"]),
    )
    assert resp.status_code == 403


def test_acknowledge_alert_sets_acknowledged_true(
    client_with_alert_db, auth_as, mock_db
):
    """POST /alerts/{id}/acknowledge marks the alert acknowledged."""
    alert = _make_alert_row(alert_id=42, acknowledged=False)
    acknowledged_alert = _make_alert_row(alert_id=42, acknowledged=True)
    mock_db.alert.find_unique.return_value = alert
    mock_db.alert.update.return_value = acknowledged_alert

    resp = client_with_alert_db.post(
        "/api/v1/alerts/42/acknowledge",
        headers=auth_as(["doctor"]),
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True


def test_acknowledge_alert_not_found(client_with_alert_db, auth_as, mock_db):
    """POST /alerts/{id}/acknowledge returns 404 when alert doesn't exist."""
    mock_db.alert.find_unique.return_value = None
    resp = client_with_alert_db.post(
        "/api/v1/alerts/9999/acknowledge",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 404


def test_acknowledge_alert_receptionist_forbidden(client_with_alert_db, auth_as):
    """Receptionist cannot acknowledge alerts."""
    resp = client_with_alert_db.post(
        "/api/v1/alerts/1/acknowledge",
        headers=auth_as(["receptionist"]),
    )
    assert resp.status_code == 403
