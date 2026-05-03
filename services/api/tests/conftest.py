"""Shared pytest fixtures for API tests."""

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _test_env(tmp_path: Path) -> Iterator[None]:
    """Force ENV=test so the app skips MQTT setup during tests."""
    queue_dir = tmp_path / "ocr-queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    old = {}
    for k, v in {"ENV": "test", "OCR_QUEUE_DIR": str(queue_dir)}.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    # Clear settings cache so new env is picked up.
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
