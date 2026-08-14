"""Shared test setup: test database, migrations, clean state between tests."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

os.environ.setdefault("TM_DATABASE_URL", "postgresql+psycopg://telemonitor:telemonitor@localhost:5432/telemonitor_test")
os.environ.setdefault("TM_PROCRASTINATE_DATABASE_URL", "postgresql://telemonitor:telemonitor@localhost:5432/telemonitor_test")
os.environ.setdefault("DATABASE_URL", "postgresql://telemonitor:telemonitor@localhost:5432/telemonitor_test")
os.environ.setdefault(
    "TM_SECRET_KEY",
    "test-key-kiXwYpS3vN7qL9tB2mR4cE6gH8jA1dF5uZ0xW3oV6yS=",
)
os.environ.setdefault("TM_AUTH_SECRET", "test-auth-secret")
os.environ.setdefault("TM_SIMULATE_TELEGRAM", "1")
os.environ.setdefault("TM_COLLECTOR_CONTROL_URL", "http://collector:9001")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402

_TRUNCATE = (
    "TRUNCATE telegram_configuration, worker_heartbeats, alert_messages, alert_deliveries, "
    "alerts, rule_matches, rules, indicators, message_events, messages, sources, "
    "audit_events, app_settings, users RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", os.environ["TM_DATABASE_URL"])
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    with engine.begin() as conn:
        conn.execute(text(_TRUNCATE))
    yield


@pytest.fixture()
def client(clean_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, username: str, password: str):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def login_admin(client):
    return login(client, "admin", "admin123")


def login_operator(client):
    return login(client, "operator", "operator123")


def login_analyst(client):
    return login(client, "analyst", "analyst123")
