from fastapi import HTTPException
import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.core.security import create_access_token, decode_access_token
from backend.models.schemas import LoginRequest, TelemetryEvent
from backend.services.rules_engine import evaluate_event


def test_critical_rules_trigger_only_at_configured_conditions() -> None:
    normal = TelemetryEvent(source_id="sensor-01", temperature_c=38, voltage_v=220)
    assert evaluate_event(normal) == []

    critical = TelemetryEvent(
        source_id="sensor-02",
        temperature_c=38.1,
        voltage_v=0,
        intrusion=True,
        lockdown=True,
    )
    assert {alert["code"] for alert in evaluate_event(critical)} == {
        "HIGH_TEMPERATURE",
        "POWER_LOSS",
        "INTRUSION",
        "LOCKDOWN",
    }


def test_payload_rejects_unknown_fields_and_cors_rejects_wildcards() -> None:
    with pytest.raises(ValidationError):
        TelemetryEvent(source_id="sensor-01", temperature_c=20, command="unlock")
    with pytest.raises(ValidationError):
        Settings(allowed_origins=["*"])
    with pytest.raises(ValidationError):
        Settings(allowed_origins=["https://untrusted.example"])
    with pytest.raises(ValidationError):
        Settings(local_ai_url="https://untrusted.example/v1")


def test_login_role_is_derived_from_account_not_request_payload() -> None:
    request = LoginRequest(username="operator@example.test", password="valid-password")
    assert request.username == "operator@example.test"
    with pytest.raises(ValidationError):
        LoginRequest(username="operator@example.test", password="valid-password", role="admin")


def test_access_token_contains_subject_role_and_rejects_tampering() -> None:
    token, expires_in = create_access_token(subject="user-123", role="operator", email="operator@example.test")
    claims = decode_access_token(token)
    assert expires_in > 0
    assert claims["sub"] == "user-123"
    assert claims["role"] == "operator"
    assert claims["email"] == "operator@example.test"

    header, payload, signature = token.split(".")
    changed_signature = ("a" if signature[0] != "a" else "b") + signature[1:]
    with pytest.raises(HTTPException) as error:
        decode_access_token(f"{header}.{payload}.{changed_signature}")
    assert error.value.status_code == 401
