"""Telegram service protocol + real Telethon implementation.

The protocol is implemented by both the real Telethon-backed service and the
simulated service used for local testing (TM_SIMULATE_TELEGRAM=1). The collector
and backfill worker depend only on this interface.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy.orm import Session

from ..crypto import decrypt_secret, encrypt_secret, key_fingerprint
from ..db import db_session
from ..models import TelegramConfiguration, TelegramStatus

logger = logging.getLogger(__name__)

NewMessageCallback = Callable[[dict], Awaitable[None]]


class TelegramServiceProtocol:
    """Interface shared by real and simulated services."""

    # lifecycle -----------------------------------------------------------
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def get_history_sync(self, chat_id: int, offset_id: int | None = None, limit: int = 100) -> list[dict]: ...

    def download_media_sync(self, chat_id: int, message_id: int) -> dict | None: ...

    # authorization flow --------------------------------------------------
    async def initialize(self, api_id: str, api_hash: str) -> dict: ...

    async def submit_phone(self, phone: str) -> dict: ...

    async def submit_code(self, code: str) -> dict: ...

    async def submit_password(self, password: str) -> dict: ...

    async def disconnect(self) -> dict: ...

    def status(self) -> dict: ...

    # discovery -----------------------------------------------------------
    async def get_dialogs(self) -> list[dict]: ...

    # callbacks -----------------------------------------------------------
    def set_new_message_callback(self, cb: NewMessageCallback) -> None: ...


# ---------------------------------------------------------------------------
# Status persistence helpers (shared)
# ---------------------------------------------------------------------------


def load_tg_config(db: Session) -> TelegramConfiguration | None:
    return db.get(TelegramConfiguration, 1)


def set_status(db: Session, status: str, detail: str | None = None, error: str | None = None) -> None:
    cfg = load_tg_config(db)
    if cfg is None:
        cfg = TelegramConfiguration(id=1, status=status)
        db.add(cfg)
    cfg.status = status
    if detail is not None:
        cfg.status_detail = detail
    if error is not None:
        cfg.last_error = error
    cfg.last_update_at = datetime.now(timezone.utc)
    db.commit()


def save_session(db: Session, session_string: str, api_id: str, api_hash: str, phone: str) -> None:
    cfg = load_tg_config(db)
    if cfg is None:
        cfg = TelegramConfiguration(id=1)
        db.add(cfg)
    cfg.api_id_enc = encrypt_secret(api_id)
    cfg.api_hash_enc = encrypt_secret(api_hash)
    cfg.phone_enc = encrypt_secret(phone)
    cfg.session_enc = encrypt_secret(session_string)
    cfg.session_key_ref = key_fingerprint()
    cfg.connected_account = None  # set after authorization
    db.commit()


def clear_session(db: Session) -> None:
    cfg = load_tg_config(db)
    if cfg is None:
        return
    cfg.session_enc = None
    cfg.status = TelegramStatus.DISCONNECTED
    cfg.status_detail = "local session revoked"
    cfg.last_error = None
    db.commit()


# ---------------------------------------------------------------------------
# Real Telethon service
# ---------------------------------------------------------------------------


def _chat_to_dict(entity, dialog) -> dict:
    from telethon.tl.types import Channel, Chat, User  # type: ignore

    # chat_id is filled in by get_dialogs via client.get_peer_id (Telethon's
    # canonical full id: -100<id> for channels, negative for groups) so that
    # it matches Message.chat_id / event.chat_id used by the collector.
    chat_id = getattr(entity, "id", 0)
    ctype = "channel"
    if isinstance(entity, User):
        ctype = "user"
    elif isinstance(entity, Chat):
        ctype = "group"
    elif isinstance(entity, Channel):
        ctype = "channel" if getattr(entity, "megagroup", False) is False else "group"
    title = getattr(entity, "title", None) or ""
    if not title:
        first = getattr(entity, "first_name", None) or ""
        last = getattr(entity, "last_name", None) or ""
        title = f"{first} {last}".strip()
    return {
        "chat_id": chat_id,
        "title": (title or str(chat_id)).strip(),
        "username": getattr(entity, "username", None),
        "type": ctype,
        "last_activity_at": getattr(dialog, "date", None),
        "unread": getattr(dialog, "unread_count", 0),
    }


def _message_to_dict(m) -> dict:
    from telethon.tl.types import (  # type: ignore
        MessageEntityTextUrl,
        MessageEntityUrl,
        MessageMediaDocument,
        MessageMediaPhoto,
        MessageMediaWebPage,
    )

    media_type = None
    media_meta = None
    if m.media is not None:
        if isinstance(m.media, MessageMediaPhoto):
            media_type = "photo"
        elif isinstance(m.media, MessageMediaDocument):
            media_type = "document"
            attrs = getattr(m.media, "document", None)
            media_meta = {"mime_type": getattr(attrs, "mime_type", None), "size": getattr(attrs, "size", None)}
        elif isinstance(m.media, MessageMediaWebPage):
            media_type = "webpage"
        else:
            media_type = m.media.__class__.__name__.replace("MessageMedia", "").lower()
    fwd_from_id = None
    fwd_from_name = None
    if m.forward:
        fwd = m.forward
        fwd_from_id = getattr(fwd, "from_id", None)
        if fwd_from_id is not None:
            fwd_from_id = getattr(fwd_from_id, "user_id", None) or getattr(fwd_from_id, "channel_id", None)
        fwd_from_name = getattr(fwd, "from_name", None)
    # Telegram often keeps URLs only in link entities (MessageEntityUrl /
    # MessageEntityTextUrl) while the plain message text omits them. Extract
    # them so the indicator pipeline can see them.
    extra_urls: list[str] = []
    if m.entities:
        for e in m.entities:
            if isinstance(e, MessageEntityUrl):
                try:
                    extra_urls.append(m.message[e.offset : e.offset + e.length])
                except TypeError:
                    pass
            elif isinstance(e, MessageEntityTextUrl):
                if e.url:
                    extra_urls.append(e.url)
    sender_id = m.sender_id
    permalink = None
    if m.chat and getattr(m.chat, "username", None):
        permalink = f"https://t.me/{m.chat.username}/{m.id}"
    elif m.chat_id is not None and str(m.chat_id).startswith("-100"):
        permalink = f"https://t.me/c/{abs(m.chat_id) - 1000000000000}/{m.id}"
    return {
        "id": m.id,
        "chat_id": m.chat_id,
        "date": m.date,
        "text": m.message or "",
        "sender_id": sender_id,
        "reply_to_msg_id": m.reply_to_msg_id,
        "forward_from_id": fwd_from_id,
        "forward_from_name": fwd_from_name,
        "media_type": media_type,
        "media_meta": media_meta,
        "edit_date": m.edit_date,
        "permalink": permalink,
        "out": m.out,
        "urls": extra_urls,
    }


class TelethonService(TelegramServiceProtocol):
    def __init__(self) -> None:
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._phone: str | None = None
        self._api_id: str | None = None
        self._api_hash: str | None = None
        self._on_new_message: NewMessageCallback | None = None
        self._last_update: datetime | None = None

    # internals -----------------------------------------------------------

    def _db(self) -> Session:
        return db_session()

    def _load_stored(self) -> tuple[str | None, str | None, str | None, str | None]:
        db = self._db()
        try:
            cfg = load_tg_config(db)
            if cfg is None:
                return None, None, None, None
            return (
                decrypt_secret(cfg.api_id_enc),
                decrypt_secret(cfg.api_hash_enc),
                decrypt_secret(cfg.phone_enc),
                decrypt_secret(cfg.session_enc),
            )
        finally:
            db.close()

    def _client_for(self, api_id: str, api_hash: str, session_string: str | None = None):
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        session = StringSession(session_string) if session_string else StringSession()
        client = TelegramClient(session, int(api_id), api_hash, system_version="4.16.30-vxCUSTOM")
        return client

    async def _on_event(self, event) -> None:
        if self._on_new_message is None:
            return
        try:
            await self._on_new_message(_message_to_dict(event.message))
        except Exception:  # noqa: BLE001
            logger.exception("event callback failed")

    # protocol ------------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        api_id, api_hash, phone, session_str = self._load_stored()
        if not (api_id and api_hash):
            db = self._db()
            try:
                cfg = load_tg_config(db)
                if cfg and cfg.status in (TelegramStatus.AUTHORIZED, TelegramStatus.CONNECTING):
                    set_status(db, TelegramStatus.INIT_REQUIRED, "stored session missing or undecryptable")
            finally:
                db.close()
            return
        self._api_id, self._api_hash = api_id, api_hash
        if session_str:
            client = self._client_for(api_id, api_hash, session_str)
            self._client = client
            try:
                await client.connect()
                if await client.is_user_authorized():
                    self._register_handlers()
                    await self._announce_status(TelegramStatus.AUTHORIZED, "connected")
                else:
                    await client.disconnect()
                    self._client = None
                    db = self._db()
                    try:
                        set_status(db, TelegramStatus.INIT_REQUIRED, "session present but not authorized")
                    finally:
                        db.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("telethon start failed", extra={"error": str(e)})
                db = self._db()
                try:
                    set_status(db, TelegramStatus.ERROR, error=str(e)[:300])
                finally:
                    db.close()
            return
        # Credentials stored but no session yet: resume the authorization flow.
        # If a phone number was already entered (e.g. mid-flow across a
        # collector restart), request a fresh Telegram code so the UI can
        # continue where it left off.
        if phone:
            self._phone = phone
            try:
                client = self._client_for(api_id, api_hash)
                self._client = client
                await client.connect()
                await client.send_code_request(phone)
                logger.info("telegram one-time code requested", extra={"phone_prefix": phone[:4]})
                await self._announce_status(TelegramStatus.WAITING_CODE, "one-time code sent by Telegram")
            except Exception as e:  # noqa: BLE001
                logger.warning("resume code request failed", extra={"error": str(e)})
                db = self._db()
                try:
                    set_status(db, TelegramStatus.ERROR, error=str(e)[:300])
                finally:
                    db.close()
        else:
            db = self._db()
            try:
                set_status(db, TelegramStatus.WAITING_PHONE, "enter phone number")
            finally:
                db.close()

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def _register_handlers(self) -> None:
        from telethon import events  # type: ignore

        assert self._client is not None
        self._client.add_event_handler(self._on_event, events.NewMessage())
        self._client.add_event_handler(self._on_event, events.MessageEdited())

        async def on_delete(event) -> None:
            from .collector import handle_message_delete

            await asyncio.to_thread(
                handle_message_delete, event.chat_id, list(event.deleted_ids or [])
            )

        self._client.add_event_handler(on_delete, events.MessageDeleted())

    async def _announce_status(self, status: str, detail: str | None = None) -> None:
        db = self._db()
        try:
            set_status(db, status, detail)
        finally:
            db.close()

    async def initialize(self, api_id: str, api_hash: str) -> dict:
        # Re-initializing must tear down any previously connected client and
        # invalidate the stored session, otherwise the old account keeps
        # delivering events while the status claims waiting_phone.
        await self.stop()
        self._api_id, self._api_hash = api_id, api_hash
        self._phone = None
        db = self._db()
        try:
            cfg = load_tg_config(db)
            if cfg is None:
                cfg = TelegramConfiguration(id=1)
                db.add(cfg)
            cfg.api_id_enc = encrypt_secret(api_id)
            cfg.api_hash_enc = encrypt_secret(api_hash)
            cfg.session_enc = None
            cfg.connected_account = None
            cfg.session_key_ref = key_fingerprint()
            set_status(db, TelegramStatus.WAITING_PHONE, "credentials stored; enter phone number")
        finally:
            db.close()
        return self.status()

    async def submit_phone(self, phone: str) -> dict:
        if not self._api_id or not self._api_hash:
            db = self._db()
            try:
                set_status(db, TelegramStatus.INIT_REQUIRED, "credentials not initialized; run initialize first")
            finally:
                db.close()
            return self.status()
        if self._client is None or self._client.is_connected() is False:
            client = self._client_for(self._api_id, self._api_hash)
            self._client = client
            await client.connect()
        self._phone = phone
        db = self._db()
        try:
            cfg = load_tg_config(db)
            if cfg is not None:
                cfg.phone_enc = encrypt_secret(phone)
                db.commit()
        finally:
            db.close()
        try:
            await self._client.send_code_request(phone)
        except Exception as e:  # noqa: BLE001
            await self._announce_status(TelegramStatus.ERROR, error=str(e)[:300])
            return self.status()
        await self._announce_status(TelegramStatus.WAITING_CODE, "one-time code sent by Telegram")
        return self.status()

    async def submit_code(self, code: str) -> dict:
        from telethon.errors import SessionPasswordNeededError  # type: ignore

        if self._client is None or self._phone is None:
            db = self._db()
            try:
                set_status(db, TelegramStatus.WAITING_PHONE, "phone number required before code")
            finally:
                db.close()
            return self.status()
        try:
            await self._client.sign_in(self._phone, code)
        except SessionPasswordNeededError:
            await self._announce_status(TelegramStatus.WAITING_2FA, "two-factor password required")
            return self.status()
        except Exception as e:  # noqa: BLE001
            await self._announce_status(TelegramStatus.ERROR, error=str(e)[:300])
            return self.status()
        await self._finalize_authorized()
        return self.status()

    async def submit_password(self, password: str) -> dict:
        if self._client is None:
            db = self._db()
            try:
                set_status(db, TelegramStatus.INIT_REQUIRED, "no active authorization flow")
            finally:
                db.close()
            return self.status()
        try:
            await self._client.sign_in(password=password)
        except Exception as e:  # noqa: BLE001
            await self._announce_status(TelegramStatus.ERROR, error=str(e)[:300])
            return self.status()
        await self._finalize_authorized()
        return self.status()

    async def _finalize_authorized(self) -> None:
        from telethon.sessions import StringSession  # type: ignore

        assert self._client is not None
        session_str = self._client.session.save()
        me = await self._client.get_me()
        db = self._db()
        try:
            cfg = load_tg_config(db)
            if cfg is not None:
                cfg.session_enc = encrypt_secret(session_str)
                cfg.connected_account = f"{me.first_name or ''} {me.last_name or ''}".strip() or str(getattr(me, "username", ""))
            set_status(db, TelegramStatus.AUTHORIZED, "connected")
        finally:
            db.close()
        self._register_handlers()
        self._last_update = datetime.now(timezone.utc)

    async def disconnect(self) -> dict:
        await self.stop()
        db = self._db()
        try:
            cfg = load_tg_config(db)
            if cfg is not None:
                cfg.session_enc = None
                cfg.connected_account = None
                cfg.status = TelegramStatus.DISCONNECTED
                cfg.status_detail = "local session revoked"
                db.commit()
        finally:
            db.close()
        return self.status()

    def is_connected(self) -> bool:
        """True when an authorized client connection is live (for heartbeat/reconnect states)."""
        if self._client is None:
            return False
        try:
            return self._client.is_connected()
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict:
        db = self._db()
        try:
            cfg = load_tg_config(db)
            if cfg is None:
                return {"state": TelegramStatus.NOT_CONFIGURED}
            return {
                "state": cfg.status,
                "detail": cfg.status_detail,
                "error": cfg.last_error,
                "connected_account": cfg.connected_account,
                "last_update": cfg.last_update_at.isoformat() if cfg.last_update_at else None,
                "collector_heartbeat": cfg.collector_heartbeat_at.isoformat() if cfg.collector_heartbeat_at else None,
            }
        finally:
            db.close()

    async def get_dialogs(self) -> list[dict]:
        if self._client is None or not await self._client.is_user_authorized():
            return []
        out: list[dict] = []
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            d = _chat_to_dict(entity, dialog)
            if d["type"] in {"user"}:
                continue
            d["chat_id"] = await self._client.get_peer_id(entity)
            out.append(d)
            if len(out) >= 500:
                break
        return out

    async def _get_history(self, chat_id: int, offset_id: int | None, limit: int) -> list[dict]:
        if self._client is None:
            return []
        # Telethon computes max(offset_id, max_id) internally; passing an
        # explicit None for both raises TypeError, so omit the kwarg when there
        # is no checkpoint yet.
        if offset_id is not None:
            messages = await self._client.get_messages(chat_id, limit=limit, offset_id=offset_id)
        else:
            messages = await self._client.get_messages(chat_id, limit=limit)
        return [_message_to_dict(m) for m in messages]

    def get_history_sync(self, chat_id: int, offset_id: int | None = None, limit: int = 100) -> list[dict]:
        if self._loop is None or not self._loop.is_running():
            return asyncio.run(self._get_history(chat_id, offset_id, limit))
        fut = asyncio.run_coroutine_threadsafe(self._get_history(chat_id, offset_id, limit), self._loop)
        return fut.result(timeout=120)

    async def _download_media(self, chat_id: int, message_id: int) -> dict | None:
        from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto  # type: ignore

        if self._client is None:
            return None
        msg = await self._client.get_messages(chat_id, ids=message_id)
        if msg is None or msg.media is None:
            return None
        content_type = None
        filename = None
        size = None
        if isinstance(msg.media, MessageMediaPhoto):
            content_type = "image/jpeg"  # Telegram photos are stored as JPEG
        elif isinstance(msg.media, MessageMediaDocument):
            doc = msg.media.document
            mime = getattr(doc, "mime_type", None) or ""
            if not mime.startswith("image/") or "svg" in mime.lower():
                return None  # only raster images in scope; SVG excluded (MEDIA-05)
            content_type = mime
            size = getattr(doc, "size", None)
            # Pre-check known size BEFORE buffering the whole file (MEDIA-02)
            if size is not None and size > settings.media_max_bytes:
                logger.info("media skipped: exceeds size cap", extra={"size": size})
                return None
            for attr in getattr(doc, "attributes", []) or []:
                if getattr(attr, "file_name", None):
                    filename = attr.file_name
                    break
        else:
            return None
        if not content_type:
            return None
        from ..config import settings

        data = await self._client.download_media(msg, file=bytes)
        if not data or len(data) > settings.media_max_bytes:
            return None
        if size is None:
            size = len(data)
        return {"data": data, "content_type": content_type, "filename": filename, "size": size}

    def download_media_sync(self, chat_id: int, message_id: int) -> dict | None:
        if self._loop is None or not self._loop.is_running():
            return asyncio.run(self._download_media(chat_id, message_id))
        fut = asyncio.run_coroutine_threadsafe(self._download_media(chat_id, message_id), self._loop)
        return fut.result(timeout=120)

    def set_new_message_callback(self, cb: NewMessageCallback) -> None:
        self._on_new_message = cb
