"""Health/liveness/readiness endpoint (public)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import select, text

from ..db import db_session
from ..models import TelegramConfiguration, WorkerHeartbeat

router = APIRouter(prefix="/health", tags=["health"])

_QUEUE_STATS_SQL = text(
    """
    SELECT queue_name,
           count(*) FILTER (WHERE status = 'todo') AS depth,
           min(scheduled_at) FILTER (WHERE status = 'todo') AS oldest_todo,
           count(*) FILTER (WHERE status = 'failed') AS failed,
           max(scheduled_at) FILTER (WHERE status = 'succeeded') AS last_success
    FROM procrastinate_jobs
    GROUP BY queue_name
    """
)


def _queue_stats(db) -> dict:
    try:
        rows = db.execute(_QUEUE_STATS_SQL).mappings().all()
        return {
            r["queue_name"]: {
                "depth": r["depth"] or 0,
                "oldest_todo": r["oldest_todo"].isoformat() if r["oldest_todo"] else None,
                "failed": r["failed"] or 0,
                "last_success": r["last_success"].isoformat() if r["last_success"] else None,
            }
            for r in rows
        }
    except Exception:  # noqa: BLE001
        return {}


def _collector_state(db) -> dict:
    """Sanitized collector state for the public health endpoint (no error text)."""
    tg = db.get(TelegramConfiguration, 1)
    if tg is None:
        return {"state": "not_configured", "heartbeat": None, "connected": False}
    hb = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.name == "collector"))
    fresh = tg.collector_heartbeat_at and tg.collector_heartbeat_at >= datetime.now(timezone.utc) - timedelta(seconds=90)
    return {
        "state": tg.status,
        "heartbeat": tg.collector_heartbeat_at.isoformat() if tg.collector_heartbeat_at else None,
        "worker": hb.status if hb else "unknown",
        "connected": bool(fresh and tg.status == "authorized"),
    }


def _workers_state(db) -> dict:
    out = {}
    for hb in db.query(WorkerHeartbeat).all():
        out[hb.name] = {
            "kind": hb.kind,
            "status": hb.status,
            "queues": hb.queues,
            "last_beat_at": hb.last_beat_at.isoformat() if hb.last_beat_at else None,
        }
    return out


@router.get("")
def health():
    db = db_session()
    try:
        db_ok = True
        try:
            db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        collector = _collector_state(db)
        return {
            "status": "ok" if db_ok else "degraded",
            "service": "telemonitor-api",
            "version": "1.0.0",
            "database": {"ok": db_ok},
            "collector": collector,
            "workers": _workers_state(db),
            "queues": _queue_stats(db),
            "time": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        db.close()
