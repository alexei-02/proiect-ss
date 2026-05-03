"""Verify the OCR worker's schema is byte-compatible with the API service.

Since the schema is duplicated across two services for now (rather than
shared via a common package), this test guards against drift. If it
fails, either:
  - Update both copies in lockstep, or
  - Extract them into a shared package.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

# Add the API service to the path so we can import its schema for comparison.
API_SCHEMAS_PATH = Path(__file__).parent.parent.parent / "api"
sys.path.insert(0, str(API_SCHEMAS_PATH))


def test_ocr_result_round_trips_between_services() -> None:
    """Serialize from the OCR worker side, deserialize on the API side."""
    from app.core.schemas import ExtractedField, FieldName, OCRResult as WorkerResult

    try:
        from app.schemas.ocr import OCRResult as APIResult
    except ImportError:
        pytest.skip("API service not on path — run from monorepo root")

    worker_result = WorkerResult(
        document_id=uuid4(),
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

    serialized = worker_result.model_dump_json()
    api_result = APIResult.model_validate_json(serialized)

    assert str(api_result.document_id) == str(worker_result.document_id)
    assert api_result.needs_review == worker_result.needs_review
