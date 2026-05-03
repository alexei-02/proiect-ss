"""Payload size middleware — enforces 413 Payload Too Large."""

from fastapi.testclient import TestClient


def test_health_does_not_check_size(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200


def test_oversized_content_length_rejected(client: TestClient) -> None:
    """A Content-Length above the JSON limit must return 413 immediately."""
    huge = 1_000_000_000  # 1 GB
    r = client.post(
        "/api/v1/review-queue/00000000-0000-0000-0000-000000000000/resolve",
        headers={"Content-Length": str(huge)},
        json={"corrected_fields": {"patient_name": "x"}},
    )
    assert r.status_code == 413


def test_invalid_content_length_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/v1/review-queue/00000000-0000-0000-0000-000000000000/resolve",
        headers={"Content-Length": "not-a-number"},
        json={"corrected_fields": {"patient_name": "x"}},
    )
    assert r.status_code == 400


def test_normal_request_passes(client: TestClient) -> None:
    """Small JSON request is accepted by the size middleware (auth/404 may follow)."""
    r = client.get("/api/v1/review-queue")
    assert r.status_code != 413
    assert r.status_code != 400
