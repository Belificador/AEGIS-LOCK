"""Strict request and event schemas. UI-rendered content must still use textContent."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


SafeIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[\w.:-]+$"),
]
SafeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class LoginRequest(StrictModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=256)]

    @field_validator("username")
    @classmethod
    def username_must_be_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("El usuario debe ser el correo asociado a Supabase Auth")
        return value.lower()


class RefreshRequest(StrictModel):
    refresh_token: Annotated[str, StringConstraints(min_length=20, max_length=4096)]


class TokenResponse(StrictModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserResponse"


class UserResponse(StrictModel):
    id: str
    email: str
    role: UserRole


class TelemetryEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    source_id: SafeIdentifier
    event_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = "telemetry"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    temperature_c: float | None = Field(default=None, ge=-50, le=150)
    voltage_v: float | None = Field(default=None, ge=0, le=1000)
    power_kw: float | None = Field(default=None, ge=0, le=100_000)
    occupancy: int | None = Field(default=None, ge=0, le=1_000_000)
    intrusion: bool = False
    lockdown: bool = False
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ChatRequest(StrictModel):
    message: SafeText


class ChatResponse(StrictModel):
    response: str
    source: str
