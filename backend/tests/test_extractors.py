"""Extractor unit tests."""
from app.services.extractors import extract_indicators


def test_url_and_domain():
    text = "Download from https://evil.example.net/update.php now, or mirror evil2.example.org"
    inds = extract_indicators(text)
    types = {i["type"] for i in inds}
    assert "url" in types
    assert "domain" in types
    domains = {i["normalized_value"] for i in inds if i["type"] == "domain"}
    assert "evil.example.net" in domains
    assert "evil2.example.org" in domains


def test_email():
    inds = extract_indicators("contact ops@example.com or help@corp.example.co.uk")
    emails = {i["normalized_value"] for i in inds if i["type"] == "email"}
    assert emails == {"ops@example.com", "help@corp.example.co.uk"}


def test_ipv4_ipv6():
    text = "block 45.155.205.233 and 2a03:2880:f11c:8083:face:b00c:0:1"
    inds = extract_indicators(text)
    ipv4 = {i["value"] for i in inds if i["type"] == "ipv4"}
    ipv6 = {i["value"] for i in inds if i["type"] == "ipv6"}
    assert ipv4 == {"45.155.205.233"}
    assert ipv6 == {"2a03:2880:f11c:8083:face:b00c:0:1"}


def test_invalid_ipv4_rejected():
    inds = extract_indicators("999.999.1.1 is not valid, 256.1.1.1 neither")
    assert not any(i["type"] == "ipv4" for i in inds)


def test_hashes():
    text = (
        "sha256 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 "
        "md5 098f6bcd4621d373cade4e832627b4f6 sha1 a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"
    )
    inds = extract_indicators(text)
    hashes = {i["normalized_value"] for i in inds if i["type"] == "hash"}
    assert len(hashes) == 3
    # fake repetitive hash rejected
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in hashes


def test_crypto_wallets():
    text = (
        "BTC bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh and ETH 0x52908400098527886E0F7030069857D2E4169EE7 "
        "plus junk 0x1234 and 1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ"
    )
    inds = extract_indicators(text)
    crypto = [i for i in inds if i["type"] == "crypto"]
    values = {i["value"] for i in crypto}
    assert "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh" in values
    assert "0x52908400098527886E0F7030069857D2E4169EE7" in values
    assert not any("QQQ" in v for v in values)  # invalid base58 rejected


def test_telegram_usernames():
    inds = extract_indicators("contact @darktrace_ops or @sec_bot42 on telegram, not email@x")
    handles = {i["value"] for i in inds if i["type"] == "telegram_username"}
    assert handles == {"@darktrace_ops", "@sec_bot42"}


def test_aliases():
    aliases = [{"alias": "Acme Corp", "canonical": "acme"}, {"alias": "Nimbus", "canonical": "nimbus"}]
    inds = extract_indicators("Acme Corp breached — Nimbus affected", aliases)
    alias_vals = {(i["normalized_value"]) for i in inds if i["type"] == "alias"}
    assert alias_vals == {"acme", "nimbus"}


def test_no_false_positives_on_plain_text():
    inds = extract_indicators("Just a normal status update about the build pipeline.")
    assert inds == []


def test_indicator_metadata():
    inds = extract_indicators("mail admin@example.com")
    assert inds[0]["extractor_version"] == "1.0"
    assert isinstance(inds[0]["confidence"], float) and inds[0]["confidence"] >= 0.9
    assert "matched_text" in inds[0]
