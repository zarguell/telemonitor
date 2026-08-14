"""Collector process entrypoint.

Runs the Telegram service (real or simulated), the backfill worker
(queue=backfill, isolated from realtime), the internal control API, and a
heartbeat loop. Start with: python -m app.collector_entry
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from datetime import datetime, timezone

import uvicorn

from .config import settings
from .control import create_control_app
from .db import db_session
from .jobs import app as procrastinate_app
from sqlalchemy import select

from .models import TelegramConfiguration, WorkerHeartbeat
from .redact import install_redaction
from .services import collector_state
from .services.collector import handle_new_message
from .services.telegram_client import TelethonService
from .services.telegram_sim import SimTelegramService

logger = logging.getLogger("telemonitor.collector")


async def _on_new_message_async(msg: dict) -> None:
    await asyncio.to_thread(handle_new_message, msg)


async def _heartbeat_loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            db = db_session()
            try:
                hb = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.name == "collector"))
                if hb is None:
                    hb = WorkerHeartbeat(name="collector", kind="collector", queues="backfill")
                    db.add(hb)
                hb.kind = "collector"
                hb.queues = "backfill"
                hb.status = "up"
                hb.last_beat_at = datetime.now(timezone.utc)
                tg = db.get(TelegramConfiguration, 1)
                if tg is not None:
                    tg.collector_heartbeat_at = datetime.now(timezone.utc)
                    tg.last_update_at = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            logger.exception("heartbeat update failed")
        await asyncio.sleep(15)


async def _run_control_server(stop: threading.Event) -> None:
    config = uvicorn.Config(
        create_control_app(),
        host="0.0.0.0",
        port=settings.collector_control_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    task = asyncio.ensure_future(server.serve())
    while not stop.is_set() and not server.started:
        await asyncio.sleep(0.1)
    await task


def _run_backfill_worker(stop: threading.Event) -> None:
    logger.info("backfill worker starting (queue=backfill, concurrency=1)")
    procrastinate_app.run_worker(queues=["backfill"], wait=True)
    logger.info("backfill worker exited")


async def main() -> None:
    install_redaction()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from .jobs import ensure_open

    ensure_open()

    if settings.simulate_telegram:
        service = SimTelegramService()
        logger.info("using SIMULATED telegram service")
    else:
        service = TelethonService()
    collector_state.set_service(service)
    service.set_new_message_callback(_on_new_message_async)

    stop = threading.Event()

    async def _shutdown(sig=None, frame=None) -> None:
        stop.set()
        await service.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown(sig)))
        except NotImplementedError:
            pass

    worker_thread = threading.Thread(target=_run_backfill_worker, args=(stop,), daemon=True)
    worker_thread.start()

    await service.start()

    heartbeat = asyncio.ensure_future(_heartbeat_loop(stop))
    control = asyncio.ensure_future(_run_control_server(stop))

    logger.info("collector running (simulate=%s)", settings.simulate_telegram)
    while not stop.is_set():
        await asyncio.sleep(1)

    heartbeat.cancel()
    control.cancel()
    logger.info("collector stopped")


if __name__ == "__main__":
    asyncio.run(main())
