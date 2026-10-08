"""OpenRouter chat-completions client. API keys never leave the backend."""

from typing import Any

import httpx

from backend.config import get_settings


class OpenRouterError(RuntimeError):
    pass


async def create_completion(messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise OpenRouterError("Argus no está configurado: falta OPENROUTER_API_KEY")

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    headers["X-OpenRouter-Title"] = settings.openrouter_app_name
    payload: dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": messages,
        "max_tokens": 1200,
        "temperature": 0.2,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=8)) as client:
            response = await client.post(
                f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise OpenRouterError("No se pudo conectar con OpenRouter") from exc

    if response.status_code == 401:
        raise OpenRouterError("OpenRouter rechazó la API key configurada")
    if response.status_code == 402:
        raise OpenRouterError("La cuenta de OpenRouter no tiene créditos disponibles")
    if response.status_code == 429:
        raise OpenRouterError("OpenRouter limitó temporalmente las solicitudes")
    if response.status_code >= 500:
        raise OpenRouterError("El proveedor de OpenRouter no está disponible temporalmente")
    if not response.is_success:
        raise OpenRouterError(f"OpenRouter rechazó la solicitud (HTTP {response.status_code})")

    try:
        result = response.json()
        choices = result["choices"]
        message = choices[0]["message"]
        if not isinstance(message, dict):
            raise TypeError("Invalid message")
        return message
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise OpenRouterError("OpenRouter devolvió una respuesta incompleta") from exc
