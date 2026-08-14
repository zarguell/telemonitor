---
title: Configuration
description: Environment variable reference for Telemonitor — database, secrets, simulator, retention, and the collector control API.
---

All configuration is environment-based. Copy `.env.example` to `.env` and fill
in the four required values (generation one-liners are in `.env.example`):
`TM_SECRET_KEY`, `TM_AUTH_SECRET`, `TM_COLLECTOR_CONTROL_TOKEN`,
`TM_SEED_ADMIN_PASSWORD`.

## Variables

| Variable | Purpose |
|---|---|
| `TM_DATABASE_URL` | SQLAlchemy DSN (psycopg3) |
| `TM_PROCRASTINATE_DATABASE_URL` / `DATABASE_URL` | Procrastinate DSN (plain psycopg) |
| `TM_SECRET_KEY` | Fernet key for at-rest encryption of API hash, session, bot tokens. **Required in production** — deployment secret manager |
| `TM_AUTH_SECRET` | JWT signing secret |
| `TM_SIMULATE_TELEGRAM` | `1` = simulated account, `0` = real Telethon |
| `TM_COLLECTOR_CONTROL_URL` / `TM_COLLECTOR_CONTROL_TOKEN` | Private API→collector channel |
| `TM_DEFAULT_RETENTION_DAYS` | Initial content retention (admin-configurable in UI) |
| `TM_MEDIA_DIR` | Local filesystem media store root (when media storage is enabled) |
| `TM_MEDIA_STORE` | Media store backend selector (default: local filesystem) |
| `TM_MEDIA_MAX_BYTES` | Size cap for stored media objects |
| `TM_ALLOWED_WEBHOOK_HOSTS` | Explicit bypass of webhook SSRF guards (test environments only) |
| `TM_ENVIRONMENT` | `development` enables OpenAPI docs; anything else disables them |

## Development credentials (not secrets)

Everything credential-like in the repository is a **development/test value** —
there are no real secrets committed:

| Item | Value | Used for |
|---|---|---|
| `TM_SECRET_KEY` | generated per environment (`.env`); no committed default | Fernet at-rest encryption of API hash, Telethon session, bot tokens |
| `TM_AUTH_SECRET` / `TM_COLLECTOR_CONTROL_TOKEN` | generated per environment (`.env`); no committed default | JWT signing / collector control API guard |
| Bootstrap admin | `admin` + `TM_SEED_ADMIN_PASSWORD` (generated, `.env`) | First-login administrator |
| Simulator OTP | `12345` | Simulated Telegram one-time code (simulator only, never a real credential) |

Values from earlier commits of this repository (demo passwords, dev secrets)
are rejected at startup in every environment.

## Collector control API

The collector exposes an internal control API on port `9001` (bound to
`127.0.0.1` on the host in the dev compose; do not expose in production). It
accepts one-time codes / 2FA passwords / disconnect / discovery, and — in
simulation mode only — `POST /control/sim/message {"chat_id": ..., "text": ...}`
to inject a specific message.
