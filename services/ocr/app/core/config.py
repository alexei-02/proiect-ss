"""OCR worker configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCR_", env_file=".env", extra="ignore")

    queue_dir: Path = Path("/tmp/ocr-queue")
    confidence_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    languages: list[str] = Field(default_factory=lambda: ["en", "ro"])
    engine_version: str = "easyocr-1.7.1"

    # Hard cap on image dimensions to bound resource use.
    max_image_pixels: int = 25_000_000  # ~25 megapixels

    poll_interval_seconds: float = 1.0


def get_settings() -> Settings:
    return Settings()
