"""FastAPI app entry point.

Wires up:
    - Settings
    - Body-size middleware (DoS defense layer 1)
    - Rate limiter (DoS defense layer 2)
    - Audit middleware (PHI-touching request logging)
    - Routers: health, documents, review, metrics, auth, audit-log
    - Prisma database connection
    - PhiCipher (AES-256-GCM for PHI fields)
    - UserStore, RefreshTokenStore, PrismaAuditSink
    - PostgresStore (with cipher + audit sink)
    - MQTT consumer (started during lifespan)
    - Result poller (reads OCR result files, writes to DB)
    - Hourly refresh-token cleanup task
    - Production TLS startup guard
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.routes import (
    admin_users,
    alerts,
    audit_log,
    auth,
    documents,
    health,
    metrics,
    reports,
    review,
)
from app.core.audit import AuditMiddleware, PrismaAuditSink
from app.core.config import get_settings
from app.core.crypto import EnvKeyProvider, PhiCipher
from app.core.limiter import limiter
from app.core.middleware import BodySizeLimitMiddleware
from app.mqtt.consumer import MQTTConsumer
from app.services.ocr_client import OCRClient
from app.services.refresh_tokens import RefreshTokenStore
from app.services.result_poller import poll_results
from app.services.scheduler import run_scheduler
from app.services.storage import PostgresStore
from app.services.users import UserStore
from prisma import Prisma

logger = logging.getLogger(__name__)


async def _cleanup_refresh_tokens(rt_store: RefreshTokenStore) -> None:
    """Hourly background task: delete expired refresh token rows."""
    while True:
        await asyncio.sleep(3600)
        try:
            deleted = await rt_store.cleanup_expired()
            if deleted:
                logger.info("Cleaned up %d expired refresh tokens", deleted)
        except Exception as exc:  # pragma: no cover
            logger.error("Refresh token cleanup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings

    # Production TLS guard — refuse to start without sslmode on the DSN.
    if settings.env == "production" and "sslmode=" not in settings.database_url:
        raise RuntimeError("Production deployment requires sslmode=verify-full in DATABASE_URL")

    # Database
    db = Prisma()
    await db.connect()
    app.state.db = db  # exposed for audit-log route

    # PHI encryption
    provider = EnvKeyProvider(settings.phi_master_key)
    cipher = PhiCipher(provider)

    # Dependent services
    audit_sink = PrismaAuditSink(db)
    user_store = UserStore(db)
    rt_store = RefreshTokenStore(db)
    store = PostgresStore(db, cipher=cipher, audit_sink=audit_sink)

    app.state.audit_sink = audit_sink
    app.state.user_store = user_store
    app.state.rt_store = rt_store
    app.state.store = store

    # Seed initial admin on first boot if configured and no admin exists yet.
    if settings.initial_admin_username and settings.initial_admin_password:
        if not await user_store.exists_with_role("admin"):
            await user_store.create_user(
                settings.initial_admin_username,
                settings.initial_admin_password,
                ["admin", "doctor"],
            )
            logger.info("Created initial admin user: %s", settings.initial_admin_username)

    # OCR client + result poller
    ocr_client = OCRClient(settings.ocr_queue_dir)
    app.state.ocr_client = ocr_client
    poller_task = asyncio.create_task(poll_results(settings.ocr_queue_dir, store))

    # Hourly refresh token cleanup
    cleanup_task = asyncio.create_task(_cleanup_refresh_tokens(rt_store))

    # Daily expiry alert scheduler (02:00 UTC)
    scheduler_task = asyncio.create_task(run_scheduler(app))

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

    cleanup_task.cancel()
    poller_task.cancel()
    scheduler_task.cancel()
    for task in (cleanup_task, poller_task, scheduler_task):
        try:
            await task
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

    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(
            app, endpoint="/metrics/prometheus", include_in_schema=False
        )
    except ImportError:  # pragma: no cover
        logger.warning(
            "prometheus-fastapi-instrumentator not installed; /metrics/prometheus disabled"
        )

    app.add_middleware(
        BodySizeLimitMiddleware,
        max_upload=settings.max_upload_size_bytes,
        max_json=settings.max_json_body_bytes,
    )
    app.add_middleware(AuditMiddleware)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc.detail)})

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin_users.router)
    app.include_router(documents.router)
    app.include_router(review.router)
    app.include_router(metrics.router)
    app.include_router(audit_log.router)
    app.include_router(reports.router)
    app.include_router(alerts.router)

    return app


app = create_app()
