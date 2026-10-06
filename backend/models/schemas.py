"""Strict request and event schemas. UI-rendered content must still use textContent."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
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
    username: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=80, pattern=r"^[\w.@:+-]+$"),
    ]
    password: Annotated[str, StringConstraints(min_length=8, max_length=256)]

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
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
    username: str
    role: UserRole


class TelemetryEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    source_id: SafeIdentifier
    event_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = "telemetry"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    temperature_c: float | None = Field(default=None, ge=-50, le=150)
    voltage_v: float | None = Field(default=None, ge=0, le=1000)
    power_kw: float | None = Field(default=None, ge=0, le=100_000)
    energy_kwh: float | None = Field(default=None, ge=0, le=1_000_000_000)
    occupancy: int | None = Field(default=None, ge=0, le=1_000_000)
    intrusion: bool = False
    lockdown: bool = False
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class ChatRequest(StrictModel):
    message: SafeText


class ChatResponse(StrictModel):
    response: str
    source: str


class PinGenerateRequest(StrictModel):
    door_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    duration_hours: int = Field(ge=1, le=720)
    target_user: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class PinGenerateResponse(StrictModel):
    id: str
    door_name: str
    pin_code: str
    target_user: str
    created_by: str
    expires_at: datetime
    is_active: bool


class PinValidationRequest(StrictModel):
    door_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    pin_code: Annotated[str, StringConstraints(min_length=4, max_length=8, pattern=r"^\d+$")]


class ServiceErrorRequest(StrictModel):
    error_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: SafeText
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class AuditAction(str, Enum):
    LOCKDOWN_ACTIVATED = "LOCKDOWN_ACTIVATED"
    LOCKDOWN_RELEASED = "LOCKDOWN_RELEASED"
    EVACUATION_ACTIVATED = "EVACUATION_ACTIVATED"
    EVACUATION_RELEASED = "EVACUATION_RELEASED"
    ALARM_ACKNOWLEDGED = "ALARM_ACKNOWLEDGED"


class AuditActionRequest(StrictModel):
    action: AuditAction
    details: dict[str, Any] = Field(default_factory=dict)


class PinValidationResponse(StrictModel):
    valid: bool
    target_user: str | None = None
    pin_id: str | None = None


class CameraFeedResponse(StrictModel):
    camera_id: str
    feed_url: str | None
    available: bool
