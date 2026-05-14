"""Tests for the reports endpoints (T18)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _make_report_row(
    report_id=None,
    status="queued",
    report_type="ocr_summary",
    result_path=None,
    error_msg=None,
):
    row = MagicMock()
    row.id = str(report_id or uuid4())
    row.reportType = report_type
    row.status = status
    row.params = {}
    row.resultPath = result_path
    row.createdAt = datetime.now(tz=timezone.utc)
    row.completedAt = None
    row.errorMsg = error_msg
    row.requestedBy = "test-user"
    return row


@pytest.fixture
def client_with_report_db(mock_db, tmp_path):
    """Client with report-table mock wired in."""
    from unittest.mock import patch

    mock_db.report = MagicMock()
    mock_db.report.create = AsyncMock(return_value=_make_report_row())
    mock_db.report.find_unique = AsyncMock(return_value=None)
    mock_db.report.update = AsyncMock(return_value=_make_report_row())
    mock_db.document.count = AsyncMock(return_value=5)
    mock_db.query_raw = AsyncMock(return_value=[{"p50": 120.0, "p95": 300.0, "total": 10}])

    with patch("app.main.Prisma", return_value=mock_db):
        from app.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


def test_create_report_queued(client_with_report_db, auth_as, mock_db):
    """POST /reports creates a row with status 'queued'."""
    report_id = str(uuid4())
    mock_db.report.create.return_value = _make_report_row(
        report_id=report_id, status="queued"
    )
    resp = client_with_report_db.post(
        "/api/v1/reports",
        json={"report_type": "ocr_summary", "params": {}},
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["report_type"] == "ocr_summary"
    mock_db.report.create.assert_called_once()


def test_get_report_status_returns_correct_status(client_with_report_db, auth_as, mock_db):
    """GET /reports/{id}/status returns the current report status."""
    report_id = uuid4()
    mock_db.report.find_unique.return_value = _make_report_row(
        report_id=report_id, status="running"
    )
    resp = client_with_report_db.get(
        f"/api/v1/reports/{report_id}/status",
        headers=auth_as(["auditor"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"


def test_get_report_status_not_found(client_with_report_db, auth_as, mock_db):
    """GET /reports/{id}/status returns 404 when report doesn't exist."""
    mock_db.report.find_unique.return_value = None
    resp = client_with_report_db.get(
        f"/api/v1/reports/{uuid4()}/status",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 404


def test_download_not_ready_returns_404(client_with_report_db, auth_as, mock_db):
    """GET /reports/{id}/download returns 404 when status is not 'ready'."""
    report_id = uuid4()
    mock_db.report.find_unique.return_value = _make_report_row(
        report_id=report_id, status="queued"
    )
    resp = client_with_report_db.get(
        f"/api/v1/reports/{report_id}/download",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 404


def test_download_ready_but_file_missing_returns_404(
    client_with_report_db, auth_as, mock_db, tmp_path
):
    """GET /reports/{id}/download returns 404 when file doesn't exist on disk."""
    report_id = uuid4()
    missing_path = str(tmp_path / "nonexistent.csv")
    mock_db.report.find_unique.return_value = _make_report_row(
        report_id=report_id, status="ready", result_path=missing_path
    )
    resp = client_with_report_db.get(
        f"/api/v1/reports/{report_id}/download",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 404


def test_create_report_doctor_role_forbidden(client_with_report_db, auth_as):
    """POST /reports returns 403 for the doctor role."""
    resp = client_with_report_db.post(
        "/api/v1/reports",
        json={"report_type": "ocr_summary"},
        headers=auth_as(["doctor"]),
    )
    assert resp.status_code == 403


def test_create_report_receptionist_role_forbidden(client_with_report_db, auth_as):
    """POST /reports returns 403 for the receptionist role."""
    resp = client_with_report_db.post(
        "/api/v1/reports",
        json={"report_type": "ocr_summary"},
        headers=auth_as(["receptionist"]),
    )
    assert resp.status_code == 403


def test_download_ready_streams_csv(client_with_report_db, auth_as, mock_db, tmp_path):
    """GET /reports/{id}/download streams CSV content when file exists."""
    report_id = uuid4()
    csv_file = tmp_path / f"{report_id}.csv"
    csv_file.write_text("id,status\nfoo,queued\n")

    mock_db.report.find_unique.return_value = _make_report_row(
        report_id=report_id, status="ready", result_path=str(csv_file)
    )
    resp = client_with_report_db.get(
        f"/api/v1/reports/{report_id}/download",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "id,status" in resp.text
