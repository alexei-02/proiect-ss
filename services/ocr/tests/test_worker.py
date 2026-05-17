"""End-to-end worker test using the mock OCR engine."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from app.core.engine import MockOCREngine
from app.core.schemas import OCRResult


@pytest.fixture(autouse=True)
def _mock_ocr() -> None:
    os.environ["MOCK_OCR"] = "1"
    yield
    os.environ.pop("MOCK_OCR", None)


def _create_test_image(path: Path) -> None:
    Image.new("RGB", (200, 100), color=(255, 255, 255)).save(path, "PNG")


@pytest.mark.asyncio
async def test_worker_processes_job_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """Drop a job in the queue dir and verify a result file appears."""
    monkeypatch.setenv("OCR_QUEUE_DIR", str(tmp_path))

    # Reset the cached settings so the new env is picked up.
    from app.core import config as cfg_module
    cfg = cfg_module.get_settings()
    assert str(cfg.queue_dir) == str(tmp_path)

    from app import worker

    document_id = uuid4()
    image_path = tmp_path / f"{document_id}.bin"
    _create_test_image(image_path)

    job_path = tmp_path / f"{document_id}.job.json"
    job_path.write_text(
        json.dumps({
            "document_id": str(document_id),
            "image_path": str(image_path),
            "source_device": "dev_001",
        })
    )

    await worker.process_job(job_path, MockOCREngine())

    # Result should be written, job + image cleaned up.
    result_path = tmp_path / f"{document_id}.result.json"
    assert result_path.exists()
    assert not job_path.exists()
    assert not image_path.exists()

    result = OCRResult.model_validate_json(result_path.read_text())
    assert result.document_id == document_id
    # MockOCREngine returns one block at 0.92 < 0.95 threshold, so review expected.
    assert result.needs_review is True
    assert result.processing_time_ms >= 0


@pytest.mark.asyncio
async def test_worker_handles_missing_image(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OCR_QUEUE_DIR", str(tmp_path))
    from app.core import config as cfg_module
    cfg_module.get_settings()
    from app import worker

    document_id = uuid4()
    job_path = tmp_path / f"{document_id}.job.json"
    job_path.write_text(json.dumps({
        "document_id": str(document_id),
        "image_path": str(tmp_path / "nonexistent.bin"),
        "source_device": "dev_001",
    }))

    await worker.process_job(job_path, MockOCREngine())

    # Worker should still emit a "failed" result rather than crashing.
    result_path = tmp_path / f"{document_id}.result.json"
    assert result_path.exists()
    result = OCRResult.model_validate_json(result_path.read_text())
    assert result.needs_review is True
    assert "validation_error" in result.raw_text


@pytest.mark.asyncio
async def test_worker_handles_malformed_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OCR_QUEUE_DIR", str(tmp_path))
    from app.core import config as cfg_module
    cfg_module.get_settings()
    from app import worker

    job_path = tmp_path / "bad.job.json"
    job_path.write_text("{not valid json")

    await worker.process_job(job_path, MockOCREngine())

    # Should be cleaned up without raising.
    assert not job_path.exists()
