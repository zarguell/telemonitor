"""At-rest encryption for secrets (Fernet)."""
from __future__ import annotations

import base64
import hashlib
import os
import warnings

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_fernet: Fernet | None = None
_key_fingerprint: str | None = None
_warned = False


def _get_fernet() -> Fernet:
    global _fernet, _key_fingerprint, _warned
    if _fernet is not None:
        return _fernet
    if settings.secret_key:
        try:
            key = settings.secret_key.encode("utf-8")
            _fernet = Fernet(key)
            _key_fingerprint = hashlib.sha256(key).hexdigest()[:16]
            return _fernet
        except Exception:  # invalid key
            _fernet = None
    if not _warned:
        warnings.warn(
            "TM_SECRET_KEY is not set or invalid; using an ephemeral per-process key. "
            "Restarts will lose decryptability of stored secrets — set TM_SECRET_KEY in production.",
            RuntimeWarning,
        )
        _warned = True
    _fernet = Fernet(Fernet.generate_key())
    _key_fingerprint = "ephemeral"
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask(value: str | None, visible: int = 4) -> str | None:
    """Mask a secret for display (e.g. '************1234')."""
    if not value:
        return None
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * max(8, len(value) - visible) + value[-visible:]


def key_fingerprint() -> str | None:
    _get_fernet()
    return _key_fingerprint
