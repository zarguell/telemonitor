"""Simulated Telegram account for local testing (TM_SIMULATE_TELEGRAM=1).

Deterministic history (per chat, per 15-minute slot) so backfill jobs are
resumable and repeatable. Live messages are generated on a timer and via the
internal /control/sim/message endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..crypto import encrypt_secret, key_fingerprint
from ..db import db_session
from ..models import TelegramConfiguration, TelegramStatus
from .collector_state import get_service
from .telegram_client import TelegramServiceProtocol, set_status

logger = logging.getLogger(__name__)

SLOT_SECONDS = 900  # 15 minutes

_DIALOGS = [
    {
        "chat_id": 1001000000001,
        "title": "Security Alerts",
        "username": "sec_alerts",
        "type": "channel",
    },
    {
        "chat_id": 1001000000002,
        "title": "Threat Intel Daily",
        "username": "threat_intel_daily",
        "type": "channel",
    },
    {
        "chat_id": 1001000000003,
        "title": "Ops Notifications",
        "username": "ops_notifications",
        "type": "group",
    },
]

_BENIGN = [
    "Weekly status update: build pipeline is green.",
    "Reminder: patch Tuesday maintenance window this weekend.",
    "The staging environment is stable. No action required.",
    "Coffee machine restocked on floor 3.",
    "Network maintenance scheduled Sunday 02:00-04:00 UTC.",
    "Q3 roadmap review moved to Thursday.",
    "On-call rotation published for next month.",
    "DNS change for internal tooling is complete.",
    "Backup verification passed for all primary services.",
    "New hire onboarding checklist updated.",
]

_TRIGGER = [
    "URGENT: critical credential stuffing campaign observed against corporate VPN endpoints. "
    "Indicators: SHA256 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08, "
    "email ops@example.com, domain vpn-auth.example.net.",
    "APT29-style activity: phishing email with attachment link https://evil.example.net/update.php",
    "Wallet drain attempt: BTC address bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh associated with "
    "a known cluster. Contact @darktrace_ops on Telegram.",
    "New IOC: 45.155.205.233 and 2a03:2880:f11c:8083:face:b00c:0:1 — block at the perimeter.",
    "Malware sample hash md5 098f6bcd4621d373cade4e832627b4f6 — treat as malicious.",
    "Credential leak: 1.2.3.4:8080 exposed admin panel with default creds.",
    "URGENT: phishkit domain renewed — track github.io subdomain c2-update-7f3a.",
]

_TEMPLATES = _BENIGN + _TRIGGER


def _pick_template(chat_id: int, msg_id: int) -> str:
    h = hashlib.sha256(f"{chat_id}:{msg_id}".encode()).hexdigest()
    return _TEMPLATES[int(h, 16) % len(_TEMPLATES)]


def _sim_permalink(chat_id: int, msg_id: int) -> str | None:
    d = next((x for x in _DIALOGS if x["chat_id"] == chat_id), None)
    if d and d["username"]:
        return f"https://t.me/{d['username']}/{msg_id}"
    return None


def _make_message(chat_id: int, msg_id: int, ts: datetime, text: str | None = None) -> dict:
    text = text if text is not None else _pick_template(chat_id, msg_id)
    return {
        "id": msg_id,
        "chat_id": chat_id,
        "date": ts,
        "text": text,
        "sender_id": 999000001,
        "reply_to_msg_id": None,
        "forward_from_id": None,
        "forward_from_name": None,
        "media_type": None,
        "media_meta": None,
        "edit_date": None,
        "permalink": _sim_permalink(chat_id, msg_id),
        "out": False,
    }


class SimTelegramService(TelegramServiceProtocol):
    def __init__(self) -> None:
        self._on_new_message = None
        self._running = False
        self._generator_task: asyncio.Task | None = None
        self._next_live_id = 2_000_000_000
        self._connected = False

    # auth helpers --------------------------------------------------------

    def _db(self) -> Session:
        return db_session()

    async def start(self) -> None:
        db = self._db()
        try:
            cfg = db.get(TelegramConfiguration, 1)
            if cfg is None:
                set_status(db, TelegramStatus.NOT_CONFIGURED)
            elif cfg.session_enc:
                self._connected = True
                set_status(db, TelegramStatus.AUTHORIZED, "connected (simulated)")
                self._start_generator()
            else:
                set_status(db, cfg.status or TelegramStatus.NOT_CONFIGURED)
        finally:
            db.close()

    async def stop(self) -> None:
        self._running = False
        if self._generator_task:
            self._generator_task.cancel()
            self._generator_task = None
        self._connected = False

    async def initialize(self, api_id: str, api_hash: str) -> dict:
        db = self._db()
        try:
            cfg = db.get(TelegramConfiguration, 1)
            if cfg is None:
                cfg = TelegramConfiguration(id=1)
                db.add(cfg)
            cfg.api_id_enc = encrypt_secret(api_id)
            cfg.api_hash_enc = encrypt_secret(api_hash)
            cfg.session_key_ref = key_fingerprint()
            set_status(db, TelegramStatus.WAITING_PHONE, "simulated: enter phone number")
        finally:
            db.close()
        return self.status()

    async def submit_phone(self, phone: str) -> dict:
        db = self._db()
        try:
            cfg = db.get(TelegramConfiguration, 1)
            if cfg is not None:
                cfg.phone_enc = encrypt_secret(phone)
            set_status(db, TelegramStatus.WAITING_CODE, "simulated: enter one-time code")
        finally:
            db.close()
        return self.status()

    async def submit_code(self, code: str) -> dict:
        from ..config import settings

        if code != settings.sim_otp:
            db = self._db()
            try:
                set_status(db, TelegramStatus.WAITING_CODE, "simulated: invalid code, try again")
            finally:
                db.close()
            return self.status()
        db = self._db()
        try:
            phone = db.get(TelegramConfiguration, 1).phone_enc if db.get(TelegramConfiguration, 1) else None
        finally:
            db.close()
        from ..crypto import decrypt_secret

        plain_phone = decrypt_secret(phone) if phone else ""
        if plain_phone.rstrip().endswith("2"):
            # Simulated 2FA: account with phone ending in "2" requires a password.
            self._awaiting_2fa = True
            db = self._db()
            try:
                set_status(db, TelegramStatus.WAITING_2FA, "simulated: two-factor password required")
            finally:
                db.close()
            return self.status()
        return await self._finish_authorized()

    async def _finish_authorized(self) -> dict:
        self._connected = True
        db = self._db()
        try:
            cfg = db.get(TelegramConfiguration, 1)
            if cfg is not None:
                cfg.session_enc = "sim:session:placeholder"
                cfg.connected_account = "Simulated Account"
            set_status(db, TelegramStatus.AUTHORIZED, "connected (simulated)")
        finally:
            db.close()
        self._start_generator()
        return self.status()

    async def submit_password(self, password: str) -> dict:
        if not getattr(self, "_awaiting_2fa", False) or not password:
            return self.status()
        self._awaiting_2fa = False
        return await self._finish_authorized()

    async def disconnect(self) -> dict:
        await self.stop()
        db = self._db()
        try:
            cfg = db.get(TelegramConfiguration, 1)
            if cfg is not None:
                cfg.session_enc = None
                cfg.connected_account = None
                cfg.status = TelegramStatus.DISCONNECTED
                cfg.status_detail = "local session revoked (simulated)"
                db.commit()
        finally:
            db.close()
        return self.status()

    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> dict:
        db = self._db()
        try:
            cfg = db.get(TelegramConfiguration, 1)
            if cfg is None:
                return {"state": TelegramStatus.NOT_CONFIGURED}
            return {
                "state": cfg.status,
                "detail": cfg.status_detail,
                "error": cfg.last_error,
                "connected_account": cfg.connected_account,
                "last_update": cfg.last_update_at.isoformat() if cfg.last_update_at else None,
                "collector_heartbeat": cfg.collector_heartbeat_at.isoformat() if cfg.collector_heartbeat_at else None,
                "simulated": True,
            }
        finally:
            db.close()

    async def get_dialogs(self) -> list[dict]:
        if not self._connected:
            return []
        now = datetime.now(timezone.utc)
        return [
            {**d, "last_activity_at": now - timedelta(minutes=7 * (i + 1)), "unread": 0}
            for i, d in enumerate(_DIALOGS)
        ]

    # history (deterministic) --------------------------------------------

    def _slots(self, chat_id: int, start_ts: datetime, end_ts: datetime) -> list[tuple[int, int]]:
        """(msg_id, epoch_slot) pairs for 15-minute slots in [start_ts, end_ts), newest first."""
        start = int(start_ts.timestamp())
        end = int(end_ts.timestamp())
        first_slot = start // SLOT_SECONDS
        last_slot = end // SLOT_SECONDS
        base = chat_id % 1_000_000
        pairs = [(base * 1_000_000 + s, s) for s in range(first_slot, last_slot + 1)]
        return sorted(pairs, key=lambda p: p[0], reverse=True)

    def _history_for(self, chat_id: int, offset_id: int | None, limit: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        start_ts = now - timedelta(days=365)
        pairs = self._slots(chat_id, start_ts, now)
        if offset_id is not None:
            pairs = [p for p in pairs if p[0] < offset_id]
        pairs = pairs[:limit]
        return [
            _make_message(
                chat_id,
                msg_id,
                datetime.fromtimestamp(slot * SLOT_SECONDS, tz=timezone.utc),
            )
            for msg_id, slot in pairs
        ]

    def get_history_sync(self, chat_id: int, offset_id: int | None = None, limit: int = 100) -> list[dict]:
        return self._history_for(chat_id, offset_id, limit)

    # live generation -----------------------------------------------------

    def _start_generator(self) -> None:
        if self._generator_task and not self._generator_task.done():
            return
        self._running = True
        self._generator_task = asyncio.ensure_future(self._live_loop())

    async def _live_loop(self) -> None:
        from ..models import Source, SourceStatus

        while self._running:
            try:
                await asyncio.sleep(20)
                db = self._db()
                try:
                    enabled = list(
                        db.query(Source)
                        .filter(Source.enabled.is_(True))
                        .filter(Source.status.in_([SourceStatus.LIVE, SourceStatus.ENABLED]))
                        .all()
                    )
                finally:
                    db.close()
                if not enabled:
                    continue
                src = random.choice(enabled)
                self._next_live_id += 1
                msg = _make_message(
                    src.telegram_chat_id,
                    self._next_live_id,
                    datetime.now(timezone.utc),
                    text=random.choice(_TEMPLATES),
                )
                if self._on_new_message:
                    await self._on_new_message(msg)
                logger.info("simulated live message", extra={"chat_id": src.telegram_chat_id})
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("sim live loop error")

    async def inject_message(self, chat_id: int, text: str | None = None) -> dict | None:
        """Control endpoint: inject a specific message into a chat (sim only)."""
        if not self._connected:
            return None
        if not any(d["chat_id"] == chat_id for d in _DIALOGS):
            raise ValueError(f"unknown chat_id {chat_id}")
        self._next_live_id += 1
        msg = _make_message(chat_id, self._next_live_id, datetime.now(timezone.utc), text=text)
        if self._on_new_message:
            await self._on_new_message(msg)
        return msg

    def set_new_message_callback(self, cb) -> None:
        self._on_new_message = cb
