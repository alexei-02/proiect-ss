"""OCR worker entry point.

Polls the queue directory for `*.job.json` files, runs OCR, writes the
result back to the API service via a sibling JSON file that the result
poller reads (in production this becomes an MQTT publish).
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.core.engine import MockOCREngine, OCREngine, get_engine, validate_image
from app.core.extractor import extract_fields, gate_confidence
from app.core.schemas import OCRResult

logger = logging.getLogger(__name__)


async def process_job(job_path: Path, engine: OCREngine | MockOCREngine) -> None:
    """Process a single queued OCR job."""
    settings = get_settings()
    started = time.monotonic()

    try:
        job = json.loads(job_path.read_text())
        document_id = UUID(job["document_id"])
        image_path = Path(job["image_path"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.error("Malformed job %s: %s", job_path, exc)
        job_path.unlink(missing_ok=True)
        return

    try:
        validate_image(image_path, max_pixels=settings.max_image_pixels)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Image validation failed for %s: %s", image_path, exc)
        _write_result(
            settings.queue_dir,
            OCRResult(
                document_id=document_id,
                processed_at=datetime.now(timezone.utc),
                ocr_engine=settings.engine_version,
                fields={},
                needs_review=True,
                low_confidence_fields=[],
                raw_text=f"validation_error: {exc}",
                processing_time_ms=int((time.monotonic() - started) * 1000),
            ),
        )
        _cleanup(job_path, image_path)
        return

    blocks = engine.read(image_path)

    fields = extract_fields(blocks)
    needs_review, low = gate_confidence(fields, threshold=settings.confidence_threshold)

    raw_text = "\n".join(b.text for b in blocks)[:65536]

    result = OCRResult(
        document_id=document_id,
        processed_at=datetime.now(timezone.utc),
        ocr_engine=settings.engine_version,
        fields=fields,
        needs_review=needs_review,
        low_confidence_fields=low,
        raw_text=raw_text,
        processing_time_ms=int((time.monotonic() - started) * 1000),
    )

    _write_result(settings.queue_dir, result)
    _cleanup(job_path, image_path)
    logger.info(
        "Processed %s in %d ms (needs_review=%s)",
        document_id,
        result.processing_time_ms,
        needs_review,
    )


def _write_result(queue_dir: Path, result: OCRResult) -> None:
    out_path = queue_dir / f"{result.document_id}.result.json"
    out_path.write_text(result.model_dump_json())


def _cleanup(job_path: Path, image_path: Path) -> None:
    job_path.unlink(missing_ok=True)
    image_path.unlink(missing_ok=True)


async def main() -> None:
    settings = get_settings()
    settings.queue_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading OCR engine...")
    engine = get_engine()
    logger.info("OCR engine ready, queue=%s", settings.queue_dir)

    while True:
        jobs = sorted(settings.queue_dir.glob("*.job.json"))
        for job in jobs:
            try:
                await process_job(job, engine)
            except Exception as exc:  # pragma: no cover
                logger.exception("Failed to process %s: %s", job, exc)
        if not jobs:
            await asyncio.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
