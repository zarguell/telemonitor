---
title: Security
description: Threat model and safeguards — authentication, RBAC, encryption at rest, SSRF guards, redaction, and audit.
---

## Authentication and authorization

- All API routes except `GET /api/v1/health` require authentication (httpOnly
  signed cookie, Secure-flagged outside development) with role-based access
  control (admin / operator / analyst).
- Sessions are revocable: logout and password changes bump a per-user token
  version, invalidating previously issued JWTs.
- Login is rate-limited (per username and per IP) and failed attempts are
  audited.
- Demo users are seeded only on a fresh database (empty users table) — deleted
  accounts are never resurrected.

## Compliance boundary

The product operates only against chats and channels the configured account is
authorized to access and an operator has explicitly enabled. The MVP must not:

- Bypass Telegram access controls, scrape content unavailable to the configured
  account, or automate joining channels.
- Collect secret chats or use copied Telegram Web cookies/browser sessions.
- Enable collection from unapproved sources.
- Use LLMs, embeddings, semantic search, or model-based classification of
  Telegram-derived content.
- Automatically make attribution, notify external parties, publish findings, or
  take enforcement action.

The Telegram configuration UI requires an operator acknowledgement that they
are authorized to use the account and have reviewed applicable platform,
privacy, and organizational requirements.

## Secrets and redaction

- The collector control API is guarded by a token compared in constant time;
  production startup refuses insecure default secrets (`TM_AUTH_SECRET`,
  `TM_COLLECTOR_CONTROL_TOKEN`, `TM_SECRET_KEY`, demo admin password).
- Webhook destinations are SSRF-guarded: loopback/private/link-local/metadata
  ranges are rejected at save and at delivery time (with an explicit
  `TM_ALLOWED_WEBHOOK_HOSTS` bypass for test environments), redirects are
  disabled, and URLs with embedded credentials are rejected.
- API hash, Telegram session, and bot tokens are encrypted at rest (Fernet).
- One-time codes and 2FA passwords exist in process memory only, are never
  persisted, and are redacted from logs and audit payloads (verified by the E2E
  suite's secret-hygiene checks).
- Message content, phone numbers, and credentials are redacted from logs by a
  global logging filter.
- nginx serves the UI with CSP, X-Frame-Options DENY, and nosniff headers.
- OpenAPI docs are disabled outside development.

## Audit

Telegram configuration changes, source allowlist changes, rule changes,
searches, alert triage, settings changes, and user management are audited in
`audit_events` with sanitized details only.

## Retention

Retention (default 90 days) deletes message content, indicators, rule matches,
and search records; audit metadata is preserved. The exact retention value must
be approved for the deployment environment before production use. Backups are
encrypted and follow the same retention policy.
