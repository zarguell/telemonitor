"""Procrastinate worker process for realtime/alerts/maintenance queues.

Also runs the maintenance scheduler (enqueues periodic jobs) and a worker
heartbeat loop. Start with: python -m app.worker
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from datetime import datetime, timezone

from .config import settings
from sqlalchemy import select

from .db import db_session
from .jobs import (
    TASK_ALERT_CLOSE_DEDUPE,
    TASK_REPROCESS_STALE,
    TASK_RETENTION,
    TASK_SOURCE_RECONCILE,
    TASK_WORKER_HEALTH,
    app as procrastinate_app,
    enqueue,
    ensure_open,
)
from .models import WorkerHeartbeat
from .redact import install_redaction

logger = logging.getLogger("telemonitor.worker")

QUEUES = ["realtime", "alerts", "maintenance"]


def _heartbeat_loop(name: str, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            db = db_session()
            try:
                hb = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.name == name))
                if hb is None:
                    hb = WorkerHeartbeat(name=name, kind="worker", queues=",".join(QUEUES))
                    db.add(hb)
                hb.kind = "worker"
                hb.queues = ",".join(QUEUES)
                hb.status = "up"
                hb.last_beat_at = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            logger.exception("worker heartbeat failed")
        time.sleep(20)


def _scheduler_loop(stop: threading.Event) -> None:
    """Enqueue maintenance jobs on an interval. Jobs are cheap/idempotent/guarded."""
    while not stop.is_set():
        try:
            enqueue(TASK_RETENTION)
            enqueue(TASK_REPROCESS_STALE)
            enqueue(TASK_SOURCE_RECONCILE)
            enqueue(TASK_WORKER_HEALTH)
            enqueue(TASK_ALERT_CLOSE_DEDUPE)
        except Exception:  # noqa: BLE001
            logger.exception("maintenance scheduler failed")
        time.sleep(60)


def main() -> None:
    install_redaction()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ensure_open()  # opens connector so the scheduler thread can defer jobs

    name = f"worker-{socket.gethostname()}"
    stop = threading.Event()
    threads = [
        threading.Thread(target=_heartbeat_loop, args=(name, stop), daemon=True),
        threading.Thread(target=_scheduler_loop, args=(stop,), daemon=True),
    ]
    for t in threads:
        t.start()

    logger.info("worker starting queues=%s", QUEUES)
    try:
        procrastinate_app.run_worker(queues=QUEUES, wait=True)
    finally:
        stop.set()


if __name__ == "__main__":
    main()
