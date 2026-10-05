"""JWT creation and verification helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from jose import JWTError, jwt

from backend.config import get_settings


def create_access_token(*, subject: str, role: str, email: str = "") -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": str(uuid4()),
        "iss": "aegis-lock-api",
        "aud": "aegis-lock-dashboard",
        "type": "access",
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="aegis-lock-dashboard",
            issuer="aegis-lock-api",
        )
        if claims.get("type") != "access" or not claims.get("sub"):
            raise JWTError("Invalid access token")
        return claims
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas o token expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
