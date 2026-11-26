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
| `db` | PostgreSQL 19 (single instance) |
| `api` | FastAPI — auth/RBAC, configuration, query API, orchestration |
| `collector` | Telethon (or simulator) — account connection, discovery, new-message events |
| `worker` | Procrastinate workers — realtime processing, alert delivery, backfill, maintenance |
| `web` | nginx serving the React UI with CSP, X-Frame-Options DENY, and nosniff headers |

## Upgrading PostgreSQL

`docker-compose.yml` pins the `db` image by digest to the current PostgreSQL
major (19, `19-alpine`). Data directories are **major-version specific**: since
PG18 the official image keeps `PGDATA` at `/var/lib/postgresql/<major>/docker`
and the volume is mounted at `/var/lib/postgresql`, so the same `pgdata` volume
is reused across majors — but a 19 server only looks in `19/docker`. Changing
the tag on a stack that already holds data is therefore not an upgrade: `db`
exits at startup with

```text
Error: in 18+, these Docker images are configured to store database data in a
       format which is compatible with "pg_ctlcluster" ...
       Counter to that, there appears to be PostgreSQL data in:
         /var/lib/postgresql/18/docker
```

and nothing else starts, because `migrate` waits for `db` to become healthy.
Pick one path:

**A — dump and restore (recommended; rebuilds every index)**

```bash
# 1. With the OLD stack still running, dump everything. Use the PG19 tooling, or
#    keep standard_conforming_strings on (the default): PG19 forces it on and
#    dumps taken with it off will not load correctly.
docker compose exec -T db pg_dumpall -U telemonitor > telemonitor-pre19.sql
# 2. Stop the stack and remove the old cluster volume (compose project name is
#    the directory name unless you set COMPOSE_PROJECT_NAME).
docker compose down
docker volume rm "$(basename "$PWD")_pgdata"
# 3. Start PostgreSQL 19 alone, restore, then bring the rest of the stack up.
docker compose up -d db
docker compose exec -T db psql -U telemonitor -d postgres < telemonitor-pre19.sql
docker compose up -d
```

**B — `pg_upgrade --link`** (keeps the old cluster inside the same volume). The
19 image does not ship the 18 binaries, so run `pg_upgrade` from a container or
host that has both, pointing it at `/var/lib/postgresql/18/docker` →
`/var/lib/postgresql/19/docker`; see the
[pg_upgrade documentation](https://www.postgresql.org/docs/19/pgupgrade.html).
Then:

- `REINDEX DATABASE telemonitor` (and `telemonitor_test` if present). PostgreSQL
  19 classifies text for full-text search and `pg_trgm` using the database's
  locale provider instead of libc, so the release notes recommend reindexing all
  full-text/`pg_trgm` indexes after `pg_upgrade`. This schema has both (the two
  GIN indexes on `messages`) and stores no `tsvector` column, so no stored values
  need recomputing.
- `pg_upgrade` refuses clusters with `btree_gist` indexes on `inet`/`cidr`, or
  with carriage returns/line feeds in database or role names. This schema uses
  neither, but custom additions must be dropped first.

Application compatibility is verified: migrations (`CREATE EXTENSION pg_trgm`,
the `to_tsvector('simple', …)` GIN index, `gin_trgm_ops`) apply cleanly to a
fresh 19 cluster, and the backend suite passes against PostgreSQL 19.0. Nothing
in the stack depends on features removed in 19 (RADIUS, `io_workers`,
`escape_string_warning`); the new MD5-auth warning does not apply because the
image defaults to `scram-sha-256`, and JIT being off by default suits this
OLTP workload.

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
