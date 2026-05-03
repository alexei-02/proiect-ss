"""Unit tests for MQTT consumer dispatch logic — no broker required."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.mqtt.consumer import MAX_PAYLOAD_BYTES, MQTTConsumer
from app.schemas.ocr import ExtractedField, FieldName, OCRResult
from app.services.ocr_client import OCRClient
from app.services.storage import _InMemoryStore


def _make_consumer(tmp_path: Path) -> MQTTConsumer:
    settings = Settings(
        ocr_queue_dir=tmp_path / "queue",
        mqtt_tls_ca=tmp_path / "ca.crt",
        mqtt_tls_cert=tmp_path / "cert.crt",
        mqtt_tls_key=tmp_path / "cert.key",
    )
    ocr = OCRClient(settings.ocr_queue_dir)
    store = _InMemoryStore()
    return MQTTConsumer(settings, ocr, store)


@pytest.mark.asyncio
async def test_image_topic_creates_document(tmp_path: Path) -> None:
    c = _make_consumer(tmp_path)
    await c._dispatch("medical/images/dev_001/upload", b"image-bytes")
    # Dispatch was awaited inline; check the side effects.
    queue = list(c.settings.ocr_queue_dir.glob("*.job.json"))
    assert len(queue) == 1


@pytest.mark.asyncio
async def test_unknown_topic_dropped(tmp_path: Path) -> None:
    c = _make_consumer(tmp_path)
    await c._dispatch("evil/path/here", b"data")
    assert list(c.settings.ocr_queue_dir.glob("*.job.json")) == []


@pytest.mark.asyncio
async def test_oversized_payload_dropped(tmp_path: Path) -> None:
    c = _make_consumer(tmp_path)
    huge = b"\x00" * (MAX_PAYLOAD_BYTES + 1)
    await c._dispatch("medical/images/dev_001/upload", huge)
    assert list(c.settings.ocr_queue_dir.glob("*.job.json")) == []


@pytest.mark.asyncio
async def test_empty_payload_dropped(tmp_path: Path) -> None:
    c = _make_consumer(tmp_path)
    await c._dispatch("medical/images/dev_001/upload", b"")
    assert list(c.settings.ocr_queue_dir.glob("*.job.json")) == []


@pytest.mark.asyncio
async def test_valid_result_stored(tmp_path: Path) -> None:
    c = _make_consumer(tmp_path)
    doc = await c.store.create_document(device_id="dev_001")
    result = OCRResult(
        document_id=doc.id,
        processed_at=datetime.now(timezone.utc),
        ocr_engine="easyocr-1.7.1",
        fields={
            FieldName.PATIENT_NAME: ExtractedField(value="X", confidence=0.99),
        },
        needs_review=False,
        low_confidence_fields=[],
        raw_text="",
        processing_time_ms=10,
    )
    await c._dispatch(f"medical/ocr/dev_001/results", result.model_dump_json().encode())
    stored = await c.store.get_document(doc.id)
    assert stored is not None
    assert stored.ocr_result is not None


@pytest.mark.asyncio
async def test_malformed_result_does_not_crash(tmp_path: Path) -> None:
    c = _make_consumer(tmp_path)
    await c._dispatch("medical/ocr/dev_001/results", b"not-valid-json")
    # No exception, no stored doc.
    assert await c.store.list_review_queue() == []


@pytest.mark.asyncio
async def test_device_id_with_path_traversal_rejected(tmp_path: Path) -> None:
    """The regex must reject device IDs containing slashes or dots."""
    c = _make_consumer(tmp_path)
    await c._dispatch("medical/images/../etc/upload", b"data")
    assert list(c.settings.ocr_queue_dir.glob("*.job.json")) == []
