---
title: Set up sources, rules, and alerts
description: Admin guide — allowlist channels, configure backfill, create deterministic monitors (keywords, phrases, regex, indicators), and wire up alert destinations and triage.
---

Once the account is authorized (see [Configure Telegram](configure-telegram)),
this guide covers enabling channels, creating monitors, and receiving alerts.

## 1. Add channels to the allowlist

The **Sources** page has two panels:

- **Accessible sources** — a searchable list of chats and channels visible to
  the configured account (title, username, Telegram chat ID, type, current
  allowlist state).
- **Monitored sources** — enabled/paused state, label, source ID, backfill
  configuration/progress, last received message time, and latest error.

To monitor a channel:

1. Find it in the accessible list (search by title, username, or type) — this
   list does **not** auto-enable anything.
2. Add it to monitoring and confirm the source is approved.
3. Choose the backfill window: `No history`, `Last 24 hours`, `Last 7 days`,
   `Last 30 days`, or a custom earliest timestamp.
4. Set an optional source label, and enable live monitoring.

Discovery is passive: Telemonitor never joins channels automatically, and the
allowlist is enforced server-side — the collector ignores every message from a
chat that is not both allowlisted and enabled.

Source states you can observe: `enabled`, `backfilling`, `live`, `paused`,
`error`, plus last successful ingestion time. Backfill checkpoints per source
and resumes after interruption.

## 2. Create rules

The **Rules** page lists rules with enabled state, severity, source scope,
recent match count, and last match time. Supported rule types:

| Type | Matches |
|---|---|
| Keyword | Case-insensitive keyword in message text |
| Phrase | Exact phrase |
| Regex | Regular expression (with a warning/test action for unsafe or expensive patterns) |
| Indicator | An extracted indicator value (URL, domain, IP, email, hash, wallet address, handle) |
| Source | Messages from a specific monitored source |
| Compound | Simple conditions combined with ALL/ANY logic |

Each rule has a name, description, enabled state, severity
(`informational`, `low`, `medium`, `high`, `critical`), the rule definition, an
optional source scope, a deduplication window, and creator/update timestamps.
Rule modifications are audited.

**Test before enabling:** the rule editor's test action evaluates an unsaved
rule against a sample message. This catches broken regexes and surprising
matches before they go live.

## 3. Configure alert destinations

Under **Settings**, an Administrator configures the alert destination — one
internal webhook or one internal Telegram bot destination. The destination is
testable from the UI before it is used.

Delivery is decoupled from alert creation: a temporary destination failure
never prevents an alert from being created, and delivery is retried with
backoff independently.

## 4. Triage alerts

A rule match creates an alert candidate; candidates with the same dedup key
inside the rule's configured window are grouped rather than re-notified. Each
alert links to the exact message(s), the rule version, the matching excerpt,
the source, and extracted indicators.

The **Alerts** page is a filterable queue; analysts and operators can change
alert state — `open`, `acknowledged`, `resolved`, `false positive` — and add a
triage note. Delivery status and analyst notes are visible on the alert detail.

## 5. Verify with search

New messages from enabled sources appear in **Search** within 60 seconds under
normal operating conditions. Search covers normalized message text with
filters for source, date range, rule, alert state, indicator type, and message
state, and links each result to its provenance and associated alerts.

## Retention

Retention (default 90 days, Administrator-configurable) deletes message
content, indicators, rule matches, and search records on expiry. The exact
retention value must be approved for the deployment environment before
production use.
