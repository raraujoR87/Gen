"""JWT authentication for the API gateway.

Validates bearer tokens signed with ``JWT_SECRET`` (env var) using PyJWT, and
exposes a FastAPI dependency, ``get_current_user_id``, that resolves the
authenticated user's id from the token's ``sub`` claim.
"""
from __future__ import annotations

import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

_bearer_scheme = HTTPBearer(auto_error=True)


def _get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        # Fail closed: without a configured secret we cannot safely validate
        # tokens, so every request must be rejected rather than silently
        # trusting an empty/default secret.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    return secret


def decode_token(token: str) -> dict:
    """Decode and validate a JWT, raising HTTPException(401) on failure."""
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency resolving the authenticated user id from a bearer JWT."""
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(user_id)
