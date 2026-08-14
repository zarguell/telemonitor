"""Message normalization for matching/search.

Normalization pipeline:
- NFKC unicode normalization (collapses lookalikes/width variants)
- casefold (aggressive lowercasing incl. non-ASCII)
- whitespace collapse
- keep punctuation (needed for regex/phrase matching and indicator extraction on the ORIGINAL text)

The extractors run on `original_text`; rules and search operate on `normalized_text`.
"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.casefold()
    t = _WS.sub(" ", t)
    return t.strip()


def excerpt(text: str | None, needle: str | None = None, radius: int = 90) -> str:
    """Build a short excerpt around the first match of `needle` (case-insensitive)."""
    if not text:
        return ""
    if not needle:
        return text[: radius * 2]
    t = normalize_text(text)
    n = normalize_text(needle)
    idx = t.find(n)
    if idx < 0:
        return text[: radius * 2]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def highlight_snippet(text: str | None, needle: str | None, radius: int = 90) -> str:
    """HTML-escaped snippet with <mark> around matches of needle (case-insensitive)."""
    import html

    if not text:
        return ""
    if not needle:
        return html.escape(text[: radius * 2])
    t = normalize_text(text)
    n = normalize_text(needle)
    idx = t.find(n)
    if idx < 0:
        return html.escape(text[: radius * 2])
    start = max(0, idx - radius)
    end = min(len(text), idx + len(n) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    body = text[start:end]
    # highlight all case-insensitive occurrences inside the snippet
    out: list[str] = []
    pos = 0
    lowered = body.casefold()
    needle_l = n
    while True:
        hit = lowered.find(needle_l, pos)
        if hit < 0:
            out.append(html.escape(body[pos:]))
            break
        out.append(html.escape(body[pos:hit]))
        out.append(f"<mark>{html.escape(body[hit:hit + len(n)])}</mark>")
        pos = hit + len(n)
    return f"{prefix}{''.join(out)}{suffix}"
