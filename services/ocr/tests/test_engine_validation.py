"""Image validation tests — first defense against malicious image CVEs."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.core.engine import MockOCREngine, validate_image


def _write_png(tmp_path: Path, width: int, height: int) -> Path:
    """Create a real PNG file of the given dimensions."""
    img = Image.new("RGB", (width, height), color=(200, 200, 200))
    p = tmp_path / "test.png"
    img.save(p, "PNG")
    return p


def test_valid_image_passes(tmp_path: Path) -> None:
    p = _write_png(tmp_path, 100, 100)
    validate_image(p, max_pixels=25_000_000)  # no exception


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_image(tmp_path / "doesnotexist.png", max_pixels=25_000_000)


def test_oversized_image_rejected(tmp_path: Path) -> None:
    p = _write_png(tmp_path, 1000, 1000)
    with pytest.raises(ValueError, match="too large"):
        validate_image(p, max_pixels=100_000)  # 100k < 1M


def test_malformed_file_rejected(tmp_path: Path) -> None:
    p = tmp_path / "fake.png"
    p.write_bytes(b"This is not a real PNG file, just garbage bytes")
    with pytest.raises(ValueError, match="Invalid image"):
        validate_image(p, max_pixels=25_000_000)


def test_truncated_file_rejected(tmp_path: Path) -> None:
    """A real PNG header followed by truncated data."""
    p = _write_png(tmp_path, 100, 100)
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])  # truncate
    with pytest.raises(ValueError):
        validate_image(p, max_pixels=25_000_000)


def test_mock_engine_returns_blocks(tmp_path: Path) -> None:
    p = _write_png(tmp_path, 100, 100)
    engine = MockOCREngine()
    blocks = engine.read(p)
    assert len(blocks) == 3
    assert all(b.confidence > 0 for b in blocks)
    assert all(len(b.bounding_box) == 4 for b in blocks)
