"""Alerts endpoints — list and acknowledge system alerts."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.limiter import limiter
from app.core.security import require_any_role
from app.schemas.reports import AlertResponse, AlertSeverity

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def _alert_to_response(alert) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        alert_type=alert.alertType,
        severity=AlertSeverity(alert.severity),
        document_id=alert.documentId,
        message=alert.message,
        expires_on=alert.expiresOn,
        acknowledged=alert.acknowledged,
        created_at=alert.createdAt,
    )


@router.get(
    "",
    response_model=list[AlertResponse],
    dependencies=[Depends(require_any_role("admin", "auditor", "doctor"))],
)
@limiter.limit("60/minute")
async def list_alerts(
    request: Request,
    acknowledged: bool = False,
    severity: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[AlertResponse]:
    """List alerts filtered by acknowledgement status and optionally by severity."""
    db = request.app.state.store._db

    where: dict = {"acknowledged": acknowledged}
    if severity is not None:
        where["severity"] = severity

    alerts = await db.alert.find_many(
        where=where,
        skip=offset,
        take=limit,
        order={"createdAt": "desc"},
    )
    return [_alert_to_response(a) for a in alerts]


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertResponse,
    dependencies=[Depends(require_any_role("admin", "doctor"))],
)
@limiter.limit("60/minute")
async def acknowledge_alert(
    request: Request,
    alert_id: int,
) -> AlertResponse:
    """Mark an alert as acknowledged."""
    db = request.app.state.store._db

    alert = await db.alert.find_unique(where={"id": alert_id})
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    updated = await db.alert.update(
        where={"id": alert_id},
        data={"acknowledged": True},
    )
    return _alert_to_response(updated)
