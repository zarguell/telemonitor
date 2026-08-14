---
title: Configure Telegram
description: "Admin guide — authorize the organization-controlled Telegram account through the guided flow: API credentials, phone, one-time code, 2FA, and session revocation."
---

This guide walks through connecting the organization-controlled Telegram account
to Telemonitor. Only **Operators** and **Administrators** can access the
Telegram Configuration page.

## Before you start

- You need the application credentials (`api_id`, `api_hash`) and the dedicated
  account's phone number. API ID and API hash come from your Telegram app
  registration; they are not the phone's login credentials.
- The account must already be a member of every channel you plan to monitor —
  Telemonitor never joins channels or bypasses Telegram access controls.
- Confirm you are authorized to use the account for monitoring and have
  reviewed applicable platform, privacy, and organizational requirements — the
  UI asks you to acknowledge exactly this before proceeding.
- In production, `TM_SECRET_KEY` must come from deployment secret management.
  Never authorize a real account while the deployment runs with a committed or
  publicly known key — its session would be recoverable by anyone with repo
  access.

## The guided flow

The page is a step-based form:

1. **Review authorization and acceptable-use acknowledgement.**
2. **Enter API ID and API hash.** API ID must be numeric and is format-checked
   before submission; the hash is a secret input and is never displayed after
   save.
3. **Enter the dedicated account phone number** (E.164 style; masked after
   submission).
4. **Enter the one-time code** — the field appears only when Telegram requests
   it.
5. **Enter the 2FA password** — only if Telegram requests it.
6. **Connected summary** — the page shows just enough to confirm the configured
   account, never secret material.

One-time codes and 2FA passwords exist in process memory only: they are never
persisted, never written to logs, and never included in audit payloads.

## Authorization states

The page renders one of these states at a time:

| State | Meaning |
|---|---|
| Not configured | No credentials stored |
| Initialization required | Credentials saved; client not yet started |
| Waiting for phone number | Client started; phone required |
| Waiting for one-time code | Code required from the operator |
| Waiting for two-factor password | 2FA password required from the operator |
| Authorized and connected | Session live; new-message events flowing |
| Reconnecting | Temporary connectivity loss |
| Disconnected | Session ended cleanly |
| Error | Something failed; check collector health |

## Verify and operate

- **Test status** verifies collector-to-Telegram connectivity without changing
  monitored sources.
- **Disconnect / revoke local session** stops the collector and removes or
  invalidates the local session state — after an explicit confirmation dialog.
  The operation creates an audit event.

## Simulated mode (local development)

With `TM_SIMULATE_TELEGRAM=1` (the compose default) no real account is used:
the simulator presents the same flow with one-time code `12345` and exposes
three deterministic channels — `@sec_alerts`, `@threat_intel_daily`,
`@ops_notifications`. Use this for development and end-to-end tests; the real
Telethon path shares the same service interface.

## Next

[Set up sources, rules, and alerts](monitors-and-alerts) — allowlist channels,
create monitors, and configure notification destinations.
