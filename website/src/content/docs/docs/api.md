---
title: API reference
description: The HTTP API surface (v1) — auth, Telegram configuration, sources, rules, search, alerts, and settings.
---

All routes except `GET /api/v1/health` require authentication (httpOnly signed
cookie) and enforce role-based access control. OpenAPI docs (`/docs`) are
exposed only when `TM_ENVIRONMENT=development`; the full schemas live in
`backend/app/api/`.

## Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Liveness/readiness and service state |
| GET | `/api/v1/telegram/status` | Sanitized Telegram authorization/collector status |
| POST | `/api/v1/telegram/initialize` | Submit API ID/hash and initialize authorization |
| POST | `/api/v1/telegram/phone` | Submit phone number when requested |
| POST | `/api/v1/telegram/code` | Submit one-time code when requested |
| POST | `/api/v1/telegram/password` | Submit 2FA password when requested |
| POST | `/api/v1/telegram/disconnect` | Revoke local session after confirmation |
| POST | `/api/v1/telegram/test` | Verify collector-to-Telegram connectivity without changing monitored sources |
| GET | `/api/v1/sources/discovered` | List account-accessible sources |
| GET/POST | `/api/v1/sources` | List/create approved monitored sources |
| PATCH | `/api/v1/sources/{id}` | Enable, pause, relabel, or configure backfill |
| DELETE | `/api/v1/sources/{id}` | Remove a source from the allowlist |
| GET/POST | `/api/v1/rules` | List/create rules |
| PATCH | `/api/v1/rules/{id}` | Update/enable/disable a rule |
| POST | `/api/v1/rules/test` | Evaluate an unsaved rule against supplied sample text |
| GET | `/api/v1/search` | Search messages and extracted indicators |
| GET | `/api/v1/alerts` | List/filter alerts |
| PATCH | `/api/v1/alerts/{id}` | Update triage state and note |
| GET | `/api/v1/settings` | Read global settings |
| PATCH | `/api/v1/settings` | Update global settings (admin) |
| POST | `/api/v1/settings/destinations/test` | Test an alert destination |
| GET | `/api/v1/users` | List users (admin) |
| GET | `/api/v1/audit` | Audit log (admin) |
| GET | `/api/v1/overview` | Dashboard summary (status, counts, health) |
| GET | `/api/v1/media/{message_id}` | Stored image for a message (analyst+) |

## Search behavior

- Full-text query over normalized message text.
- Case-insensitive substring support for short names and domains.
- Filters: source, date/time range, rule, alert state, indicator type, and
  message state.
- Default sort newest first; cursor or offset pagination; snippet highlighting.
- Results include source name, sent time, message identifier, text snippet,
  extracted indicators, and linked alert state.

## See also

- [Security](security) — how auth, RBAC, and redaction behave on the wire
- [Configuration](configuration) — environment variables that affect the API
