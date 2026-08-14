"""Regression tests for audit-driven fixes: edit reprocessing, terminal retries,
forward metadata, search wildcard escaping, source delete cascade, backfill
validation, and login rate limiting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Indicator, Message, MessageState, Source, User
from app.services.collector import persist_message
from app.services.normalize import excerpt, highlight_snippet

from .conftest import login_admin, login_operator


def _make_source(db, chat_id=777):
    s = Source(
        telegram_chat_id=chat_id,
        title=f"Chat {chat_id}",
        type="channel",
        enabled=True,
        status="live",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_edit_resets_state_for_reprocessing():
    from app.jobs import process_message

    db = SessionLocal()
    try:
        src = _make_source(db)
        msg = persist_message(
            db,
            {"id": 5, "chat_id": src.telegram_chat_id, "date": datetime.now(timezone.utc), "text": "original text"},
        )
        process_message(msg.id)
        db.refresh(msg)
        assert msg.state == MessageState.PROCESSED

        # edit arrives: state must reset so the enqueued realtime job reprocesses
        edited = persist_message(
            db,
            {
                "id": 5,
                "chat_id": src.telegram_chat_id,
                "date": datetime.now(timezone.utc),
                "text": "edited content with https://evil.example/x",
                "edit_date": datetime.now(timezone.utc),
            },
        )
        db.refresh(edited)
        assert edited.state == MessageState.PENDING

        process_message(edited.id)
        db.refresh(edited)
        assert edited.state == MessageState.PROCESSED
        inds = db.scalars(select(Indicator).where(Indicator.message_id == edited.id)).all()
        assert any(i.type == "url" for i in inds), "indicators must be re-extracted after edit"
    finally:
        db.close()


def test_forward_metadata_persisted():
    db = SessionLocal()
    try:
        src = _make_source(db, chat_id=778)
        msg = persist_message(
            db,
            {
                "id": 9,
                "chat_id": src.telegram_chat_id,
                "date": datetime.now(timezone.utc),
                "text": "forwarded note",
                "forward_from_id": 123456,
                "forward_from_name": "Some Channel",
            },
        )
        db.refresh(msg)
        assert msg.forward_from_id == 123456
        assert msg.forward_from_name == "Some Channel"
    finally:
        db.close()


def test_search_wildcards_are_literal(client):
    from app.api.search import _build_query

    db = SessionLocal()
    try:
        src = _make_source(db, chat_id=779)
        m = Message(
            source_id=src.id,
            telegram_message_id=1,
            sent_at=datetime.now(timezone.utc),
            original_text="50% discount applied",
            normalized_text="50% discount applied",
            state="processed",
        )
        db.add(m)
        db.commit()
    finally:
        db.close()
    login_admin(client)
    r = client.get("/api/v1/search", params={"q": "%"})
    assert r.status_code == 200
    assert r.json()["total"] == 1, "%% must only match literal %% (the one message that has it), not everything"
    r2 = client.get("/api/v1/search", params={"q": "50%"})
    assert r2.json()["total"] == 1
    r3 = client.get("/api/v1/search", params={"q": "_"})
    assert r3.json()["total"] == 0, "bare _ must not act as a single-char wildcard"


def test_source_delete_cascades(client):
    db = SessionLocal()
    try:
        src = _make_source(db, chat_id=780)
        for i in range(3):
            db.add(
                Message(
                    source_id=src.id,
                    telegram_message_id=i + 1,
                    sent_at=datetime.now(timezone.utc),
                    original_text=f"msg {i}",
                    normalized_text=f"msg {i}",
                    state="processed",
                )
            )
        db.commit()
        src_id = src.id
    finally:
        db.close()
    login_operator(client)
    r = client.delete(f"/api/v1/sources/{src_id}")
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        assert db.get(Source, src_id) is None
        assert db.scalar(select(func.count(Message.id)).where(Message.source_id == src_id)) == 0
    finally:
        db.close()


def test_patch_source_backfill_validation(client):
    login_operator(client)
    r = client.post(
        "/api/v1/sources",
        json={"telegram_chat_id": 9999001, "title": "V", "type": "channel", "enabled": False},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.patch(f"/api/v1/sources/{sid}", json={"backfill": {"mode": "bogus_mode"}})
    assert r2.status_code == 400, r2.text
    r3 = client.patch(
        f"/api/v1/sources/{sid}", json={"backfill": {"mode": "custom", "custom_start": "not-a-date"}}
    )
    assert r3.status_code == 400, r3.text
    r4 = client.patch(
        f"/api/v1/sources/{sid}",
        json={"backfill": {"mode": "custom", "custom_start": "2099-01-01T00:00:00+00:00"}},
    )
    assert r4.status_code == 400, "future custom_start must be rejected"
    # valid update still works
    r5 = client.patch(f"/api/v1/sources/{sid}", json={"label": "labelled"})
    assert r5.status_code == 200 and r5.json()["label"] == "labelled"


def test_login_rate_limiting(client):
    # 10 failed attempts allowed per username; the 11th is throttled
    status = None
    for _ in range(11):
        r = client.post(
            "/api/v1/auth/login", json={"username": "ratelimit-user", "password": "wrong-password"}
        )
        status = r.status_code
    assert status == 429, f"expected 429 after repeated failures, got {status}"


def test_failed_logins_are_audited(client):
    client.post("/api/v1/auth/login", json={"username": "ghost-user", "password": "x"})
    login_admin(client)
    r = client.get("/api/v1/audit", params={"action": "auth.login_failed"})
    assert r.status_code == 200
    assert any(e["actor_username"] == "ghost-user" for e in r.json()["items"])


def test_logout_revokes_previous_token(client):
    login_admin(client)
    # capture the current cookie value
    cookie = client.cookies.get("tm_token")
    assert cookie is not None
    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    client.cookies.set("tm_token", cookie)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401, "revoked token must be rejected"


def test_token_version_increments_on_password_change(client):
    login_admin(client)
    old_cookie = client.cookies.get("tm_token")
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": "admin123", "new_password": "a-new-admin-pass-1"},
    )
    assert r.status_code == 200, r.text
    client.cookies.clear()
    client.cookies.set("tm_token", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    # restore the password for other tests (login with the NEW password first)
    r = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "a-new-admin-pass-1"}
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/password",
        json={"current_password": "a-new-admin-pass-1", "new_password": "admin123"},
    )
    assert r.status_code == 200, r.text


def test_normalize_index_alignment():
    # casefold-length-changing content must not corrupt highlight indices
    text = "Straße and STRASSE and café"
    out = highlight_snippet(text, "strasse")
    assert "STRASSE" in out  # original casing preserved in the marked text
    assert "<mark>STRASSE</mark>" in out
    ex = excerpt("alpha beta gamma delta", "GAMMA")
    assert "gamma" in ex


def test_alert_rule_version_snapshotted(client):
    from app.models import Alert, Rule

    db = SessionLocal()
    try:
        src = _make_source(db, chat_id=781)
        rule = Rule(
            name="ver rule",
            severity="high",
            definition={"match": "any", "conditions": [{"type": "keyword", "value": "boom"}]},
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        m = Message(
            source_id=src.id,
            telegram_message_id=2,
            sent_at=datetime.now(timezone.utc),
            original_text="boom here",
            normalized_text="boom here",
            state="pending",
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        from app.services.alerts_service import create_alert_candidate

        alert, _ = create_alert_candidate(
            db,
            rule=rule,
            message=m,
            source=src,
            excerpt="boom",
            matched_conditions=[{"condition": {"type": "keyword", "value": "boom"}, "detail": {"matched_text": "boom"}}],
        )
        assert alert.rule_version == rule.version
        # bump rule version; alert snapshot must not change
        rule.version += 1
        db.commit()
        db.refresh(alert)
        assert alert.rule_version == 1
    finally:
        db.close()
