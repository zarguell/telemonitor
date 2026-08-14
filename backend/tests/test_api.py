"""API-level tests: auth, RBAC, rules, sources, search, alerts triage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Alert, Message, Rule, Source

from .conftest import login_admin, login_analyst, login_operator

API = "/api/v1"


def test_health_public(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("ok", "degraded")
    assert "database" in data


def test_login_and_me(client):
    user = login_operator(client)
    assert user["role"] == "operator"
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "operator"


def test_login_wrong_password(client):
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_unauthenticated_search_rejected(client):
    r = client.get(f"{API}/search")
    assert r.status_code == 401


def test_rbac_analyst_cannot_configure_telegram(client):
    login_analyst(client)
    r = client.post(
        f"{API}/telegram/initialize",
        json={"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": True},
    )
    assert r.status_code == 403


def test_rbac_analyst_can_search_and_triage(client):
    login_analyst(client)
    assert client.get(f"{API}/search").status_code == 200
    assert client.get(f"{API}/alerts").status_code == 200


def test_rbac_operator_cannot_manage_users(client):
    login_operator(client)
    assert client.get(f"{API}/users").status_code == 403


def test_rbac_analyst_cannot_change_retention(client):
    login_analyst(client)
    assert client.put(f"{API}/settings", json={"retention_days": 30}).status_code == 403


def test_telegram_initialize_requires_ack(client):
    login_operator(client)
    r = client.post(
        f"{API}/telegram/initialize",
        json={"api_id": "1234567", "api_hash": "a" * 32, "acknowledgement": False},
    )
    assert r.status_code == 400
    assert "acknowledge" in r.json()["detail"].lower()


def test_telegram_initialize_validates_format(client):
    login_operator(client)
    r = client.post(
        f"{API}/telegram/initialize",
        json={"api_id": "not-a-number", "api_hash": "short", "acknowledgement": True},
    )
    assert r.status_code == 400


def test_rule_crud_and_validation(client):
    login_operator(client)
    # invalid definition rejected
    r = client.post(f"{API}/rules", json={"name": "bad", "definition": {"match": "any", "conditions": []}})
    assert r.status_code == 400
    # create
    r = client.post(
        f"{API}/rules",
        json={
            "name": "Credential mention",
            "severity": "high",
            "definition": {"match": "any", "conditions": [{"type": "keyword", "value": "credential"}]},
            "dedup_window_seconds": 300,
        },
    )
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["version"] == 1
    # patch bumps version
    r = client.patch(
        f"{API}/rules/{rule['id']}",
        json={"definition": {"match": "any", "conditions": [{"type": "keyword", "value": "credential"}, {"type": "keyword", "value": "leak"}]}},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2
    # test endpoint
    r = client.post(
        f"{API}/rules/test",
        json={
            "definition": {"match": "any", "conditions": [{"type": "keyword", "value": "credential"}]},
            "sample_text": "credential stuffing observed",
        },
    )
    assert r.status_code == 200
    assert r.json()["matched"] is True


def test_source_crud(client):
    login_operator(client)
    r = client.post(
        f"{API}/sources",
        json={
            "telegram_chat_id": 1001000000001,
            "title": "Security Alerts",
            "username": "sec_alerts",
            "type": "channel",
            "enabled": True,
            "backfill": {"mode": "last_24h"},
        },
    )
    assert r.status_code == 200, r.text
    src = r.json()
    assert src["status"] == "backfilling"
    assert src["backfill_start"] is not None
    # duplicate rejected
    r2 = client.post(
        f"{API}/sources",
        json={"telegram_chat_id": 1001000000001, "title": "dup"},
    )
    assert r2.status_code == 409
    # pause
    r3 = client.patch(f"{API}/sources/{src['id']}", json={"enabled": False})
    assert r3.status_code == 200
    assert r3.json()["status"] == "paused"


def test_search_filters_and_alert_link(client):
    db = SessionLocal()
    try:
        src = Source(telegram_chat_id=555, title="Test Channel", username="test_ch", type="channel", enabled=True, status="live")
        db.add(src)
        db.commit()
        db.refresh(src)
        m1 = Message(
            source_id=src.id, telegram_message_id=1, sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
            original_text="URGENT: leaked credentials at https://evil.example/x",
            normalized_text="urgent: leaked credentials at https://evil.example/x",
            state="processed",
        )
        m2 = Message(
            source_id=src.id, telegram_message_id=2, sent_at=datetime.now(timezone.utc),
            original_text="routine build status",
            normalized_text="routine build status",
            state="processed",
        )
        db.add_all([m1, m2])
        db.commit()
        db.refresh(m1)
        from app.models import Indicator

        db.add(Indicator(message_id=m1.id, type="url", value="https://evil.example/x", normalized_value="https://evil.example/x", extractor_version="1.0"))
        db.commit()
    finally:
        db.close()

    login_analyst(client)
    r = client.get(f"{API}/search", params={"q": "credentials"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["source_name"] == "Test Channel"
    assert "<mark>" in data["items"][0]["snippet"]

    r2 = client.get(f"{API}/search", params={"indicator_type": "url"})
    assert r2.json()["total"] == 1

    r3 = client.get(f"{API}/search", params={"q": "build"})
    assert r3.json()["total"] == 1

    # unknown search terms return zero
    r4 = client.get(f"{API}/search", params={"q": "zzz-no-such-term"})
    assert r4.json()["total"] == 0


def test_alert_triage_flow(client):
    db = SessionLocal()
    try:
        src = Source(telegram_chat_id=666, title="Intel", type="channel", enabled=True, status="live")
        db.add(src)
        db.commit()
        db.refresh(src)
        rule = Rule(name="R", severity="critical", definition={"match": "any", "conditions": [{"type": "keyword", "value": "x"}]})
        db.add(rule)
        db.commit()
        db.refresh(rule)
        alert = Alert(
            rule_id=rule.id, source_id=src.id, dedupe_key="k1", severity="critical",
            state="open", excerpt="excerpt here", message_count=1,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        alert_id = alert.id
    finally:
        db.close()

    login_analyst(client)
    r = client.patch(f"{API}/alerts/{alert_id}", json={"state": "resolved", "note": "checked with team, false alarm"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["state"] == "resolved"
    assert data["triage_note"] == "checked with team, false alarm"
    assert data["triaged_by"] == "analyst"

    # invalid state rejected
    r2 = client.patch(f"{API}/alerts/{alert_id}", json={"state": "banana"})
    assert r2.status_code == 400


def test_audit_events_recorded(client):
    login_operator(client)
    client.post(
        f"{API}/rules",
        json={"name": "Audited rule", "definition": {"match": "any", "conditions": [{"type": "keyword", "value": "x"}]}},
    )
    login_admin(client)
    r = client.get(f"{API}/audit")
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()["items"]}
    assert "rule.create" in actions
    assert "auth.login" in actions


def test_settings_retention_update(client):
    login_admin(client)
    r = client.put(f"{API}/settings", json={"retention_days": 45})
    assert r.status_code == 200
    assert r.json()["retention_days"] == 45
    r2 = client.get(f"{API}/settings")
    assert r2.json()["retention_days"] == 45
