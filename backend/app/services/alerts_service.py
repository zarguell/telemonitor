"""Alert candidate creation with deduplication windows, and alert lifecycle helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Alert, AlertMessage, AlertState, DeliveryState, Severity, Source, TelegramConfiguration
from .normalize import normalize_text

logger = logging.getLogger(__name__)


def _match_key(matched_conditions: list[dict]) -> str:
    """Stable dedup identity derived from what actually matched."""
    parts: list[str] = []
    for mc in matched_conditions:
        cond = mc.get("condition", {})
        ctype = cond.get("type")
        detail = mc.get("detail", {})
        if ctype == "indicator" and detail.get("matched_text"):
            parts.append(f"ind:{detail.get('indicator_type')}:{normalize_text(str(detail['matched_text']))[:200]}")
        elif ctype == "source":
            parts.append(f"src:{detail.get('source_id')}")
        else:
            matched = detail.get("matched_text") or cond.get("value", "")
            parts.append(f"{ctype}:{normalize_text(str(matched))[:200]}")
    if not parts:
        return "any"
    return "|".join(parts)


def dedupe_key_for(rule_id: int, source_id: int, matched_conditions: list[dict], excerpt: str) -> str:
    mk = _match_key(matched_conditions) or normalize_text(excerpt)[:200]
    return f"{rule_id}:{source_id}:{mk}"


def create_alert_candidate(
    db: Session,
    *,
    rule,
    message,
    source,
    excerpt: str | None,
    matched_conditions: list[dict],
) -> tuple[Alert, bool]:
    """Create or fold into an existing alert for the same dedupe key within the window.

    Returns (alert, is_new).
    """
    now = datetime.now(timezone.utc)
    key = dedupe_key_for(rule.id, source.id, matched_conditions, excerpt or "")
    window = max(0, int(rule.dedup_window_seconds or 0))

    # Serialize candidates for the same dedupe key within this transaction so a
    # check-then-act race cannot create duplicate alerts (PRD 7.5 grouping).
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})

    existing = db.scalar(
        select(Alert).where(
            Alert.dedupe_key == key,
            Alert.state.in_([AlertState.OPEN, AlertState.ACKNOWLEDGED]),
            Alert.first_seen_at >= now - timedelta(seconds=window),
        )
    )
    if existing is not None:
        # Only count NEW links: reprocessing an already-linked message (edit,
        # re-index) must not inflate message_count.
        if not db.get(AlertMessage, (existing.id, message.id)):
            db.add(AlertMessage(alert_id=existing.id, message_id=message.id))
            existing.message_count += 1
        existing.last_seen_at = now
        db.flush()
        return existing, False

    alert = Alert(
        rule_id=rule.id,
        rule_version=rule.version,  # snapshot at match time
        source_id=source.id,
        dedupe_key=key,
        severity=rule.severity,
        state=AlertState.OPEN,
        excerpt=excerpt,
        dedup_window_seconds=window,
        first_seen_at=now,
        last_seen_at=now,
        message_count=1,
        delivery_state=DeliveryState.PENDING,
    )
    db.add(alert)
    db.flush()
    db.add(AlertMessage(alert_id=alert.id, message_id=message.id))
    # No commit here: the caller (process_message) owns the transaction so a
    # later failure rolls back partial alert/rule-match state atomically.
    # Delivery is scheduled independently from creation; a destination outage
    # must not prevent alert creation.
    try:
        from ..jobs import TASK_ALERT_DELIVER, enqueue

        enqueue(TASK_ALERT_DELIVER, alert_id=alert.id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to schedule alert delivery", extra={"alert_id": alert.id})
    return alert, True
    logger.info("alert candidate created", extra={"alert_id": alert.id, "rule": rule.id, "source": source.id})
    # Delivery is scheduled independently from creation; a destination outage
    # must not prevent alert creation.
    try:
        from ..jobs import TASK_ALERT_DELIVER, enqueue

        enqueue(TASK_ALERT_DELIVER, alert_id=alert.id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to schedule alert delivery", extra={"alert_id": alert.id})
    return alert, True


def close_dedupe_windows(db: Session, batch: int = 200) -> int:
    """Mark alerts whose dedupe window has elapsed (observability/state hygiene)."""
    now = datetime.now(timezone.utc)
    rows = list(
        db.scalars(
            select(Alert)
            .where(Alert.dedupe_closed_at.is_(None), Alert.state.in_([AlertState.OPEN, AlertState.ACKNOWLEDGED]))
            .limit(batch)
        )
    )
    closed = 0
    for a in rows:
        if a.first_seen_at + timedelta(seconds=max(0, a.dedup_window_seconds)) <= now:
            a.dedupe_closed_at = now
            closed += 1
    db.commit()
    return closed


def set_alert_triage(db: Session, alert: Alert, state: str, note: str | None, actor: str) -> Alert:
    if state not in (AlertState.OPEN, AlertState.ACKNOWLEDGED, AlertState.RESOLVED, AlertState.FALSE_POSITIVE):
        raise ValueError(f"invalid alert state: {state}")
    alert.state = state
    if note:
        alert.triage_note = note
    alert.triaged_by = actor
    alert.triaged_at = datetime.now(timezone.utc)
    db.commit()
    return alert
