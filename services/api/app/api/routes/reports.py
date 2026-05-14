"""Reports endpoints — request, check status, and download CSV reports."""

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.audit import AuditEvent
from app.core.limiter import limiter
from app.core.security import User, require_any_role
from app.schemas.reports import ReportRequest, ReportStatusResponse, ReportType
from app.services.report_runner import run_report
from prisma import Json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _report_to_response(report, base_url: str) -> ReportStatusResponse:
    download_url: str | None = None
    if report.status == "ready":
        download_url = f"{base_url}/api/v1/reports/{report.id}/download"
    return ReportStatusResponse(
        id=UUID(report.id),
        report_type=ReportType(report.reportType),
        status=report.status,  # type: ignore[arg-type]
        created_at=report.createdAt,
        completed_at=report.completedAt,
        error_msg=report.errorMsg,
        download_url=download_url,
    )


async def _run_report_background(
    report_id: UUID,
    report_type: ReportType,
    params: dict,
    app,  # type: ignore[no-untyped-def]
) -> None:
    """Background task: generate the report and update status."""
    store = app.state.store
    db = store._db
    cipher = store._cipher
    queue_dir: Path = app.state.ocr_client.queue_dir
    try:
        await run_report(report_id, report_type, params, db, cipher, queue_dir)
    except Exception:
        # run_report already updates DB status to "failed" — log here for
        # visibility, since this is the background task's top-level catch.
        logger.exception("Background report generation failed (id=%s)", report_id)


@router.post(
    "",
    response_model=ReportStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_any_role("admin", "auditor"))],
)
@limiter.limit("10/minute")
async def create_report(
    request: Request,
    body: ReportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_any_role("admin", "auditor")),
) -> ReportStatusResponse:
    """Queue a new report for generation."""
    db = request.app.state.store._db

    report = await db.report.create(
        data={
            "reportType": body.report_type.value,
            "user": {"connect": {"id": current_user.id}},
            "status": "queued",
            "params": Json(body.params or {}),
        }
    )

    # Emit audit event
    audit_sink = getattr(request.app.state, "audit_sink", None)
    if audit_sink is not None:
        import asyncio

        asyncio.create_task(
            audit_sink.write(
                AuditEvent(
                    action="report.create",
                    outcome="success",
                    resource_type="report",
                    resource_id=report.id,
                    user_id=current_user.id,
                    username=current_user.username,
                    metadata={"report_type": body.report_type.value},
                )
            )
        )

    background_tasks.add_task(
        _run_report_background,
        UUID(report.id),
        body.report_type,
        body.params,
        request.app,
    )

    base_url = str(request.base_url).rstrip("/")
    return _report_to_response(report, base_url)


@router.get(
    "/{report_id}/status",
    response_model=ReportStatusResponse,
    dependencies=[Depends(require_any_role("admin", "auditor"))],
)
@limiter.limit("60/minute")
async def get_report_status(
    request: Request,
    report_id: UUID,
) -> ReportStatusResponse:
    """Return current status of a report."""
    db = request.app.state.store._db
    report = await db.report.find_unique(where={"id": str(report_id)})
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    base_url = str(request.base_url).rstrip("/")
    return _report_to_response(report, base_url)


@router.get(
    "/{report_id}/download",
    dependencies=[Depends(require_any_role("admin", "auditor"))],
)
@limiter.limit("60/minute")
async def download_report(
    request: Request,
    report_id: UUID,
    current_user: User = Depends(require_any_role("admin", "auditor")),
) -> StreamingResponse:
    """Stream the completed CSV report file."""
    db = request.app.state.store._db
    report = await db.report.find_unique(where={"id": str(report_id)})

    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    if report.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report not ready (status: {report.status})",
        )

    if not report.resultPath:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report file path missing"
        )

    result_path = Path(report.resultPath)
    if not result_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found on disk"
        )

    # Emit audit event for PHI-touching download
    audit_sink = getattr(request.app.state, "audit_sink", None)
    if audit_sink is not None:
        import asyncio

        asyncio.create_task(
            audit_sink.write(
                AuditEvent(
                    action="report.download",
                    outcome="success",
                    resource_type="report",
                    resource_id=str(report_id),
                    user_id=current_user.id,
                    username=current_user.username,
                    metadata={"report_type": report.reportType},
                )
            )
        )

    def _iter_file():
        with open(result_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    filename = f"report_{report_id}.csv"
    return StreamingResponse(
        _iter_file(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
