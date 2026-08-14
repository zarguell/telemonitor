"""Log redaction: strip secrets, phone numbers, message content, and credentials from log lines."""
from __future__ import annotations

import logging
import re

from .config import settings

# Patterns to redact from log output. Values are matched on the raw record and
# replaced with <redacted>.
_PATTERNS: list[tuple[str, re.Pattern]] = []


def _add(name: str, pattern: str) -> None:
    _PATTERNS.append((name, re.compile(pattern, re.IGNORECASE)))


_add("api_hash", r"(api[_-]?hash[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9+/=_\-]{8,}")
_add("api_id", r"(api[_-]?id[\"']?\s*[:=]\s*[\"']?)[0-9]{4,}")
_add("otp", r"(\b(?:otp|one[ -]?time[ -]?code|code|password|passwd|2fa|two[ -]?factor)[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9!@#$%^&*().\-_]{4,}")
_add("phone", r"(\+\d{1,3}[\s.\-]?)?(\(?\d{2,4}\)?[\s.\-]?)\d{2,4}[\s.\-]?\d{2,4}[\s.\-]?\d{2,4}")
_add("authorization", r"(authorization|bearer|token|secret|password|apikey|api[_-]?key)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9+/=_\-\.]{6,}")
_add("fernent", r"(Fernet\.generate_key|TM_SECRET_KEY|SECRET_KEY)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9\-_=]{16,}")


def redact_text(text: str) -> str:
    for _name, pat in _PATTERNS:
        text = pat.sub(r"\1<redacted>", text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that redacts sensitive content from every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not settings.redact_logging:
            return True
        for attr in ("msg", "message"):
            value = getattr(record, attr, None)
            if isinstance(value, str):
                setattr(record, attr, redact_text(value))
        try:
            if isinstance(record.args, dict):
                record.args = {k: redact_text(v) if isinstance(v, str) else v for k, v in record.args.items()}
        except Exception:
            pass
        return True


def install_redaction() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
