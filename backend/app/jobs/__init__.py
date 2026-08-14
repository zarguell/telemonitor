"""Procrastinate application and background job definitions (procrastinate >= 3.9).

Queues:
- realtime:  normalize / extract / evaluate / alert candidates
- alerts:    delivery, retries, dedupe window closing
- backfill:  historical fetch + checkpointing (runs inside the collector process)
- maintenance: retention, stale reprocessing, reconciliation, health
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import procrastinate
from procrastinate.exceptions import JobRetry
from procrastinate.retry import RetryDecision
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import db_session
from ..models import (
    Alert,
    AlertDelivery,
    AlertMessage,
    DeliveryAttemptStatus,
    DeliveryState,
    Indicator,
    Message,
    MessageState,
    Rule,
    RuleMatch,
    Source,
    SourceStatus,
    TelegramConfiguration,
)
from ..services import retention  # noqa: F401  (imported so the module is wired)
from ..services.alerts_service import close_dedupe_windows, create_alert_candidate
from ..services.delivery import build_alert_payload, get_destination, send_alert_payload
from ..services.extractors import EXTRACTOR_VERSION, extract_indicators
from ..services.normalize import excerpt, normalize_text
from ..services.rules_engine import evaluate_rule

logger = logging.getLogger(__name__)

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = settings.procrastinate_database_url

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=settings.procrastinate_database_url)
)
# Separate sync-only app for all enqueue/defer operations. Mixing sync defers
# with run_worker's async pool in one process deadlocks pool initialization.
sync_app = procrastinate.App(
    connector=procrastinate.SyncPsycopgConnector(conninfo=settings.procrastinate_database_url)
)

TASK_REALTIME_PROCESS = "realtime.process_message"
TASK_ALERT_DELIVER = "alerts.deliver"
TASK_ALERT_CLOSE_DEDUPE = "alerts.close_dedupe_windows"
TASK_BACKFILL_PAGE = "backfill.fetch_page"
TASK_MEDIA_DOWNLOAD = "media.download"
TASK_MEDIA_BACKFILL = "media.backfill_missing"
TASK_RETENTION = "maintenance.retention"
TASK_REPROCESS_STALE = "maintenance.reprocess_stale"
TASK_SOURCE_RECONCILE = "maintenance.source_reconcile"
TASK_WORKER_HEALTH = "maintenance.worker_health"


def enqueue(task_name: str, **kwargs) -> int:
    """Defer a job via the sync app; requires it to be open (see ensure_open).

    The queue is taken from the task registered on the worker app, because
    deferring by name on sync_app does not inherit queue attributes.
    """
    task = app.tasks.get(task_name)
    queue = task.queue if task is not None else None
    options = {"queue": queue} if queue else {}
    return sync_app.configure_task(name=task_name, **options).defer(**kwargs)


def _procrastinate_schema_exists() -> bool:
    from ..db import engine

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'procrastinate_jobs')"
                )
            ).scalar()
            return bool(row)
    except Exception:  # noqa: BLE001
        return False


def ensure_open() -> None:
    """Open the sync app connector (idempotent). Safe to call from any process/thread."""
    sync_app.open()
    if not _procrastinate_schema_exists():
        sync_app.schema_manager.apply_schema()


def _db_retry(seconds: float) -> JobRetry:
    return JobRetry(RetryDecision(retry_in={"seconds": seconds}))


# ---------------------------------------------------------------------------
# realtime
# ---------------------------------------------------------------------------


class _JobRetryOnlyStrategy(procrastinate.RetryStrategy):
    """Only honor explicit JobRetry decisions raised by tasks.

    Unexpected exceptions fail the job immediately instead of retry-looping.
    """

    def get_retry_decision(self, *, exception, job):
        if isinstance(exception, JobRetry):
            return exception.retry_decision
        return None


RETRY_STRATEGY = _JobRetryOnlyStrategy()


@app.task(name=TASK_REALTIME_PROCESS, queue="realtime", retry=RETRY_STRATEGY)
def process_message(message_id: int):
    db = db_session()
    try:
        msg = db.get(Message, message_id)
        if msg is None:
            return
        if msg.state in (MessageState.PROCESSED, MessageState.FAILED):
            return  # idempotent; FAILED is terminal
        msg.processing_attempts = (msg.processing_attempts or 0) + 1
        source = db.get(Source, msg.source_id)
        try:
            if not msg.normalized_text:
                msg.normalized_text = normalize_text(msg.original_text)

            from ..audit import get_setting

            aliases = (get_setting(db, "aliases", {}) or {}).get("items", []) or []
            # Entity-only URLs (Telegram link previews) are appended so the
            # indicator pipeline sees them even though they are absent from
            # the plain message text.
            extraction_text = msg.original_text or ""
            if msg.extra_text:
                extraction_text = f"{extraction_text}\n{msg.extra_text}"
            inds = extract_indicators(extraction_text, aliases)
            # replace indicators idempotently
            db.execute(delete(Indicator).where(Indicator.message_id == msg.id))
            for ind in inds:
                db.add(
                    Indicator(
                        message_id=msg.id,
                        type=ind["type"],
                        value=ind["value"],
                        normalized_value=ind["normalized_value"],
                        matched_text=ind.get("matched_text"),
                        extractor_version=EXTRACTOR_VERSION,
                        confidence=ind.get("confidence"),
                        observed_at=msg.sent_at or datetime.now(timezone.utc),
                    )
                )
            db.flush()

            rules = list(db.scalars(select(Rule).where(Rule.enabled.is_(True))))
            ctx = {
                "normalized_text": msg.normalized_text,
                "source_id": source.id if source else None,
                "indicators": inds,
            }
            for rule in rules:
                scope = rule.source_scope
                if scope and source and source.id not in [int(s) for s in scope]:
                    continue
                result = evaluate_rule(rule.definition, ctx)
                if not result["matched"]:
                    continue
                match_excerpt = excerpt(msg.original_text, rule.name)
                existing = db.scalar(
                    select(RuleMatch).where(
                        RuleMatch.message_id == msg.id, RuleMatch.rule_id == rule.id
                    )
                )
                if existing is None:
                    db.add(
                        RuleMatch(
                            message_id=msg.id,
                            rule_id=rule.id,
                            excerpt=match_excerpt,
                            rule_version=rule.version,
                            matched_conditions=result["matched_conditions"],
                            matched_at=datetime.now(timezone.utc),
                        )
                    )
                else:
                    # reprocessed (edited) content: refresh match snapshot
                    existing.excerpt = match_excerpt
                    existing.rule_version = rule.version
                    existing.matched_conditions = result["matched_conditions"]
                    existing.matched_at = datetime.now(timezone.utc)
                rule.last_match_at = datetime.now(timezone.utc)
                if source:
                    create_alert_candidate(
                        db,
                        rule=rule,
                        message=msg,
                        source=source,
                        excerpt=match_excerpt,
                        matched_conditions=result["matched_conditions"],
                    )
            msg.state = MessageState.PROCESSED
            msg.process_error = None
            if source:
                # newest-wins: concurrent processing must not regress the
                # "last received message" indicator to an older message
                if not source.last_message_at or (msg.sent_at and msg.sent_at > source.last_message_at):
                    source.last_message_at = msg.sent_at or msg.ingested_at
                source.last_success_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:  # noqa: BLE001
            # Persist the attempt counter separately: the transaction rollback
            # above would otherwise undo it and the job would retry forever.
            db.rollback()
            msg = db.get(Message, message_id)
            if msg is not None:
                msg.processing_attempts = (msg.processing_attempts or 0) + 1
                msg.process_error = f"{type(e).__name__}: {e}"[:500]
                if (msg.processing_attempts or 0) >= 3:
                    msg.state = MessageState.FAILED
                db.commit()
            logger.warning("realtime processing failed", extra={"message_id": message_id, "error": str(e), "attempts": msg.processing_attempts if msg else None})
            if msg is None or msg.state == MessageState.FAILED:
                return  # terminal — stop retrying
            raise _db_retry(10)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------


@app.task(name=TASK_ALERT_DELIVER, queue="alerts", retry=RETRY_STRATEGY)
def deliver_alert(alert_id: int):
    db = db_session()
    try:
        alert = db.get(Alert, alert_id)
        if alert is None:
            return
        if alert.delivery_state == DeliveryState.DELIVERED:
            return  # idempotent
        dest = get_destination(db)
        if not dest or dest.get("type") in (None, "none"):
            alert.delivery_state = DeliveryState.SKIPPED
            alert.last_delivery_error = "no alert destination configured"
            db.commit()
            logger.info("alert delivery skipped (no destination)", extra={"alert_id": alert_id})
            return
        alert.delivery_state = DeliveryState.DELIVERING
        alert.delivery_attempts = (alert.delivery_attempts or 0) + 1
        db.commit()
        payload = build_alert_payload(db, alert)
        ok, status_code, error = send_alert_payload(db, dest, payload, settings.webhook_timeout_seconds)
        db.add(
            AlertDelivery(
                alert_id=alert_id,
                destination_type=str(dest.get("type")),
                destination_ref=_masked_dest(dest),
                attempt=alert.delivery_attempts,
                status=DeliveryAttemptStatus.SUCCESS if ok else DeliveryAttemptStatus.FAILED,
                status_code=status_code,
                error=error,
            )
        )
        if ok:
            alert.delivery_state = DeliveryState.DELIVERED
            alert.last_delivery_error = None
            db.commit()
            logger.info("alert delivered", extra={"alert_id": alert_id, "attempt": alert.delivery_attempts})
            return
        alert.last_delivery_error = error
        db.commit()
        if (alert.delivery_attempts or 0) >= settings.delivery_max_attempts:
            alert.delivery_state = DeliveryState.FAILED
            db.commit()
            logger.error("alert delivery permanently failed", extra={"alert_id": alert_id, "error": error})
            return
        backoff = min(30 * (2 ** min(alert.delivery_attempts - 1, 5)), 3600)
        logger.info("alert delivery scheduled retry", extra={"alert_id": alert_id, "backoff": backoff})
        raise _db_retry(backoff)
    except JobRetry:
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.exception("deliver_alert unexpected error", extra={"alert_id": alert_id})
        alert = db.get(Alert, alert_id)
        attempts = (alert.delivery_attempts or 0) if alert else 0
        if alert is not None and attempts >= settings.delivery_max_attempts:
            alert.delivery_state = DeliveryState.FAILED
            alert.last_delivery_error = f"{type(e).__name__}: {e}"[:300]
            db.commit()
            logger.error("alert delivery permanently failed (exception path)", extra={"alert_id": alert_id})
            return
        raise _db_retry(60) from e
    finally:
        db.close()


def _masked_dest(dest: dict) -> str:
    from ..crypto import mask

    if dest.get("type") == "webhook":
        return mask(dest.get("url", ""), 8)
    if dest.get("type") == "telegram_bot":
        return f"chat:{str(dest.get('chat_id', ''))[:6]}…"
    return str(dest.get("type"))


@app.task(name=TASK_ALERT_CLOSE_DEDUPE, queue="alerts")
def close_dedupe_windows_task():
    db = db_session()
    try:
        n = close_dedupe_windows(db)
        logger.info("dedupe windows closed", extra={"count": n})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# backfill (runs inside collector process)
# ---------------------------------------------------------------------------


@app.task(name=TASK_BACKFILL_PAGE, queue="backfill", retry=RETRY_STRATEGY)
def fetch_backfill_page(source_id: int):
    """Fetch one page of history for a source and re-enqueue until complete."""
    from ..services.collector_state import get_service

    db = db_session()
    try:
        source = db.get(Source, source_id)
        if source is None:
            return
        if source.status != SourceStatus.BACKFILLING:
            return  # paused/stopped by operator — no-op
        service = get_service()
        if service is None:
            raise RuntimeError("telegram service not available in this process")

        # Verify the Telegram service is actually usable before interpreting an
        # empty page as "history exhausted" (a disconnected/unconfigured client
        # returns an empty page and must NOT flip the source to live).
        if service.status().get("state") != "authorized":
            raise RuntimeError("telegram service not authorized; deferring backfill")
        page = service.get_history_sync(
            chat_id=source.telegram_chat_id,
            offset_id=source.backfill_checkpoint,
            limit=100,
        )
        if not page:
            _finish_backfill(db, source)
            return
        from ..services.collector import persist_message  # noqa: PLC0415

        oldest = None
        reached_start = False
        persisted = 0
        for m in page:
            # The page is newest-first; once a message predates the configured
            # window, everything after it is out of scope — do not ingest it.
            if source.backfill_start and m.get("date") and m["date"] < source.backfill_start:
                reached_start = True
                break
            persist_message(db, m)
            persisted += 1
            if oldest is None or m["id"] < oldest:
                oldest = m["id"]
        source.backfill_done = (source.backfill_done or 0) + persisted
        source.backfill_checkpoint = oldest - 1 if oldest else None
        source.backfill_failures = 0
        db.commit()

        if len(page) < 100 or reached_start:
            _finish_backfill(db, source)
            return
        raise _db_retry(1)  # continue pagination
    except JobRetry:
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        source = db.get(Source, source_id)
        if source is not None:
            seconds = getattr(e, "seconds", None)
            if type(e).__name__ == "FloodWaitError" or seconds is not None:
                wait = int(seconds or 10) + 5
                source.backfill_failures = (source.backfill_failures or 0) + 1
                db.commit()
                logger.warning("backfill rate limited", extra={"source_id": source_id, "wait": wait})
                raise _db_retry(wait)
            source.backfill_failures = (source.backfill_failures or 0) + 1
            source.backfill_error = f"{type(e).__name__}: {e}"[:500]
            if (source.backfill_failures or 0) >= 5:
                source.status = SourceStatus.ERROR
                db.commit()
                logger.error("backfill failed permanently", extra={"source_id": source_id, "error": str(e)})
                return
            db.commit()
        logger.warning("backfill page failed", extra={"source_id": source_id, "error": str(e)})
        raise _db_retry(30)
    finally:
        db.close()


def _finish_backfill(db: Session, source: Source) -> None:
    source.status = SourceStatus.LIVE if source.enabled else SourceStatus.PAUSED
    source.backfill_error = None
    source.last_success_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("backfill complete", extra={"source_id": source.id, "done": source.backfill_done})


# ---------------------------------------------------------------------------
# media (runs inside the collector process: needs the Telegram client)
# ---------------------------------------------------------------------------

# Media types eligible for storage (images only, per product scope).
_IMAGE_DOC_TYPES = {"photo"}
_ALLOWED_MEDIA_TYPES = {"photo", "document"}


def _media_enabled(db: Session) -> bool:
    from ..audit import get_setting

    cfg = get_setting(db, "media_settings", {}) or {}
    return bool((cfg or {}).get("store_media"))


@app.task(name=TASK_MEDIA_DOWNLOAD, queue="media", retry=RETRY_STRATEGY)
def download_media(message_id: int):
    """Download and store a message's image via the MediaStore (idempotent)."""
    from ..services.storage import MediaStoreError, get_media_store

    db = db_session()
    try:
        msg = db.get(Message, message_id)
        if msg is None or msg.media_stored:
            return
        if not _media_enabled(db):
            return  # toggle off — metadata only
        if msg.media_type not in _ALLOWED_MEDIA_TYPES:
            return
        meta = msg.media_metadata or {}
        if msg.media_type == "document" and not str(meta.get("mime_type", "")).startswith("image/"):
            return
        from ..services.collector_state import get_service

        service = get_service()
        if service is None:
            raise RuntimeError("telegram service not available in this process")
        result = service.download_media_sync(msg.source.telegram_chat_id, msg.telegram_message_id)
        if result is None:
            logger.debug("no downloadable image", extra={"message_id": message_id})
            return
        data = result["data"]
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        try:
            get_media_store().put(digest, data, result.get("content_type"))
        except MediaStoreError as e:
            raise RuntimeError(f"media store failure: {e}") from e
        msg.media_sha256 = digest
        msg.media_content_type = result.get("content_type")
        msg.media_size_bytes = result.get("size") or len(data)
        msg.media_filename = result.get("filename")
        msg.media_stored = True
        db.commit()
        logger.info("media stored", extra={"message_id": message_id, "bytes": len(data)})
    except JobRetry:
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("media download failed", extra={"message_id": message_id, "error": str(e)})
        raise _db_retry(30)
    finally:
        db.close()


