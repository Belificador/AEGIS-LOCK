import asyncio
import json

import pytest

from backend.agents.argus import agent
from backend.agents.argus.tools import run_tool, tools_for_role
from backend.services.argus_reporting import _activity_label, _safe_zone
from backend.services.postgres_client import postgres_service


def test_pin_code_stays_out_of_openrouter_tool_results(monkeypatch) -> None:
    requests = []
    responses = iter([
        {
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "generate_temporary_pin",
                    "arguments": '{"door_name":"Puerta Lobby","target_user":"visitante-17","duration_hours":8}',
                },
            }],
        },
        {"content": "PIN creado para la puerta solicitada."},
    ])

    async def create_completion(messages, *, tools=None):
        requests.append(messages)
        return next(responses)

    async def run_tool(name, arguments, claims, *, allow_telegram_report=False):
        assert name == "generate_temporary_pin"
        assert claims["role"] == "admin"
        assert allow_telegram_report is False
        return (
            {"created": True, "door_name": "Puerta Lobby", "expires_at": "2026-10-07T12:00:00+00:00"},
            {
                "pin_code": "0042",
                "target_user": "visitante-17",
                "door_name": "Puerta Lobby",
                "expires_at": "2026-10-07T12:00:00+00:00",
            },
        )

    monkeypatch.setattr(agent, "create_completion", create_completion)
    monkeypatch.setattr(agent, "run_tool", run_tool)

    answer = asyncio.run(agent.ask_argus("Crea un PIN temporal", {"role": "admin", "sub": "admin"}))

    assert "0042" in answer
    tool_result = requests[1][-1]["content"]
    assert "0042" not in tool_result
    assert "visitante-17" not in tool_result
    assert "0042" not in json.dumps(requests[1])
    assert "visitante-17" not in json.dumps(requests[1][-1])


def test_non_admin_toolset_does_not_include_pin_generation() -> None:
    assert all(
        tool["function"]["name"] != "generate_temporary_pin"
        for tool in tools_for_role("operator")
    )
    assert any(
        tool["function"]["name"] == "generate_temporary_pin"
        for tool in tools_for_role("admin")
    )


def test_telegram_admin_still_gets_read_only_toolset(monkeypatch) -> None:
    requested_tools = []

    async def create_completion(_messages, *, tools=None):
        requested_tools.extend(tools or [])
        return {"content": "Consulté el estado de AEGIS."}

    monkeypatch.setattr(agent, "create_completion", create_completion)
    answer = asyncio.run(agent.ask_argus(
        "temperatura",
        {"role": "admin", "sub": "admin", "channel": "telegram"},
    ))

    assert answer == "Consulté el estado de AEGIS."
    assert all(tool["function"]["name"] != "generate_temporary_pin" for tool in requested_tools)


def test_telegram_admin_cannot_call_pin_tool_even_if_requested_directly() -> None:
    with pytest.raises(PermissionError, match="no está disponible desde Telegram"):
        asyncio.run(run_tool(
            "generate_temporary_pin",
            '{"door_name":"Puerta Lobby","target_user":"visitante","duration_hours":1}',
            {"role": "admin", "sub": "admin", "channel": "telegram"},
        ))


def test_telegram_send_tool_requires_explicit_request_and_linked_admin(monkeypatch) -> None:
    requested_tools = []

    async def create_completion(_messages, *, tools=None):
        requested_tools.extend(tools or [])
        return {"content": "Listo."}

    monkeypatch.setattr(agent, "create_completion", create_completion)
    monkeypatch.setattr(
        agent,
        "get_settings",
        lambda: type("Settings", (), {"authorized_telegram_users": {123: "admin"}})(),
    )

    asyncio.run(agent.ask_argus("Dame un informe general", {"role": "admin", "username": "admin"}))
    assert all(tool["function"]["name"] != "send_report_to_telegram" for tool in requested_tools)

    requested_tools.clear()
    asyncio.run(agent.ask_argus(
        "Envía un informe general a Telegram",
        {"role": "admin", "username": "admin"},
    ))
    assert any(tool["function"]["name"] == "send_report_to_telegram" for tool in requested_tools)


def test_telegram_report_tool_is_not_available_to_telegram_or_without_intent() -> None:
    report_tool = lambda tools: any(tool["function"]["name"] == "send_report_to_telegram" for tool in tools)
    assert not report_tool(tools_for_role("admin"))
    assert report_tool(tools_for_role("admin", allow_telegram_report=True))
    assert not report_tool(tools_for_role("admin", channel="telegram", allow_telegram_report=True))


