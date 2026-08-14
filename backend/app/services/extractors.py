"""Deterministic indicator extraction.

Extractors run on the ORIGINAL message text and emit validated values only.
Confidence: 1.0 for exact validation, lower for heuristic-only extraction.
"""
from __future__ import annotations

import base58check
import ipaddress
import re

from ..models import IndicatorType

EXTRACTOR_VERSION = "1.0"

_URL_RE = re.compile(
    r"""(?i)\b(?P<url>https?://[^\s<>"']+|[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s<>"']*)?)"""
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(
    r"\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}(?:::\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})?\b|"
    r"\b::(?:ffff(?::0{1,4})?:)?(?:\d{1,3}\.){3}\d{1,3}\b",
    re.IGNORECASE,
)
_HASH_RE = re.compile(r"\b(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|[0-9a-fA-F]{128})\b")
_TG_USERNAME_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{4,32})\b")

_BTC_RE = re.compile(r"\b(bc1[a-z0-9]{25,39}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")
_ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_TRON_RE = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")

# Known TLDs used to sanity-check bare-domain matches
_TLDS = {
    "com", "net", "org", "io", "ai", "dev", "app", "info", "biz", "xyz", "me", "tv", "cc",
    "co", "us", "uk", "de", "fr", "ru", "cn", "jp", "in", "br", "au", "ca", "nl", "se",
    "ch", "at", "be", "dk", "fi", "no", "pl", "pt", "es", "it", "gr", "tr", "za", "mx",
    "ar", "cl", "co.uk", "com.au", "com.br", "github.io", "onion", "to", "gg", "ly", "sh",
}


def _strip_trailing_punct(s: str) -> str:
    return s.rstrip(".,;:!?)\"'»\u201d\u2019]")


def _is_valid_ipv4(s: str) -> bool:
    try:
        ipaddress.IPv4Address(s)
        return True
    except ValueError:
        return False


def _is_valid_ipv6(s: str) -> bool:
    try:
        ipaddress.IPv6Address(s)
        return True
    except ValueError:
        return False


def _valid_hash(s: str) -> bool:
    # Reject all-same-digit/letter runs and obviously fake hex
    lowered = s.lower()
    if len(set(lowered)) <= 2:
        return False
    return True


def extract_indicators(text: str | None, aliases: list[dict] | None = None) -> list[dict]:
    """Return list of dicts: {type, value, normalized_value, matched_text, confidence}."""
    if not text:
        return []
    out: list[dict] = []

    def add(i_type: str, value: str, norm: str, conf: float = 1.0, matched: str | None = None):
        value = _strip_trailing_punct(value)
        norm = norm.strip().lower()
        if not value:
            return
        out.append(
            {
                "type": i_type,
                "value": value,
                "normalized_value": norm,
                "matched_text": matched,
                "confidence": conf,
                "extractor_version": EXTRACTOR_VERSION,
            }
        )

    # URLs + domains
    for m in _URL_RE.finditer(text):
        raw = _strip_trailing_punct(m.group("url"))
        if raw.startswith(("http://", "https://")):
            add(IndicatorType.URL, raw, raw.lower())
            try:
                from urllib.parse import urlparse

                host = urlparse(raw).netloc or urlparse(raw).path.split("/")[0]
                if "." in host:
                    add(IndicatorType.DOMAIN, host, host.lower(), 1.0, raw)
            except Exception:
                pass
        else:
            # bare domain candidate
            domain = raw.lower()
            tld = domain.split(".")[-1]
            if tld in _TLDS:
                add(IndicatorType.DOMAIN, domain, domain, 0.95)

    # Emails
    for m in _EMAIL_RE.finditer(text):
        add(IndicatorType.EMAIL, m.group(0), m.group(0).lower())

    # IPv4 / IPv6
    for m in _IPV4_RE.finditer(text):
        if _is_valid_ipv4(m.group(0)):
            add(IndicatorType.IPV4, m.group(0), m.group(0))
    for m in _IPV6_RE.finditer(text):
        candidate = _strip_trailing_punct(m.group(0))
        if _is_valid_ipv6(candidate):
            add(IndicatorType.IPV6, candidate, candidate.lower())

    # Hashes
    for m in _HASH_RE.finditer(text):
        h = m.group(0)
        if _valid_hash(h):
            add(IndicatorType.HASH, h, h.lower())

    # Crypto wallets (high-confidence parsers: BTC base58check / bech32, ETH 0x40, TRON base58)
    for m in _BTC_RE.finditer(text):
        addr = m.group(0)
        if addr.startswith("bc1"):
            # bech32: charset + length check (no base58 checksum applies)
            _BECH32_CHARS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
            if 42 <= len(addr) <= 62 and all(c in _BECH32_CHARS for c in addr[3:]):
                add(IndicatorType.CRYPTO, addr, addr.lower(), 1.0, "btc")
            continue
        try:
            base58check.b58decode_check(addr)
            add(IndicatorType.CRYPTO, addr, addr.lower(), 1.0, "btc")
        except Exception:
            continue
    for m in _ETH_RE.finditer(text):
        add(IndicatorType.CRYPTO, m.group(0), m.group(0).lower(), 1.0, "eth")
    for m in _TRON_RE.finditer(text):
        addr = m.group(0)
        try:
            base58check.b58decode_check(addr)
            add(IndicatorType.CRYPTO, addr, addr.lower(), 1.0, "tron")
        except Exception:
            continue

    # Telegram usernames
    for m in _TG_USERNAME_RE.finditer(text):
        add(IndicatorType.TELEGRAM_USERNAME, "@" + m.group(1), m.group(1).lower())

    # User-defined aliases (company names, product names, keywords)
    for item in aliases or []:
        alias = (item or {}).get("alias", "")
        canonical = (item or {}).get("canonical", "") or alias
        if not alias:
            continue
        # case-insensitive whole-word-ish match
        pat = re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])")
        for m in pat.finditer(text):
            add(IndicatorType.ALIAS, m.group(0), canonical.lower(), 1.0, alias)

    return out
