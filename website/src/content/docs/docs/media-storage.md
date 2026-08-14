---
title: Media storage
description: Optional storage and display of images from monitored messages — never analyzed.
---

Images from monitored messages can optionally be stored and displayed — never
analyzed (no OCR/vision in scope). Metadata-only remains the default
(PRD §7.3).

## Enabling

- **Toggle**: Settings → Media storage → "Store and display images…"
  (Administrators only).
- When enabled, the collector downloads images at ingest time and the
  maintenance worker backfills already-ingested messages within a minute.

## Storage backend

An abstracted `MediaStore` interface (`backend/app/services/storage.py`):
today a local filesystem store keyed by content SHA-256 (`TM_MEDIA_DIR`, mounted
as a docker volume); an object store (S3) can be added later by implementing
the same interface and setting `TM_MEDIA_STORE`.

## Serving

- Authenticated `GET /api/v1/media/{message_id}` (analyst+), content-type
  checked, cache-control private.
- The message detail views show stored images.

## Retention and limits

- Purged media objects are deleted from the store alongside the messages.
- Only `photo` and image documents (≤ `TM_MEDIA_MAX_BYTES`) are stored; size is
  capped to avoid unbounded growth.
