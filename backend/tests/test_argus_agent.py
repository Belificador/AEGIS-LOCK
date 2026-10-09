import asyncio
import json

import pytest

from backend.agents.argus import agent
from backend.agents.argus.tools import tools_for_role
from backend.config import Settings


def test_argus_tool_policy_keeps_writes_out_of_operator_and_hermes() -> None:
    names = lambda role, **kwargs: {tool["function"]["name"] for tool in tools_for_role(role, **kwargs)}
    assert "generate_temporary_pin" not in names("operator")
    assert "send_report_to_telegram" not in names("admin")
    assert "generate_temporary_pin" not in names("admin", channel="telegram")
    assert "generate_temporary_pin" not in names("admin")
    assert "send_report_to_telegram" not in names("admin", channel="telegram", allow_telegram_report=True)
    assert "generate_temporary_pin" in names("admin", allow_temporary_pin=True)
    assert "send_report_to_telegram" in names("admin", allow_telegram_report=True)


def test_argus_never_sends_created_pin_to_openrouter(monkeypatch) -> None:
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
        requests.append(json.loads(json.dumps(messages)))
        return next(responses)

    async def run_tool(name, arguments, claims, *, allow_temporary_pin=False, allow_telegram_report=False):
        assert name == "generate_temporary_pin"
        assert claims["role"] == "admin"
        assert allow_temporary_pin is True
        return (
            {"created": True, "door_name": "Puerta Lobby", "expires_at": "2026-10-08T12:00:00+00:00"},
            {
                "pin_code": "0042",
                "target_user": "visitante-17",
                "door_name": "Puerta Lobby",
                "expires_at": "2026-10-08T12:00:00+00:00",
            },
        )

    monkeypatch.setattr(agent, "get_settings", lambda: Settings(telegram_user_map="123456:admin"))
    monkeypatch.setattr(agent, "create_completion", create_completion)
    monkeypatch.setattr(agent, "run_tool", run_tool)

    answer = asyncio.run(agent.ask_argus(
        "Genera un PIN temporal para Puerta Lobby y visitante-17 por 8 horas",
        {"role": "admin", "sub": "admin"},
    ))

    assert "0042" in answer
    serialized_requests = json.dumps(requests, ensure_ascii=False)
    assert "0042" not in serialized_requests
    tool_result = requests[1][-1]["content"]
    assert "0042" not in tool_result
    assert "visitante-17" not in tool_result


def test_argus_recognizes_explicit_report_requests_only() -> None:
    assert agent._explicitly_requests_telegram_report("Envía el informe a Telegram")
    assert agent._explicitly_requests_telegram_report("Mandá el reporte general por Telegram")
    assert not agent._explicitly_requests_telegram_report("¿Qué actividad hubo en Telegram?")


def test_argus_only_enables_pin_tool_after_explicit_admin_request() -> None:
    assert agent._explicitly_requests_pin("Genera un PIN para Puerta Lobby")
    assert not agent._explicitly_requests_pin("¿Cuántos PINes se validaron hoy?")
    assert not agent._explicitly_requests_pin("No generes un PIN")


@pytest.mark.parametrize("tool_calls", ["invalid", [None], [{"id": "call-1"}]])
def test_argus_rejects_malformed_provider_tool_calls(monkeypatch, tool_calls) -> None:
    async def create_completion(*_args, **_kwargs):
        return {"tool_calls": tool_calls}

    monkeypatch.setattr(agent, "get_settings", lambda: Settings())
    monkeypatch.setattr(agent, "create_completion", create_completion)
    answer = asyncio.run(agent.ask_argus("Consulta", {"role": "operator"}))
    assert answer == "No pude procesar una respuesta de herramienta válida. Reintenta."
