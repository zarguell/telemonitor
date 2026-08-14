---
title: Architecture
description: Components, queue layout, data model, and reliability properties of Telemonitor.
---

## Components

| Component | Technology | Responsibility |
|---|---|---|
| Web UI | React 18 + Vite + TypeScript (nginx) | Operator configuration, search, rules, alert triage |
| API | Python FastAPI | Auth/RBAC, configuration, query API, orchestration |
| Collector | Python Telethon (or built-in simulator) | Account connection, auth flow, discovery, new-message events |
| Workers | Procrastinate (on PostgreSQL) | Realtime processing, alert delivery, backfill, maintenance |
| Database | PostgreSQL 18 (single instance) | Operational state, messages, search, queue, rules, alerts, audits |
| Migrations | Alembic | Versioned schema |

## Queue layout

Procrastinate, backed by the same PostgreSQL:

| Queue | Job types |
|---|---|
| `realtime` | Normalize message, extract indicators, evaluate rules, create alert candidates |
| `alerts` | Deliver notifications, retry failed delivery, close dedupe windows |
| `backfill` | Paginated historical fetch + checkpoints (isolated in the collector process, concurrency 1) |
| `maintenance` | Retention cleanup, stale-job recovery, source reconciliation, worker health |

The Telethon event handler persists a new message quickly and defers all
post-processing to the `realtime` queue. Backfill concurrency is capped and
isolated from realtime processing; at most one active backfill runs per source.

## Data model

Core entities (see `docs/PRD.md` §10 for the full schema): `telegram_configuration`,
`sources`, `messages`, `message_events`, `indicators`, `rules`, `rule_matches`,
`alerts`, `alert_deliveries`, `audit_events`.

Key constraints and indexes:

- Unique message key `(source_id, telegram_message_id)` — duplicate Telegram events cannot create duplicate messages or alerts.
- Full-text index over `normalized_text`, plus trigram index for substring matching.
- B-tree indexes over message sent time, source + sent time, indicator value, alert state + severity, and queue-processing state.

Original message text is preserved; a separately generated normalized text is
used for matching and search. Edits/deletions are recorded as state changes or
immutable events without losing investigation provenance.

## Reliability

- Message writes are idempotent on `(source_id, telegram_message_id)`.
- A message persisted before a crash is re-enqueued by the maintenance worker.
- Alert delivery is decoupled from alert creation and retried with backoff.
- Backfill checkpoints per source and resumes after interruption (verified by
  the E2E interrupt/resume test).
- A temporary alert-destination failure never prevents alert creation.

## See also

- [Security](security) — authentication, encryption, and redaction
- [API reference](api) — the HTTP surface
