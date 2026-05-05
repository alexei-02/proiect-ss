"""Integration tests for auth routes (/login, /refresh, /logout, /me).

Uses TestClient with a mocked Prisma DB (via conftest.mock_db) so no real
PostgreSQL is required.  Each test configures the mock_db stubs it needs.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.passwords import hash_password


# ─── helpers ──────────────────────────────────────────────────────────────────


def _user_row(roles: list[str] | None = None, active: bool = True) -> MagicMock:
    row = MagicMock()
    row.id = str(uuid4())
    row.username = "testuser"
    row.passwordHash = hash_password("correct-password")  # noqa: S106
    row.roles = roles or ["doctor"]
    row.isActive = active
    row.createdAt = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    row.lastLoginAt = None
    return row


def _rt_row(user_id: str, revoked: bool = False) -> MagicMock:
    row = MagicMock()
    row.userId = user_id
    row.revokedAt = datetime.now(tz=timezone.utc).replace(tzinfo=None) if revoked else None
    row.expiresAt = (datetime.now(tz=timezone.utc) + timedelta(days=7)).replace(tzinfo=None)
    return row


# ─── login ────────────────────────────────────────────────────────────────────


def test_login_success(client: TestClient, mock_db: MagicMock) -> None:
    prisma_row = _user_row()
    mock_db.user.find_unique.return_value = prisma_row
    mock_db.refreshtoken.create.return_value = MagicMock()

    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "correct-password"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0


def test_login_wrong_password(client: TestClient, mock_db: MagicMock) -> None:
    mock_db.user.find_unique.return_value = _user_row()
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "wrong"},
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


def test_login_unknown_user(client: TestClient, mock_db: MagicMock) -> None:
    mock_db.user.find_unique.return_value = None
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "ghost", "password": "pass"},
    )
    assert resp.status_code == 401
    # Same message as wrong password — no user enumeration.
    assert resp.json()["detail"] == "Invalid username or password"


def test_login_inactive_user(client: TestClient, mock_db: MagicMock) -> None:
    mock_db.user.find_unique.return_value = _user_row(active=False)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "correct-password"},
    )
    assert resp.status_code == 401


# ─── refresh ──────────────────────────────────────────────────────────────────


def test_refresh_success(client: TestClient, mock_db: MagicMock) -> None:
    from app.core.jwt_utils import encode_refresh

    user = _user_row()
    mock_db.user.find_unique.return_value = user

    raw_refresh, _ = encode_refresh(user.id)
    rt = _rt_row(user.id, revoked=False)
    mock_db.refreshtoken.find_unique.return_value = rt

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_refresh_revoked_triggers_replay_detection(
    client: TestClient, mock_db: MagicMock
) -> None:
    from app.core.jwt_utils import encode_refresh

    user = _user_row()
    raw_refresh, _ = encode_refresh(user.id)
    rt = _rt_row(user.id, revoked=True)
    mock_db.refreshtoken.find_unique.return_value = rt

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw_refresh})
    assert resp.status_code == 401
    # revoke_all_for_user must have been called (replay detection)
    mock_db.refreshtoken.update_many.assert_called()


def test_refresh_invalid_jwt(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "not.a.jwt"})
    assert resp.status_code == 401


def test_refresh_unknown_token(client: TestClient, mock_db: MagicMock) -> None:
    from app.core.jwt_utils import encode_refresh
    raw, _ = encode_refresh("u1")
    mock_db.refreshtoken.find_unique.return_value = None
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert resp.status_code == 401


# ─── logout ───────────────────────────────────────────────────────────────────


def test_logout_single_token(client: TestClient, auth_as) -> None:
    headers = auth_as(["doctor"])
    resp = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "some-raw-token"},
        headers=headers,
    )
    assert resp.status_code == 204


def test_logout_all_tokens(client: TestClient, mock_db: MagicMock, auth_as) -> None:
    headers = auth_as(["doctor"])
    resp = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": None},
        headers=headers,
    )
    assert resp.status_code == 204
    # revoke_all_for_user should have been called
    mock_db.refreshtoken.update_many.assert_called()


def test_logout_unauthenticated(client: TestClient) -> None:
    """With DEV_AUTH_BYPASS=true a missing token still provides dev-user."""
    resp = client.post("/api/v1/auth/logout", json={})
    # dev bypass gives a user, so 204 is expected
    assert resp.status_code == 204


# ─── /me ──────────────────────────────────────────────────────────────────────


def test_me_returns_user_info(client: TestClient, auth_as) -> None:
    headers = auth_as(["doctor", "admin"], user_id="uid-1", username="alice")
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "uid-1"
    assert body["username"] == "alice"
    assert set(body["roles"]) == {"doctor", "admin"}


def test_me_unauthenticated_with_bypass(client: TestClient) -> None:
    """With DEV_AUTH_BYPASS=true the dev-user is returned."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["id"] == "dev-user"
