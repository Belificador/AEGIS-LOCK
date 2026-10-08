"""Strict request and event schemas. UI-rendered content must still use textContent."""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator, model_validator


SafeIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[\w.:-]+$"),
]
SafeLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$"),
]
SafeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1200, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+$"),
]
SafeLogText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1200, pattern=r"^[^\x00-\x1f\x7f]+$"),
]
EventType = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_.:-]*$")]
TelemetryMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class UserRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class CameraMetadata(StrictModel):
    id: SafeIdentifier | None = None
    name: SafeLabel | None = None
    location: SafeLabel | None = None


class TelemetryMetadata(StrictModel):
    sensor: SafeIdentifier | None = None
    estado_actual: bool | None = None
    power_w: float | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    watts: float | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    power_kw: float | None = Field(default=None, ge=0, le=100_000, strict=True)
    energy_kwh: float | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    power_estimated: bool | None = None
    direccion: int | None = Field(default=None, ge=0, le=1, strict=True)
    camera_id: SafeIdentifier | None = None
    cameraId: SafeIdentifier | None = None
    camera: CameraMetadata | None = None
    name: SafeLabel | None = None
    location: SafeLabel | None = None
    ubicacion: SafeLabel | None = None
    door_name: SafeLabel | None = None
    pin_id: UUID | None = None
    target_user: SafeLabel | None = None
    access_direction: Literal["entry", "exit"] | None = None
    node_name: SafeLabel | None = None
    node: SafeLabel | None = None
    nodo: SafeLabel | None = None
    nodo_3d: SafeLabel | None = None
    mesh: SafeLabel | None = None
    mesh_name: SafeLabel | None = None
    room: SafeLabel | None = None
    habitacion: SafeLabel | None = None
    nodes: list[SafeLabel] | None = Field(default=None, max_length=32)

    @field_validator("access_direction", mode="before")
    @classmethod
    def normalize_access_direction(cls, value: object) -> object:
        if isinstance(value, str):
            direction = value.strip().lower()
            return {"entrada": "entry", "salida": "exit"}.get(direction, direction)
        return value


_VALUE_OBJECT_KEYS = {
    "temperature_c", "celsius", "lectura", "value", "valor", "voltage_v", "voltage",
    "v", "power_w", "watts", "w", "power_kw", "count", "personas",
}
_SAFE_LABEL_ADAPTER = TypeAdapter(SafeLabel)
_SAFE_AUDIT_VALUE_ADAPTER = TypeAdapter(SafeLabel)


def validate_telemetry_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or abs(float(value)) > 1_000_000_000:
            raise ValueError("El valor numérico está fuera de rango")
        return value
    if isinstance(value, str):
        return _SAFE_LABEL_ADAPTER.validate_python(value)
    if isinstance(value, dict) and depth == 0 and len(value) <= 12:
        if any(not isinstance(key, str) or key not in _VALUE_OBJECT_KEYS for key in value):
            raise ValueError("El objeto valor contiene campos no permitidos")
        return {key: validate_telemetry_value(item, depth=1) for key, item in value.items()}
    raise ValueError("El valor debe ser escalar o un objeto numérico conocido")


class TelemetryEnvelope(StrictModel):
    event_id: UUID | None = None
    source_id: SafeIdentifier | None = None
    origen: SafeIdentifier | None = None
    tipo_evento: EventType
    event_type: EventType | None = None
    timestamp: datetime | None = None
    zona: SafeLabel | None = None
    zone: SafeLabel | None = None
    valor: Any = None
    metadata: TelemetryMetadata = Field(default_factory=TelemetryMetadata)
    temperature_c: float | None = Field(default=None, ge=-50, le=150, strict=True)
    voltage_v: float | None = Field(default=None, ge=0, le=1000, strict=True)
    power_kw: float | None = Field(default=None, ge=0, le=100_000, strict=True)
    energy_kwh: float | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    occupancy: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    intrusion: bool = False
    lockdown: bool = False
    message: SafeText | None = None
    camera_id: SafeIdentifier | None = None

    @field_validator("valor")
    @classmethod
    def validate_value(cls, value: Any) -> Any:
        return validate_telemetry_value(value)

    @model_validator(mode="after")
    def require_source(self) -> "TelemetryEnvelope":
        if not (self.source_id or self.origen):
            raise ValueError("El evento requiere source_id u origen")
        if self.source_id and self.origen and self.source_id != self.origen:
            raise ValueError("source_id y origen deben identificar la misma fuente")
        if self.event_type and self.event_type != self.tipo_evento:
            raise ValueError("event_type y tipo_evento deben coincidir")
        if self.tipo_evento == "camera_selected":
            camera_ids = [
                value for value in (
                    self.camera_id,
                    self.metadata.camera_id,
                    self.metadata.cameraId,
                    self.valor if isinstance(self.valor, str) else None,
                ) if value is not None
            ]
            if len(set(camera_ids)) > 1:
                raise ValueError("La selección contiene identificadores de cámara distintos")
        return self


