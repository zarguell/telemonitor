"""Alert deduplication + idempotent realtime processing tests (DB-backed)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Alert, Message, Rule, Source
from app.services.alerts_service import close_dedupe_windows, create_alert_candidate


def make_source(db, chat_id=1001, enabled=True):
    s = Source(
        telegram_chat_id=chat_id,
        title=f"Chat {chat_id}",
        type="channel",
        enabled=enabled,
        status="live",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def make_message(db, source, tg_id, text):
    m = Message(
        source_id=source.id,
        telegram_message_id=tg_id,
        sent_at=datetime.now(timezone.utc),
        original_text=text,
        normalized_text=text.lower(),
        state="pending",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def make_rule(db, dedup_window=600, source_scope=None):
    r = Rule(
        name="test rule",
        severity="high",
        definition={"match": "any", "conditions": [{"type": "keyword", "value": "urgent"}]},
        source_scope=source_scope,
        dedup_window_seconds=dedup_window,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_dedup_folds_within_window():
    db = SessionLocal()
    try:
        src = make_source(db)
        rule = make_rule(db, dedup_window=600)
        m1 = make_message(db, src, 1, "URGENT event one")
        m2 = make_message(db, src, 2, "URGENT event two")

        alert1, is_new1 = create_alert_candidate(
            db, rule=rule, message=m1, source=src, excerpt="URGENT event one",
            matched_conditions=[{"condition": {"type": "keyword", "value": "urgent"}, "detail": {"matched_text": "URGENT"}}],
        )
        alert2, is_new2 = create_alert_candidate(
            db, rule=rule, message=m2, source=src, excerpt="URGENT event two",
            matched_conditions=[{"condition": {"type": "keyword", "value": "urgent"}, "detail": {"matched_text": "URGENT"}}],
        )
        assert is_new1 is True
        assert is_new2 is False
        assert alert1.id == alert2.id
        assert alert1.message_count == 2
        db.refresh(alert1)
        assert len(alert1.messages) == 2
    finally:
        db.close()


def test_dedup_key_differs_by_value():
    db = SessionLocal()
    try:
        src = make_source(db)
        rule = make_rule(db, dedup_window=600)
        m1 = make_message(db, src, 1, "hits 1.2.3.4")
        m2 = make_message(db, src, 2, "hits 5.6.7.8")
        a1, n1 = create_alert_candidate(
            db, rule=rule, message=m1, source=src, excerpt="hits 1.2.3.4",
            matched_conditions=[{"condition": {"type": "indicator", "value": "ipv4"}, "detail": {"matched_text": "1.2.3.4", "indicator_type": "ipv4"}}],
        )
        a2, n2 = create_alert_candidate(
            db, rule=rule, message=m2, source=src, excerpt="hits 5.6.7.8",
            matched_conditions=[{"condition": {"type": "indicator", "value": "ipv4"}, "detail": {"matched_text": "5.6.7.8", "indicator_type": "ipv4"}}],
        )
        assert n1 and n2
        assert a1.id != a2.id
    finally:
        db.close()


def test_dedup_expires_after_window():
    db = SessionLocal()
    try:
        src = make_source(db)
        rule = make_rule(db, dedup_window=0)  # zero window = always new
        m1 = make_message(db, src, 1, "URGENT one")
        m2 = make_message(db, src, 2, "URGENT two")
        a1, n1 = create_alert_candidate(
            db, rule=rule, message=m1, source=src, excerpt="one",
            matched_conditions=[{"condition": {"type": "keyword", "value": "urgent"}, "detail": {"matched_text": "URGENT"}}],
        )
        a2, n2 = create_alert_candidate(
            db, rule=rule, message=m2, source=src, excerpt="two",
            matched_conditions=[{"condition": {"type": "keyword", "value": "urgent"}, "detail": {"matched_text": "URGENT"}}],
        )
        assert n1 and n2
        assert a1.id != a2.id
    finally:
        db.close()


def test_close_dedupe_windows_marks_elapsed():
    db = SessionLocal()
    try:
        src = make_source(db)
        rule = make_rule(db, dedup_window=1)
        m1 = make_message(db, src, 1, "URGENT x")
        alert, _ = create_alert_candidate(
            db, rule=rule, message=m1, source=src, excerpt="x",
            matched_conditions=[{"condition": {"type": "keyword", "value": "urgent"}, "detail": {"matched_text": "URGENT"}}],
        )
        alert.first_seen_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()
        closed = close_dedupe_windows(db)
        assert closed == 1
        db.refresh(alert)
        assert alert.dedupe_closed_at is not None
    finally:
        db.close()


def test_message_write_idempotent_via_unique():
    db = SessionLocal()
    try:
        src = make_source(db)
        from sqlalchemy.exc import IntegrityError

        from app.services.collector import persist_message

        msg = {
            "id": 42,
            "chat_id": src.telegram_chat_id,
            "date": datetime.now(timezone.utc),
            "text": "hello",
        }
        m1 = persist_message(db, msg)
        m2 = persist_message(db, msg)
        assert m1 is not None and m2 is not None
        assert m1.id == m2.id
        from sqlalchemy import func

        assert db.scalar(select(func.count(Message.id)).where(Message.source_id == src.id)) == 1
    finally:
        db.close()


def test_allowlist_enforced_on_persist():
    db = SessionLocal()
    try:
        src = make_source(db, enabled=False)
        from app.services.collector import persist_message

        msg = {"id": 7, "chat_id": src.telegram_chat_id, "date": datetime.now(timezone.utc), "text": "ignored"}
        assert persist_message(db, msg) is None
        # unknown chat entirely
        assert persist_message(db, {"id": 8, "chat_id": 999999, "date": datetime.now(timezone.utc), "text": "x"}) is None
    finally:
        db.close()
