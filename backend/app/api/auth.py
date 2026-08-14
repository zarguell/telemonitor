"""Authentication endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import ACTION_LOGIN, ACTION_LOGIN_FAILED, ACTION_LOGOUT, log_audit
from ..config import settings
from ..db import get_db
from ..models import User
from ..security import AuthContext, create_token, require_auth, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# In-process fixed-window rate limiting for the login endpoint (single API
# process; sufficient for the MVP deployment). Per username AND per IP.
_MAX_FAILURES = 10
_WINDOW_SECONDS = 300

_failures: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def _throttle(key: str) -> None:
    now = time.monotonic()
    with _lock:
        dq = _failures[key]
        while dq and now - dq[0] > _WINDOW_SECONDS:
            dq.popleft()
        if len(dq) >= _MAX_FAILURES and (now - dq[0]) < _WINDOW_SECONDS:
            raise HTTPException(status_code=429, detail="Too many failed login attempts; try again later")
        dq.append(now)
        # prune old entries so the dict does not grow unboundedly
        if len(_failures) > 10_000:
            for k in [k for k, v in _failures.items() if not v]:
                del _failures[k]


def _record_success(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "display_name": u.display_name,
        "email": u.email,
        "is_active": u.is_active,
    }


def _cookie_secure() -> bool:
    return settings.environment != "development"


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else None
    _throttle(f"user:{body.username}")
    # Only throttle real IP addresses (TestClient uses a non-IP identifier).
    if client_ip and any(ch in client_ip for ch in ".:"):
        _throttle(f"ip:{client_ip}")
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        log_audit(
            db,
            actor_user_id=None,
            actor_username=body.username,
            action=ACTION_LOGIN_FAILED,
            object_type="user",
            ip_address=client_ip,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    _record_success(f"user:{body.username}")
    token = create_token(user)
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=settings.auth_ttl_hours * 3600,
        path="/",
    )
    log_audit(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        action=ACTION_LOGIN,
        object_type="user",
        object_id=str(user.id),
    )
    return {"user": _user_dict(user)}


@router.post("/logout")
def logout(
    response: Response,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_LOGOUT,
        ip_address=ctx.ip_address,
    )
    # Revoke all previously issued tokens for this user.
    ctx.user.token_version += 1
    db.commit()
    response.delete_cookie(settings.auth_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: AuthContext = Depends(require_auth)):
    return {"user": _user_dict(ctx.user)}


@router.post("/password")
def change_password(
    body: PasswordChangeRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    from ..security import hash_password

    ctx.user.password_hash = hash_password(body.new_password)
    ctx.user.token_version += 1  # revoke existing sessions on password change
    db.commit()
    return {"ok": True}
