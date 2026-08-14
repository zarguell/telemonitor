"""Telemonitor FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .audit import ensure_seeded_settings
from .config import settings, validate_config
from .db import db_session
from .redact import install_redaction
from .security import hash_password
from .services import telegram_client

logger = logging.getLogger("telemonitor.api")


def _seed_users() -> None:
    """Bootstrap demo users ONLY on a fresh database (users table empty).

    Deleted demo users are never resurrected: once any user exists, seeding is
    skipped regardless of environment.
    """
    from sqlalchemy import func, select

    from .models import Roles, User

    db = db_session()
    try:
        existing = db.scalar(select(func.count(User.id))) or 0
        if existing > 0:
            return
        db.add(
            User(
                username=settings.seed_admin_username,
                password_hash=hash_password(settings.seed_admin_password),
                role=Roles.ADMIN,
                display_name="Administrator",
                email=settings.seed_admin_email,
            )
        )
        db.commit()
        logger.info("bootstrapped initial administrator (fresh database only)")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_redaction()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    problems = validate_config(settings)
    if problems:
        raise RuntimeError("Refusing to start with insecure configuration: " + "; ".join(problems))
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
    # OpenAPI docs are an information-disclosure surface; only expose them in dev.
    docs_enabled = settings.environment == "development"
    app = FastAPI(
        title="Telemonitor API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .api import alerts, auditlog, auth, health, media, overview, rules, search, settings_api, sources, telegram, users

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
        media.router,
    ):
        app.include_router(router, prefix="/api/v1")

    return app


app = create_app()
