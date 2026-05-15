"""
Storage layer — PostgreSQL via Prisma.

Interface contract (kept identical so routes are unchanged):
  create_document(*, device_id, status) -> DocumentResponse
  get_document(doc_id)                  -> DocumentResponse | None
  attach_ocr_result(doc_id, result)     -> DocumentResponse
  list_review_queue(*, offset, limit)   -> list[OCRResult]
  resolve_review_item(doc_id)           -> None

PHI encryption:
  If a PhiCipher is supplied, attach_ocr_result encrypts patient_name,
  medication, and raw_text BEFORE writing to the DB.  All read paths
  decrypt transparently.  Decryption failures on individual rows are
  logged and emitted as phi.decrypt.error audit events; the row is
  excluded from list results rather than crashing the whole response.

  Encryption happens at the dict level (before Pydantic validation),
  so the encrypted envelopes never pass through OCRResult validators.
"""

import asyncio
import copy
import logging
from datetime import UTC
from uuid import UUID

from app.schemas.ocr import DocumentResponse, DocumentStatus, FieldName, OCRResult
from prisma import Json, Prisma

logger = logging.getLogger(__name__)

# PHI field names as they appear inside the JSON dict's "fields" object.
_PHI_FIELD_NAMES = frozenset({FieldName.PATIENT_NAME.value, FieldName.MEDICATION.value})


# ─── dict-level helpers (no Pydantic validation) ──────────────────────────────


def _encrypt_phi_dict(data: dict, cipher) -> dict:  # type: ignore[no-untyped-def]
    data = copy.deepcopy(data)
    for fname in _PHI_FIELD_NAMES:
        field = data.get("fields", {}).get(fname)
        if field and not cipher.is_encrypted(field.get("value", "")):
            field["value"] = cipher.encrypt(field["value"])
    raw = data.get("raw_text", "")
    if raw and not cipher.is_encrypted(raw):
        data["raw_text"] = cipher.encrypt(raw)
    return data


def _decrypt_phi_dict(data: dict, cipher) -> dict:  # type: ignore[no-untyped-def]
    data = copy.deepcopy(data)
    for fname in _PHI_FIELD_NAMES:
        field = data.get("fields", {}).get(fname)
        if field and cipher.is_encrypted(field.get("value", "")):
            field["value"] = cipher.decrypt(field["value"])
    raw = data.get("raw_text", "")
    if raw and cipher.is_encrypted(raw):
        data["raw_text"] = cipher.decrypt(raw)
    return data


# ─── Prisma row → response ─────────────────────────────────────────────────────


def _decode_ocr(raw: dict, doc_id: str, cipher, audit_sink) -> OCRResult | None:
    """Decrypt (if needed) then validate through Pydantic. Returns None on error."""
    try:
        if cipher is not None:
            raw = _decrypt_phi_dict(raw, cipher)
        return OCRResult.model_validate(raw)
    except Exception as exc:
        logger.error("OCR decode failed for document %s: %s", doc_id, exc)
        if audit_sink is not None:
            from app.core.audit import AuditEvent

            asyncio.create_task(
                audit_sink.write(
                    AuditEvent(
                        action="phi.decrypt.error",
                        outcome="error",
                        resource_type="document",
                        resource_id=doc_id,
                        metadata={"error": str(exc)},
                    )
                )
            )
        return None


def _to_response(doc, cipher=None, audit_sink=None) -> DocumentResponse:  # type: ignore[no-untyped-def]
    doc_status = DocumentStatus(doc.status)

    if doc.ocrResult is None or doc_status == DocumentStatus.QUEUED:
        ocr_result = None
    elif doc_status == DocumentStatus.PENDING_REVIEW:
        ocr_result = "pending_review"
    else:
        ocr_result = _decode_ocr(doc.ocrResult, doc.id, cipher, audit_sink)

    return DocumentResponse(
        id=UUID(doc.id),
        status=doc_status,
        submitted_at=doc.submittedAt.replace(tzinfo=UTC),
        device_id=doc.deviceId,
        ocr_result=ocr_result,
    )


# ─── Store ────────────────────────────────────────────────────────────────────


class PostgresStore:
    def __init__(self, db: Prisma, cipher=None, audit_sink=None) -> None:  # type: ignore[no-untyped-def]
        self._db = db
        self._cipher = cipher
        self._audit_sink = audit_sink

    async def create_document(
        self,
        *,
        device_id: str,
        status: DocumentStatus = DocumentStatus.QUEUED,
    ) -> DocumentResponse:
        doc = await self._db.document.create(data={"status": status.value, "deviceId": device_id})
        return _to_response(doc, self._cipher, self._audit_sink)

    async def get_document(self, doc_id: UUID) -> DocumentResponse | None:
        doc = await self._db.document.find_unique(where={"id": str(doc_id)})
        if doc is None:
            return None
        resp = _to_response(doc, self._cipher, self._audit_sink)
        # Emit phi.decrypt audit event when plaintext PHI is returned.
        if isinstance(resp.ocr_result, OCRResult) and self._audit_sink is not None:
            from app.core.audit import AuditEvent

            asyncio.create_task(
                self._audit_sink.write(
                    AuditEvent(
                        action="phi.decrypt",
                        outcome="success",
                        resource_type="document",
                        resource_id=str(doc_id),
                    )
                )
            )
        return resp

    async def attach_ocr_result(self, doc_id: UUID, result: OCRResult) -> DocumentResponse:
        new_status = (
            DocumentStatus.PENDING_REVIEW if result.needs_review else DocumentStatus.COMPLETED
        )
        data_dict = result.model_dump(mode="json")
        if self._cipher is not None:
            data_dict = _encrypt_phi_dict(data_dict, self._cipher)

        doc = await self._db.document.update(
            where={"id": str(doc_id)},
            data={
                "status": new_status.value,
                "ocrResult": Json(data_dict),
            },
        )
        return _to_response(doc, self._cipher, self._audit_sink)

    async def list_review_queue(self, *, offset: int = 0, limit: int = 50) -> list[OCRResult]:
        docs = await self._db.document.find_many(
            where={"status": DocumentStatus.PENDING_REVIEW.value},
            skip=offset,
            take=limit,
        )
        results = []
        for doc in docs:
            if doc.ocrResult is not None:
                decoded = _decode_ocr(doc.ocrResult, doc.id, self._cipher, self._audit_sink)
                if decoded is not None:
                    results.append(decoded)
        return results

    async def resolve_review_item(self, doc_id: UUID) -> None:
        await self._db.document.update(
            where={"id": str(doc_id)},
            data={"status": DocumentStatus.COMPLETED.value},
        )
