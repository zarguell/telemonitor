#!/usr/bin/env python3
"""End-to-end test against the local docker stack.

Requires: `docker compose up -d --build` running with TM_SIMULATE_TELEGRAM=1,
and a webhook receiver (scripts/webhook_receiver.py) reachable at
host.docker.internal:9899 (started automatically here).

Run from the repo root: python3 scripts/e2e.py
"""
from __future__ import annotations

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
CONTROL_TOKEN = "dev-control-token"
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
        admin = make_client()
        req(admin, "POST", "/auth/login", {"username": "admin", "password": "admin123"})
        op = make_client()
        req(op, "POST", "/auth/login", {"username": "operator", "password": "operator123"})
        an = make_client()
        req(an, "POST", "/auth/login", {"username": "analyst", "password": "analyst123"})

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
        ok(f"live message searchable in {elapsed:.1f}s", bool(found), "(>75s budget)")
        ok("within 60s budget", elapsed <= 75, f"({elapsed:.1f}s)")

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

    finally:
        receiver.terminate()

    print()
    print(f"E2E RESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
