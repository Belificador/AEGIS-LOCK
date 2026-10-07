from fastapi import HTTPException
import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.core.security import create_access_token, decode_access_token
from backend.core.passwords import hash_password, verify_password
from backend.models.schemas import AuditAction, AuditActionRequest, LoginRequest, PinGenerateRequest, TelemetryEvent
from backend.services.rules_engine import evaluate_event
from backend.services.telemetry_ingest import parse_telemetry


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
    with pytest.raises(ValidationError):
        PinGenerateRequest(door_name="Puerta Lobby", duration_hours="8", target_user="visitante")
    with pytest.raises(ValidationError):
        AuditActionRequest(action=AuditAction.LOCKDOWN_ACTIVATED, details={"source": "manual", "command": "unlock"})
    with pytest.raises(ValidationError):
        AuditActionRequest(action=AuditAction.ALARM_ACKNOWLEDGED, details={"password": "no-log"})


def test_production_requires_separate_pin_key_and_shared_redis_rate_storage() -> None:
    with pytest.raises(ValidationError, match="Production rate limits require"):
        Settings(
            environment="production",
            allowed_origins=["https://aegis-lock.onrender.com"],
            jwt_secret="j" * 48,
            database_url="postgresql://aegis:secret@db.example.test/aegis",
            telemetry_api_key="t" * 48,
            demo_operator_password="o" * 24,
            demo_admin_password="a" * 24,
            pin_encryption_key="p" * 48,
            rate_limit_storage_uri="memory://",
        )


def test_login_role_is_derived_from_account_not_request_payload() -> None:
    request = LoginRequest(username="operator@example.test", password="valid-password-123")
    assert request.username == "operator@example.test"
    with pytest.raises(ValidationError):
        LoginRequest(username="operator@example.test", password="valid-password-123", role="admin")

    demo_user = LoginRequest(username=" Operador ", password="valid-password-123")
    assert demo_user.username == "operador"


def test_scrypt_password_hashes_are_salted_and_verified() -> None:
    first_hash = hash_password("demo-password-123")
    second_hash = hash_password("demo-password-123")
    assert first_hash != second_hash
    assert verify_password("demo-password-123", first_hash)
    assert not verify_password("wrong-password", first_hash)


def test_simulator_envelopes_are_normalized_before_rules() -> None:
    event, event_data = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "temperatura",
        "zona": "entrada",
        "valor": 39,
        "timestamp": "2026-10-05T12:00:00Z",
        "metadata": {"estado_actual": True},
    })
    assert event.source_id == "simulador"
    assert event.temperature_c == 39
    assert event_data["tipo_evento"] == "temperatura"
    assert event_data["metadata"]["estado_actual"] is True
    assert evaluate_event(event)[0]["code"] == "HIGH_TEMPERATURE"

    denied, _ = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "acceso_pin",
        "zona": "entrada",
        "valor": "DENIED",
    })
    assert denied.intrusion is True
    assert evaluate_event(denied)[0]["code"] == "INTRUSION"

    voltage, _ = parse_telemetry({
        "origen": "simulador",
        "tipo_evento": "voltaje",
        "zona": "entrada",
        "valor": 220,
        "metadata": {"power_w": 50},
    })
    assert voltage.voltage_v == 220
    assert voltage.power_kw == 0.05

    with pytest.raises((ValidationError, ValueError)):
        parse_telemetry({"origen": "simulador", "tipo_evento": "temperatura", "valor": "no-numérico"})

    with pytest.raises(ValidationError):
        parse_telemetry({
            "origen": "simulador",
            "tipo_evento": "temperatura",
            "valor": 20,
            "execute": "unlock all doors",
        })
    with pytest.raises(ValidationError):
        parse_telemetry({
            "origen": "simulador",
            "tipo_evento": "temperatura",
            "valor": 20,
            "metadata": {"script": "__import__('os').system('id')"},
        })
    with pytest.raises(ValidationError):
        parse_telemetry({"origen": "simulador", "tipo_evento": "temperatura", "valor": float("nan")})
    with pytest.raises((ValidationError, ValueError)):
        parse_telemetry({"origen": "simulador", "tipo_evento": "temperatura", "valor": "39"})


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
