"""Alert notification delivery: webhook or internal Telegram bot, with retries."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..audit import get_setting
from ..crypto import decrypt_secret, mask
from ..models import Alert, DeliveryAttemptStatus, DeliveryState, Indicator, Source

logger = logging.getLogger(__name__)


def get_destination(db: Session) -> dict:
    dest = get_setting(db, "alert_destination", {}) or {}
    return dest


def destination_summary(dest: dict) -> dict:
    """Sanitized destination description for API responses (no secrets)."""
    if not dest or dest.get("type") in (None, "none"):
        return {"type": "none", "configured": False}
    if dest.get("type") == "webhook":
        url = dest.get("url", "")
        return {"type": "webhook", "configured": True, "url": mask(url, 8), "testable": True}
    if dest.get("type") == "telegram_bot":
        chat = dest.get("chat_id", "")
        return {"type": "telegram_bot", "configured": True, "chat_id": str(chat)[:6] + "…", "testable": True}
    return {"type": "none", "configured": False}


def build_alert_payload(db: Session, alert: Alert) -> dict:
    rule = alert.rule
    source = alert.source
    messages = alert.messages
    indicators: list[dict] = []
    first_msg = messages[0] if messages else None
    if first_msg:
        for ind in first_msg.indicators:
            indicators.append(
                {"type": ind.type, "value": ind.value, "normalized_value": ind.normalized_value}
            )
    return {
        "event": "alert.created",
        "alert": {
            "id": alert.id,
            "severity": alert.severity,
            "state": alert.state,
            "excerpt": alert.excerpt,
            "message_count": alert.message_count,
            "first_seen_at": alert.first_seen_at.isoformat() if alert.first_seen_at else None,
        },
        "rule": {
            "id": rule.id if rule else None,
            "name": rule.name if rule else None,
            "severity": rule.severity if rule else None,
            "version": rule.version if rule else None,
        },
        "source": {
            "id": source.id if source else None,
            "title": source.title if source else None,
            "username": source.username,
            "telegram_chat_id": source.telegram_chat_id if source else None,
        },
        "message": {
            "id": first_msg.id if first_msg else None,
            "telegram_message_id": first_msg.telegram_message_id if first_msg else None,
            "sent_at": first_msg.sent_at.isoformat() if first_msg and first_msg.sent_at else None,
            "excerpt": alert.excerpt,
            "permalink": first_msg.permalink if first_msg else None,
        },
        "indicators": indicators,
    }


def _webhook_send(url: str, payload: dict, timeout: int) -> tuple[bool, int | None, str | None]:
    try:
        r = httpx.post(url, json=payload, timeout=timeout, headers={"User-Agent": "Telemonitor/1.0"})
        ok = 200 <= r.status_code < 300
        return ok, r.status_code, (None if ok else r.text[:300])
    except httpx.HTTPError as e:
        return False, None, f"{type(e).__name__}: {e}"


def _telegram_bot_send(token: str, chat_id: str, payload: dict, timeout: int) -> tuple[bool, int | None, str | None]:
    text = (
        f"\u26a0\ufe0f Telemonitor alert #{payload['alert']['id']} "
        f"[{payload['alert']['severity']}]\n"
        f"Rule: {payload['rule']['name']}\n"
        f"Source: {payload['source']['title']}\n"
        f"Excerpt: {payload['alert']['excerpt']}\n"
        f"Permalink: {payload['message']['permalink'] or 'n/a'}"
    )
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=timeout,
        )
        ok = r.status_code == 200 and r.json().get("ok") is True
        return ok, r.status_code, (None if ok else r.text[:300])
    except (httpx.HTTPError, ValueError) as e:
        return False, None, f"{type(e).__name__}: {e}"


def send_alert_payload(db: Session, dest: dict, payload: dict, timeout: int) -> tuple[bool, int | None, str | None]:
    """Send payload to the configured destination. Returns (ok, status_code, error)."""
    d_type = dest.get("type")
    if d_type == "webhook":
        return _webhook_send(dest.get("url", ""), payload, timeout)
    if d_type == "telegram_bot":
        token = decrypt_secret(dest.get("token_enc"))
        chat_id = str(dest.get("chat_id", ""))
        if not token or not chat_id:
            return False, None, "bot token or chat_id missing"
        return _telegram_bot_send(token, chat_id, payload, timeout)
    return False, None, f"no supported destination configured (type={d_type!r})"


def test_destination(db: Session, dest: dict, timeout: int = 10) -> dict:
    """Test endpoint: send a minimal probe payload (no real message content)."""
    payload = {
        "event": "destination.test",
        "message": "Telemonitor destination test — no message content included.",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
    ok, code, err = send_alert_payload(db, dest, payload, timeout)
    if ok:
        logger.info("destination test succeeded", extra={"type": dest.get("type")})
        return {"ok": True, "status_code": code}
    logger.info("destination test failed", extra={"type": dest.get("type"), "error": err})
    return {"ok": False, "status_code": code, "error": err}
