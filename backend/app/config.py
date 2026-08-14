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

    # No default: must be provided via .env / secret management (never committed).
    auth_secret: str = ""
    auth_ttl_hours: int = 12
    auth_cookie_name: str = "tm_token"

    simulate_telegram: bool = False

    # No default: must be provided via .env / secret management.
    collector_control_token: str = ""
    collector_control_port: int = 9001
    collector_control_url: str = "http://collector:9001"

    log_level: str = "INFO"
    redact_logging: bool = True

    webhook_timeout_seconds: int = 10
    # Media storage (images): backend + limits. The operator-facing enable
    # toggle lives in app settings; these are deployment configuration.
    media_store: str = "local"  # local (S3 can be added behind MediaStore)
    media_dir: str = "/data/media"
    media_max_bytes: int = 10 * 1024 * 1024

    # Explicit allowlist of webhook destination hostnames (comma-separated) that
    # bypass the private-range SSRF guard (test environments only; empty in production).
    allowed_webhook_hosts: str = ""
    delivery_max_attempts: int = 5
    reprocess_stale_minutes: int = 2

    # Default retention (days) applied on first boot
    default_retention_days: int = 90

    # Bootstrap admin: the username is not a secret, the password MUST be
    # provided via .env / secret management — there is no default.
    seed_admin_username: str = "admin"
    seed_admin_password: str = ""
    seed_admin_email: str = "admin@example.invalid"

    # Simulated Telegram account details used when TM_SIMULATE_TELEGRAM=1
    sim_otp: str = "12345"


_KNOWN_LEAKED = {
    # Values that existed in earlier commits of this repository. Any of these
    # must be rejected in EVERY environment — they are public knowledge.
    "auth_secret": {"change-me-auth-secret", "local-dev-auth-secret-change-me"},
    "collector_control_token": {"dev-control-token"},
    "secret_key": {"kiXwYpS3vN7qL9tB2mR4cE6gH8jA1dF5uZ0xW3oV6yS="},
    "seed_admin_password": {"admin123"},
}


def validate_config(settings: Settings) -> list[str]:
    """Return a list of configuration problems that must be fixed before boot.

    Secrets have NO defaults and leaked historical values are rejected in every
    environment.
    """
    problems: list[str] = []
    if not settings.secret_key or settings.secret_key in _KNOWN_LEAKED["secret_key"]:
        problems.append("TM_SECRET_KEY must be a strong, non-committed Fernet key")
    if settings.auth_secret in _KNOWN_LEAKED["auth_secret"] or len(settings.auth_secret) < 16:
        problems.append("TM_AUTH_SECRET must be a strong, non-committed secret")
    if not settings.collector_control_token or settings.collector_control_token in _KNOWN_LEAKED["collector_control_token"]:
        problems.append("TM_COLLECTOR_CONTROL_TOKEN must be a strong, non-committed secret")
    if not settings.seed_admin_password or settings.seed_admin_password in _KNOWN_LEAKED["seed_admin_password"]:
        problems.append("TM_SEED_ADMIN_PASSWORD must be a non-committed password")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
