"""System performance metrics — feeds the reports epic."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request

from app.core.limiter import limiter
from app.core.security import require_any_role
from prisma import Prisma

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get(
    "/ocr",
    dependencies=[Depends(require_any_role("admin", "auditor"))],
)
@limiter.limit("60/minute")
async def ocr_metrics(request: Request) -> dict[str, float | int]:
    """Real OCR processing metrics aggregated from the database."""
    store = request.app.state.store
    db: Prisma = store._db

    cutoff = datetime.now(UTC) - timedelta(hours=24)

    queue_depth = await db.document.count(where={"status": "pending_review"})
    completed_24h = await db.document.count(
        where={"status": "completed", "submittedAt": {"gte": cutoff}}
    )

    # Use raw query for JSONB percentile — parameterised, no user input in SQL
    rows = await db.query_raw(
        """
        SELECT
          COALESCE(percentile_cont(0.50) WITHIN GROUP
            (ORDER BY (ocr_result->>'processing_time_ms')::float), 0) AS p50,
          COALESCE(percentile_cont(0.95) WITHIN GROUP
            (ORDER BY (ocr_result->>'processing_time_ms')::float), 0) AS p95,
          COUNT(*) AS total
        FROM documents
        WHERE status IN ('completed','pending_review')
          AND submitted_at >= $1::timestamp
          AND ocr_result->>'processing_time_ms' IS NOT NULL
        """,
        cutoff,
    )
    p50 = float(rows[0]["p50"]) if rows else 0.0
    p95 = float(rows[0]["p95"]) if rows else 0.0

    return {
        "review_queue_depth": queue_depth,
        "completed_last_24h": completed_24h,
        "p50_latency_ms": round(p50, 1),
        "p95_latency_ms": round(p95, 1),
    }
