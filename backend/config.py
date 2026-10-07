"""Application settings loaded from the environment and an optional .env file."""

from functools import lru_cache
from ipaddress import ip_address
import os
import secrets
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AEGIS LOCK API"
    environment: Literal["local", "development", "test", "production"] = "local"
    api_v1_prefix: str = "/api/v1"

    jwt_secret: str | None = Field(default=None, repr=False)
    pin_encryption_key: str | None = Field(default=None, repr=False)
    rate_limit_storage_uri: str | None = Field(default=None, repr=False)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_days: int = Field(default=7, ge=1, le=90)
    database_url: str | None = Field(default=None, repr=False)
    telemetry_api_key: str | None = Field(default=None, repr=False)
    demo_operator_password: str | None = Field(default=None, repr=False)
    demo_admin_password: str | None = Field(default=None, repr=False)
    gemelo_media_base_url: str = "https://gemelo-digital-bhjp.onrender.com"
    pin_code_length: int = Field(default=4, ge=4, le=8)
    analytics_default_days: int = Field(default=7, ge=1, le=90)
    analytics_max_rows: int = Field(default=1000, ge=100, le=5000)

    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5500",
            "http://127.0.0.1:5500",
        ]
    )

    local_ai_url: str | None = None
    local_ai_model: str = "llama3.2"
    max_request_bytes: int = Field(default=1_048_576, ge=1024)
    max_telemetry_event_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return {"dev": "development", "prod": "production"}.get(normalized, normalized)
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("allowed_origins")
    @classmethod
    def reject_wildcard_origins(cls, origins: list[str]) -> list[str]:
        if not origins or "*" in origins:
            raise ValueError("ALLOWED_ORIGINS must contain explicit origins; '*' is forbidden")
        return origins

    @field_validator("local_ai_url")
    @classmethod
    def restrict_ai_to_local_network(cls, value: str | None) -> str | None:
        if value and not _is_loopback_origin(value):
            raise ValueError("LOCAL_AI_URL must point to a loopback host")
        return value

    @field_validator("gemelo_media_base_url")
    @classmethod
    def validate_media_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("GEMELO_MEDIA_BASE_URL must be an HTTP(S) origin without embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("GEMELO_MEDIA_BASE_URL cannot include query strings or fragments")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            if not self.jwt_secret or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must contain at least 32 characters in production")
            if not self.database_url:
                raise ValueError("DATABASE_URL is required in production")
            if not self.telemetry_api_key or len(self.telemetry_api_key) < 32:
                raise ValueError("TELEMETRY_API_KEY must contain at least 32 characters in production")
            if not self.demo_operator_password or len(self.demo_operator_password) < 16:
                raise ValueError("DEMO_OPERATOR_PASSWORD must contain at least 16 characters in production")
            if not self.demo_admin_password or len(self.demo_admin_password) < 16:
                raise ValueError("DEMO_ADMIN_PASSWORD must contain at least 16 characters in production")
            if not self.pin_encryption_key or len(self.pin_encryption_key) < 32:
                raise ValueError("PIN_ENCRYPTION_KEY must contain at least 32 characters in production")
            if not self.rate_limit_storage_uri:
                raise ValueError("RATE_LIMIT_STORAGE_URI must point to Render Key Value in production")
            if urlsplit(self.rate_limit_storage_uri).scheme not in {"redis", "rediss"}:
                raise ValueError("Production rate limits require a redis:// or rediss:// storage URI")
            if urlsplit(self.gemelo_media_base_url).scheme != "https":
                raise ValueError("GEMELO_MEDIA_BASE_URL must use HTTPS in production")
            if any(_is_loopback_origin(origin) for origin in self.allowed_origins):
                raise ValueError("Localhost origins are not allowed in production")
            if any(urlsplit(origin).scheme != "https" for origin in self.allowed_origins):
                raise ValueError("Production ALLOWED_ORIGINS must use HTTPS")
        else:
            if os.getenv("RENDER", "").lower() == "true":
                raise ValueError("ENVIRONMENT=production is required on Render")
            if any(not _is_loopback_origin(origin) for origin in self.allowed_origins):
                raise ValueError("Local ALLOWED_ORIGINS must use localhost or a loopback IP")
            if not self.jwt_secret:
                # A process-local development key lets the API boot without committing a secret.
                # Tokens naturally become invalid after a local server restart.
                self.jwt_secret = secrets.token_urlsafe(48)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _is_loopback_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname
    if hostname is None:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False
