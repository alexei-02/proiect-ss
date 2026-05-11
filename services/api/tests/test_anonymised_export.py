"""Tests for the anonymised export generator (T18)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.ocr import DocumentStatus


def _make_doc_row_with_ocr(doc_id=None, patient_name="John Doe", medication="Aspirin"):
    """Build a Prisma-like document row with a full OCR result."""
    import json

    row = MagicMock()
    row.id = str(doc_id or uuid4())
    row.status = "completed"
    row.submittedAt = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    row.deviceId = "dev-001"
    row.ocrResult = {
        "document_id": row.id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "ocr_engine": "mock-1.0",
        "fields": {
            "patient_name": {"value": patient_name, "confidence": 0.98},
            "medication": {"value": medication, "confidence": 0.97},
            "expiry_date": {"value": "2026-12-31", "confidence": 0.99},
        },
        "needs_review": False,
        "low_confidence_fields": [],
        "raw_text": "some raw text",
        "processing_time_ms": 123,
    }
    return row


async def test_generate_anonymised_export_masks_phi():
    """generate_anonymised_export yields dicts with '***' for PHI fields."""
    from app.services.report_runner import generate_anonymised_export

    doc = _make_doc_row_with_ocr(patient_name="Jane Smith", medication="Warfarin")
    db = MagicMock()
    db.document.find_many = AsyncMock(return_value=[doc])

    rows = []
    async for row in generate_anonymised_export({}, db, cipher=None):
        rows.append(row)

    assert len(rows) == 1
    row = rows[0]
    assert row["field_patient_name_value"] == "***"
    assert row["field_medication_value"] == "***"


async def test_generate_anonymised_export_preserves_non_phi():
    """generate_anonymised_export preserves expiry_date and confidence scores."""
    from app.services.report_runner import generate_anonymised_export

    doc = _make_doc_row_with_ocr()
    db = MagicMock()
    db.document.find_many = AsyncMock(return_value=[doc])

    rows = []
    async for row in generate_anonymised_export({}, db, cipher=None):
        rows.append(row)

    assert len(rows) == 1
    row = rows[0]
    # Expiry date is not PHI and should be preserved
    assert row.get("field_expiry_date_value") == "2026-12-31"
    # Confidence scores must be present
    assert "field_patient_name_confidence" in row
    assert row["field_patient_name_confidence"] == 0.98


async def test_generate_anonymised_export_pagination():
    """generate_anonymised_export uses cursor-based pagination (batch 500)."""
    from app.services.report_runner import generate_anonymised_export

    doc = _make_doc_row_with_ocr()
    db = MagicMock()
    # First batch: 500 docs; second batch: empty (signals end)
    db.document.find_many = AsyncMock(
        side_effect=[[doc] * 500, [doc] * 3, []]
    )

    rows = []
    async for row in generate_anonymised_export({}, db, cipher=None):
        rows.append(row)

    # Should have iterated 500 + 3 = 503 rows
    assert len(rows) == 503
    # find_many short-circuits on a partial batch (<500), so 2 calls is correct.
    assert db.document.find_many.call_count == 2


async def test_generate_anonymised_export_queued_doc_no_fields():
    """Queued documents (no OCR result) are exported with basic metadata only."""
    from app.services.report_runner import generate_anonymised_export

    doc = MagicMock()
    doc.id = str(uuid4())
    doc.status = "queued"
    doc.submittedAt = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    doc.deviceId = "dev-002"
    doc.ocrResult = None

    db = MagicMock()
    db.document.find_many = AsyncMock(return_value=[doc])

    rows = []
    async for row in generate_anonymised_export({}, db, cipher=None):
        rows.append(row)

    assert len(rows) == 1
    assert rows[0]["status"] == "queued"
    # No PHI fields present
    assert "field_patient_name_value" not in rows[0]
