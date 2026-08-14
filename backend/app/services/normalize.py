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


def _find_first(text: str, needle: str) -> int:
    """Case-insensitive index of `needle` in the ORIGINAL text (no length drift)."""
    import regex

    m = regex.search(regex.escape(needle), text, regex.IGNORECASE)
    return m.start() if m else -1


def excerpt(text: str | None, needle: str | None = None, radius: int = 90) -> str:
    """Build a short excerpt around the first match of `needle` (case-insensitive)."""
    if not text:
        return ""
    if not needle:
        return text[: radius * 2]
    idx = _find_first(text, needle)
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

    import regex

    if not text:
        return ""
    if not needle:
        return html.escape(text[: radius * 2])
    idx = _find_first(text, needle)
    if idx < 0:
        return html.escape(text[: radius * 2])
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    body = text[start:end]
    # highlight all case-insensitive occurrences inside the snippet; matches are
    # found against the ORIGINAL text so indices always map 1:1
    out: list[str] = []
    pos = 0
    for m in regex.finditer(regex.escape(needle), body, regex.IGNORECASE):
        out.append(html.escape(body[pos : m.start()]))
        out.append(f"<mark>{html.escape(m.group(0))}</mark>")
        pos = m.end()
    out.append(html.escape(body[pos:]))
    return f"{prefix}{''.join(out)}{suffix}"
