"""Deterministic rule evaluation over normalized message text, indicators, and source."""
from __future__ import annotations

import re as std_re
from typing import Any

import regex

from ..models import IndicatorType, RuleConditionType

REGEX_TIMEOUT_SECONDS = 1.0

# Heuristics for patterns likely to cause catastrophic backtracking
_CATASTROPHIC_PATTERNS = [
    std_re.compile(r"\((?:[^()]|\\.)*[+*](?:[^()]|\\.)*\)[+*{?]"),
    std_re.compile(r"\((?:[^()]|\\.)*\{[0-9,]+\}(?:[^()]|\\.)*\)[+*]"),
    std_re.compile(r"\.\*\.\*"),
    std_re.compile(r"\[\^?\]?[^\]]*\][+*]\s*[+*]"),
]


def regex_safety_warning(pattern: str) -> str | None:
    """Return a warning string if the pattern risks catastrophic backtracking."""
    if not pattern:
        return None
    try:
        regex.compile(pattern)
    except regex.error as e:
        return f"Pattern does not compile: {e}"
    for pat in _CATASTROPHIC_PATTERNS:
        if pat.search(pattern):
            return (
                "This pattern contains nested/adjacent quantifiers that can cause "
                "catastrophic backtracking (ReDoS). It will be evaluated under a 1s "
                "timeout and may miss matches on large messages. Prefer a simpler pattern."
            )
    return None


def validate_definition(definition: dict) -> list[str]:
    """Validate a rule definition, returning a list of errors (empty = valid)."""
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["definition must be an object"]
    match_mode = definition.get("match", "any")
    if match_mode not in ("all", "any"):
        errors.append("match must be 'all' or 'any'")
    conditions = definition.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        return ["at least one condition is required"]
    for i, c in enumerate(conditions):
        if not isinstance(c, dict) or "type" not in c:
            errors.append(f"condition #{i + 1}: missing 'type'")
            continue
        ctype = c["type"]
        if ctype not in RuleConditionType.__dict__.values():
            errors.append(f"condition #{i + 1}: unknown type '{ctype}'")
            continue
        value = c.get("value")
        if ctype == RuleConditionType.REGEX:
            if not isinstance(value, str) or not value:
                errors.append(f"condition #{i + 1}: regex value required")
                continue
            try:
                regex.compile(value)
            except regex.error as e:
                errors.append(f"condition #{i + 1}: invalid regex: {e}")
        elif ctype in (RuleConditionType.KEYWORD, RuleConditionType.PHRASE):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"condition #{i + 1}: value required")
        elif ctype == RuleConditionType.INDICATOR:
            if value not in (
                IndicatorType.URL,
                IndicatorType.DOMAIN,
                IndicatorType.IPV4,
                IndicatorType.IPV6,
                IndicatorType.EMAIL,
                IndicatorType.HASH,
                IndicatorType.CRYPTO,
                IndicatorType.TELEGRAM_USERNAME,
                IndicatorType.ALIAS,
                IndicatorType.KEYWORD,
            ):
                errors.append(f"condition #{i + 1}: unknown indicator type '{value}'")
        elif ctype == RuleConditionType.SOURCE:
            try:
                int(value)
            except (TypeError, ValueError):
                errors.append(f"condition #{i + 1}: source value must be a numeric source id")
    return errors


def evaluate_condition(condition: dict, ctx: dict) -> tuple[bool, dict]:
    """Evaluate one condition against ctx {normalized_text, source_id, indicators}.

    Returns (matched, detail).
    """
    ctype = condition.get("type")
    value = condition.get("value", "")
    text: str = (ctx.get("normalized_text") or "").casefold()
    source_id = ctx.get("source_id")
    indicators: list[dict] = ctx.get("indicators") or []
    detail: dict = {"type": ctype, "value": value}

    if ctype == RuleConditionType.KEYWORD:
        detail["matched_text"] = value
        return value.strip().casefold() in text, detail
    if ctype == RuleConditionType.PHRASE:
        phrase = std_re.escape(value.strip().casefold())
        detail["matched_text"] = value
        return bool(std_re.search(rf"(?<![\w]){phrase}(?![\w])", text)), detail
    if ctype == RuleConditionType.REGEX:
        try:
            m = regex.search(value, text, timeout=REGEX_TIMEOUT_SECONDS)
        except (regex.error, TimeoutError):
            return False, {**detail, "error": "regex timeout or error"}
        if m:
            detail["matched_text"] = m.group(0)
            return True, detail
        return False, detail
    if ctype == RuleConditionType.INDICATOR:
        i_type = value
        exact = condition.get("match")
        for ind in indicators:
            if ind.get("type") == i_type:
                if exact is None or ind.get("normalized_value") == str(exact).casefold():
                    detail["matched_text"] = ind.get("value")
                    detail["indicator_type"] = i_type
                    return True, detail
        return False, detail
    if ctype == RuleConditionType.SOURCE:
        try:
            matched = source_id == int(value)
        except (TypeError, ValueError):
            matched = False
        detail["source_id"] = source_id
        return matched, detail
    return False, {**detail, "error": f"unsupported condition type {ctype}"}


def evaluate_rule(definition: dict, ctx: dict) -> dict:
    """Evaluate a full rule definition; returns {matched, conditions:[...]}."""
    mode = definition.get("match", "any") if isinstance(definition, dict) else "any"
    conditions = definition.get("conditions", []) if isinstance(definition, dict) else []
    results = [evaluate_condition(c, ctx) for c in conditions]
    outcomes = [r[0] for r in results]
    if mode == "all":
        matched = all(outcomes)
    else:
        matched = any(outcomes)
    return {
        "matched": matched,
        "mode": mode,
        "conditions": [
            {"condition": cond, "matched": ok, "detail": det}
            for cond, (ok, det) in zip(conditions, results)
        ],
        "matched_conditions": [
            {"condition": cond, "detail": det}
            for cond, (ok, det) in zip(conditions, results)
            if ok
        ],
    }
