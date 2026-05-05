"""Tests for app.core.security — 100% branch coverage target."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.core.security import User, _ACTIVE_CACHE, get_current_user, require_any_role, require_role


# ─── helpers ──────────────────────────────────────────────────────────────────


def _make_request(headers: dict | None = None, env: str = "test", bypass: bool = True):
    settings_mock = MagicMock()
    settings_mock.env = env
    settings_mock.dev_auth_bypass = bypass

    app_mock = MagicMock()
    app_mock.state.user_store = None

    request = MagicMock()
    request.headers = headers or {}
    request.app = app_mock
    request.state = MagicMock()
    # simulate missing state.user gracefully
    del request.state.user
    return request, settings_mock


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _valid_token(user_id: str = "u1", roles: list | None = None) -> str:
    from app.core.jwt_utils import encode_access
    token, _ = encode_access(user_id, "tester", roles or ["doctor"])
    return token


# ─── dev bypass ───────────────────────────────────────────────────────────────


async def test_dev_bypass_no_header(monkeypatch) -> None:
    request, settings_mock = _make_request(env="test", bypass=True)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        user = await get_current_user(request)
    assert user.id == "dev-user"
    assert "admin" in user.roles


async def test_dev_bypass_disabled_requires_token(monkeypatch) -> None:
    request, settings_mock = _make_request(env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


async def test_dev_bypass_ignored_in_production(monkeypatch) -> None:
    """Production env must NOT bypass even when dev_auth_bypass=True."""
    request, settings_mock = _make_request(env="production", bypass=True)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


async def test_bypass_skipped_when_auth_header_present(monkeypatch) -> None:
    """Even with bypass=True, a provided Bearer token must be verified."""
    token = _valid_token()
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=True)
    request.app.state.user_store = None
    with patch("app.core.security.get_settings", return_value=settings_mock):
        user = await get_current_user(request)
    assert user.id == "u1"


# ─── missing / malformed header ───────────────────────────────────────────────


async def test_missing_auth_header(monkeypatch) -> None:
    request, settings_mock = _make_request(env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


async def test_malformed_auth_header(monkeypatch) -> None:
    request, settings_mock = _make_request(headers={"Authorization": "Basic abc"}, env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


# ─── invalid tokens ───────────────────────────────────────────────────────────


async def test_bad_signature_rejected(monkeypatch) -> None:
    token = jwt.encode(
        {"sub": "u1", "type": "access", "roles": []},
        "wrong-secret",
        algorithm="HS256",
    )
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


async def test_expired_token_rejected() -> None:
    from app.core.config import get_settings
    settings = get_settings()
    payload = {
        "sub": "u1",
        "username": "tester",
        "roles": ["doctor"],
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": int(time.time()) - 3600,  # already expired
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


async def test_refresh_token_as_access_rejected() -> None:
    from app.core.jwt_utils import encode_refresh
    token, _ = encode_refresh("u1")
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


async def test_wrong_audience_rejected() -> None:
    from app.core.config import get_settings
    settings = get_settings()
    payload = {
        "sub": "u1",
        "username": "tester",
        "roles": [],
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": "wrong-audience",
        "exp": int(time.time()) + 900,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


# ─── is_active kill switch ────────────────────────────────────────────────────


async def test_deactivated_user_rejected() -> None:
    token = _valid_token("inactive-user")
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)

    user_store_mock = AsyncMock()
    user_store_mock.get_by_id.return_value = {"is_active": False}
    request.app.state.user_store = user_store_mock

    _ACTIVE_CACHE.pop("inactive-user", None)

    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request)
    assert exc_info.value.status_code == 401


async def test_active_user_passes() -> None:
    token = _valid_token("active-user")
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)

    user_store_mock = AsyncMock()
    user_store_mock.get_by_id.return_value = {"is_active": True}
    request.app.state.user_store = user_store_mock

    _ACTIVE_CACHE.pop("active-user", None)

    with patch("app.core.security.get_settings", return_value=settings_mock):
        user = await get_current_user(request)
    assert user.id == "active-user"


async def test_is_active_cache_used() -> None:
    """Second call should not hit user_store again within TTL."""
    token = _valid_token("cached-user")
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)

    user_store_mock = AsyncMock()
    user_store_mock.get_by_id.return_value = {"is_active": True}
    request.app.state.user_store = user_store_mock

    _ACTIVE_CACHE.pop("cached-user", None)

    with patch("app.core.security.get_settings", return_value=settings_mock):
        await get_current_user(request)
        await get_current_user(request)

    user_store_mock.get_by_id.assert_called_once()  # cached on second call


# ─── require_role / require_any_role ──────────────────────────────────────────


async def test_require_role_passes_correct_role() -> None:
    dep = require_role("doctor")
    request, settings_mock = _make_request(env="test", bypass=True)
    with patch("app.core.security.get_settings", return_value=settings_mock):
        user = await dep(request)
    assert "doctor" in user.roles


async def test_require_role_blocks_missing_role() -> None:
    dep = require_role("admin")
    token = _valid_token(roles=["doctor"])
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    request.app.state.user_store = None
    _ACTIVE_CACHE.pop("u1", None)

    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
    assert exc_info.value.status_code == 403


async def test_require_any_role_passes_first_match() -> None:
    dep = require_any_role("auditor", "doctor")
    token = _valid_token(roles=["doctor"])
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    request.app.state.user_store = None
    _ACTIVE_CACHE.pop("u1", None)

    with patch("app.core.security.get_settings", return_value=settings_mock):
        user = await dep(request)
    assert "doctor" in user.roles


async def test_require_any_role_blocks_no_match() -> None:
    dep = require_any_role("admin", "auditor")
    token = _valid_token(roles=["doctor"])
    request, settings_mock = _make_request(headers=_bearer(token), env="test", bypass=False)
    request.app.state.user_store = None
    _ACTIVE_CACHE.pop("u1", None)

    with patch("app.core.security.get_settings", return_value=settings_mock):
        with pytest.raises(HTTPException) as exc_info:
            await dep(request)
    assert exc_info.value.status_code == 403