@app.task(name=TASK_MEDIA_BACKFILL, queue="maintenance")
def media_backfill_missing_task():
    """Enqueue media downloads for already-ingested messages with media metadata."""
    db = db_session()
    try:
        if not _media_enabled(db):
            return
        rows = list(
            db.scalars(
                select(Message.id)
                .where(
                    Message.media_type.in_(_ALLOWED_MEDIA_TYPES),
                    Message.media_stored.is_(False),
                    Message.state == MessageState.PROCESSED,
                )
                .limit(100)
            )
        )
        for mid in rows:
            enqueue(TASK_MEDIA_DOWNLOAD, message_id=mid)
        if rows:
            from ..audit import ACTION_MAINTENANCE_RUN, log_audit

            log_audit(
                db,
                actor_user_id=None,
                actor_username="system",
                action=ACTION_MAINTENANCE_RUN,
                object_type="messages",
                detail={"job": "media_backfill", "queued": len(rows)},
            )
            logger.info("media backfill queued", extra={"count": len(rows)})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# maintenance
# ---------------------------------------------------------------------------


@app.task(name=TASK_RETENTION, queue="maintenance")
def retention_task(force: bool = False):
    from ..audit import get_retention_days, get_setting, set_setting

    db = db_session()
    try:
        last = (get_setting(db, "retention_last_run", {}) or {}).get("at")
        if not force and last:
            try:
                last_dt = datetime.fromisoformat(last)
                if datetime.now(timezone.utc) - last_dt < timedelta(hours=23):
                    return
            except ValueError:
                pass
        days = get_retention_days(db)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = retention.delete_expired(db, cutoff)
        set_setting(db, "retention_last_run", {"at": datetime.now(timezone.utc).isoformat()})
        from ..audit import ACTION_RETENTION_RUN, log_audit

        log_audit(
            db,
            actor_user_id=None,
            actor_username="system",
            action=ACTION_RETENTION_RUN,
            object_type="messages",
            detail={"deleted_messages": deleted, "retention_days": days},
        )
        logger.info("retention run complete", extra={"deleted_messages": deleted, "days": days})
    finally:
        db.close()


