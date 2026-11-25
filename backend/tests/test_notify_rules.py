"""Notification rules: webhook URLs, problem types, secrets kept out of the UI, error text."""

import pytest

from netsync.notify_rules import (
    clean_config, clean_types, clean_url, error_text, problem_type, public_config, wants,
)

WEBHOOK = [
    {"key": "url", "label": "URL", "type": "text", "required": True},
    {"key": "secret", "label": "Bearer token (optional)", "type": "secret"},
]


@pytest.mark.parametrize(("raw", "url"), [
    (" http://n8n.infra.example:5678/webhook/x", "http://n8n.infra.example:5678/webhook/x"),  # the reported bug
    ("https://hooks.example.com/a?b=1", "https://hooks.example.com/a?b=1"),
    ("10.0.0.5:5678/webhook/x", "http://10.0.0.5:5678/webhook/x"),
    ("10.0.0.5", "http://10.0.0.5"),
    ("[fd00::5]:8080/hook", "http://[fd00::5]:8080/hook"),
    ("alerts.lan/hook", "http://alerts.lan/hook"),
    ("HTTPS://Example.com", "HTTPS://Example.com"),
])
def test_clean_url_accepts_http_https_ip_and_host(raw, url):
    assert clean_url(raw) == url


@pytest.mark.parametrize("bad", ["", "   ", "ftp://x.example", "http://", "http://a b/c", "http://h:99999/", "javascript:alert(1)"])
def test_clean_url_rejects(bad):
    with pytest.raises(ValueError):
        clean_url(bad)


def test_problem_types():
    assert problem_type("cpu_util") == "cpu" and problem_type("if") == "port"
    assert problem_type("ping_loss") == "device_down" and problem_type("storage_used") == "disk"
    assert problem_type("something_new") == "other" and problem_type(None) == "other"
    assert wants(None, "cpu_util") and wants([], "if")
    assert wants(["cpu", "disk"], "storage_used") and not wants(["cpu"], "if")
    assert clean_types(["disk", "cpu", "cpu"]) == ["cpu", "disk"] and clean_types([]) is None
    with pytest.raises(ValueError):
        clean_types(["cpu", "nope"])


def test_secrets_never_go_back_to_the_ui_and_survive_an_edit():
    saved = {"url": "http://10.0.0.5/hook", "secret": "s3cr3t-token"}
    config, secrets_set = public_config(WEBHOOK, saved)
    assert config == {"url": "http://10.0.0.5/hook"} and secrets_set == ["secret"]
    # the edit form sends the secret back empty: the saved one is kept
    assert clean_config(WEBHOOK, {"url": " 10.0.0.6/hook ", "secret": ""}, saved) == {
        "url": "http://10.0.0.6/hook", "secret": "s3cr3t-token"}
    # a new value replaces it
    assert clean_config(WEBHOOK, {"url": "10.0.0.6", "secret": "new-one"}, saved)["secret"] == "new-one"
    with pytest.raises(ValueError, match="URL"):
        clean_config(WEBHOOK, {"url": ""})


def test_error_text_hides_tokens():
    cfg = {"bot_token": "123456:ABCDEF", "chat_id": "42"}
    e = RuntimeError("Client error '401' for url 'https://api.telegram.org/bot123456:ABCDEF/sendMessage'")
    assert "ABCDEF" not in error_text(e, cfg) and "***" in error_text(e, cfg)
