"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import ACTION_LOGIN, ACTION_LOGOUT, log_audit
from ..config import settings
from ..db import get_db
from ..models import User
from ..security import AuthContext, create_token, require_auth, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_token(user)
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
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
    db.commit()
    return {"ok": True}