@app.task(name=TASK_REPROCESS_STALE, queue="maintenance")
def reprocess_stale_task():
    """Re-enqueue messages persisted before a crash but never processed."""
    db = db_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.reprocess_stale_minutes)
        rows = list(
            db.scalars(
                select(Message.id)
                .where(
                    Message.state == MessageState.PENDING,
                    Message.ingested_at < cutoff,
                    Message.processing_attempts < 3,
                )
                .limit(200)
            )
        )
        for mid in rows:
            enqueue(TASK_REALTIME_PROCESS, message_id=mid)
        if rows:
            from ..audit import ACTION_MAINTENANCE_RUN, log_audit

            log_audit(
                db,
                actor_user_id=None,
                actor_username="system",
                action=ACTION_MAINTENANCE_RUN,
                object_type="messages",
                detail={"job": "reprocess_stale", "requeued": len(rows)},
            )
            logger.info("stale messages requeued", extra={"count": len(rows)})
    finally:
        db.close()


@app.task(name=TASK_SOURCE_RECONCILE, queue="maintenance")
def source_reconcile_task():
    db = db_session()
    try:
        sources = list(db.scalars(select(Source)))
        for s in sources:
            if s.enabled and s.status in (SourceStatus.ENABLED, SourceStatus.LIVE):
                s.status = SourceStatus.LIVE
            elif not s.enabled and s.status in (SourceStatus.LIVE, SourceStatus.ENABLED):
                s.status = SourceStatus.PAUSED
        db.commit()
    finally:
        db.close()


@app.task(name=TASK_WORKER_HEALTH, queue="maintenance")
def worker_health_task():
    db = db_session()
    try:
        from ..models import WorkerHeartbeat

        stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
        for hb in db.scalars(select(WorkerHeartbeat)):
            if hb.last_beat_at and hb.last_beat_at < stale_cutoff and hb.status != "down":
                hb.status = "down"
        tg = db.get(TelegramConfiguration, 1)
        if tg and tg.collector_heartbeat_at and tg.collector_heartbeat_at < stale_cutoff:
            tg.status_detail = "collector heartbeat expired"
        # requeue abandoned jobs (worker died mid-job) so backfill/realtime recover.
        # Based on the worker's heartbeat staleness, NOT the job's due time — a
        # job that simply waited in the queue must not be double-executed.
        db.execute(
            text(
                "UPDATE procrastinate_jobs SET status = 'todo', scheduled_at = now() "
                "WHERE status = 'doing' AND worker_id IS NOT NULL AND worker_id NOT IN ("
                "  SELECT id FROM procrastinate_workers "
                "  WHERE last_heartbeat > now() - interval '45 seconds')"
            )
        )
        db.commit()
    finally:
        db.close()
