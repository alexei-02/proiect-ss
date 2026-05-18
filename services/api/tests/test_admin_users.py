"""Tests for admin user management endpoints."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _make_user_row(
    user_id: str = "user-001",
    username: str = "testuser",
    roles: list | None = None,
    is_active: bool = True,
) -> MagicMock:
    from datetime import datetime, timezone

    row = MagicMock()
    row.id = user_id
    row.username = username
    row.passwordHash = "hashed"
    row.roles = roles if roles is not None else ["doctor"]
    row.isActive = is_active
    row.createdAt = datetime.now(tz=timezone.utc)
    row.lastLoginAt = None
    return row


# ─── create user ─────────────────────────────────────────────────────────────


def test_create_user_success(client: TestClient, auth_as, mock_db) -> None:
    new_row = _make_user_row(user_id=str(uuid4()), username="newdoc", roles=["doctor"])
    actor = _make_user_row(user_id="test-user", username="testuser", roles=["admin"])

    # find_unique is used for both the is_active check (by id) and the username check.
    def _find_unique(*, where):
        if "id" in where:
            return actor  # is_active check → active
        return None  # username lookup → not taken

    mock_db.user.find_unique = AsyncMock(side_effect=_find_unique)
    mock_db.user.create.return_value = new_row
    mock_db.auditlog.create = AsyncMock()

    resp = client.post(
        "/api/v1/admin/users",
        headers=auth_as(["admin"]),
        json={"username": "newdoc", "password": "Str0ngP@ssword1", "roles": ["doctor"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newdoc"
    assert data["roles"] == ["doctor"]
    assert data["is_active"] is True


def test_create_user_duplicate_username(client: TestClient, auth_as, mock_db) -> None:
    existing = _make_user_row(username="taken")
    mock_db.user.find_unique.return_value = existing

    resp = client.post(
        "/api/v1/admin/users",
        headers=auth_as(["admin"]),
        json={"username": "taken", "password": "Str0ngP@ssword1", "roles": ["doctor"]},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_create_user_invalid_role(client: TestClient, auth_as) -> None:
    resp = client.post(
        "/api/v1/admin/users",
        headers=auth_as(["admin"]),
        json={"username": "newuser", "password": "Str0ngP@ssword1", "roles": ["superuser"]},
    )
    assert resp.status_code == 422


def test_create_user_short_password(client: TestClient, auth_as) -> None:
    resp = client.post(
        "/api/v1/admin/users",
        headers=auth_as(["admin"]),
        json={"username": "newuser", "password": "short", "roles": ["doctor"]},
    )
    assert resp.status_code == 422


def test_create_user_invalid_username_chars(client: TestClient, auth_as) -> None:
    resp = client.post(
        "/api/v1/admin/users",
        headers=auth_as(["admin"]),
        json={"username": "new user!", "password": "Str0ngP@ssword1", "roles": ["doctor"]},
    )
    assert resp.status_code == 422


def test_create_user_non_admin_denied(client: TestClient, auth_as) -> None:
    for role in ["doctor", "receptionist", "auditor"]:
        resp = client.post(
            "/api/v1/admin/users",
            headers=auth_as([role]),
            json={"username": "x", "password": "Str0ngP@ssword1", "roles": ["doctor"]},
        )
        assert resp.status_code == 403, f"Expected 403 for role={role}, got {resp.status_code}"


# ─── list users ──────────────────────────────────────────────────────────────


def test_list_users_success(client: TestClient, auth_as, mock_db) -> None:
    rows = [_make_user_row(user_id=f"u-{i}", username=f"user{i}") for i in range(3)]
    mock_db.user.find_many.return_value = rows
    mock_db.user.count.return_value = 3

    resp = client.get("/api/v1/admin/users", headers=auth_as(["admin"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["users"]) == 3


def test_list_users_non_admin_denied(client: TestClient, auth_as) -> None:
    for role in ["doctor", "receptionist", "auditor"]:
        resp = client.get("/api/v1/admin/users", headers=auth_as([role]))
        assert resp.status_code == 403


def test_list_users_pagination_params(client: TestClient, auth_as, mock_db) -> None:
    mock_db.user.find_many.return_value = []
    mock_db.user.count.return_value = 0

    resp = client.get("/api/v1/admin/users?limit=10&offset=20", headers=auth_as(["admin"]))
    assert resp.status_code == 200


# ─── get user ────────────────────────────────────────────────────────────────


def test_get_user_success(client: TestClient, auth_as, mock_db) -> None:
    target = _make_user_row(user_id="target-id", username="targetuser", roles=["receptionist"])
    mock_db.user.find_unique.return_value = target

    resp = client.get("/api/v1/admin/users/target-id", headers=auth_as(["admin"]))
    assert resp.status_code == 200
    assert resp.json()["username"] == "targetuser"


def test_get_user_not_found(client: TestClient, auth_as, mock_db) -> None:
    actor = _make_user_row(user_id="test-user", username="testuser", roles=["admin"])

    def _find_unique(*, where):
        # is_active check returns actor; any other id lookup returns None
        if where.get("id") == "test-user":
            return actor
        return None

    mock_db.user.find_unique = AsyncMock(side_effect=_find_unique)

    resp = client.get(f"/api/v1/admin/users/{uuid4()}", headers=auth_as(["admin"]))
    assert resp.status_code == 404


def test_get_user_non_admin_denied(client: TestClient, auth_as) -> None:
    resp = client.get("/api/v1/admin/users/some-id", headers=auth_as(["doctor"]))
    assert resp.status_code == 403


# ─── update user ─────────────────────────────────────────────────────────────


def test_update_user_change_roles(client: TestClient, auth_as, mock_db) -> None:
    target = _make_user_row(user_id="other-id", username="otheruser", roles=["doctor"])
    updated = _make_user_row(user_id="other-id", username="otheruser", roles=["doctor", "auditor"])
    mock_db.user.find_unique.return_value = target
    mock_db.user.update.return_value = updated

    resp = client.patch(
        "/api/v1/admin/users/other-id",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"roles": ["doctor", "auditor"]},
    )
    assert resp.status_code == 200
    assert "auditor" in resp.json()["roles"]


def test_update_user_deactivate_revokes_tokens(client: TestClient, auth_as, mock_db) -> None:
    target = _make_user_row(user_id="victim-id", username="victim", is_active=True)
    deactivated = _make_user_row(user_id="victim-id", username="victim", is_active=False)
    mock_db.user.find_unique.return_value = target
    mock_db.user.update.return_value = deactivated
    mock_db.refreshtoken.update_many = AsyncMock()

    resp = client.patch(
        "/api/v1/admin/users/victim-id",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    # Refresh tokens must have been revoked.
    mock_db.refreshtoken.update_many.assert_called_once()


def test_update_user_self_deactivate_denied(client: TestClient, auth_as, mock_db) -> None:
    me = _make_user_row(user_id="admin-id", username="admin", roles=["admin"])
    mock_db.user.find_unique.return_value = me

    resp = client.patch(
        "/api/v1/admin/users/admin-id",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"is_active": False},
    )
    assert resp.status_code == 403
    assert "deactivate" in resp.json()["detail"].lower()


def test_update_user_self_remove_admin_role_denied(client: TestClient, auth_as, mock_db) -> None:
    me = _make_user_row(user_id="admin-id", username="admin", roles=["admin"])
    mock_db.user.find_unique.return_value = me

    resp = client.patch(
        "/api/v1/admin/users/admin-id",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"roles": ["doctor"]},  # removes "admin"
    )
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"].lower()


def test_update_user_self_add_role_allowed(client: TestClient, auth_as, mock_db) -> None:
    me = _make_user_row(user_id="admin-id", username="admin", roles=["admin"])
    updated = _make_user_row(user_id="admin-id", username="admin", roles=["admin", "doctor"])
    mock_db.user.find_unique.return_value = me
    mock_db.user.update.return_value = updated

    resp = client.patch(
        "/api/v1/admin/users/admin-id",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"roles": ["admin", "doctor"]},  # keeps "admin", adds "doctor"
    )
    assert resp.status_code == 200


def test_update_user_not_found(client: TestClient, auth_as, mock_db) -> None:
    actor = _make_user_row(user_id="admin-id", username="admin", roles=["admin"])

    def _find_unique(*, where):
        if where.get("id") == "admin-id":
            return actor  # is_active check → active
        return None  # target user not found

    mock_db.user.find_unique = AsyncMock(side_effect=_find_unique)

    resp = client.patch(
        f"/api/v1/admin/users/{uuid4()}",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"is_active": True},
    )
    assert resp.status_code == 404


def test_update_user_no_fields_rejected(client: TestClient, auth_as) -> None:
    resp = client.patch(
        "/api/v1/admin/users/some-id",
        headers=auth_as(["admin"]),
        json={},
    )
    assert resp.status_code == 422


def test_update_user_password_reset(client: TestClient, auth_as, mock_db) -> None:
    target = _make_user_row(user_id="other-id", username="other")
    mock_db.user.find_unique.return_value = target
    mock_db.user.update.return_value = target

    resp = client.patch(
        "/api/v1/admin/users/other-id",
        headers=auth_as(["admin"], user_id="admin-id"),
        json={"password": "NewStr0ngP@ssword"},
    )
    assert resp.status_code == 200


def test_update_user_non_admin_denied(client: TestClient, auth_as) -> None:
    for role in ["doctor", "receptionist", "auditor"]:
        resp = client.patch(
            "/api/v1/admin/users/some-id",
            headers=auth_as([role]),
            json={"is_active": False},
        )
        assert resp.status_code == 403