class LoginRequest(StrictModel):
    username: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=80, pattern=r"^[\w.@:+-]+$"),
    ]
    password: Annotated[str, StringConstraints(min_length=16, max_length=256)]

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.lower()


class RefreshRequest(StrictModel):
    refresh_token: Annotated[str, StringConstraints(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class LogoutRequest(StrictModel):
    refresh_token: Annotated[str, StringConstraints(min_length=20, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


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
    event_type: EventType = "telemetry"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    temperature_c: float | None = Field(default=None, ge=-50, le=150, strict=True)
    voltage_v: float | None = Field(default=None, ge=0, le=1000, strict=True)
    power_kw: float | None = Field(default=None, ge=0, le=100_000, strict=True)
    energy_kwh: float | None = Field(default=None, ge=0, le=1_000_000_000, strict=True)
    occupancy: int | None = Field(default=None, ge=0, le=1_000_000, strict=True)
    intrusion: bool = False
    lockdown: bool = False
    message: TelemetryMessage | None = None

    @model_validator(mode="after")
    def require_voltage_value_for_voltage_event(self) -> "TelemetryEvent":
        if self.event_type in {"voltaje", "voltage"} and self.voltage_v is None:
            raise ValueError("Un evento de voltaje requiere una lectura numérica explícita")
        return self


class ChatRequest(StrictModel):
    message: SafeText


class ChatResponse(StrictModel):
    response: str
    source: str


class PinGenerateRequest(StrictModel):
    door_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")]
    duration_hours: int = Field(ge=1, le=720, strict=True)
    target_user: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$")]


class PinGenerateResponse(StrictModel):
    id: str
    door_name: str
    pin_code: str
    target_user: str
    created_by: str
    expires_at: datetime
    is_active: bool


class PinValidationRequest(StrictModel):
    door_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80, pattern=r"^[^\x00-\x1f\x7f]+$")]
    pin_code: Annotated[str, StringConstraints(min_length=4, max_length=8, pattern=r"^[0-9]+$")]


class ServiceErrorRequest(StrictModel):
    error_type: SafeLabel
    description: SafeLogText
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000, strict=True)


class AuditAction(str, Enum):
    LOCKDOWN_ACTIVATED = "LOCKDOWN_ACTIVATED"
    LOCKDOWN_RELEASED = "LOCKDOWN_RELEASED"
    EVACUATION_ACTIVATED = "EVACUATION_ACTIVATED"
    EVACUATION_RELEASED = "EVACUATION_RELEASED"
    ALARM_ACKNOWLEDGED = "ALARM_ACKNOWLEDGED"


class AuditActionRequest(StrictModel):
    action: AuditAction
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_details(self) -> "AuditActionRequest":
        allowed_by_action = {
            AuditAction.LOCKDOWN_ACTIVATED: {"source"},
            AuditAction.LOCKDOWN_RELEASED: {"source"},
            AuditAction.EVACUATION_ACTIVATED: {"source"},
            AuditAction.EVACUATION_RELEASED: {"source"},
            AuditAction.ALARM_ACKNOWLEDGED: {"event_id", "code", "zone", "source"},
        }
        allowed = allowed_by_action[self.action]
        if len(self.details) > 12 or self.details.keys() - allowed:
            raise ValueError("Los detalles no corresponden a la acción de auditoría")
        for key, value in self.details.items():
            if not isinstance(key, str) or not key.isidentifier():
                raise ValueError("Clave de auditoría inválida")
            if isinstance(value, str):
                _SAFE_AUDIT_VALUE_ADAPTER.validate_python(value)
            elif value is not None and (isinstance(value, (dict, list, tuple, set)) or not isinstance(value, (bool, int, float))):
                raise ValueError("Los valores de auditoría deben ser escalares")
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("El valor de auditoría debe ser finito")
        return self


class PinValidationResponse(StrictModel):
    valid: bool
    target_user: str | None = None
    pin_id: str | None = None


class CameraFeedResponse(StrictModel):
    camera_id: str
    feed_url: str | None
    available: bool
