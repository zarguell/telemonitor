"""Application configuration via environment variables (TM_ prefix)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TM_", env_file=".env", extra="ignore")

    app_name: str = "Telemonitor"
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
    delivery_max_attempts: int = 5
    reprocess_stale_minutes: int = 2

    # Default retention (days) applied on first boot
    default_retention_days: int = 90

    # Seed admin credentials (dev only; replace in production)
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"
    seed_admin_email: str = "admin@example.invalid"

    # Simulated Telegram account details used when TM_SIMULATE_TELEGRAM=1
    sim_phone: str = "+15550001111"
    sim_otp: str = "12345"
    sim_dialogs: int = 3

    @property
    def secret_key_bytes(self) -> bytes:
        return self.secret_key.encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
