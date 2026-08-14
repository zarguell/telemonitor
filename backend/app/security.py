"""Authentication & authorization: PBKDF2 password hashing, signed JWT cookies, RBAC deps."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Roles, User

PBKDF2_ITERATIONS = 260_000


# --- Password hashing (stdlib only) ---


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# --- JWT ---


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=settings.auth_ttl_hours),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# --- FastAPI dependencies ---


class AuthContext:
    def __init__(self, user: User, token_payload: dict, request: Request):
        self.user = user
        self.token_payload = token_payload
        self.request = request

    @property
    def ip_address(self) -> str | None:
        return self.request.client.host if self.request.client else None


def require_auth(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    tm_token: Annotated[str | None, Cookie(alias=settings.auth_cookie_name)] = None,
) -> AuthContext:
    if not tm_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(tm_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    user = db.scalar(select(User).where(User.id == int(payload["sub"])))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account disabled")
    return AuthContext(user=user, token_payload=payload, request=request)


def require_roles(*roles: str):
    allowed = set(roles)

    def dep(ctx: Annotated[AuthContext, Depends(require_auth)]) -> AuthContext:
        if ctx.user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return ctx

    return dep


require_admin = require_roles(Roles.ADMIN)
require_operator = require_roles(Roles.ADMIN, Roles.OPERATOR)
require_any = require_roles(Roles.ADMIN, Roles.OPERATOR, Roles.ANALYST)
