"""Daily scheduler — runs expiry alert scan at 02:00 UTC."""

import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def _seconds_until_next_2am_utc() -> float:
    now = datetime.now(UTC)
    target = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target.replace(day=target.day + 1)
    return (target - now).total_seconds()


async def run_scheduler(app) -> None:  # type: ignore[no-untyped-def]
    """Runs forever; call as a background asyncio task in the app lifespan."""
    from app.services.alert_generator import scan_expiry_alerts

    while True:
        delay = _seconds_until_next_2am_utc()
        await asyncio.sleep(delay)
        try:
            count = await scan_expiry_alerts(app.state.store._db)
            logger.info("Expiry scan complete: %d alerts created", count)
        except Exception:
            logger.exception("Expiry scan failed")
