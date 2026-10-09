"""Optional OpenAI-compatible local model adapter (for example, Ollama)."""

import httpx

from backend.config import get_settings


async def ask_local_model(message: str, building_context: str) -> str:
    settings = get_settings()
    if not settings.local_ai_url:
        return (
            "El asistente local aún no está conectado. Configura LOCAL_AI_URL para apuntar "
            "a un endpoint OpenAI-compatible local (por ejemplo, Ollama)."
        )

    endpoint = settings.local_ai_url.rstrip("/")
    if not endpoint.endswith("/v1/chat/completions"):
        endpoint = f"{endpoint}/v1/chat/completions"
    payload = {
        "model": settings.local_ai_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres el asistente local de seguridad AEGIS LOCK. Basa tus respuestas "
                    "en el estado recibido y no inventes lecturas.\n" + building_context
                ),
            },
            {"role": "user", "content": message},
        ],
        "temperature": 0.2,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return "No fue posible obtener respuesta del modelo local. Revisa su estado y LOCAL_AI_URL."
