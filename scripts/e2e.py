#!/usr/bin/env python3
"""End-to-end test against the local docker stack.

Requires: `docker compose up -d --build` running with TM_SIMULATE_TELEGRAM=1,
and a webhook receiver (scripts/webhook_receiver.py) reachable at
host.docker.internal:9899 (started automatically here).

Run from the repo root: python3 scripts/e2e.py
"""
from __future__ import annotations

import datetime
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://localhost:8080/api/v1"
CONTROL = "http://127.0.0.1:9001"


def _env_or_default(key: str, default: str) -> str:
    """Read the project .env (gitignored, local-only secrets) if present."""
    env_file = os.path.join(ROOT, ".env")
    if os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key, default)


CONTROL_TOKEN = _env_or_default("TM_COLLECTOR_CONTROL_TOKEN", "")
assert CONTROL_TOKEN, "TM_COLLECTOR_CONTROL_TOKEN missing from .env"
RECEIVER_PORT = 9899
RECEIVER_URL = f"http://host.docker.internal:{RECEIVER_PORT}/webhook"
RECEIVER_LOG = os.path.join(ROOT, "scripts", ".webhook_payloads.log")
SIM_PHONE = "+15550001111"
SIM_OTP = "12345"

PASS = 0
FAIL = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


def wait_until(name: str, fn, timeout: float, interval: float = 2.0, desc: str = "") -> object:
    """Poll fn() until truthy or timeout. Returns the last result."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(interval)
    print(f"  TIMEOUT waiting for: {name} {desc}")
    return last


def make_client() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(client, method: str, path: str, body=None, expect: int | None = 200, base: str = BASE):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with client.open(r, timeout=30) as resp:
            payload = resp.read().decode()
            try:
                data = json.loads(payload) if payload else None
            except json.JSONDecodeError:
                data = None
            if expect is not None:
                ok(f"{method} {path} -> {resp.status}", resp.status == expect, f"(got {resp.status}: {payload[:200]})")
            return resp.status, data
    except urllib.error.HTTPError as e:
        payload = e.read().decode()
        try:
            data = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            data = None
        if expect is not None:
            ok(f"{method} {path} -> {e.code}", e.code == expect, f"(got {e.code}: {payload[:200]})")
        return e.code, data


def control(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        CONTROL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Control-Token": CONTROL_TOKEN} if data else {"X-Control-Token": CONTROL_TOKEN},
    )
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode() or "null")


def receiver_events(kind: str | None = None) -> list[dict]:
    if not os.path.exists(RECEIVER_LOG):
        return []
    out = []
    for line in open(RECEIVER_LOG, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        body = rec.get("body") or {}
        if kind is None or body.get("event") == kind:
            out.append(rec)
    return out


def sh(cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, **kw)


def main() -> None:
    # ---- start webhook receiver ----
    if os.path.exists(RECEIVER_LOG):
        os.remove(RECEIVER_LOG)
    receiver = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "scripts", "webhook_receiver.py"), str(RECEIVER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1)

        print("== 1. Health & auth ==")
        health = wait_until("health ok", lambda: req(make_client(), "GET", "/health", expect=None)[1], 180, desc="stack startup")
        ok("health endpoint responds", health is not None and health.get("status") == "ok")
        control_ok = wait_until(
            "collector control ready",
            lambda: (lambda st: st == 200)(control("GET", "/control/status")[0]),
            90,
        )
        ok("collector control endpoint ready", bool(control_ok))
        ADMIN_PASSWORD = _env_or_default("TM_SEED_ADMIN_PASSWORD", "")
        assert ADMIN_PASSWORD, "TM_SEED_ADMIN_PASSWORD missing from .env"
        admin = make_client()
        req(admin, "POST", "/auth/login", {"username": "admin", "password": ADMIN_PASSWORD})
        # operator/analyst are NOT seeded by the app; create them via the admin API
        for uname, upass, role in (
            ("operator", "e2e-operator-pass-x7", "operator"),
            ("analyst", "e2e-analyst-pass-x7", "analyst"),
        ):
            st, _ = req(admin, "POST", "/users", {"username": uname, "password": upass, "role": role})
            ok(f"created test user {uname}", st == 200)
        op = make_client()
        req(op, "POST", "/auth/login", {"username": "operator", "password": "e2e-operator-pass-x7"})
        an = make_client()
        req(an, "POST", "/auth/login", {"username": "analyst", "password": "e2e-analyst-pass-x7"})

        print("== 2. RBAC ==")
        req(an, "POST", "/telegram/initialize", {"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": True}, expect=403)
        req(an, "GET", "/search", expect=200)
        req(op, "GET", "/users", expect=403)
        req(an, "PUT", "/settings", {"retention_days": 30}, expect=403)

        print("== 3. Telegram authorization flow ==")
        req(op, "POST", "/telegram/initialize", {"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": False}, expect=400)
        st, tg = req(op, "POST", "/telegram/initialize", {"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": True})
        ok("initialize -> waiting_phone", tg.get("state") == "waiting_phone")
        st, tg = req(op, "POST", "/telegram/phone", {"phone": SIM_PHONE})
        ok("phone -> waiting_code", tg.get("state") == "waiting_code")
        st, tg = req(op, "POST", "/telegram/code", {"code": SIM_OTP})
        ok("code -> authorized", tg.get("state") == "authorized", f"(got {tg.get('state')})")
        status = wait_until("authorized status visible", lambda: req(op, "GET", "/telegram/status", expect=None)[1], 30)
        ok("telegram status authorized", status.get("state") == "authorized")
        st, ttest = req(op, "POST", "/telegram/test")
        ok("test status verifies connectivity", ttest.get("ok") is True, f"(got {ttest})")

        print("== 4. Discovery & allowlist ==")
        st, disc = req(op, "GET", "/sources/discovered")
        ok("discovered 3 sources", isinstance(disc, list) and len(disc) == 3, f"(got {len(disc) if isinstance(disc, list) else disc})")
        if not isinstance(disc, list) or not disc:
            raise SystemExit("aborting: discovery failed")
        ok("discovery does not auto-allowlist", all(not d["allowlisted"] for d in disc))
        first = disc[0]

        print("== 5. Alert destination (webhook) ==")
        st, sres = req(admin, "PUT", "/settings", {"alert_destination": {"type": "webhook", "url": RECEIVER_URL}})
        ok("destination saved", sres is not None)
        req(admin, "POST", "/settings/destination/test", expect=200)
        probe = wait_until("probe delivered", lambda: receiver_events("destination.test"), 30)
        ok("destination test reached receiver", bool(probe))

        print("== 6. Add monitored source with backfill ==")
        st, src1 = req(
            op,
            "POST",
            "/sources",
            {
                "telegram_chat_id": first["chat_id"],
                "title": first["title"],
                "username": first.get("username"),
                "type": first.get("type"),
                "enabled": True,
                "backfill": {"mode": "last_24h"},
            },
        )
        ok("source created backfilling", src1.get("status") == "backfilling", f"(got {src1.get('status')})")
        src_id = src1["id"]

        def backfill_done():
            st, s = req(op, "GET", "/sources", expect=None)
            for item in s["items"]:
                if item["id"] == src_id:
                    return item
            return None

        src = wait_until("backfill completes", lambda: (lambda s: s if s and s.get("status") == "live" else None)(backfill_done()), 180, desc="source backfill")
        ok("backfill reached live", src is not None)
        ok("backfill progress recorded", (src or {}).get("backfill_done", 0) >= 90, f"(done={ (src or {}).get('backfill_done') })")

        st, search = req(op, "GET", "/search?q=urgent")
        ok("search finds backfilled messages", search["total"] >= 1, f"(total={search['total']})")

        print("== 7. Rule creation ==")
        st, rule = req(
            op,
            "POST",
            "/rules",
            {
                "name": "Credential watch",
                "severity": "high",
                "dedup_window_seconds": 600,
                "definition": {"match": "any", "conditions": [{"type": "keyword", "value": "credential"}]},
            },
        )
        ok("rule created", rule.get("id") is not None)
        rule_id = rule["id"]
        st, test = req(
            op,
            "POST",
            "/rules/test",
            {"definition": rule["definition"], "sample_text": "credential stuffing observed"},
        )
        ok("rule test matches sample", test.get("matched") is True)

        print("== 8. Live message -> alert -> delivery (60s budget) ==")
        t0 = time.time()
        control("POST", "/control/sim/message", {"chat_id": first["chat_id"], "text": "credential stuffing observed in VPN logs"})
        found = wait_until(
            "live message searchable",
            lambda: req(op, "GET", "/search?q=credential+stuffing", expect=None)[1]["total"] >= 1,
            90,
        )
        elapsed = time.time() - t0
        ok(f"live message searchable in {elapsed:.1f}s", bool(found), "(no result)")
        ok("within 60s budget (PRD 13)", elapsed <= 60, f"({elapsed:.1f}s)")

        alert = wait_until(
            "alert created for rule",
            lambda: (lambda r: r["items"][0] if r["total"] else None)(
                req(op, "GET", f"/alerts?rule_id={rule_id}", expect=None)[1]
            ),
            90,
        )
        ok("open alert exists", alert is not None and alert.get("state") == "open")
        alert_id = alert["id"]

        delivered = wait_until(
            "alert delivered",
            lambda: (lambda a: a if a and a.get("delivery_state") == "delivered" else None)(
                req(op, "GET", f"/alerts/{alert_id}", expect=None)[1]
            ),
            90,
        )
        ok("alert delivery_state delivered", delivered is not None)
        ok("webhook received alert.created", len(receiver_events("alert.created")) == 1)

        print("== 9. Deduplication window ==")
        time.sleep(2)
        control("POST", "/control/sim/message", {"chat_id": first["chat_id"], "text": "another credential dump in progress"})
        time.sleep(12)
        st, alerts = req(op, "GET", f"/alerts?rule_id={rule_id}", expect=None)
        ok("still exactly one alert for rule", alerts["total"] == 1, f"(total={alerts['total']})")
        st, detail = req(op, "GET", f"/alerts/{alert_id}", expect=None)
        ok("dedup folded second message", detail["message_count"] >= 2, f"(count={detail['message_count']})")
        ok("no duplicate notification", len(receiver_events("alert.created")) == 1)

        print("== 9b. Search filters + provenance ==")
        st, by_rule = req(op, "GET", f"/search?rule_id={rule_id}", expect=None)
        ok("search filter by rule_id", by_rule["total"] >= 1, f"(total={by_rule['total']})")
        st, by_src = req(op, "GET", f"/search?source_id={src_id}", expect=None)
        ok("search filter by source_id", by_src["total"] >= 1, f"(total={by_src['total']})")
        st, by_range = req(
            op,
            "GET",
            "/search?start_time=" + urllib.parse.quote((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat()) + "&end_time=" + urllib.parse.quote(datetime.datetime.now(datetime.timezone.utc).isoformat()),
            expect=None,
        )
        ok("search filter by date range", by_range["total"] >= 1, f"(total={by_range['total']})")
        st, by_ind = req(op, "GET", "/search?indicator_type=hash", expect=None)
        ok("search filter by indicator type", by_ind["total"] >= 1, f"(total={by_ind['total']})")
        st, search = req(op, "GET", "/search?q=credential", expect=None)
        ok("search results carry permalinks", search["items"][0].get("permalink") is not None, f"(items={len(search['items'])})")
        ok("search results carry normalized_text", "normalized_text" in search["items"][0])

        print("== 10. Triage by analyst ==")
        st, triaged = req(an, "PATCH", f"/alerts/{alert_id}", {"state": "resolved", "note": "checked with team"})
        ok("alert resolved with note", triaged.get("state") == "resolved" and triaged.get("triage_note") == "checked with team")
        ok("triaged_by analyst", triaged.get("triaged_by") == "analyst")

        print("== 11. Backfill interrupt/resume ==")
        st, disc = req(op, "GET", "/sources/discovered")
        second = disc[1]
        st, src2 = req(
            op,
            "POST",
            "/sources",
            {"telegram_chat_id": second["chat_id"], "title": second["title"], "type": second.get("type"), "enabled": True, "backfill": {"mode": "last_30d"}},
        )
        src2_id = src2["id"]
        time.sleep(5)  # let backfill start
        r = sh("docker compose restart collector")
        ok("collector restarted", r.returncode == 0)

        def src2_state():
            st, s = req(op, "GET", "/sources", expect=None)
            for item in s["items"]:
                if item["id"] == src2_id:
                    return item
            return None

        resumed = wait_until("backfill resumes after restart", lambda: (lambda s: s if s and s.get("status") == "live" else None)(src2_state()), 360, desc="interrupt/resume")
        ok("source2 backfill completed after restart", resumed is not None)
        ok("source2 backfilled large window", (resumed or {}).get("backfill_done", 0) > 2500, f"(done={(resumed or {}).get('backfill_done')})")
        ok("no backfill error", not (resumed or {}).get("backfill_error"))
        req(op, "DELETE", f"/sources/{src2_id}", expect=200)
        st, after_del = req(op, "GET", "/sources", expect=None)
        ok("source removed from allowlist", all(x["id"] != src2_id for x in after_del["items"]))

        print("== 12. Retention cleanup ==")
        psql = (
            f"INSERT INTO messages (source_id, telegram_message_id, sent_at, ingested_at, original_text, "
            f"normalized_text, state, processing_attempts) VALUES ({src_id}, 9900001, "
            f"now() - interval '30 days', now() - interval '30 days', "
            f"'OLD_RETENTION_MARKER unique content', 'old_retention_marker unique content', 'processed', 1);"
        )
        r = sh(f"docker compose exec -T db psql -U telemonitor -d telemonitor -c \"{psql}\"")
        ok("old message inserted for retention test", r.returncode == 0, r.stderr[:200])
        req(admin, "PUT", "/settings", {"retention_days": 7})
        r = sh('docker compose exec -T worker python -c "from app.jobs import enqueue, ensure_open, TASK_RETENTION; ensure_open(); enqueue(TASK_RETENTION, force=True)"')
        ok("retention job enqueued", r.returncode == 0, r.stderr[:200])
        gone = wait_until(
            "old message purged",
            lambda: req(op, "GET", "/search?q=OLD_RETENTION_MARKER", expect=None)[1]["total"] == 0,
            120,
            desc="retention",
        )
        ok("retention deleted old message content", bool(gone))
        st, keep = req(op, "GET", "/search?q=credential", expect=None)
        ok("recent messages retained", keep["total"] >= 1)

        print("== 13. Audit trail & secret hygiene ==")
        st, audit = req(op, "GET", "/audit?limit=200")
        actions = {e["action"] for e in audit["items"]}
        for needed in ("telegram.initialize", "telegram.code_submitted", "source.add", "rule.create", "search.query", "alert.triage", "settings.update"):
            ok(f"audit has {needed}", needed in actions)
        audit_blob = json.dumps(audit["items"])
        ok("no OTP in audit payloads", SIM_OTP not in audit_blob)
        ok("no phone number in audit payloads", SIM_PHONE not in audit_blob)
        ok("no api hash in audit payloads", ("a" * 32) not in audit_blob)
        logs = sh("docker compose logs api 2>&1").stdout + sh("docker compose logs collector 2>&1").stdout
        ok("no OTP in api/collector logs", SIM_OTP not in logs)
        ok("no phone in api/collector logs", SIM_PHONE not in logs)

        print("== 14. Health & UI ==")
        st, h = req(admin, "GET", "/health")
        ok("health collector connected", h["collector"]["connected"] is True, f"(state={h['collector']['state']})")
        ok("health shows queues", set(h["queues"]) >= {"realtime", "alerts", "backfill", "maintenance"})
        html = urllib.request.urlopen("http://localhost:8080/", timeout=15).read().decode()
        ok("frontend serves SPA", "root" in html)
        st, via_proxy = req(make_client(), "GET", "/api/v1/health", base="http://localhost:8080")
        ok("nginx proxies API", via_proxy is not None and via_proxy.get("status") == "ok")

        print("== 15. Operator disconnect (confirmed) ==")
        req(op, "POST", "/telegram/disconnect", {"confirm": False}, expect=400)
        st, tg = req(op, "POST", "/telegram/disconnect", {"confirm": True})
        ok("disconnect revokes session", tg.get("state") == "disconnected")
        # reconnect via sim: initialize again with phone+code
        req(op, "POST", "/telegram/initialize", {"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": True})
        req(op, "POST", "/telegram/phone", {"phone": SIM_PHONE})
        req(op, "POST", "/telegram/code", {"code": SIM_OTP})
        status = wait_until("reconnect", lambda: req(op, "GET", "/telegram/status", expect=None)[1], 30)
        ok("reconnected after revoke", status.get("state") == "authorized")

        print("== 16. Two-factor password path ==")
        req(op, "POST", "/telegram/initialize", {"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": True})
        req(op, "POST", "/telegram/phone", {"phone": "+15550001112"})
        st, tg = req(op, "POST", "/telegram/code", {"code": SIM_OTP})
        ok("2FA requested for 2FA-enabled account", tg.get("state") == "waiting_2fa", f"(got {tg.get('state')})")
        st, tg = req(op, "POST", "/telegram/password", {"password": "sim-2fa-pass"})
        ok("2FA password completes authorization", tg.get("state") == "authorized", f"(got {tg.get('state')})")
        status = wait_until("2FA reauthorized", lambda: req(op, "GET", "/telegram/status", expect=None)[1], 30)
        ok("telegram status authorized after 2FA", status.get("state") == "authorized")

    finally:
        receiver.terminate()

    print()
    print(f"E2E RESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
