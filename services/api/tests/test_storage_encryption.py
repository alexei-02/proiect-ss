"""Tests for PHI encryption in PostgresStore.

Uses the in-memory PhiCipher fixture (no real DB) to verify:
- encrypt/decrypt helpers work on raw dicts
- _to_response decrypts before building DocumentResponse
- Corrupted envelopes degrade gracefully
"""

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.crypto import EnvKeyProvider, PhiCipher
from app.schemas.ocr import DocumentStatus, ExtractedField, FieldName, OCRResult
from app.services.storage import (
    PostgresStore,
    _decrypt_phi_dict,
    _encrypt_phi_dict,
    _to_response,
)

_KEY = "0" * 64


@pytest.fixture
def cipher() -> PhiCipher:
    return PhiCipher(EnvKeyProvider(_KEY))


def _ocr_dict() -> dict:
    return {
        "document_id": str(uuid4()),
        "processed_at": datetime.now(tz=timezone.utc).isoformat(),
        "ocr_engine": "test-1.0",
        "fields": {
            "patient_name": {"value": "Jane Doe", "confidence": 0.99, "bounding_box": None},
            "medication": {"value": "Aspirin", "confidence": 0.97, "bounding_box": None},
            "expiry_date": {"value": "2027-01-01", "confidence": 0.98, "bounding_box": None},
        },
        "needs_review": False,
        "low_confidence_fields": [],
        "raw_text": "Jane Doe Aspirin 2027-01-01",
        "processing_time_ms": 100,
    }


# ─── dict helpers ─────────────────────────────────────────────────────────────


def test_encrypt_phi_dict_encrypts_phi_fields(cipher: PhiCipher) -> None:
    data = _ocr_dict()
    enc = _encrypt_phi_dict(data, cipher)
    assert PhiCipher.is_encrypted(enc["fields"]["patient_name"]["value"])
    assert PhiCipher.is_encrypted(enc["fields"]["medication"]["value"])
    assert PhiCipher.is_encrypted(enc["raw_text"])


def test_encrypt_phi_dict_leaves_expiry_date_plain(cipher: PhiCipher) -> None:
    data = _ocr_dict()
    enc = _encrypt_phi_dict(data, cipher)
    assert enc["fields"]["expiry_date"]["value"] == "2027-01-01"


def test_encrypt_phi_dict_idempotent(cipher: PhiCipher) -> None:
    """Encrypting an already-encrypted value must not double-encrypt."""
    data = _ocr_dict()
    enc1 = _encrypt_phi_dict(data, cipher)
    enc2 = _encrypt_phi_dict(enc1, cipher)
    # Decrypting enc2 should still yield the original value.
    dec = _decrypt_phi_dict(enc2, cipher)
    assert dec["fields"]["patient_name"]["value"] == "Jane Doe"


def test_decrypt_phi_dict_round_trip(cipher: PhiCipher) -> None:
    data = _ocr_dict()
    enc = _encrypt_phi_dict(data, cipher)
    dec = _decrypt_phi_dict(enc, cipher)
    assert dec["fields"]["patient_name"]["value"] == "Jane Doe"
    assert dec["fields"]["medication"]["value"] == "Aspirin"
    assert dec["raw_text"] == "Jane Doe Aspirin 2027-01-01"


def test_encrypt_phi_dict_does_not_mutate_input(cipher: PhiCipher) -> None:
    data = _ocr_dict()
    original_name = data["fields"]["patient_name"]["value"]
    _encrypt_phi_dict(data, cipher)
    assert data["fields"]["patient_name"]["value"] == original_name


# ─── _to_response integration ─────────────────────────────────────────────────


def _make_prisma_row(status: str = "completed", ocr_result=None):
    row = MagicMock()
    row.id = str(uuid4())
    row.status = status
    row.submittedAt = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    row.deviceId = "dev-001"
    row.ocrResult = ocr_result
    return row


