"""System performance metrics — feeds the reports epic."""

from fastapi import APIRouter, Depends, Request

from app.core.limiter import limiter
from app.core.security import require_any_role

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get(
    "/ocr",
    dependencies=[Depends(require_any_role("admin", "auditor"))],
)
@limiter.limit("60/minute")
async def ocr_metrics(request: Request) -> dict[str, float | int]:
    """OCR processing metrics. Real aggregations land in the reports epic."""
    store = request.app.state.store
    review = await store.list_review_queue(offset=0, limit=10000)
    return {
        "review_queue_depth": len(review),
        "p50_latency_ms": 0,
        "p95_latency_ms": 0,
        "success_rate": 1.0,
    }
