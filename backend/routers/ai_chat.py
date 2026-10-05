"""REST endpoint for the optional local safety assistant."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.core.dependencies import current_claims
from backend.core.rate_limit import limiter
from backend.models.schemas import ChatRequest, ChatResponse
from backend.services.assistant import ask_local_model

router = APIRouter(prefix="/chat", tags=["assistant"])


@router.post("", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat(
    payload: ChatRequest,
    request: Request,
    _claims: Annotated[dict, Depends(current_claims)],
) -> ChatResponse:
    latest = getattr(request.app.state, "latest_event", None)
    context = "Sin telemetría reciente."
    if latest:
        context = "Último evento validado: " + json.dumps(latest, ensure_ascii=True)
    response = await ask_local_model(payload.message, context)
    source = "local-model" if request.app.state.settings.local_ai_url else "configuration"
    return ChatResponse(response=response, source=source)
