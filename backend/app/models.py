"""ORM models for Telemonitor (PostgreSQL)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Enumerated values (stored as varchar for migration friendliness) ---

class Roles:
    ADMIN = "admin"
    OPERATOR = "operator"
    ANALYST = "analyst"


class TelegramStatus:
    NOT_CONFIGURED = "not_configured"
    INIT_REQUIRED = "initialization_required"
    WAITING_PHONE = "waiting_phone"
    WAITING_CODE = "waiting_code"
    WAITING_2FA = "waiting_2fa"
    AUTHORIZED = "authorized"
    CONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class SourceStatus:
    DISCOVERED = "discovered"
    ENABLED = "enabled"
    BACKFILLING = "backfilling"
    LIVE = "live"
    PAUSED = "paused"
    ERROR = "error"


class SourceType:
    CHANNEL = "channel"
    GROUP = "group"
    BOT = "bot"
    USER = "user"


class BackfillMode:
    NONE = "none"
    HOURS_24 = "last_24h"
    DAYS_7 = "last_7d"
    DAYS_30 = "last_30d"
    CUSTOM = "custom"


class MessageState:
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    DELETED = "deleted"


class EventType:
    CREATED = "created"
    EDITED = "edited"
    DELETED = "deleted"


class Severity:
    INFO = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertState:
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class DeliveryState:
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class DeliveryAttemptStatus:
    SUCCESS = "success"
    FAILED = "failed"


class IndicatorType:
    URL = "url"
    DOMAIN = "domain"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    EMAIL = "email"
    HASH = "hash"
    CRYPTO = "crypto"
    TELEGRAM_USERNAME = "telegram_username"
    ALIAS = "alias"
    KEYWORD = "keyword"


class RuleConditionType:
    KEYWORD = "keyword"
    PHRASE = "phrase"
    REGEX = "regex"
    INDICATOR = "indicator"
    SOURCE = "source"


# --- Models ---


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Roles.ANALYST)
    display_name: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramConfiguration(Base):
    """Singleton row (id=1) holding encrypted credential/session material."""

    __tablename__ = "telegram_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_id_enc: Mapped[str | None] = mapped_column(Text)  # Fernet(api_id)
    api_hash_enc: Mapped[str | None] = mapped_column(Text)  # Fernet(api_hash)
    phone_enc: Mapped[str | None] = mapped_column(Text)  # Fernet(phone)
    session_enc: Mapped[str | None] = mapped_column(Text)  # Fernet(StringSession)
    session_key_ref: Mapped[str | None] = mapped_column(String(128))  # key fingerprint, not the key
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TelegramStatus.NOT_CONFIGURED)
    status_detail: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_account: Mapped[str | None] = mapped_column(String(256))  # sanitized display only
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collector_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # collector | worker
    queues: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="up")
    last_beat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    username: Mapped[str | None] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16), nullable=False, default=SourceType.CHANNEL)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowlisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SourceStatus.DISCOVERED)
    backfill_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=BackfillMode.NONE)
    backfill_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_checkpoint: Mapped[int | None] = mapped_column(BigInteger)  # next offset_id to fetch
    backfill_total: Mapped[int | None] = mapped_column(Integer)
    backfill_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backfill_error: Mapped[str | None] = mapped_column(Text)
    backfill_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_sources_enabled", "enabled"),
        Index("ix_sources_status", "status"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    reply_to_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    forward_from_id: Mapped[int | None] = mapped_column(BigInteger)
    forward_from_name: Mapped[str | None] = mapped_column(String(256))
    media_type: Mapped[str | None] = mapped_column(String(64))
    media_metadata: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=MessageState.PENDING)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    permalink: Mapped[str | None] = mapped_column(Text)
    process_error: Mapped[str | None] = mapped_column(Text)
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[Source] = relationship(back_populates="messages")
    indicators: Mapped[list["Indicator"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    events: Mapped[list["MessageEvent"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    rule_matches: Mapped[list["RuleMatch"]] = relationship(back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_id", "telegram_message_id", name="uq_message_source_tg_id"),
        Index("ix_messages_sent_at", "sent_at"),
        Index("ix_messages_source_sent", "source_id", "sent_at"),
        Index("ix_messages_state_ingested", "state", "ingested_at"),
    )


class MessageEvent(Base):
    __tablename__ = "message_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    detail: Mapped[dict | None] = mapped_column(JSONB)

    message: Mapped[Message] = relationship(back_populates="events")


class Indicator(Base):
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # original matched text
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)  # canonical form
    matched_text: Mapped[str | None] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    message: Mapped[Message] = relationship(back_populates="indicators")

    __table_args__ = (
        Index("ix_indicators_type_value", "type", "normalized_value"),
        Index("ix_indicators_message", "message_id"),
    )


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.MEDIUM)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {match, conditions[]}
    source_scope: Mapped[list | None] = mapped_column(JSONB)  # [source_id, ...] or null = all
    dedup_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_match_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    matches: Mapped[list["RuleMatch"]] = relationship(back_populates="rule", cascade="all, delete-orphan")


class RuleMatch(Base):
    __tablename__ = "rule_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_conditions: Mapped[list | None] = mapped_column(JSONB)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    message: Mapped[Message] = relationship(back_populates="rule_matches")
    rule: Mapped[Rule] = relationship(back_populates="matches")

    __table_args__ = (
        UniqueConstraint("message_id", "rule_id", name="uq_rule_match_message_rule"),
        Index("ix_rule_matches_rule_time", "rule_id", "matched_at"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"))
    rule_version: Mapped[int | None] = mapped_column(Integer)  # snapshot at match time
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=Severity.MEDIUM)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertState.OPEN)
    excerpt: Mapped[str | None] = mapped_column(Text)
    dedup_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    delivery_state: Mapped[str] = mapped_column(String(16), nullable=False, default=DeliveryState.PENDING)
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delivery_error: Mapped[str | None] = mapped_column(Text)
    dedupe_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triage_note: Mapped[str | None] = mapped_column(Text)
    triaged_by: Mapped[str | None] = mapped_column(String(64))
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    rule: Mapped[Rule | None] = relationship()
    source: Mapped[Source | None] = relationship()
    messages: Mapped[list[Message]] = relationship(
        secondary="alert_messages", backref="alerts", lazy="selectin"
    )
    deliveries: Mapped[list["AlertDelivery"]] = relationship(back_populates="alert", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_alerts_state_severity", "state", "severity"),
        Index("ix_alerts_created", "created_at"),
        Index("ix_alerts_dedupe_key", "dedupe_key"),
    )


class AlertMessage(Base):
    __tablename__ = "alert_messages"

    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    destination_type: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_ref: Mapped[str | None] = mapped_column(String(256))  # masked (e.g. https://***)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DeliveryAttemptStatus.FAILED)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    alert: Mapped[Alert] = relationship(back_populates="deliveries")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSONB)  # sanitized only — never secrets
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_action", "action"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(64))
