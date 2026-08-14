---
title: Product specification
description: The full product requirements document for Telemonitor — purpose, compliance boundary, functional requirements, and acceptance criteria.
---

:::note
This page mirrors [`docs/PRD.md`](https://github.com/zarguell/telemonitor/blob/main/docs/PRD.md) in the repository — that file is canonical; re-copy it here when the PRD changes.
:::

# Product Requirements Document: Telegram Monitoring MVP

**Status:** Implemented (MVP)

**Product:** Authorized Telegram Monitoring

**Audience:** Security engineering, platform engineering, threat-intelligence analysts, and operators

**Version:** MVP / initial implementation

## 1. Purpose

Build an internal, operator-managed application that monitors explicitly approved Telegram channels using a Telegram account controlled by the organization. The system must ingest permitted messages, retain searchable records, run deterministic monitors, and notify operators when a rule matches.

The MVP is an analyst-assistance and monitoring tool. It must present source posts as unverified claims, preserve provenance, and require human review before any external action.

## 2. Compliance and operating boundary

The product must operate only against chats and channels the configured Telegram account is authorized to access and that an operator has explicitly enabled in the application.

The MVP must not:

- Bypass Telegram access controls, scrape content unavailable to the configured account, or automate joining channels.
- Collect secret chats or use copied Telegram Web cookies/browser sessions.
- Enable collection from unapproved sources.
- Include an LLM, embeddings, semantic search, model training, or model-based classification of Telegram-derived content.
- Automatically make attribution, notify external parties, publish findings, or take enforcement action.

The system must include an operator acknowledgement during Telegram configuration that they are authorized to use the account and have reviewed applicable platform, privacy, and organizational requirements.

## 3. Goals

1. Allow an operator to configure one authorized Telegram user account through a secure web UI.
2. Allow an operator to explicitly select and enable accessible channels for monitoring.
3. Ingest both historical channel messages and new messages after monitoring is enabled.
4. Store messages, source metadata, edits/deletions, and deterministic extracted indicators in PostgreSQL.
5. Allow operators to create and manage deterministic keyword, phrase, regex, and indicator rules.
6. Create deduplicated alerts for rule matches and deliver them to configured internal destinations.
7. Provide a web UI to search messages, inspect source context, review alerts, and manage monitoring configuration.
8. Provide auditability, retention controls, secure handling of account session material, and operational health visibility.

## 4. Non-goals

- Multi-tenant customer-facing SaaS.
- Multiple active Telegram accounts in the first release.
- Automated channel discovery or channel joining.
- Attachment/media bulk downloading or OCR.
- LLM enrichment, entity resolution by model, embeddings, or vector search.
- Threat-intelligence scoring or source reputation automation.
- Full case-management, ticketing, or incident-response workflow.
- Distributed queue infrastructure such as Redis, RabbitMQ, Kafka, or Celery.
- ClickHouse/OpenSearch; PostgreSQL is the sole persistence and search system for the MVP.

## 5. Users and permissions

### Operator

An authenticated internal user who configures Telegram, selects approved sources, manages rules, searches content, and reviews alerts.

### Analyst

An authenticated internal user who searches data and triages alerts but cannot modify Telegram configuration or retention settings.

### Administrator

An authenticated internal user who manages access, global configuration, alert destinations, and retention policy.

### Service account

A non-human identity used by the backend services. It has no interactive UI access and only the minimum database and secret-store permissions required.

## 6. User stories

### Telegram setup

- As an operator, I can enter Telegram application credentials so the service can initialize a Telegram client.
- As an operator, I can enter the dedicated account phone number and complete Telegram's one-time-code flow.
- As an operator, I can provide the account's two-factor-authentication password only when Telegram requests it.
- As an operator, I can see whether the Telegram client is connected, awaiting a code, awaiting 2FA, authorized, disconnected, or in error.
- As an operator, I can revoke the local connection/session and reconnect the authorized account.

### Source configuration

- As an operator, I can browse the chats and channels available to the authorized account.
- As an operator, I can add a selected channel to the monitoring allowlist.
- As an operator, I can enable or disable a monitored source without leaving the channel in Telegram.
- As an operator, I can configure a historical backfill start date or choose no historical backfill.
- As an operator, I can view source state: enabled, backfilling, live, paused, error, and last successful ingestion time.

### Monitoring and alerting

- As an operator, I can create rules matching keywords, phrases, regex patterns, and extracted indicators.
- As an operator, I can combine simple conditions using ALL or ANY logic.
- As an operator, I can set a severity and deduplication window for a rule.
- As an operator, I can test a rule against a sample message before enabling it.
- As an operator, I can receive alert notifications through one approved internal alert destination.
- As an analyst, I can acknowledge, resolve, or mark an alert as false positive with a note.

### Search and investigation

- As an analyst, I can search message text across enabled sources.
- As an analyst, I can filter by source, date range, rule, alert status, indicator type, and source event type.
- As an analyst, I can inspect original text, normalized text, message timestamp, source, message identifier, reply/forward metadata, extracted indicators, rule matches, and edit/deletion state.
- As an analyst, I can open the source message in Telegram only when an official permalink is available.

## 7. Functional requirements

### 7.1 Telegram configuration UI

The application must provide a dedicated **Telegram Configuration** page, accessible only to Operators and Administrators.

#### States

The page must render one of the following states:

- Not configured
- Initialization required
- Waiting for phone number
- Waiting for one-time code
- Waiting for two-factor password
- Authorized and connected
- Reconnecting
- Disconnected
- Error

#### Inputs and actions

| Field/action | Requirement |
|---|---|
| API ID | Required numeric application identifier; validate format before submission |
| API hash | Required secret input; never display after save |
| Phone number | Required E.164-style input; masked after submission |
| One-time code | Display only after Telegram requests it; never persist in the application database or logs |
| 2FA password | Display only after Telegram requests it; never persist in the application database or logs |
| Storage encryption key | Generated and managed by deployment secret management; never entered in the routine operator UI |
| Connect | Begins the authorization-state flow |
| Submit code/password | Advances only the current authorization state |
| Disconnect/revoke local session | Stops collector and removes/invalidates local session state after a confirmation dialog |
| Test status | Verifies collector-to-Telegram connectivity without changing monitored sources |

#### Security requirements

- API hash, account session state, and session encryption key must be encrypted at rest.
- One-time codes and 2FA passwords must be handled in process memory only, redacted from logs, and never written to audit payloads.
- UI responses must not return saved secrets to the browser after initial submission.
- The system must provide a visible confirmation that the operator acknowledges responsibility for account authorization and source selection.
- A session-revoke operation must require explicit confirmation and create an audit event.

### 7.2 Source allowlist UI

The application must provide a **Sources** page.

#### Source discovery

- After authorization, the backend retrieves chats/channels visible to the configured account.
- The UI displays source title, username where available, Telegram chat ID, type, current allowlist state, and last activity metadata where available.
- Search/filter may operate on title, username, and type.
- Discovery does not automatically enable monitoring.

#### Add and configure source

Operators must be able to:

- Add a source from the accessible-source list.
- Confirm that the source is approved for monitoring.
- Select `No history`, `Last 24 hours`, `Last 7 days`, `Last 30 days`, or a custom earliest timestamp for backfill.
- Enable or pause live monitoring.
- Set an optional source label.
- View backfill progress and failure status.

The service must enforce the allowlist server-side. The collector must ignore messages from sources not present and enabled in the allowlist.

### 7.3 Message ingestion

- The collector must use Telethon as an authorized MTProto client.
- The collector must ingest new-message events only for enabled allowlisted sources.
- The collector must support paginated historical backfill for enabled sources.
- Message writes must be idempotent using `(source_id, telegram_message_id)`.
- The system must preserve original message text and separately generate normalized text for matching/search.
- The system must record message timestamp, ingestion timestamp, sender identifier when available, reply metadata, forward metadata, and media metadata.
- Media must not be downloaded by default. Store metadata only.
- The system must record edits/deletions as state changes or immutable events without losing investigation provenance.
- The system must checkpoint per-source backfill progress.

### 7.4 Deterministic extraction

The processor must extract, where recognizable:

- URLs and domains
- IPv4 and IPv6 addresses
- Email addresses
- SHA-1, SHA-256, MD5, and other validated hash-like values
- Cryptocurrency wallet addresses only when a high-confidence parser is available
- Telegram usernames/handles
- User-defined company aliases, domains, product names, and keywords

Each extracted value must retain source message reference, observed timestamp, original matched text, normalized value, extractor version, and confidence where applicable.

### 7.5 Rules and alerts

The MVP must support the following rule types:

- Case-insensitive keyword match
- Exact phrase match
- Regular expression match
- Indicator-value match
- Source match
- Simple ALL/ANY compound rules

Each rule requires:

- Name
- Description
- Enabled state
- Severity: informational, low, medium, high, critical
- Rule definition
- Optional source scope
- Deduplication window
- Creator and update timestamps

Alert requirements:

- A rule match creates an alert candidate.
- Candidates with the same deduplication key inside the configured time window must be grouped rather than repeatedly notified.
- An alert must link to the exact message(s), rule version, matching excerpt, source, and extracted indicators.
- Alert states: open, acknowledged, resolved, false positive.
- Alert delivery must be retried independently from alert creation.
- MVP notification destination: one administrator-configured webhook or one internal Telegram bot destination. The destination must be testable from the UI.

### 7.6 Search UI and API

The application must provide a **Search** page and internal API.

#### Required search behavior

- Full-text query over normalized message text.
- Case-insensitive substring support for short names and domains.
- Filters: source, date/time range, rule ID, alert state, indicator type, and message state.
- Default sort: newest first.
- Cursor or offset pagination.
- Snippet highlighting for matched terms.
- Results must include source name, sent time, message identifier, text snippet, extracted indicators, and linked alert state.

#### Initial API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness/readiness and service state |
| GET | `/api/v1/telegram/status` | Sanitized Telegram authorization/collector status |
| POST | `/api/v1/telegram/initialize` | Submit API ID/hash and initialize authorization |
| POST | `/api/v1/telegram/phone` | Submit phone number when requested |
| POST | `/api/v1/telegram/code` | Submit one-time code when requested |
| POST | `/api/v1/telegram/password` | Submit 2FA password when requested |
| POST | `/api/v1/telegram/disconnect` | Revoke local session after confirmation |
| GET | `/api/v1/sources/discovered` | List account-accessible sources |
| GET/POST | `/api/v1/sources` | List/create approved monitored sources |
| PATCH | `/api/v1/sources/{id}` | Enable, pause, relabel, or configure backfill |
| GET/POST | `/api/v1/rules` | List/create rules |
| PATCH | `/api/v1/rules/{id}` | Update/enable/disable a rule |
| POST | `/api/v1/rules/test` | Evaluate an unsaved rule against supplied sample text |
| GET | `/api/v1/search` | Search messages and extracted indicators |
| GET | `/api/v1/alerts` | List/filter alerts |
| PATCH | `/api/v1/alerts/{id}` | Update triage state and note |

### 7.7 Jobs and background processing

Use Procrastinate backed by the same PostgreSQL deployment.

Required queues:

| Queue | Job types |
|---|---|
| `realtime` | Normalize message, extract indicators, evaluate rules, create alert candidates |
| `alerts` | Deliver notifications, retry failed delivery, close dedupe windows |
| `backfill` | Fetch historical messages, checkpoint progress, retry rate-limited work |
| `maintenance` | Retention, source reconciliation, health checks, cleanup |

Requirements:

- The Telethon event handler must persist a new message quickly and defer post-processing to `realtime`.
- Jobs must be idempotent and safe to retry.
- Backfill concurrency must be capped and isolated from realtime processing.
- At most one active backfill runs for a source.
- The application must expose queue depth, oldest queued job age, failed jobs, and most recent successful job timestamps.

## 8. User interface

### Navigation

- Overview
- Telegram Configuration
- Sources
- Rules
- Alerts
- Search
- Settings
- Audit Log

### Overview page

Display:

- Telegram connection status
- Number of enabled sources
- Messages ingested in the last 24 hours
- Backfill jobs in progress
- Open alerts by severity
- Collector/worker health
- Recent ingestion or job errors

### Telegram Configuration page

The page should use a guided, step-based form:

1. Review authorization and acceptable-use acknowledgement.
2. Enter API ID and API hash.
3. Enter dedicated account phone number.
4. Enter one-time code only when prompted.
5. Enter 2FA password only when prompted.
6. Display connected account summary and collector status.

Do not display an account identifier beyond what is needed to confirm the configured account. Do not display or export secret material.

### Sources page

Two panels:

- **Accessible sources:** searchable list from the authorized account, with an action to add to monitoring.
- **Monitored sources:** enabled/paused state, label, source ID, backfill configuration/progress, last received message time, and latest error.

### Rules page

- Rule list with enabled state, severity, source scope, recent match count, and last match time.
- Rule editor with a structured simple-rule builder plus an advanced regex field.
- Warning and test action for unsafe/expensive regex patterns.
- Audit trail of rule modifications.

### Alerts page

- Filterable alert queue.
- Alert detail with rule, excerpt, source metadata, linked messages, extracted indicators, delivery status, and analyst notes.
- Triage buttons: acknowledge, resolve, false positive.

### Search page

- Query input.
- Filter controls.
- Result list with highlighted excerpts.
- Message detail drawer or page showing complete retained metadata and source context.

## 9. Technical architecture

### Components

| Component | Technology | Responsibility |
|---|---|---|
| Web UI | React/Next.js or equivalent | Operator configuration, search, rules, alert triage |
| API | Python FastAPI | Authentication, authorization, configuration, query API, orchestration |
| Collector | Python Telethon service | Authorized account connection, source discovery, new-message events, history retrieval |
| Worker | Procrastinate workers | Background ingestion processing, matching, alerts, maintenance |
| Database | PostgreSQL 13+ | Operational state, messages, search, queue, rules, alerts, audits |
| Migration tool | Alembic | Versioned schema changes |
| Secret manager | Deployment-provided | API hash, encrypted session key, notification secrets |

### Deployment

Initial deployment may be a single private VM or private container environment with:

- One API process
- One collector process
- One or more Procrastinate worker processes
- One PostgreSQL instance with backups
- A reverse proxy with TLS

Use separate process identities and database roles for API, collector, worker, and read-only reporting access.

## 10. Data model

Required entities:

- `telegram_configuration`: encrypted configuration references, authorization status, session storage location reference, configured account metadata, timestamps.
- `sources`: Telegram chat ID, title, username, type, enabled state, label, backfill configuration, checkpoints, status, timestamps.
- `messages`: source ID, Telegram message ID, sent/ingested/edited timestamps, original/normalized text, sender/reply/forward/media metadata, current state, raw permitted metadata, content hash.
- `message_events`: edits, deletes, and ingestion/provenance events where immutable tracking is selected.
- `indicators`: source message reference, indicator type/value/normalized value, extraction details.
- `rules`: definition, enabled state, severity, deduplication configuration, version, creator/updater.
- `rule_matches`: message/rule references, excerpts, rule version, match time.
- `alerts`: dedupe key, severity, state, delivery state, triage metadata.
- `alert_deliveries`: destination, attempt history, status, timestamps.
- `audit_events`: actor, action, object type/ID, timestamp, sanitized metadata.

Required constraints/indexes:

- Unique message key: `(source_id, telegram_message_id)`.
- Full-text index over `normalized_text`.
- Trigram index over `normalized_text` where supported for substring matching.
- B-tree indexes over message sent time, source ID + sent time, indicator normalized value, alert state + severity, and queue-processing state.

## 11. Security, privacy, and retention

- Require authenticated access to all UI/API routes except health endpoints appropriate for infrastructure.
- Enforce role-based access control.
- Use TLS in transit and encryption at rest for database volumes, backups, session storage, and secrets.
- Redact secrets, message content, phone numbers, and credentials from application logs by default.
- Do not store OTPs or 2FA passwords.
- Audit Telegram configuration changes, source allowlist changes, rule changes, searches, exports if later enabled, and alert triage changes.
- Default retention: 90 days for message content, configurable by an Administrator. Exact retention must be approved before production use.
- On expiration, delete message content, extracted indicators, and dependent search records according to the retention policy; preserve only minimal non-content audit metadata if required.
- Backups must be encrypted and follow the same retention policy.
- No bulk export feature in MVP.

## 12. Reliability and observability

### Required telemetry

- Telegram authorization status and last successful update time.
- Number of messages received, stored, processed, and failed.
- Source-level last received message and ingestion error.
- Backfill progress, rate, checkpoint, and failure count.
- Queue depth, retry count, failed-job count, and worker heartbeats.
- Search latency and database errors.
- Alert candidate count, deduplicated alert count, and notification delivery outcome.

### Reliability requirements

- Duplicate Telegram events must not create duplicate stored messages or alerts.
- A worker restart must not lose messages already persisted.
- A message persisted before a crash must be discoverable for reprocessing.
- A temporary alert-destination failure must not prevent alert creation.
- Backfill failures must be resumable from a source checkpoint.

## 13. Acceptance criteria

### Telegram configuration

- An authorized Operator can complete the UI-driven authorization flow using an owned dedicated account.
- API hash, OTP, 2FA password, and session material are not visible in logs, audit events, or subsequent UI reads.
- The Overview page shows a connected state within two minutes of successful authorization.
- An Operator can disconnect/revoke the local session only after confirmation.

### Source monitoring

- An Operator can view accessible sources and explicitly add one to the allowlist.
- The collector does not ingest a message from a source that is not enabled in the allowlist.
- A selected source can backfill its configured time window and resume after an interrupted job.
- A new message in an enabled source appears in search within 60 seconds under normal operating conditions.

### Search and alerts

- A keyword rule matching a newly received source message creates one alert candidate.
- Repeated matching messages inside a configured deduplication window do not produce duplicate notifications.
- An Analyst can find a retained message by keyword, source, and date range.
- Search results link to source message provenance, extracted indicators, and associated alerts.
- An Analyst can update alert state and add a triage note.

### Operations

- Health and status views identify collector disconnection, worker failure, backfill failure, and alert-delivery failure.
- Message and job processing are idempotent across retry/restart tests.
- Retention cleanup deletes test data according to configured retention settings.

## 14. Delivery plan

### Phase 0: Foundation

- Repository, local development environment, PostgreSQL, migrations, application authentication, RBAC, structured logging, secret integration.
- Basic FastAPI health/status endpoints.

### Phase 1: Telegram setup and source management

- Telethon collector process.
- Telegram Configuration guided UI and authorization-state API.
- Encrypted session storage.
- Accessible-source discovery and source allowlist UI.

### Phase 2: Ingestion and search

- Live new-message collection.
- Source backfill jobs/checkpoints.
- Message normalization and PostgreSQL search indexes.
- Search API and Search UI.

### Phase 3: Rules and alerts

- Extraction pipeline.
- Rule editor, evaluation, deduplication, alert lifecycle.
- One internal notification destination and delivery retry.

### Phase 4: Hardening

- Retention cleanup.
- Full audit coverage.
- Health dashboard/metrics.
- Load, recovery, authorization, and secret-redaction testing.

## 15. Open decisions

1. Which internal authentication provider will supply SSO and role claims?
2. Which internal alert destination should be supported first: webhook, email, Slack, or a Telegram bot?
3. What message-content retention period is approved for the deployment environment?
4. Is raw Telegram metadata retained, minimized, or excluded beyond the normalized message fields?
5. What source approval process is required before an Operator enables a channel?
6. Is a source-level maximum historical backfill window required?
7. Which deployment environment will provide encrypted persistent storage for Telethon session data?
8. What audit-log retention and access restrictions are required?

## 16. Success metrics

- 100% of monitored sources are explicitly allowlisted.
- At least 99% of new-message events from enabled sources are searchable within 60 seconds, excluding Telegram-side/network outages.
- Zero persisted OTPs, 2FA passwords, or plaintext API hashes in logs and application tables.
- At least 95% of notification deliveries complete successfully within five minutes after alert creation, excluding destination outages.
- Operators can configure an authorized account and enable a source without command-line access.
- Analysts can retrieve a matching retained message and its provenance in under 10 seconds for normal query volume.

## Implementation notes (MVP)

- Open decision 1: local username/password auth with role claims (admin/operator/analyst); SSO can be dropped in behind the auth dependency.
- Open decision 2: webhook destination implemented and testable from the UI; a Telegram-bot destination is also implemented (Settings page).
- Open decision 3: retention configurable by an Administrator (default 90 days).
- Open decisions 5/6/8: allowlist requires explicit operator confirmation; no source-level backfill cap in MVP; audit events retained per retention settings.
- For local testing without real credentials, `TM_SIMULATE_TELEGRAM=1` provides a deterministic simulated account; the real Telethon path shares the same service interface.
