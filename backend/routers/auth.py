"""Database-backed demo login with short-lived API access JWTs."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.config import get_settings
from backend.core.dependencies import current_claims
from backend.core.passwords import hash_password, verify_password
from backend.core.rate_limit import limiter
from backend.core.security import create_access_token
from backend.models.schemas import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse, UserResponse, UserRole
from backend.services.postgres_client import postgres_service

router = APIRouter(prefix="/auth", tags=["auth"])
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-aegis-account-password")


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(payload: LoginRequest, request: Request) -> TokenResponse:
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL no está configurado")

    user = await postgres_service.get_user(payload.username)
    password_hash = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    if user is None or not password_valid:
        await postgres_service.write_audit_log(
            action="LOGIN_FAILED",
            performed_by="anonymous",
            details={"username": payload.username, "result": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    role = UserRole(user["role"])
    settings = get_settings()
    refresh_token = await postgres_service.issue_refresh_token(
        user["username"], days=settings.refresh_token_days
    )
    await postgres_service.write_audit_log(
        action="LOGIN_SUCCEEDED",
        performed_by=user["username"],
        details={"role": role.value},
    )
    return _token_response(user, refresh_token, role)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(payload: RefreshRequest, request: Request) -> TokenResponse:
    if postgres_service.pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL no está configurado")
    settings = get_settings()
    rotated = await postgres_service.rotate_refresh_token(
        payload.refresh_token, days=settings.refresh_token_days
    )
    if rotated is None:
        await postgres_service.write_audit_log(
            action="REFRESH_REJECTED",
            performed_by="anonymous",
            details={"result": "invalid_or_expired"},
        )
        raise HTTPException(status_code=401, detail="Sesión expirada; inicia sesión nuevamente")

    refresh_token, user = rotated
    return _token_response(user, refresh_token, UserRole(user["role"]))


@router.post("/logout")
@limiter.limit("20/minute")
async def logout(
    payload: LogoutRequest,
    request: Request,
) -> dict[str, bool]:
    username = await postgres_service.revoke_refresh_token(payload.refresh_token)
    if username:
        await postgres_service.write_audit_log(action="LOGOUT", performed_by=username, details={})
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
@limiter.limit("60/minute")
async def me(request: Request, claims: Annotated[dict[str, Any], Depends(current_claims)]) -> UserResponse:
    return UserResponse(id=claims["sub"], username=claims.get("username", claims["sub"]), role=claims["role"])


def _token_response(user: dict[str, Any], refresh_token: str, role: UserRole) -> TokenResponse:
    access_token, expires_in = create_access_token(
        subject=user["username"], role=role.value, email=user["username"]
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserResponse(id=user["username"], username=user["username"], role=role),
    )
