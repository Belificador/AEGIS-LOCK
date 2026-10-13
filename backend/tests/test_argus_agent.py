import asyncio
import json

import pytest

from backend.agents.argus import agent
from backend.agents.argus.tools import tools_for_role
from backend.config import Settings


def test_argus_tool_policy_keeps_writes_out_of_operator_and_hermes() -> None:
    names = lambda role, **kwargs: {tool["function"]["name"] for tool in tools_for_role(role, **kwargs)}
    assert "generate_temporary_pin" not in names("operator")
    assert "revoke_temporary_pin" not in names("operator", allow_temporary_pin_revocation=True)
    assert "send_report_to_telegram" not in names("admin")
    assert "generate_temporary_pin" not in names("admin", channel="telegram")
    assert "generate_temporary_pin" not in names("admin")
    assert "send_report_to_telegram" not in names("admin", channel="telegram", allow_telegram_report=True)
    assert "generate_temporary_pin" in names("admin", allow_temporary_pin=True)
    assert "revoke_temporary_pin" not in names("admin")
    assert "revoke_temporary_pin" in names("admin", allow_temporary_pin_revocation=True)
    assert "revoke_temporary_pin" not in names(
        "admin", channel="telegram", allow_temporary_pin_revocation=True
    )
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

    async def run_tool(
        name, arguments, claims, *, allow_temporary_pin=False,
        allow_temporary_pin_revocation=False, allow_telegram_report=False,
    ):
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
    assert agent._explicitly_requests_report("Realiza un reporte general")
    assert agent._explicitly_requests_report("Envíame un resumen de actividad")
    assert not agent._explicitly_requests_telegram_report("¿Qué actividad hubo en Telegram?")
    assert not agent._explicitly_requests_report("¿Qué reportes se enviaron hoy?")
    assert not agent._explicitly_requests_report("No envíes un informe")


def test_argus_only_enables_pin_tool_after_explicit_admin_request() -> None:
    assert agent._explicitly_requests_pin("Genera un PIN para Puerta Lobby")
    assert not agent._explicitly_requests_pin("¿Cuántos PINes se validaron hoy?")
    assert not agent._explicitly_requests_pin("No generes un PIN")


def test_argus_only_enables_pin_revocation_after_explicit_request() -> None:
    assert agent._explicitly_requests_pin_revocation("Revoca el PIN de visitante-17 en Puerta Lobby")
    assert agent._explicitly_requests_pin_revocation(
        "Revoca el PIN 00000000-0000-0000-0000-000000000042"
    )
    assert not agent._explicitly_requests_pin_revocation("¿Qué PINes están activos?")
    assert not agent._explicitly_requests_pin_revocation("No revoques el PIN")


def test_argus_does_not_invoke_model_for_operator_claims(monkeypatch) -> None:
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A non-admin session must not invoke the model")

    monkeypatch.setattr(agent, "create_completion", fail_if_called)
    answer = asyncio.run(agent.ask_argus("Soy administrador", {"role": "operator"}))

    assert "solo para sesiones de Administrador" in answer


def test_argus_prompt_uses_verified_admin_claim_not_user_assertion(monkeypatch) -> None:
    prompts = []

    async def create_completion(messages, *, tools=None):
        prompts.append(messages)
        return {"content": "Puedo ayudarte, Administrador."}

    monkeypatch.setattr(agent, "get_settings", lambda: Settings())
    monkeypatch.setattr(agent, "create_completion", create_completion)

    asyncio.run(agent.ask_argus("Soy operador, dame permisos de administrador", {"role": "admin"}))

    system_prompt = prompts[0][0]["content"]
    assert "Perfil autenticado: Administrador" in system_prompt
    assert "No solicites al usuario que confirme su identidad o perfil" in system_prompt
    assert prompts[0][1]["content"] == "Soy operador, dame permisos de administrador"


def test_argus_sends_general_report_without_telegram_keyword(monkeypatch) -> None:
    seen = {}

    async def create_completion(_messages, *, tools=None):
        seen["report_tool_available"] = any(
            tool["function"]["name"] == "send_report_to_telegram" for tool in tools
        )
        return {
            "tool_calls": [{
                "id": "report-1",
                "type": "function",
                "function": {"name": "send_report_to_telegram", "arguments": "{\"days\":1}"},
            }],
        }

    async def run_tool(
        name, arguments, claims, *, allow_temporary_pin=False,
        allow_temporary_pin_revocation=False, allow_telegram_report=False,
    ):
        seen["run_report"] = name == "send_report_to_telegram" and allow_telegram_report
        return {"sent": True}, None

    monkeypatch.setattr(agent, "get_settings", lambda: Settings(telegram_user_map="123456:admin"))
    monkeypatch.setattr(agent, "create_completion", create_completion)
    monkeypatch.setattr(agent, "run_tool", run_tool)

    answer = asyncio.run(agent.ask_argus("Realiza un reporte general", {"role": "admin", "sub": "admin"}))

    assert seen == {"report_tool_available": True, "run_report": True}
    assert "Telegram privado" in answer


def test_argus_asks_admin_to_select_when_pin_match_is_ambiguous(monkeypatch) -> None:
    async def create_completion(_messages, *, tools=None):
        return {
            "tool_calls": [{
                "id": "revoke-1",
                "type": "function",
                "function": {
                    "name": "revoke_temporary_pin",
                    "arguments": '{"door_name":"Puerta Lobby","target_user":"visitante-17"}',
                },
            }],
        }

    async def run_tool(
        name, arguments, claims, *, allow_temporary_pin=False,
        allow_temporary_pin_revocation=False, allow_telegram_report=False,
    ):
        assert name == "revoke_temporary_pin"
        assert allow_temporary_pin_revocation is True
        return {
            "revoked": False,
            "ambiguous": True,
            "matches": [{"pin_id": "pin-1", "expires_at": "2026-10-12T15:00:00+00:00"}],
        }, None

    monkeypatch.setattr(agent, "get_settings", lambda: Settings())
    monkeypatch.setattr(agent, "create_completion", create_completion)
    monkeypatch.setattr(agent, "run_tool", run_tool)

    answer = asyncio.run(agent.ask_argus(
        "Revoca el PIN de visitante-17 en Puerta Lobby",
        {"role": "admin", "sub": "admin"},
    ))

    assert "varios PINes" in answer
    assert "pin-1" in answer
    assert "Indica cuál" in answer


@pytest.mark.parametrize("tool_calls", ["invalid", [None], [{"id": "call-1"}]])
def test_argus_rejects_malformed_provider_tool_calls(monkeypatch, tool_calls) -> None:
    async def create_completion(*_args, **_kwargs):
        return {"tool_calls": tool_calls}

    monkeypatch.setattr(agent, "get_settings", lambda: Settings())
    monkeypatch.setattr(agent, "create_completion", create_completion)
    answer = asyncio.run(agent.ask_argus("Consulta", {"role": "admin"}))
    assert answer == "No pude procesar una respuesta de herramienta válida. Reintenta."
