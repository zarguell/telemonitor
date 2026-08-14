"""Authenticated media serving (stored message images)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Message
from ..security import AuthContext, require_any
from ..services.storage import MediaStoreError, get_media_store

router = APIRouter(prefix="/media", tags=["media"])

# Only image content types were stored; refuse to serve anything else.
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff"}


@router.get("/{message_id}")
def get_media(message_id: int, ctx: AuthContext = Depends(require_any), db: Session = Depends(get_db)):
    msg = db.get(Message, message_id)
    if msg is None or not msg.media_stored or not msg.media_sha256:
        raise HTTPException(status_code=404, detail="media not stored for this message")
    content_type = msg.media_content_type or "application/octet-stream"
    try:
        data = get_media_store().get(msg.media_sha256)
    except MediaStoreError as e:
        raise HTTPException(status_code=500, detail=str(e))
    if data is None:
        raise HTTPException(status_code=404, detail="media object missing from store")
    headers = {"Cache-Control": "private, max-age=3600"}
    if content_type in _ALLOWED_TYPES:
        headers["Content-Type"] = content_type
    else:
        headers["Content-Type"] = "application/octet-stream"
    # MEDIA-01: only emit Content-Disposition for already-sanitized ASCII names
    # (defense in depth — never trust the DB value in a header).
    filename = msg.media_filename or ""
    if filename and re.fullmatch(r"[\x20-\x7e]+", filename) and '"' not in filename and "\\" not in filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return Response(content=data, headers=headers)
