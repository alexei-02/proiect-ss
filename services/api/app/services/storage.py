"""
Storage layer — PostgreSQL via Prisma.

Interface contract (kept identical to the original stub so routes are unchanged):
  create_document(*, device_id, status) -> DocumentResponse
  get_document(doc_id)                  -> DocumentResponse | None
  attach_ocr_result(doc_id, result)     -> DocumentResponse
  list_review_queue(*, offset, limit)   -> list[OCRResult]
  resolve_review_item(doc_id)           -> None

PHI fields (patient_name, medication, raw_text) must be encrypted at rest
before this module is used in production — see docs/PHI_FIELDS.md.
"""

from datetime import datetime, timezone
from uuid import UUID

from prisma import Json, Prisma

from app.schemas.ocr import DocumentResponse, DocumentStatus, OCRResult


def _to_response(doc) -> DocumentResponse:  # type: ignore[no-untyped-def]
    """Map a Prisma Document row to the API response model."""
    status = DocumentStatus(doc.status)

    if doc.ocrResult is None or status == DocumentStatus.QUEUED:
        ocr_result = None
    elif status == DocumentStatus.PENDING_REVIEW:
        ocr_result = "pending_review"
    else:
        ocr_result = OCRResult.model_validate(doc.ocrResult)

    return DocumentResponse(
        id=UUID(doc.id),
        status=status,
        submitted_at=doc.submittedAt.replace(tzinfo=timezone.utc),
        device_id=doc.deviceId,
        ocr_result=ocr_result,
    )


class PostgresStore:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def create_document(
        self, *, device_id: str, status: DocumentStatus = DocumentStatus.QUEUED
    ) -> DocumentResponse:
        doc = await self._db.document.create(
            data={"status": status.value, "deviceId": device_id}
        )
        return _to_response(doc)

    async def get_document(self, doc_id: UUID) -> DocumentResponse | None:
        doc = await self._db.document.find_unique(where={"id": str(doc_id)})
        return _to_response(doc) if doc is not None else None

    async def attach_ocr_result(self, doc_id: UUID, result: OCRResult) -> DocumentResponse:
        new_status = (
            DocumentStatus.PENDING_REVIEW if result.needs_review else DocumentStatus.COMPLETED
        )
        doc = await self._db.document.update(
            where={"id": str(doc_id)},
            data={
                "status": new_status.value,
                "ocrResult": Json(result.model_dump(mode="json")),
            },
        )
        return _to_response(doc)

    async def list_review_queue(
        self, *, offset: int = 0, limit: int = 50
    ) -> list[OCRResult]:
        docs = await self._db.document.find_many(
            where={"status": DocumentStatus.PENDING_REVIEW.value},
            skip=offset,
            take=limit,
        )
        results = []
        for doc in docs:
            if doc.ocrResult is not None:
                results.append(OCRResult.model_validate(doc.ocrResult))
        return results

    async def resolve_review_item(self, doc_id: UUID) -> None:
        await self._db.document.update(
            where={"id": str(doc_id)},
            data={"status": DocumentStatus.COMPLETED.value},
        )
