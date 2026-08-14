"""Application configuration via environment variables (TM_ prefix)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TM_", env_file=".env", extra="ignore")

    environment: str = "development"

    # SQLAlchemy URL (psycopg3 driver)
    database_url: str = "postgresql+psycopg://telemonitor:telemonitor@db:5432/telemonitor"
    # Plain URL for Procrastinate (reads DATABASE_URL env by default; fall back to this)
    procrastinate_database_url: str = "postgresql://telemonitor:telemonitor@db:5432/telemonitor"

    # Fernet key for at-rest encryption of API hash / session / bot tokens.
    # Required in production; dev builds derive a per-process key when unset.
    secret_key: str = ""

    auth_secret: str = "change-me-auth-secret"
    auth_ttl_hours: int = 12
    auth_cookie_name: str = "tm_token"

    simulate_telegram: bool = False

    collector_control_token: str = "dev-control-token"
    collector_control_port: int = 9001
    collector_control_url: str = "http://collector:9001"

    log_level: str = "INFO"
    redact_logging: bool = True

    webhook_timeout_seconds: int = 10
    # Explicit allowlist of webhook destination hostnames (comma-separated) that
    # bypass the private-range SSRF guard (test environments only; empty in production).
    allowed_webhook_hosts: str = ""
    delivery_max_attempts: int = 5
    reprocess_stale_minutes: int = 2

    # Default retention (days) applied on first boot
    default_retention_days: int = 90

    # Seed admin credentials (dev only; replace in production)
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"
    seed_admin_email: str = "admin@example.invalid"

    # Simulated Telegram account details used when TM_SIMULATE_TELEGRAM=1
    sim_otp: str = "12345"


_INSECURE_DEFAULTS = {
    "auth_secret": {"change-me-auth-secret", "local-dev-auth-secret-change-me"},
    "collector_control_token": {"dev-control-token", ""},
}


def validate_config(settings: Settings) -> list[str]:
    """Return a list of configuration problems that must be fixed before boot.

    In non-development environments, insecure default secrets are fatal.
    """
    problems: list[str] = []
    if settings.environment != "development":
        if not settings.secret_key:
            problems.append("TM_SECRET_KEY is required outside development")
        if settings.auth_secret in _INSECURE_DEFAULTS["auth_secret"] or len(settings.auth_secret) < 16:
            problems.append("TM_AUTH_SECRET must be a strong, deployment-managed secret outside development")
        if settings.collector_control_token in _INSECURE_DEFAULTS["collector_control_token"]:
            problems.append("TM_COLLECTOR_CONTROL_TOKEN must be a strong, deployment-managed secret outside development")
        if settings.seed_admin_password == "admin123":
            problems.append("TM_SEED_ADMIN_PASSWORD must be changed outside development")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
