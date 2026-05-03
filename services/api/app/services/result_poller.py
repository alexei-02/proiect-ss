"""
Background task that bridges the file-based OCR queue back to the API store.

The OCR worker writes `<doc_id>.result.json` files to the shared queue volume.
This poller reads them, persists the result to PostgreSQL via the store, and
deletes the file. This replaces the intended MQTT publish-back until the
messaging epic lands.
"""

import asyncio
import logging
from pathlib import Path

from app.schemas.ocr import OCRResult
from app.services.storage import PostgresStore

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0  # seconds


async def poll_results(queue_dir: Path, store: PostgresStore) -> None:
    """Run forever, draining *.result.json files into the database."""
    logger.info("Result poller started, watching %s", queue_dir)
    while True:
        for result_file in sorted(queue_dir.glob("*.result.json")):
            try:
                result = OCRResult.model_validate_json(result_file.read_text())
                await store.attach_ocr_result(result.document_id, result)
                result_file.unlink()
                logger.info(
                    "Stored OCR result for %s (needs_review=%s)",
                    result.document_id,
                    result.needs_review,
                )
            except Exception as exc:
                # Orphaned result (document not in DB) — discard rather than retry forever.
                if "RecordNotFound" in type(exc).__name__ or "Record to update not found" in str(exc):
                    logger.warning("Discarding orphaned result %s (document not in DB)", result_file.stem)
                    result_file.unlink(missing_ok=True)
                else:
                    logger.exception("Failed to process result file %s", result_file)
        await asyncio.sleep(_POLL_INTERVAL)
