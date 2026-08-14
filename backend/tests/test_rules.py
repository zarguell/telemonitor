"""Rules engine unit tests."""
import pytest

from app.services.rules_engine import (
    evaluate_condition,
    evaluate_rule,
    regex_safety_warning,
    validate_definition,
)


def ctx(text, source_id=7, indicators=None):
    return {"normalized_text": text, "source_id": source_id, "indicators": indicators or []}


def test_keyword_case_insensitive():
    ok, detail = evaluate_condition({"type": "keyword", "value": "APT29"}, ctx("apt29 activity observed"))
    assert ok


def test_keyword_no_match():
    ok, _ = evaluate_condition({"type": "keyword", "value": "urgent"}, ctx("nothing here"))
    assert not ok


def test_phrase_whole_word():
    ok, _ = evaluate_condition({"type": "phrase", "value": "credential stuffing"}, ctx("credential stuffing campaign"))
    assert ok
    ok2, _ = evaluate_condition({"type": "phrase", "value": "cred"}, ctx("credentials leaked"))
    assert not ok2  # substring of a word must not match


def test_regex():
    # regex runs on normalized (lowercased) text; use inline flags when needed
    ok, detail = evaluate_condition({"type": "regex", "value": r"\bhands\b"}, ctx("calling all HANDS"))
    assert ok
    assert detail["matched_text"] == "hands"
    ok2, _ = evaluate_condition({"type": "regex", "value": r"^\d{4,}$"}, ctx("code 12345 here"))
    assert not ok2


def test_regex_timeout_no_crash():
    # catastrophic backtracking pattern must return False, not hang
    ok, detail = evaluate_condition(
        {"type": "regex", "value": r"^(a|aa)+$"}, ctx("a" * 40 + "b")
    )
    assert not ok
    assert "timeout" in detail.get("error", "")


def test_indicator_condition():
    inds = [{"type": "hash", "value": "abc123", "normalized_value": "abc123"}]
    ok, _ = evaluate_condition({"type": "indicator", "value": "hash"}, ctx("x", indicators=inds))
    assert ok
    ok2, _ = evaluate_condition({"type": "indicator", "value": "email"}, ctx("x", indicators=inds))
    assert not ok2


def test_source_condition():
    ok, _ = evaluate_condition({"type": "source", "value": "7"}, ctx("x", source_id=7))
    assert ok
    ok2, _ = evaluate_condition({"type": "source", "value": "8"}, ctx("x", source_id=7))
    assert not ok2


def test_any_vs_all():
    definition = {
        "match": "all",
        "conditions": [
            {"type": "keyword", "value": "alpha"},
            {"type": "keyword", "value": "beta"},
        ],
    }
    assert evaluate_rule(definition, ctx("alpha only"))["matched"] is False
    assert evaluate_rule(definition, ctx("alpha and beta"))["matched"] is True
    definition["match"] = "any"
    assert evaluate_rule(definition, ctx("alpha only"))["matched"] is True


def test_validate_definition():
    assert validate_definition({"match": "all", "conditions": [{"type": "keyword", "value": "x"}]}) == []
    errors = validate_definition({"match": "sometimes", "conditions": []})
    assert errors
    errors2 = validate_definition({"match": "any", "conditions": [{"type": "regex", "value": "(["}]})
    assert errors2
    errors3 = validate_definition({"match": "any", "conditions": [{"type": "indicator", "value": "nope"}]})
    assert errors3


def test_regex_safety_warning():
    assert regex_safety_warning(r"(a+)+$") is not None
    assert regex_safety_warning(r"^[a-z0-9]{4,16}$") is None
    assert regex_safety_warning("([") is not None  # compile error reported


def test_evaluate_rule_reports_conditions():
    definition = {
        "match": "any",
        "conditions": [
            {"type": "keyword", "value": "urgent"},
            {"type": "indicator", "value": "ipv4"},
        ],
    }
    result = evaluate_rule(definition, ctx("URGENT note", indicators=[{"type": "email", "value": "a@b.c"}]))
    assert result["matched"] is True
    assert len(result["matched_conditions"]) == 1
    assert result["matched_conditions"][0]["condition"]["type"] == "keyword"
