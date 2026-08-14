"""Abstracted media storage.

The collector stores downloaded media (images) through a MediaStore so the
backend can be swapped (local filesystem today, S3/object store later) without
touching ingestion or serving code. Keys are always SHA-256 hex digests of the
content, so implementations never need to sanitize user input.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MediaStoreError(Exception):
    pass


class MediaStore(ABC):
    """Storage contract for media objects (keyed by content SHA-256)."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalMediaStore(MediaStore):
    """Filesystem store: <base>/<key[0:2]>/<key[2:4]>/<key>.

    Only validated 64-hex SHA-256 keys are accepted, so no path traversal is
    possible even if a key were ever derived from untrusted input.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        if not _SHA256_RE.match(key):
            raise MediaStoreError(f"invalid media key: {key!r}")
        return self.base_dir / key[0:2] / key[2:4] / key

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # unique temp name + os.replace for atomic publish (no shared .tmp path)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        logger.info("media stored", extra={"key": key[:12], "bytes": len(data)})

    def get(self, key: str) -> bytes | None:
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            return path.read_bytes()
        except OSError as e:  # noqa: BLE001
            logger.warning("media read failed", extra={"key": key[:12], "error": str(e)})
            return None

    def delete(self, key: str) -> None:
        try:
            self._path_for(key).unlink(missing_ok=True)
        except MediaStoreError:
            pass

    def exists(self, key: str) -> bool:
        try:
            return self._path_for(key).exists()
        except MediaStoreError:
            return False


@lru_cache
def get_media_store() -> MediaStore:
    """Select the configured media store (local filesystem today)."""
    kind = settings.media_store.lower()
    if kind == "local":
        return LocalMediaStore(settings.media_dir)
    raise MediaStoreError(
        f"unsupported TM_MEDIA_STORE={kind!r} (implemented: 'local'; S3 can be added "
        "behind the MediaStore interface)"
    )
