"""User management (Administrators only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import ACTION_USER_CREATE, ACTION_USER_UPDATE, log_audit
from ..db import get_db
from ..models import Roles, User
from ..security import AuthContext, hash_password, require_admin

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = Roles.ANALYST
    display_name: str | None = None
    email: str | None = None


class UserPatch(BaseModel):
    role: str | None = None
    display_name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    password: str | None = None


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "display_name": u.display_name,
        "email": u.email,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("")
def list_users(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.username)).all()
    return {"items": [_user_dict(u) for u in users], "total": len(users)}


@router.post("")
def create_user(
    body: UserCreate,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if body.role not in (Roles.ADMIN, Roles.OPERATOR, Roles.ANALYST):
        raise HTTPException(status_code=400, detail="invalid role")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
        email=body.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_USER_CREATE,
        object_type="user",
        object_id=str(user.id),
        detail={"username": user.username, "role": user.role},
        ip_address=ctx.ip_address,
    )
    return _user_dict(user)


@router.patch("/{user_id}")
def patch_user(
    user_id: int,
    body: UserPatch,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if body.role is not None:
        if body.role not in (Roles.ADMIN, Roles.OPERATOR, Roles.ANALYST):
            raise HTTPException(status_code=400, detail="invalid role")
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.email is not None:
        user.email = body.email
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="password must be at least 8 characters")
        user.password_hash = hash_password(body.password)
    db.commit()
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_USER_UPDATE,
        object_type="user",
        object_id=str(user.id),
        detail={"username": user.username},
        ip_address=ctx.ip_address,
    )
    return _user_dict(user)
