from backend.routers.telemetry import _lockdown_access_alert


def test_successful_entry_during_lockdown_uses_requested_alert_text() -> None:
    alert = _lockdown_access_alert({"zona": "Puerta Lobby", "metadata": {"access_direction": "ENTRY"}}, "GRANTED")

    assert alert == {
        "severity": "critical",
        "code": "ENTRY_DURING_LOCKDOWN",
        "message": "Acaba de ingresar una persona con el Lockdown activo · Zona: Puerta Lobby",
    }


def test_granted_access_without_direction_is_reported_without_claiming_entry() -> None:
    alert = _lockdown_access_alert({"zona": "Puerta Lobby"}, "GRANTED")

    assert alert["code"] == "ACCESS_GRANTED_DURING_LOCKDOWN"
    assert "dirección no fue informada" in alert["message"]


def test_lockdown_exit_is_not_reported_as_a_new_entry() -> None:
    assert _lockdown_access_alert(
        {"metadata": {"access_direction": "EXIT"}}, "GRANTED"
    ) is None


def test_denied_access_attempt_is_distinct_from_a_successful_entry() -> None:
    alert = _lockdown_access_alert({"zona": "Puerta Lobby"}, "DENIED")

    assert alert["code"] == "ACCESS_ATTEMPT_DURING_LOCKDOWN"
    assert "Intento" in alert["message"]
