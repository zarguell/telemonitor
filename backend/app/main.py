"""Telemonitor FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .audit import ensure_seeded_settings
from .config import settings
from .db import db_session
from .redact import install_redaction
from .security import hash_password
from .services import telegram_client

logger = logging.getLogger("telemonitor.api")


def _seed_users() -> None:
    from sqlalchemy import select

    from .models import Roles, User

    db = db_session()
    try:
        defaults = [
            (settings.seed_admin_username, settings.seed_admin_password, Roles.ADMIN, "Administrator", settings.seed_admin_email),
            ("operator", "operator123", Roles.OPERATOR, "Operator", "operator@example.invalid"),
            ("analyst", "analyst123", Roles.ANALYST, "Analyst", "analyst@example.invalid"),
        ]
        for username, password, role, display, email in defaults:
            if db.scalar(select(User).where(User.username == username)) is None:
                db.add(
                    User(
                        username=username,
                        password_hash=hash_password(password),
                        role=role,
                        display_name=display,
                        email=email,
                    )
                )
        db.commit()
        logger.info("seeded default users")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_redaction()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _seed_users()
    db = db_session()
    try:
        ensure_seeded_settings(db)
    finally:
        db.close()
    from .jobs import ensure_open

    ensure_open()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Telemonitor API", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .api import alerts, auditlog, auth, health, overview, rules, search, settings_api, sources, telegram, users

    for router in (
        health.router,
        auth.router,
        telegram.router,
        sources.router,
        rules.router,
        search.router,
        alerts.router,
        settings_api.router,
        users.router,
        auditlog.router,
        overview.router,
    ):
        app.include_router(router, prefix="/api/v1")

    return app


app = create_app()
