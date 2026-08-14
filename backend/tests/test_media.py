"""Media storage + serving tests."""
from __future__ import annotations

import hashlib

import pytest

from app.services.storage import LocalMediaStore, MediaStoreError


@pytest.fixture()
def store(tmp_path):
    return LocalMediaStore(str(tmp_path / "media"))


def test_put_get_roundtrip(store):
    data = b"\x89PNG fake image bytes"
    key = hashlib.sha256(data).hexdigest()
    store.put(key, data, "image/png")
    assert store.exists(key)
    assert store.get(key) == data
    assert (store.base_dir / key[0:2] / key[2:4] / key).exists()


def test_missing_key_returns_none(store):
    assert store.get("f" * 64) is None
    assert store.exists("f" * 64) is False


def test_delete_removes_file(store):
    data = b"x" * 16
    key = hashlib.sha256(data).hexdigest()
    store.put(key, data)
    store.delete(key)
    assert not store.exists(key)


def test_invalid_key_rejected(store):
    for bad in ("../../etc/passwd", "abc", "..", "A" * 64, "../" + "a" * 62):
        with pytest.raises(MediaStoreError):
            store.get(bad)
        with pytest.raises(MediaStoreError):
            store.put(bad, b"x")
        # delete is best-effort: must not raise, must not create anything
        store.delete(bad)
    # nothing was written for invalid keys (no files anywhere under base_dir)
    files = [p for p in store.base_dir.rglob("*") if p.is_file()]
    assert files == []


