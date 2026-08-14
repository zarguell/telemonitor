"""Process-local singleton for the active Telegram service (real or simulated)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .telegram_client import TelegramServiceProtocol

_service: "TelegramServiceProtocol | None" = None


def set_service(service) -> None:
    global _service
    _service = service


def get_service():
    return _service
