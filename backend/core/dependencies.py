"""Shared HTTP authentication dependencies."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.security import decode_access_token
from backend.services.postgres_client import postgres_service

bearer_scheme = HTTPBearer(auto_error=False)


async def current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_access_token(credentials.credentials)
    if postgres_service.pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="El servicio de usuarios no está disponible")
    try:
        user = await postgres_service.get_user(str(claims["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No se pudo verificar la cuenta") from exc
    if user is None or user["role"] != claims.get("role"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sesión ya no está activa",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims["username"] = user["username"]
    return claims


async def require_operator(claims: Annotated[dict[str, Any], Depends(current_claims)]) -> dict[str, Any]:
    if claims.get("role") not in {"admin", "operator"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permisos insuficientes")
    return claims


async def require_admin(claims: Annotated[dict[str, Any], Depends(current_claims)]) -> dict[str, Any]:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere perfil Administrador")
    return claims
