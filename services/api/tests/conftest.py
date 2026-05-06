"""Shared pytest fixtures for API tests."""

import os
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Fixed test keys — never use outside tests.
_TEST_JWT_SECRET = "test-jwt-secret-for-pytest-minimum-256-bits-long-xxxxxxxxxxxx"  # noqa: S105
_TEST_PHI_KEY = "0" * 64  # 32 zero bytes, hex-encoded


@pytest.fixture(autouse=True)
def _test_env(tmp_path: Path) -> Iterator[None]:
    """Force ENV=test and inject required secrets so the app boots cleanly."""
    queue_dir = tmp_path / "ocr-queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    overrides = {
        "ENV": "test",
        "OCR_QUEUE_DIR": str(queue_dir),
        "JWT_SECRET": _TEST_JWT_SECRET,
        "PHI_MASTER_KEY": _TEST_PHI_KEY,
        "DEV_AUTH_BYPASS": "true",  # existing tests work without Bearer tokens
    }
    old = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)

    from app.core.config import get_settings
    from app.core.security import _ACTIVE_CACHE
    get_settings.cache_clear()
    _ACTIVE_CACHE.clear()
    yield
    _ACTIVE_CACHE.clear()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()


@pytest.fixture
def mock_db() -> MagicMock:
    """A Prisma mock with all table accessors pre-stubbed as AsyncMocks."""
    db = MagicMock()
    db.connect = AsyncMock()
    db.disconnect = AsyncMock()

    # document
    db.document.create = AsyncMock(return_value=_make_doc_row())
    db.document.update = AsyncMock(return_value=_make_doc_row())
    db.document.find_unique = AsyncMock(return_value=None)
    db.document.find_many = AsyncMock(return_value=[])

    # user — default: return an active stub so is_active checks pass.
    # Individual tests can override with db.user.find_unique.return_value = ...
    _active_user = MagicMock()
    _active_user.id = "test-user"
    _active_user.username = "testuser"
    _active_user.passwordHash = ""
    _active_user.roles = ["admin", "doctor"]
    _active_user.isActive = True
    _active_user.createdAt = None
    _active_user.lastLoginAt = None
    db.user.find_unique = AsyncMock(return_value=_active_user)
    db.user.create = AsyncMock()
    db.user.update = AsyncMock()
    db.user.count = AsyncMock(return_value=0)

    # refresh_token
    db.refreshtoken.create = AsyncMock()
    db.refreshtoken.find_unique = AsyncMock(return_value=None)
    db.refreshtoken.update_many = AsyncMock()
    db.refreshtoken.delete_many = AsyncMock(return_value=0)

    # audit_log
    db.auditlog.create = AsyncMock()
    db.auditlog.find_many = AsyncMock(return_value=[])

    return db


def _make_doc_row():
    from datetime import datetime, timezone
    from uuid import uuid4
    row = MagicMock()
    row.id = str(uuid4())
    row.status = "queued"
    row.submittedAt = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    row.deviceId = "dev-001"
    row.ocrResult = None
    return row


@pytest.fixture
def client(mock_db: MagicMock) -> Iterator[TestClient]:
    """TestClient with Prisma replaced by mock_db (no real DB needed)."""
    with patch("app.main.Prisma", return_value=mock_db):
        from app.main import create_app
        app = create_app()
        with TestClient(app) as c:
            yield c


@pytest.fixture
def auth_as():
    """Factory: return an Authorization header dict for the given roles.

    Usage::
        headers = auth_as(["doctor"], user_id="u1")
        client.get("/api/v1/documents/...", headers=headers)
    """
    from app.core.jwt_utils import encode_access

    def _factory(roles: list[str], user_id: str = "test-user", username: str = "testuser") -> dict:
        token, _ = encode_access(user_id, username, roles)
        return {"Authorization": f"Bearer {token}"}

    return _factory


@pytest.fixture
def phi_cipher():
    """A PhiCipher with a fixed test key."""
    from app.core.crypto import EnvKeyProvider, PhiCipher
    return PhiCipher(EnvKeyProvider(_TEST_PHI_KEY))


@pytest.fixture
def in_memory_audit_sink():
    """An audit sink that captures events in memory for assertions."""
    from app.core.audit import AuditEvent

    class MemorySink:
        def __init__(self) -> None:
            self.events: list[AuditEvent] = []

        async def write(self, event: AuditEvent) -> None:
            self.events.append(event)

    return MemorySink()
