"""Application settings, loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(
    env_key: str,
    file_env_key: str | None = None,
    default: str | None = None,
) -> str | None:
    """Read a secret from the file pointed at by *file_env_key* if it exists,
    otherwise fall back to the env var *env_key*, otherwise *default*.
    """
    if file_env_key:
        path = os.environ.get(file_env_key)
        if path:
            p = Path(path)
            if p.exists():
                return p.read_text().strip()
    return os.environ.get(env_key, default)


class Settings(BaseSettings):
    """Centralized configuration. All env vars validated at boot."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service
    app_name: str = "medical-ocr-api"
    env: str = "development"
    log_level: str = "INFO"

    # HTTP
    http_host: str = "0.0.0.0"
    http_port: int = 8989
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

    # Database
    database_url: str = Field(
        default_factory=lambda: _read_secret(
            "DATABASE_URL",
            "DATABASE_URL_FILE",
            "postgresql://medical:dev_only_replace_me@postgres:5432/medical_ocr",
        )
    )

    # OCR
    ocr_queue_dir: Path = Path("/tmp/ocr-queue")  # noqa: S108 — intentional; overridden in prod
    ocr_confidence_threshold: float = Field(default=0.95, ge=0.0, le=1.0)

    # JWT
    jwt_secret: str = Field(
        default_factory=lambda: _read_secret(
            "JWT_SECRET",
            "JWT_SECRET_FILE",
            "change-me-in-production-use-a-long-random-secret",
        )
    )
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "medical-ocr-api"
    jwt_issuer: str = "medical-ocr-api"
    jwt_access_ttl_seconds: int = 900  # 15 minutes
    jwt_refresh_ttl_seconds: int = 604800  # 7 days

    # PHI encryption — 64 hex chars = 32 bytes (AES-256 key)
    phi_master_key: str = Field(
        default_factory=lambda: _read_secret(
            "PHI_MASTER_KEY",
            "PHI_MASTER_KEY_FILE",
            "0" * 64,  # dev default; overridden by env or secret file
        )
    )

    # Auth behaviour
    dev_auth_bypass: bool = False
    initial_admin_username: str = ""
    initial_admin_password: str = Field(
        default_factory=lambda: _read_secret(
            "INITIAL_ADMIN_PASSWORD",
            "INITIAL_ADMIN_PASSWORD_FILE",
            "",
        )
    )

    @field_validator("phi_master_key")
    @classmethod
    def _validate_phi_key(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError("PHI_MASTER_KEY must be 64 hex characters (32 bytes)")
        bytes.fromhex(v)  # raises ValueError if not valid hex
        return v

    @field_validator("dev_auth_bypass")
    @classmethod
    def _guard_bypass_in_prod(cls, v: bool, info) -> bool:
        env = (info.data or {}).get("env", "development")
        if v and env == "production":
            raise ValueError("DEV_AUTH_BYPASS must not be enabled in production")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
