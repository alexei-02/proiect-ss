"""Application settings, loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized configuration. All env vars validated at boot."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service
    app_name: str = "medical-ocr-api"
    env: str = "development"
    log_level: str = "INFO"

    # HTTP
    http_host: str = "0.0.0.0"
    http_port: int = 8000
    max_upload_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_json_body_bytes: int = 256 * 1024  # 256 KB

    # Rate limits (slowapi syntax)
    rate_limit_default: str = "100/minute"
    rate_limit_upload: str = "3/minute"
    rate_limit_write: str = "10/minute"

    # MQTT
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 8883
    mqtt_tls_ca: Path = Path("/certs/ca.crt")
    mqtt_tls_cert: Path = Path("/certs/api_server.crt")
    mqtt_tls_key: Path = Path("/certs/api_server.key")
    mqtt_client_id: str = "api_server"
    mqtt_topic_image_upload: str = "medical/images/+/upload"
    mqtt_topic_ocr_results: str = "medical/ocr/+/results"

    # OCR
    ocr_queue_dir: Path = Path("/tmp/ocr-queue")
    ocr_confidence_threshold: float = Field(default=0.95, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
