---
title: Telemonitor
description: Internal, operator-managed monitoring of explicitly approved Telegram channels — deterministic rules, searchable retention, human-in-the-loop alerts.
---

Telemonitor is an internal, operator-managed application that monitors explicitly
approved Telegram channels using an organization-controlled Telegram account. It
ingests permitted messages, retains searchable records, runs deterministic
monitors (keywords, phrases, regex, extracted indicators), and notifies
operators when a rule matches.

**Status:** MVP implementation of the product specification (`docs/PRD.md` in
the repository). Source posts are presented as **unverified claims** with
preserved provenance; any external action requires human review. No LLM,
embeddings, semantic search, or automated attribution is used anywhere in the
pipeline.

## What it does

- Connects one organization-controlled Telegram account through a guided, stateful authorization flow (API ID/hash, one-time code, optional 2FA).
- Lets operators explicitly select and enable approved channels; the allowlist is enforced server-side.
- Ingests both historical messages (resumable, checkpointed backfill) and new messages in real time.
- Extracts deterministic indicators: URLs, domains, IPv4/IPv6, emails, hashes, wallet addresses, Telegram handles.
- Evaluates keyword / phrase / regex / indicator / source rules with ALL/ANY logic, severities, and deduplication windows.
- Creates deduplicated alerts and delivers them to internal webhook or Telegram-bot destinations with independent retry.
- Retains searchable records (default 90 days, admin-configurable) and logs a full audit trail.

## Operating boundary

- The product operates only against chats and channels the configured account can access and an operator has explicitly enabled.
- It never bypasses Telegram access controls, joins channels automatically, or collects unapproved sources.
- It never stores one-time codes or 2FA passwords; sessions and secrets are encrypted at rest.
- It never performs automated attribution, external notification, or enforcement — every alert requires human review.

## Next steps

- [Quick start](quickstart) — run the full stack locally with Docker
- [Installation](installation) — deployment notes for production
- [Configuration](configuration) — environment variables
- [Guides](guides/configure-telegram) — connect the account, allowlist channels, create rules, wire up alerts
- [Architecture](architecture) — components, queues, and reliability properties
- [Security](security) — threat model and safeguards
- [API reference](api) — the HTTP API surface
- [Product specification](product-spec) — the full PRD
