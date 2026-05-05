"""Review queue — items where OCR confidence fell below the threshold."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.limiter import limiter
from app.core.security import require_any_role
from app.schemas.ocr import OCRResult
from app.schemas.review import ReviewResolution

router = APIRouter(prefix="/api/v1/review-queue", tags=["review"])


@router.get(
    "",
    response_model=list[OCRResult],
    dependencies=[Depends(require_any_role("admin", "doctor"))],
)
@limiter.limit("100/minute")
async def list_review_items(
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[OCRResult]:
    store = request.app.state.store
    return await store.list_review_queue(offset=offset, limit=limit)


@router.post(
    "/{doc_id}/resolve",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_any_role("admin", "doctor"))],
)
@limiter.limit("10/minute")
async def resolve_review_item(
    request: Request,
    doc_id: UUID,
    resolution: ReviewResolution,
) -> None:
    store = request.app.state.store
    doc = await store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _ = resolution  # corrected fields persistence is a follow-up task
    await store.resolve_review_item(doc_id)
