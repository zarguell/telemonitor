---
title: Installation
description: Deployment notes for running Telemonitor in production — topology, secrets, database roles, and TLS.
---

The MVP deployment is a single private VM or container environment per the
product specification: one API process, one collector process, one or more
Procrastinate worker processes, one PostgreSQL instance with backups, and a
reverse proxy with TLS.

## Services

The `docker-compose.yml` at the repository root runs the full stack locally and
mirrors the production topology:

| Service | Role |
|---|---|
| `db` | PostgreSQL 18 (single instance) |
| `api` | FastAPI — auth/RBAC, configuration, query API, orchestration |
| `collector` | Telethon (or simulator) — account connection, discovery, new-message events |
| `worker` | Procrastinate workers — realtime processing, alert delivery, backfill, maintenance |
| `web` | nginx serving the React UI with CSP, X-Frame-Options DENY, and nosniff headers |

## Secrets

- Set `TM_SECRET_KEY`, `TM_AUTH_SECRET`, and admin credentials via deployment
  secret management — never in the operator UI.
- `TM_SECRET_KEY` is a Fernet key for at-rest encryption of the API hash,
  Telethon session, and bot tokens. Generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- Startup rejects the demo/committed default values in every environment.
  Outside `development`, the API refuses to boot with a committed default key.
- Never authorize a real Telegram account while running with a key that is
  committed or publicly known — its session would be recoverable by anyone
  with repo access.
- Replace all demo users before exposing the deployment.

## Hardening

- Use separate database roles for API, collector, worker, and read-only
  reporting access.
- The collector control API (port `9001`) is bound to `127.0.0.1` on the host
  in the dev compose — do not expose it in production.
- OpenAPI docs (`/docs`) are exposed only when `TM_ENVIRONMENT=development`.
- The retention value must be approved for the deployment environment before
  production use (default 90 days, admin-configurable).
- Backups must be encrypted and follow the same retention policy.

## See also

- [Configuration](configuration) — full environment variable reference
- [Security](security) — threat model and safeguards