def test_to_response_decrypts_phi(cipher: PhiCipher) -> None:
    data = _ocr_dict()
    enc = _encrypt_phi_dict(data, cipher)
    row = _make_prisma_row(ocr_result=enc)
    resp = _to_response(row, cipher=cipher)
    assert isinstance(resp.ocr_result, OCRResult)
    assert resp.ocr_result.fields[FieldName.PATIENT_NAME].value == "Jane Doe"


def test_to_response_no_cipher_passes_through() -> None:
    data = _ocr_dict()
    row = _make_prisma_row(ocr_result=data)
    resp = _to_response(row, cipher=None)
    assert isinstance(resp.ocr_result, OCRResult)


def test_to_response_queued_has_no_ocr_result() -> None:
    row = _make_prisma_row(status="queued", ocr_result=None)
    resp = _to_response(row)
    assert resp.ocr_result is None


def test_to_response_pending_review_returns_sentinel() -> None:
    row = _make_prisma_row(status="pending_review", ocr_result={"dummy": True})
    resp = _to_response(row)
    assert resp.ocr_result == "pending_review"


def test_to_response_corrupted_envelope_returns_none(cipher: PhiCipher) -> None:
    """A corrupted ciphertext must not crash the whole response."""
    data = _ocr_dict()
    enc = _encrypt_phi_dict(data, cipher)
    enc["fields"]["patient_name"]["value"] = "enc:v1:AAAA"  # invalid
    row = _make_prisma_row(ocr_result=enc)
    resp = _to_response(row, cipher=cipher)
    # The OCR result should be None (decode failed), not raise
    assert resp.ocr_result is None


# ─── PostgresStore attach/get round-trip (mocked Prisma) ──────────────────────


def _mock_prisma(stored_docs: dict):
    db = MagicMock()

    async def create(data):
        doc_id = str(uuid4())
        doc = MagicMock()
        doc.id = doc_id
        doc.status = data["status"]
        doc.submittedAt = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        doc.deviceId = data["deviceId"]
        doc.ocrResult = None
        stored_docs[doc_id] = doc
        return doc

    async def update(where, data):
        doc = stored_docs[where["id"]]
        if "status" in data:
            doc.status = data["status"]
        if "ocrResult" in data:
            doc.ocrResult = data["ocrResult"]
        return doc

    async def find_unique(where):
        return stored_docs.get(where["id"])

    db.document.create = create
    db.document.update = update
    db.document.find_unique = find_unique
    return db


async def test_store_encrypts_on_write_and_decrypts_on_read(cipher: PhiCipher) -> None:
    stored: dict = {}
    db = _mock_prisma(stored)
    store = PostgresStore(db, cipher=cipher)

    doc = await store.create_document(device_id="dev-001")
    doc_id = doc.id

    ocr = OCRResult(
        document_id=doc_id,
        processed_at=datetime.now(tz=timezone.utc),
        ocr_engine="test-1.0",
        fields={
            FieldName.PATIENT_NAME: ExtractedField(value="Jane Doe", confidence=0.99),
            FieldName.MEDICATION: ExtractedField(value="Aspirin", confidence=0.97),
            FieldName.EXPIRY_DATE: ExtractedField(value="2027-01-01", confidence=0.98),
        },
        needs_review=False,
        raw_text="Jane Doe Aspirin 2027-01-01",
        processing_time_ms=100,
    )
    await store.attach_ocr_result(doc_id, ocr)

    # Raw value in "DB" must be encrypted
    raw_stored = stored[str(doc_id)].ocrResult
    assert PhiCipher.is_encrypted(raw_stored["fields"]["patient_name"]["value"])
    assert "Jane Doe" not in str(raw_stored)

    # Read back via store returns plaintext
    resp = await store.get_document(doc_id)
    assert isinstance(resp.ocr_result, OCRResult)
    assert resp.ocr_result.fields[FieldName.PATIENT_NAME].value == "Jane Doe"