def test_media_endpoint_requires_auth_and_storage(client, clean_db):
    from app.db import SessionLocal
    from app.models import Message, Source

    db = SessionLocal()
    try:
        src = Source(
            telegram_chat_id=909001,
            title="Media Test",
            type="channel",
            enabled=True,
            status="live",
        )
        db.add(src)
        db.commit()
        db.refresh(src)
        m = Message(
            source_id=src.id,
            telegram_message_id=1,
            sent_at=None,
            original_text="has image",
            normalized_text="has image",
            media_type="photo",
            media_metadata={"mime_type": "image/jpeg"},
            state="processed",
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        mid = m.id
    finally:
        db.close()

    # unauthenticated
    assert client.get(f"/api/v1/media/{mid}").status_code == 401
    # not stored yet
    from .conftest import login_analyst

    login_analyst(client)
    assert client.get(f"/api/v1/media/{mid}").status_code == 404

    # store it, then it serves with the right content type
    from app.db import SessionLocal as SL2
    from app.models import Message as M2
    from app.services.storage import get_media_store

    db = SL2()
    try:
        m = db.get(M2, mid)
        data = b"\xff\xd8\xff\xe0 fake jpeg"
        m.media_sha256 = hashlib.sha256(data).hexdigest()
        m.media_content_type = "image/jpeg"
        m.media_size_bytes = len(data)
        m.media_filename = "photo.jpg"
        m.media_stored = True
        db.commit()
    finally:
        db.close()
    get_media_store().put(hashlib.sha256(data).hexdigest(), data, "image/jpeg")
    r = client.get(f"/api/v1/media/{mid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content == data


def test_media_settings_roundtrip(client):
    from .conftest import login_admin

    login_admin(client)
    r = client.put("/api/v1/settings", json={"media_settings": {"store_media": True}})
    assert r.status_code == 200, r.text
    assert r.json()["media_settings"]["store_media"] is True
    r2 = client.get("/api/v1/settings")
    assert r2.json()["media_settings"]["store_media"] is True


def test_sanitize_filename_blocks_header_injection():
    from app.jobs import _sanitize_filename

    # CR/LF/quotes/backslash (the header-injection vectors) must be removed
    out = _sanitize_filename('evil"\r\nX-Injected: yes')
    assert out is not None
    assert "\r" not in out and "\n" not in out and '"' not in out and "\\" not in out
    assert _sanitize_filename("photo.jpg") == "photo.jpg"
    out2 = _sanitize_filename("kötük.png")
    assert all(0x20 <= ord(c) <= 0x7E for c in out2), "non-ASCII chars must be replaced"
    assert '"' not in (_sanitize_filename('a"b"c.jpg') or "")
    assert _sanitize_filename("") is None


def test_media_endpoint_rejects_injected_filename_header(client, clean_db):
    import hashlib

    from app.db import SessionLocal
    from app.models import Message, Source

    db = SessionLocal()
    try:
        src = Source(telegram_chat_id=909003, title="Header Test", type="channel", enabled=True, status="live")
        db.add(src)
        db.commit()
        db.refresh(src)
        m = Message(
            source_id=src.id,
            telegram_message_id=3,
            original_text="x",
            normalized_text="x",
            media_type="photo",
            state="processed",
            media_filename='evil"\r\nX-Injected: 1',
            media_sha256=hashlib.sha256(b"data").hexdigest(),
            media_content_type="image/jpeg",
            media_size_bytes=4,
            media_stored=True,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        mid = m.id
    finally:
        db.close()
    from app.services.storage import get_media_store

    get_media_store().put(hashlib.sha256(b"data").hexdigest(), b"data", "image/jpeg")
    from .conftest import login_analyst

    login_analyst(client)
    r = client.get(f"/api/v1/media/{mid}")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "X-Injected" not in cd
    assert "\r" not in cd and "\n" not in cd


def test_retention_keeps_shared_media(client, clean_db):
    import hashlib
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Message, Source
    from app.services.retention import delete_expired

    digest = hashlib.sha256(b"shared-image").hexdigest()
    from app.services.storage import get_media_store

    get_media_store().put(digest, b"shared-image", "image/jpeg")
    db = SessionLocal()
    try:
        src = Source(telegram_chat_id=909004, title="Shared", type="channel", enabled=True, status="live")
        db.add(src)
        db.commit()
        db.refresh(src)
        old = datetime.now(timezone.utc) - timedelta(days=400)
        fresh = datetime.now(timezone.utc)
        for i, (when, kept) in enumerate([(old, False), (fresh, True)]):
            db.add(
                Message(
                    source_id=src.id,
                    telegram_message_id=i + 1,
                    sent_at=when,
                    original_text=f"m{i}",
                    normalized_text=f"m{i}",
                    state="processed",
                    media_type="photo",
                    media_sha256=digest,
                    media_stored=True,
                )
            )
        db.commit()
        deleted = delete_expired(db, datetime.now(timezone.utc) - timedelta(days=90))
        assert deleted == 1
        # the surviving message still references the digest -> file must remain
        assert get_media_store().exists(digest)
        assert db.scalar(select(func.count(Message.id)).where(Message.media_sha256 == digest)) == 1
    finally:
        db.close()


def test_media_attempts_cap_terminates():
    from app.jobs import download_media
    from app.db import SessionLocal
    from app.models import Message, Source

    db = SessionLocal()
    try:
        src = Source(telegram_chat_id=909005, title="Attempts", type="channel", enabled=True, status="live")
        db.add(src)
        db.commit()
        db.refresh(src)
        m = Message(
            source_id=src.id,
            telegram_message_id=4,
            original_text="x",
            normalized_text="x",
            media_type="photo",
            state="processed",
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        mid = m.id
    finally:
        db.close()
    # enable the toggle so download_media does not early-return
    from app.audit import set_setting

    set_setting(SessionLocal(), "media_settings", {"store_media": True})
    # no telegram service in tests -> download_media fails; after 3 attempts it
    # must go terminal (4th call no-ops without another retry)
    for _ in range(3):
        try:
            download_media(mid)
        except Exception:  # noqa: BLE001
            pass
    db = SessionLocal()
    try:
        m = db.get(Message, mid)
        assert m.media_attempts == 3
        assert m.media_stored is False
    finally:
        db.close()
    try:
        download_media(mid)
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"terminal message must not retry: {e}")
