"""OCR schema validation tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.ocr import ExtractedField, FieldName, OCRResult


def _result(**overrides):
    base = {
        "document_id": uuid4(),
        "processed_at": datetime.now(timezone.utc),
        "ocr_engine": "easyocr-1.7.1",
        "fields": {
            FieldName.PATIENT_NAME: ExtractedField(value="Ion Popescu", confidence=0.98),
            FieldName.MEDICATION: ExtractedField(value="Atorvastatin", confidence=0.92),
            FieldName.EXPIRY_DATE: ExtractedField(value="2026-08-15", confidence=0.99),
        },
        "needs_review": True,
        "low_confidence_fields": [FieldName.MEDICATION],
        "raw_text": "raw text",
        "processing_time_ms": 120,
    }
    base.update(overrides)
    return OCRResult(**base)


def test_valid_result_parses() -> None:
    r = _result()
    assert r.fields[FieldName.PATIENT_NAME].confidence == 0.98


def test_confidence_above_one_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedField(value="x", confidence=1.5)


def test_confidence_below_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedField(value="x", confidence=-0.1)


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractedField(value="x", confidence=0.9, sneaky="payload")  # type: ignore


def test_round_trip_json() -> None:
    r = _result()
    j = r.model_dump_json()
    r2 = OCRResult.model_validate_json(j)
    assert r == r2
