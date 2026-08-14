"""Log redaction: strip secrets, phone numbers, and credentials from log output.

The filter operates on the *formatted* message (so %-style tuple args are
covered) and on every string argument/extra attribute. Patterns are anchored to
phone-like or labeled context so timestamps and long numeric IDs are preserved.
"""
from __future__ import annotations

import logging
import re

from .config import settings

_PATTERNS: list[tuple[str, re.Pattern]] = []


def _add(name: str, pattern: str, flags: int = re.IGNORECASE) -> None:
    _PATTERNS.append((name, re.compile(pattern, flags)))


# E.164-style phone numbers: a leading '+' with 7-15 digits (optionally spaced/
# dashed). Anchored to the '+' so bare digit runs (timestamps, chat IDs) are
# never matched.
_add("phone", r"(\+\d{1,3}[\s.\-]?\(?\d{2,4}\)?[\s.\-]?\d{2,4}[\s.\-]?\d{2,4}[\s.\-]?\d{2,4})")
# Labeled secrets: "api_hash=...", "token: ...", "code: 12345", "password ..." etc.
_add("api_hash", r"(api[_-]?hash[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9+/=_\-]{8,}")
_add("api_id", r"(api[_-]?id[\"']?\s*[:=]\s*[\"']?)[0-9]{4,}")
_add(
    "labeled_secret",
    r"(\b(?:otp|one[ -]?time[ -]?code|code|password|passwd|2fa|two[ -]?factor|"
    r"token|secret|api[_-]?key|authorization|bearer)[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9!@#$%^&*().\-_]{4,}",
)
# Bearer/authorization headers
_add("authorization", r"(authorization|bearer)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9+/=_\-\.]{6,}")


def redact_text(text: str) -> str:
    for _name, pat in _PATTERNS:
        text = pat.sub(r"\1<redacted>", text)
    return text


# Standard LogRecord attributes whose values are never secrets and should be
# preserved as-is (the formatted message is handled separately).
_STANDARD_ATTRS = {
    "name", "msg", "message", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created",
    "msecs", "relativeCreated", "thread", "threadName", "processName", "process",
    "taskName", "asctime", "message",
}


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive content from every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not settings.redact_logging:
            return True
        # 1. The fully formatted message (covers %-tuple and %-dict args).
        try:
            formatted = record.getMessage()
            record.msg = redact_text(formatted)
            record.args = ()
        except Exception:
            pass
        # 2. String values passed via extra={...} or stored as record attributes.
        for key, value in list(vars(record).items()):
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if isinstance(value, str):
                setattr(record, key, redact_text(value))
            elif isinstance(value, dict):
                setattr(
                    record,
                    key,
                    {k: redact_text(v) if isinstance(v, str) else v for k, v in value.items()},
                )
        return True


def install_redaction() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
