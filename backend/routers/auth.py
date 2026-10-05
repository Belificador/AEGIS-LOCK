"""Supabase-backed login with short-lived API access JWTs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.dependencies import current_claims
from backend.core.rate_limit import limiter
from backend.core.security import create_access_token
from backend.models.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    UserRole,
)
from backend.services.supabase_client import supabase_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(payload: LoginRequest, request: Request) -> TokenResponse:
    client = supabase_service.client
    if client is None:
        raise HTTPException(status_code=503, detail="Autenticación Supabase no configurada")

    try:
        result = await client.auth.sign_in_with_password(
            {"email": payload.username, "password": payload.password}
        )
    except Exception as exc:
        # Do not return upstream errors: they may contain provider details.
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos") from exc

    user = getattr(result, "user", None)
    session = getattr(result, "session", None)
    if user is None or session is None:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    role = _trusted_role(user)
    return _token_response(user, session.refresh_token, role)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(payload: RefreshRequest, request: Request) -> TokenResponse:
    client = supabase_service.client
    if client is None:
        raise HTTPException(status_code=503, detail="Autenticación Supabase no configurada")
    try:
        result = await client.auth.refresh_session(payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sesión expirada; inicia sesión nuevamente") from exc

    user = getattr(result, "user", None)
    session = getattr(result, "session", None)
    if user is None or session is None:
        raise HTTPException(status_code=401, detail="Sesión expirada; inicia sesión nuevamente")
    return _token_response(user, session.refresh_token, _trusted_role(user))


@router.get("/me", response_model=UserResponse)
async def me(claims: Annotated[dict[str, Any], Depends(current_claims)]) -> UserResponse:
    return UserResponse(id=claims["sub"], email=claims.get("email", ""), role=claims["role"])


def _trusted_role(user: Any) -> UserRole:
    app_metadata = getattr(user, "app_metadata", None) or {}
    role_value = app_metadata.get("role") if isinstance(app_metadata, dict) else None
    if role_value not in {UserRole.ADMIN.value, UserRole.OPERATOR.value}:
        raise HTTPException(status_code=403, detail="La cuenta no tiene un perfil de acceso asignado")
    try:
        return UserRole(role_value)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="La cuenta tiene un rol no autorizado") from exc


def _token_response(user: Any, refresh_token: str, role: UserRole) -> TokenResponse:
    email = str(getattr(user, "email", ""))
    access_token, expires_in = create_access_token(subject=str(user.id), role=role.value, email=email)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserResponse(id=str(user.id), email=email, role=role),
    )
