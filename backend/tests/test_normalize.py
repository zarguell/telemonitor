"""Normalization unit tests."""
from app.services.normalize import excerpt, highlight_snippet, normalize_text


def test_normalize_lowercase_and_whitespace():
    assert normalize_text("  Hello   WORLD\n\tsecond line  ") == "hello world second line"


def test_normalize_casefold_unicode():
    assert normalize_text("STRASSE Straße") == "strasse strasse"


def test_normalize_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_excerpt_around_match():
    text = "alpha beta gamma delta epsilon zeta"
    out = excerpt(text, "gamma")
    assert "gamma" in out
    assert out.startswith("…") is False
    assert len(out) < len(text) or out == text


def test_highlight_snippet_marks_and_escapes():
    text = "visit https://evil.example/x?a=1&b=2 now"
    out = highlight_snippet(text, "evil.example")
    assert "<mark>" in out and "</mark>" in out
    assert "&amp;" in out  # HTML-escaped


def test_highlight_case_insensitive():
    out = highlight_snippet("URGENT: urgent again", "urgent")
    assert out.count("<mark>") == 2
