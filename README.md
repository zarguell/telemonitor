# Telemonitor

An internal, operator-managed application that monitors explicitly approved
Telegram channels using an organization-controlled Telegram account. It ingests
permitted messages, retains searchable records, runs deterministic monitors
(keywords, phrases, regex, extracted indicators), and notifies operators when a
rule matches.

**Status:** MVP implementation of the PRD in `docs/PRD.md` (see repo). Source
posts are presented as **unverified claims** with preserved provenance; any
external action requires human review. No LLM, embeddings, semantic search, or
automated attribution is used anywhere in the pipeline.

## Architecture

| Component | Technology | Responsibility |
|---|---|---|
| Web UI | React 18 + Vite + TypeScript (nginx) | Operator configuration, search, rules, alert triage |
| API | Python FastAPI | Auth/RBAC, configuration, query API, orchestration |
| Collector | Python Telethon (or built-in simulator) | Account connection, auth flow, discovery, new-message events |
| Workers | Procrastinate (on PostgreSQL) | Realtime processing, alert delivery, backfill, maintenance |
| Database | PostgreSQL 16 (single instance) | Operational state, messages, search, queue, rules, alerts, audits |
| Migrations | Alembic | Versioned schema |

Queue layout (Procrastinate, backed by the same PostgreSQL):

- `realtime` — normalize, extract indicators, evaluate rules, create alert candidates
- `alerts` — deliver notifications, retry failed delivery, close dedupe windows
- `backfill` — paginated historical fetch + checkpoints (isolated in the collector process, concurrency 1)
- `maintenance` — retention cleanup, stale-job recovery, source reconciliation, worker health

## Development credentials (not secrets)

Everything credential-like in this repository is a **development/test value** —
there are no real secrets committed:

| Item | Value | Used for |
|---|---|---|
| `TM_SECRET_KEY` (compose) | `kiXwYpS3vN7qL9tB2mR4cE6gH8jA1dF5uZ0xW3oV6yS=` | Fernet at-rest encryption of API hash, Telethon session, bot tokens in the **local dev database only** |
| Demo users | `admin/admin123`, `operator/operator123`, `analyst/analyst123` | Local logins only |
| Simulator OTP | `12345` | Simulated Telegram one-time code |

**Do not use these values with real data.** Anyone with the repository can
decrypt anything encrypted with the dev `TM_SECRET_KEY`, and the demo passwords
are public. In production:

