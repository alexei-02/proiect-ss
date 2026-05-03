"""
OCR client — pushes documents to the OCR worker.

Currently uses a file-based queue (one JSON job file per document) to keep
the dev setup dependency-free. In production this should be Redis Streams
or RabbitMQ — see the queue-tech open question in DATA_INGESTION_AND_OCR.md.

The interface stays the same regardless of the backend, so swapping is
a one-file change.
"""

import json
import logging
import uuid
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class OCRClient:
    """Submits OCR jobs and tracks their state."""

    def __init__(self, queue_dir: Path) -> None:
        self.queue_dir = queue_dir
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    async def submit(
        self, *, document_id: uuid.UUID, image_bytes: bytes, source_device: str
    ) -> None:
        """Write a job file the OCR worker will pick up."""
        # Image goes to a separate file so the job manifest stays small
        # and easy to inspect.
        image_path = self.queue_dir / f"{document_id}.bin"
        image_path.write_bytes(image_bytes)

        job_path = self.queue_dir / f"{document_id}.job.json"
        job_path.write_text(
            json.dumps(
                {
                    "document_id": str(document_id),
                    "image_path": str(image_path),
                    "source_device": source_device,
                }
            )
        )
        logger.info("Queued OCR job for document %s", document_id)

    async def health(self) -> bool:
        """Returns True if the queue directory is writable."""
        try:
            probe = self.queue_dir / ".health"
            probe.write_text("ok")
            probe.unlink()
            return True
        except OSError:
            return False


def get_ocr_client() -> OCRClient:
    return OCRClient(get_settings().ocr_queue_dir)
