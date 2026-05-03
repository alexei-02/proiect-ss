"""
Storage layer (in-memory stub).

THIS IS A STUB. The DB epic owner replaces it with SQLAlchemy + Postgres.
The interface (function names, arguments, return types) MUST stay the
same so the API routes don't change.

Contract for the DB epic implementer:
-------------------------------------
- All `*_async` functions stay async (the routes await them).
- Fields flagged as PHI in docs/PHI_FIELDS.md are encrypted at rest.
- Listing functions support pagination via (offset, limit).
"""

from datetime import datetime, timezone
from threading import Lock
from uuid import UUID, uuid4

from app.schemas.ocr import DocumentResponse, DocumentStatus, OCRResult


class _InMemoryStore:
    """Thread-safe in-memory replacement for the real DB."""

    def __init__(self) -> None:
        self._docs: dict[UUID, DocumentResponse] = {}
        self._review_queue: dict[UUID, OCRResult] = {}
        self._lock = Lock()

    async def create_document(
        self, *, device_id: str, status: DocumentStatus = DocumentStatus.QUEUED
    ) -> DocumentResponse:
        doc = DocumentResponse(
            id=uuid4(),
            status=status,
            submitted_at=datetime.now(timezone.utc),
            device_id=device_id,
        )
        with self._lock:
            self._docs[doc.id] = doc
        return doc

    async def get_document(self, doc_id: UUID) -> DocumentResponse | None:
        with self._lock:
            return self._docs.get(doc_id)

    async def attach_ocr_result(self, doc_id: UUID, result: OCRResult) -> DocumentResponse:
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc is None:
                raise KeyError(f"Document {doc_id} not found")
            new_status = (
                DocumentStatus.PENDING_REVIEW
                if result.needs_review
                else DocumentStatus.COMPLETED
            )
            updated = doc.model_copy(update={"ocr_result": result, "status": new_status})
            self._docs[doc_id] = updated
            if result.needs_review:
                self._review_queue[doc_id] = result
            return updated

    async def list_review_queue(
        self, *, offset: int = 0, limit: int = 50
    ) -> list[OCRResult]:
        with self._lock:
            items = list(self._review_queue.values())
        return items[offset : offset + limit]

    async def resolve_review_item(self, doc_id: UUID) -> None:
        with self._lock:
            self._review_queue.pop(doc_id, None)
            doc = self._docs.get(doc_id)
            if doc is not None:
                self._docs[doc_id] = doc.model_copy(
                    update={"status": DocumentStatus.COMPLETED}
                )


# Module-level singleton (the DB epic replaces this with a real connection pool).
_store = _InMemoryStore()


def get_store() -> _InMemoryStore:
    return _store