- Set `TM_SECRET_KEY` from deployment secret management (generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
- Never authorize a real Telegram account while running with the dev key —
  its session would be recoverable by anyone with repo access.
- Replace all demo users before exposing the deployment.

See [Configuration](#configuration-environment) and the security properties
below.

## Screenshots

All pages of the operator UI (captured against the local stack in simulated mode):

| Page | Screenshot |
|---|---|
| Overview | ![Overview](docs/screenshots/overview.webp) |
| Telegram Configuration | ![Telegram](docs/screenshots/telegram.webp) |
| Sources | ![Sources](docs/screenshots/sources.webp) |
| Rules | ![Rules](docs/screenshots/rules.webp) |
| Alerts | ![Alerts](docs/screenshots/alerts.webp) |
| Search | ![Search](docs/screenshots/search.webp) |
| Settings | ![Settings](docs/screenshots/settings.webp) |
| Audit Log | ![Audit Log](docs/screenshots/audit.webp) |

## Quick start (local Docker)

```bash
docker compose up -d --build
```

This starts PostgreSQL, migrations, API (`:8000`), collector (simulated Telegram),
worker, and web UI (`http://localhost:8080`). Demo accounts:

| Role | Username | Password | Permissions |
|---|---|---|---|
| Administrator | `admin` | `admin123` | Everything: settings, users, retention, destinations |
| Operator | `operator` | `operator123` | Telegram config, sources, rules, search, triage |
| Analyst | `analyst` | `analyst123` | Search + alert triage only |

### Simulated Telegram mode

`TM_SIMULATE_TELEGRAM=1` (default in the compose file) replaces the real
Telethon client with a deterministic simulator:

- 3 channels: `@sec_alerts`, `@threat_intel_daily`, `@ops_notifications`
- one-time code: `12345`
- deterministic history (15-minute slots) so backfill is resumable and repeatable
- live messages every 20s plus an injection endpoint (see below)

Set `TM_SIMULATE_TELEGRAM=0` and enter real `api_id`/`api_hash`/phone in the
Telegram Configuration page to use a real account.

## Testing

```bash
# Backend unit/integration tests (against the telemonitor_test database)
docker compose exec -T -e TM_DATABASE_URL=postgresql+psycopg://telemonitor:telemonitor@db:5432/telemonitor_test \
  -e TM_PROCRASTINATE_DATABASE_URL=postgresql://telemonitor:telemonitor@db:5432/telemonitor_test \
  -e DATABASE_URL=postgresql://telemonitor:telemonitor@db:5432/telemonitor_test \
  -e TM_SECRET_KEY=test-key-kiXwYpS3vN7qL9tB2mR4cE6gH8jA1dF5uZ0xW3oV6yS= \
  api python -m pytest tests/ -q

# End-to-end test against the running stack (82 assertions):
# auth + RBAC, full Telegram auth flow, discovery + allowlist, backfill,
# live message -> alert -> webhook delivery, deduplication, triage,
# backfill interrupt/resume, retention cleanup, audit + secret hygiene, UI.
python3 scripts/e2e.py
```

## Configuration (environment)

| Variable | Purpose |
|---|---|
| `TM_DATABASE_URL` | SQLAlchemy DSN (psycopg3) |
| `TM_PROCRASTINATE_DATABASE_URL` / `DATABASE_URL` | Procrastinate DSN (plain psycopg) |
| `TM_SECRET_KEY` | Fernet key for at-rest encryption of API hash, session, bot tokens. **Required in production** — deployment secret manager |
| `TM_AUTH_SECRET` | JWT signing secret |
| `TM_SIMULATE_TELEGRAM` | `1` = simulated account, `0` = real Telethon |
| `TM_COLLECTOR_CONTROL_URL` / `TM_COLLECTOR_CONTROL_TOKEN` | Private API→collector channel |
| `TM_RETENTION_DAYS_DEFAULT` | Initial content retention (admin-configurable in UI) |

The collector exposes an internal control API on port `9001` (bound to
`127.0.0.1` on the host in the dev compose; do not expose in production). It
accepts one-time codes / 2FA passwords / disconnect / discovery, and — in
simulation mode only — `POST /control/sim/message {"chat_id": ..., "text": ...}`
to inject a specific message.

## Security properties

- All API routes except `GET /api/v1/health` require authentication (httpOnly
  signed cookie) with role-based access control (admin / operator / analyst).
- API hash, Telegram session, and bot tokens are encrypted at rest (Fernet).
  One-time codes and 2FA passwords exist in process memory only, are never
  persisted, and are redacted from logs and audit payloads (verified by the E2E
  suite's secret-hygiene checks).
- Message content, phone numbers, and credentials are redacted from logs by a
  global logging filter.
- Telegram configuration changes, source allowlist changes, rule changes,
  searches, alert triage, settings changes, and user management are audited in
  `audit_events` with sanitized details only.
- Allowlist is enforced server-side: the collector ignores every message from a
  chat that is not both allowlisted and enabled.
- Retention (default 90 days) deletes message content, indicators, rule matches,
  and search records; audit metadata is preserved.

## API surface (v1)

`GET /api/v1/health`, `auth/*`, `telegram/*` (status, initialize, phone, code,
password, disconnect, test), `sources` (+ `discovered`, PATCH/DELETE),
`rules` (+ `test`), `search`, `alerts` (+ triage PATCH), `settings`
(+ destination test), `users`, `audit`, `overview` — see
`backend/app/api/` for details or the OpenAPI docs at `/docs` (auth required).

## Reliability

- Message writes are idempotent on `(source_id, telegram_message_id)`; duplicate
  Telegram events cannot create duplicate messages or alerts.
- A message persisted before a crash is re-enqueued by the maintenance worker.
- Alert delivery is decoupled from alert creation and retried with backoff.
- Backfill checkpoints per source and resumes after interruption (verified by
  the E2E interrupt/resume test).

## Deployment notes

- Single private VM / container environment per the PRD: API, collector, worker,
  one PostgreSQL with backups, reverse proxy with TLS.
- Use separate database roles for API, collector, worker, and read-only
  reporting access.
- Set `TM_SECRET_KEY`, `TM_AUTH_SECRET`, and admin credentials via deployment
  secret management; never in the operator UI.
- Retention value must be approved for the deployment environment before
  production use.
