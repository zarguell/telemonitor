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
    "NNoDAtgT8_rx484fmVn3681s9qS6UssOBDFk2DGR1Io=",
)
os.environ.setdefault("TM_AUTH_SECRET", "test-auth-secret-at-least-16")
os.environ.setdefault("TM_COLLECTOR_CONTROL_TOKEN", "test-control-token-9f3a")
os.environ.setdefault("TM_SEED_ADMIN_PASSWORD", "test-admin-password-x7")
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
    "audit_events, app_settings, users, procrastinate_jobs, procrastinate_events, "
    "procrastinate_workers RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", os.environ["TM_DATABASE_URL"])
    command.upgrade(cfg, "head")
    from app.jobs import ensure_open

    ensure_open()  # creates the procrastinate queue schema in the test DB
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    with engine.begin() as conn:
        conn.execute(text(_TRUNCATE))
    yield


# Test-only accounts (created per test by the client fixture; these values are
# fixtures, not product defaults).
ADMIN_PASSWORD = "test-admin-password-x7"
OPERATOR_PASSWORD = "test-operator-password-x7"
ANALYST_PASSWORD = "test-analyst-password-x7"


def _ensure_test_users() -> None:
    """Create operator/analyst test accounts (the app bootstraps only admin)."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Roles, User
    from app.security import hash_password

    db = SessionLocal()
    try:
        for username, password, role, display in (
            ("operator", OPERATOR_PASSWORD, Roles.OPERATOR, "Operator"),
            ("analyst", ANALYST_PASSWORD, Roles.ANALYST, "Analyst"),
        ):
            if db.scalar(select(User).where(User.username == username)) is None:
                db.add(
                    User(
                        username=username,
                        password_hash=hash_password(password),
                        role=role,
                        display_name=display,
                        email=f"{username}@example.invalid",
                    )
                )
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client(clean_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        _ensure_test_users()
        yield c


def login(client, username: str, password: str):
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def login_admin(client):
    return login(client, "admin", ADMIN_PASSWORD)


def login_operator(client):
    return login(client, "operator", OPERATOR_PASSWORD)


def login_analyst(client):
    return login(client, "analyst", ANALYST_PASSWORD)
