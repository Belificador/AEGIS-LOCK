"""Authenticated Argus chat endpoint."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.dependencies import current_claims
from backend.core.rate_limit import limiter
from backend.models.schemas import ChatRequest, ChatResponse
from backend.agents.argus.agent import ask_argus
from backend.agents.argus.client import OpenRouterError

router = APIRouter(prefix="/chat", tags=["assistant"])


@router.post("", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat(
    payload: ChatRequest,
    request: Request,
    claims: Annotated[dict, Depends(current_claims)],
) -> ChatResponse:
    try:
        response = await ask_argus(payload.message, claims)
    except OpenRouterError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatResponse(response=response, source="openrouter-argus")
