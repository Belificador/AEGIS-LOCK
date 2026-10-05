"""Application settings loaded from the environment and an optional .env file."""

from functools import lru_cache
import secrets
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AEGIS LOCK API"
    environment: str = "local"
    api_v1_prefix: str = "/api/v1"

    jwt_secret: str | None = Field(default=None, repr=False)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_minutes: int = Field(default=15, ge=1, le=1440)

    supabase_url: str | None = None
    supabase_key: str | None = Field(default=None, repr=False)
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5500",
            "http://127.0.0.1:5500",
        ]
    )

    local_ai_url: str | None = None
    local_ai_model: str = "llama3.2"
    max_request_bytes: int = Field(default=1_048_576, ge=1024)

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

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

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            if not self.jwt_secret or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must contain at least 32 characters in production")
            if not self.supabase_url or not self.supabase_key:
                raise ValueError("SUPABASE_URL and SUPABASE_KEY are required in production")
            if any(_is_loopback_origin(origin) for origin in self.allowed_origins):
                raise ValueError("Localhost origins are not allowed in production")
            if any(urlsplit(origin).scheme != "https" for origin in self.allowed_origins):
                raise ValueError("Production ALLOWED_ORIGINS must use HTTPS")
        elif any(not _is_loopback_origin(origin) for origin in self.allowed_origins):
            raise ValueError("Local ALLOWED_ORIGINS must use localhost or a loopback IP")
        elif not self.jwt_secret:
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
