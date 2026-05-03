"""FastAPI app entry point.

Wires up:
    - Settings
    - Body-size middleware (DoS defense layer 1)
    - Rate limiter (DoS defense layer 2)
    - Routers (health, documents, review, metrics)
    - MQTT consumer (started during lifespan)
    - OCR client + storage (in-memory until DB epic lands)
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.routes import documents, health, metrics, review
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.middleware import BodySizeLimitMiddleware
from app.mqtt.consumer import MQTTConsumer
from app.services.ocr_client import OCRClient
from app.services.storage import get_store

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start MQTT consumer on boot, shut it down on exit."""
    settings = get_settings()
    app.state.settings = settings
    app.state.store = get_store()
    app.state.ocr_client = OCRClient(settings.ocr_queue_dir)

    consumer: MQTTConsumer | None = None
    if settings.env != "test":
        # Don't try to connect to a broker during unit tests.
        consumer = MQTTConsumer(settings, app.state.ocr_client, app.state.store)
        try:
            await consumer.start()
        except Exception as exc:  # pragma: no cover — boot-time only
            logger.error("MQTT consumer failed to start: %s", exc)
            consumer = None
    app.state.mqtt_consumer = consumer

    yield

    if consumer is not None:
        await consumer.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="Medical OCR API",
        version="0.1.0",
        description="Secure ingestion and retrieval API for medical OCR.",
        lifespan=lifespan,
    )

    # Order matters — body-size first, then rate limiter.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_upload=settings.max_upload_size_bytes,
        max_json=settings.max_json_body_bytes,
    )
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc.detail)})

    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(review.router)
    app.include_router(metrics.router)

    return app


app = create_app()
