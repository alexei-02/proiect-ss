"""FastAPI app entry point.

Wires up:
    - Settings
    - Body-size middleware (DoS defense layer 1)
    - Rate limiter (DoS defense layer 2)
    - Routers (health, documents, review, metrics)
    - Prisma database connection
    - MQTT consumer (started during lifespan)
    - Result poller (reads OCR result files, writes to DB)
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from prisma import Prisma
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
from app.services.result_poller import poll_results
from app.services.storage import PostgresStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings

    # Database
    db = Prisma()
    await db.connect()
    store = PostgresStore(db)
    app.state.store = store

    # OCR client + result poller
    ocr_client = OCRClient(settings.ocr_queue_dir)
    app.state.ocr_client = ocr_client
    poller_task = asyncio.create_task(poll_results(settings.ocr_queue_dir, store))

    # MQTT consumer
    consumer: MQTTConsumer | None = None
    if settings.env != "test":
        consumer = MQTTConsumer(settings, ocr_client, store)
        try:
            await consumer.start()
        except Exception as exc:  # pragma: no cover
            logger.error("MQTT consumer failed to start: %s", exc)
            consumer = None
    app.state.mqtt_consumer = consumer

    yield

    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass

    if consumer is not None:
        await consumer.stop()

    await db.disconnect()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="Medical OCR API",
        version="0.1.0",
        description="Secure ingestion and retrieval API for medical OCR.",
        lifespan=lifespan,
    )

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