def test_on_demand_report_sends_only_to_requesting_admins_linked_chat(monkeypatch) -> None:
    delivered = []
    summary = {
        "temperature_c": {"min": None, "average": None, "max": None},
        "voltage_v": {"last": None, "power_loss_events": 0},
        "occupancy": {"current_total": None},
        "access": {
            "people_with_validated_pin": 0,
            "pin_validations": 0,
            "authorized": 0,
            "denied": 0,
            "entries": 0,
            "exits": 0,
            "without_direction": 0,
        },
        "power_kw_last": None,
        "energy_kwh_last": None,
        "readings": 0,
        "readings_with_alerts": 0,
    }

    async def summarize(days):
        assert days == 1
        return dict(summary)

    async def summarize_text(_summary):
        return "Resumen agregado sin datos personales."

    async def send_message(text, *, chat_id=None):
        delivered.append((text, chat_id))

    async def audit(**_values):
        return 17

    monkeypatch.setattr(agent, "get_settings", lambda: type("Settings", (), {"authorized_telegram_users": {123: "admin"}})())
    monkeypatch.setattr(agent, "summarize_last_days", summarize)
    monkeypatch.setattr(agent, "summarize_daily_report", summarize_text)
    monkeypatch.setattr(agent, "send_telegram_message", send_message)
    monkeypatch.setattr(postgres_service, "pool", object())
    monkeypatch.setattr(postgres_service, "write_audit_log", audit)

    result = asyncio.run(agent.send_on_demand_report(1, {"sub": "admin", "username": "admin", "role": "admin"}))

    assert result["sent"] is True
    assert delivered[0][1] == "123"
    assert "Resumen agregado" in delivered[0][0]
    assert "TELEGRAM_CHAT_ID" not in delivered[0][0]


def test_on_demand_report_refuses_unlinked_or_non_admin_user() -> None:
    with pytest.raises(PermissionError, match="Administrador"):
        asyncio.run(agent.send_on_demand_report(1, {"sub": "operator", "role": "operator"}))


def test_one_dashboard_request_cannot_send_the_same_report_twice(monkeypatch) -> None:
    tool_results = []
    provider_calls = []
    tool_call = {
        "id": "send-report",
        "type": "function",
        "function": {"name": "send_report_to_telegram", "arguments": '{"days":1}'},
    }
    responses = iter([
        {"tool_calls": [tool_call]},
        {"tool_calls": [tool_call]},
        {"content": "Informe enviado."},
    ])

    async def create_completion(_messages, *, tools=None):
        provider_calls.append(True)
        return next(responses)

    async def run_tool(name, _arguments, _claims, *, allow_telegram_report=False):
        tool_results.append(name)
        assert allow_telegram_report is True
        return ({"sent": True}, None)

    monkeypatch.setattr(agent, "get_settings", lambda: type("Settings", (), {"authorized_telegram_users": {123: "admin"}})())
    monkeypatch.setattr(agent, "create_completion", create_completion)
    monkeypatch.setattr(agent, "run_tool", run_tool)

    answer = asyncio.run(agent.ask_argus(
        "Envía el informe a Telegram",
        {"sub": "admin", "username": "admin", "role": "admin"},
    ))

    assert "Envié el informe" in answer
    assert len(provider_calls) == 1
    assert tool_results == ["send_report_to_telegram"]


def test_activity_summaries_do_not_echo_untrusted_zones_or_event_names() -> None:
    assert _safe_zone("Recepción") == "Recepción"
    assert _safe_zone("visitante-17") == "Otra zona"
    assert _activity_label("visitante_17", "secreto", {}) == "Evento registrado"


@pytest.mark.parametrize("tool_calls", ["unexpected", [None], [{"id": "call-1"}]])
def test_invalid_provider_tool_call_returns_safe_message(monkeypatch, tool_calls) -> None:
    async def create_completion(*_args, **_kwargs):
        return {"tool_calls": tool_calls}

    monkeypatch.setattr(agent, "create_completion", create_completion)
    answer = asyncio.run(agent.ask_argus("Consulta", {"role": "operator"}))
    assert answer == "No pude procesar una respuesta de herramienta válida. Reintenta."
