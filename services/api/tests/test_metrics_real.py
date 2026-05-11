"""Tests for the real metrics aggregations (T21)."""

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_metrics_db(mock_db):
    """Client with document.count and query_raw mocked."""
    from unittest.mock import patch

    mock_db.document.count = AsyncMock(return_value=7)
    mock_db.query_raw = AsyncMock(
        return_value=[{"p50": 150.5, "p95": 420.0, "total": 20}]
    )

    with patch("app.main.Prisma", return_value=mock_db):
        from app.main import create_app

        app = create_app()
        with TestClient(app) as c:
            yield c


def test_ocr_metrics_returns_correct_queue_depth(
    client_with_metrics_db, auth_as, mock_db
):
    """GET /metrics/ocr returns queue_depth from DB count."""
    mock_db.document.count = AsyncMock(side_effect=[5, 12])  # pending, then completed
    resp = client_with_metrics_db.get(
        "/api/v1/metrics/ocr",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "review_queue_depth" in body
    assert "completed_last_24h" in body
    assert "p50_latency_ms" in body
    assert "p95_latency_ms" in body


def test_ocr_metrics_returns_latency_values(client_with_metrics_db, auth_as, mock_db):
    """GET /metrics/ocr includes latency percentiles from raw query."""
    mock_db.query_raw.return_value = [{"p50": 200.0, "p95": 500.5, "total": 30}]
    resp = client_with_metrics_db.get(
        "/api/v1/metrics/ocr",
        headers=auth_as(["auditor"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["p50_latency_ms"] == 200.0
    assert body["p95_latency_ms"] == 500.5


def test_ocr_metrics_empty_query_returns_zeros(client_with_metrics_db, auth_as, mock_db):
    """GET /metrics/ocr returns 0.0 for latency when no matching rows."""
    mock_db.query_raw.return_value = []
    resp = client_with_metrics_db.get(
        "/api/v1/metrics/ocr",
        headers=auth_as(["admin"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["p50_latency_ms"] == 0.0
    assert body["p95_latency_ms"] == 0.0


def test_ocr_metrics_doctor_forbidden(client_with_metrics_db, auth_as):
    """GET /metrics/ocr returns 403 for doctor role."""
    resp = client_with_metrics_db.get(
        "/api/v1/metrics/ocr",
        headers=auth_as(["doctor"]),
    )
    assert resp.status_code == 403


def test_ocr_metrics_receptionist_forbidden(client_with_metrics_db, auth_as):
    """GET /metrics/ocr returns 403 for receptionist role."""
    resp = client_with_metrics_db.get(
        "/api/v1/metrics/ocr",
        headers=auth_as(["receptionist"]),
    )
    assert resp.status_code == 403
