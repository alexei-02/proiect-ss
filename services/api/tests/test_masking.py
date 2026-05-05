"""Tests for app.services.masking — PHI field redaction."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.ocr import DocumentResponse, DocumentStatus, ExtractedField, FieldName, OCRResult
from app.services.masking import _REDACTED, mask_phi


def _make_doc(with_ocr: bool = True) -> DocumentResponse:
    ocr: OCRResult | str | None = None
    if with_ocr:
        ocr = OCRResult(
            document_id=uuid4(),
            processed_at=datetime.now(tz=timezone.utc),
            ocr_engine="test-engine",
            fields={
                FieldName.PATIENT_NAME: ExtractedField(value="Jane Doe", confidence=0.99),
                FieldName.MEDICATION: ExtractedField(value="Aspirin 100mg", confidence=0.97),
                FieldName.EXPIRY_DATE: ExtractedField(value="2027-01-01", confidence=0.98),
            },
            needs_review=False,
            raw_text="Jane Doe Aspirin 100mg 2027-01-01",
            processing_time_ms=120,
        )
    return DocumentResponse(
        id=uuid4(),
        status=DocumentStatus.COMPLETED,
        submitted_at=datetime.now(tz=timezone.utc),
        device_id="dev-001",
        ocr_result=ocr,
    )


def test_patient_name_masked() -> None:
    masked = mask_phi(_make_doc())
    assert isinstance(masked.ocr_result, OCRResult)
    assert masked.ocr_result.fields[FieldName.PATIENT_NAME].value == _REDACTED


def test_medication_masked() -> None:
    masked = mask_phi(_make_doc())
    assert isinstance(masked.ocr_result, OCRResult)
    assert masked.ocr_result.fields[FieldName.MEDICATION].value == _REDACTED


def test_raw_text_masked() -> None:
    masked = mask_phi(_make_doc())
    assert isinstance(masked.ocr_result, OCRResult)
    assert masked.ocr_result.raw_text == _REDACTED


def test_expiry_date_preserved() -> None:
    masked = mask_phi(_make_doc())
    assert isinstance(masked.ocr_result, OCRResult)
    assert masked.ocr_result.fields[FieldName.EXPIRY_DATE].value == "2027-01-01"


def test_confidence_scores_preserved() -> None:
    original = _make_doc()
    masked = mask_phi(original)
    assert isinstance(masked.ocr_result, OCRResult)
    assert isinstance(original.ocr_result, OCRResult)
    for fname in (FieldName.PATIENT_NAME, FieldName.MEDICATION, FieldName.EXPIRY_DATE):
        assert (
            masked.ocr_result.fields[fname].confidence
            == original.ocr_result.fields[fname].confidence
        )


def test_other_document_fields_preserved() -> None:
    original = _make_doc()
    masked = mask_phi(original)
    assert masked.id == original.id
    assert masked.status == original.status
    assert masked.submitted_at == original.submitted_at
    assert masked.device_id == original.device_id


def test_none_ocr_result_unchanged() -> None:
    doc = _make_doc(with_ocr=False)
    assert mask_phi(doc) is doc


def test_pending_review_sentinel_unchanged() -> None:
    doc = _make_doc(with_ocr=False)
    doc = DocumentResponse(
        id=doc.id,
        status=DocumentStatus.PENDING_REVIEW,
        submitted_at=doc.submitted_at,
        device_id=doc.device_id,
        ocr_result="pending_review",
    )
    assert mask_phi(doc) is doc
