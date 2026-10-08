import asyncio
import json

import pytest

from backend.agents.argus import agent
from backend.agents.argus.tools import run_tool, tools_for_role
from backend.services.argus_reporting import _activity_label, _safe_zone


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

    async def run_tool(name, arguments, claims):
        assert name == "generate_temporary_pin"
        assert claims["role"] == "admin"
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
