import asyncio
from types import SimpleNamespace

import httpx
import pytest

from backend.services import telegram


def test_telegram_http_error_exposes_reason_without_secrets(monkeypatch) -> None:
    bot_token = "123456:super-secret-token"
    chat_id = "987654321"

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return httpx.Response(
                400,
                json={
                    "ok": False,
                    "error_code": 400,
                    "description": f"Bad Request: chat not found {chat_id} {bot_token}",
                },
            )

    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token=bot_token, telegram_chat_id=chat_id),
    )
    monkeypatch.setattr(telegram.httpx, "AsyncClient", lambda **_kwargs: FakeAsyncClient())

    with pytest.raises(RuntimeError) as error:
        asyncio.run(telegram.send_telegram_message("Reporte de prueba"))

    message = str(error.value)
    assert "HTTP 400" in message
    assert "chat not found" in message
    assert bot_token not in message
    assert chat_id not in message
