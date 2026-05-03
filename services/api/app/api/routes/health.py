"""Health & readiness probes."""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — dependencies are reachable."""
    ocr_client = request.app.state.ocr_client
    ocr_ok = await ocr_client.health()
    # MQTT readiness is currently best-effort: paho doesn't expose a clean
    # "are we connected" boolean across reconnects.
    mqtt_ok = request.app.state.mqtt_consumer is not None

    body = {"status": "ready" if (ocr_ok and mqtt_ok) else "degraded",
            "checks": {"ocr": ocr_ok, "mqtt": mqtt_ok}}
    code = status.HTTP_200_OK if (ocr_ok and mqtt_ok) else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=body)
