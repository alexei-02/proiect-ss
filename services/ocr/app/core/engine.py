"""OCR engine wrapper.

Lazy-imports easyocr so that the module imports cleanly in test
environments where easyocr (and its 1+ GB of torch dependencies) isn't
installed. The mock engine is used when MOCK_OCR=1 — exercised by tests
and local dev.
"""

import logging
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.core.extractor import RawBlock

logger = logging.getLogger(__name__)


class OCREngine:
    """Wrapper around easyocr.Reader. Use real_engine() or mock_engine()."""

    def __init__(self, reader) -> None:
        self._reader = reader

    def read(self, image_path: Path) -> list[RawBlock]:
        # easyocr returns: [(bbox, text, confidence), ...] where bbox is
        # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] — convert to flat min/max.
        results = self._reader.readtext(str(image_path))
        blocks: list[RawBlock] = []
        for bbox, text, conf in results:
            xs = [int(p[0]) for p in bbox]
            ys = [int(p[1]) for p in bbox]
            blocks.append(
                RawBlock(
                    text=str(text),
                    confidence=float(conf),
                    bounding_box=[min(xs), min(ys), max(xs), max(ys)],
                )
            )
        return blocks


class MockOCREngine:
    """Deterministic mock used in tests and the dev pipeline.

    Returns a fixed structured response so we can verify the rest of the
    pipeline without pulling in easyocr's heavy dependencies.
    """

    def read(self, image_path: Path) -> list[RawBlock]:
        return [
            RawBlock(text="Patient: Ion Popescu", confidence=0.98, bounding_box=[10, 10, 200, 30]),
            RawBlock(text="Medication: Atorvastatin 20mg", confidence=0.92, bounding_box=[10, 40, 250, 60]),
            RawBlock(text="2026-08-15", confidence=0.99, bounding_box=[10, 70, 100, 90]),
        ]


def validate_image(image_path: Path, *, max_pixels: int) -> None:
    """Raise if the image is malformed or too large.

    First line of defense against image-decoder CVEs — refuse anything
    we can't safely decode and reject suspiciously large pixel counts
    that could trigger memory exhaustion.
    """
    if not image_path.exists():
        raise FileNotFoundError(image_path)
    try:
        with Image.open(image_path) as img:
            img.verify()
        # verify() leaves the file unusable; reopen to inspect size.
        with Image.open(image_path) as img:
            w, h = img.size
            if w * h > max_pixels:
                raise ValueError(f"Image too large: {w}x{h} = {w * h} pixels (max {max_pixels})")
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid image: {exc}") from exc


def get_engine() -> OCREngine | MockOCREngine:
    """Return the real engine or a mock based on MOCK_OCR env var."""
    if os.environ.get("MOCK_OCR") == "1":
        logger.info("Using mock OCR engine (MOCK_OCR=1)")
        return MockOCREngine()

    # Lazy import — easyocr pulls in torch.
    try:
        import easyocr  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "easyocr not installed; install via `pip install -e .[ocr]` "
            "or set MOCK_OCR=1 for tests."
        ) from exc
    reader = easyocr.Reader(["en", "ro"], gpu=False)  # pragma: no cover
    return OCREngine(reader)  # pragma: no cover
