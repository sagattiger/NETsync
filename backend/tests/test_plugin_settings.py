import pytest

from netsync.plugins.builtin.ai import plugin as ai
from netsync.plugins.builtin.ai.context import system_prompt
from netsync.plugins.builtin.ai.ollama import THINK
from netsync.plugins.settings import MASK, coerce, masked


def test_coerce_types_and_keeps_masked_secret():
    current = {**ai.defaults, "api_key": "s3cret"}
    out = coerce(ai, {"auto_events": 0, "cooldown_minutes": "45", "temperature": "0.5",
                      "event_min_state": "2", "api_key": MASK, "model": "llama3.1:8b"}, current)
    assert out["auto_events"] is False
    assert out["cooldown_minutes"] == 45
    assert out["temperature"] == 0.5
    assert out["event_min_state"] == "2"
    assert out["api_key"] == "s3cret"  # untouched when the UI sends the mask back
    assert out["model"] == "llama3.1:8b"


def test_coerce_rejects_out_of_range_and_bad_select():
    with pytest.raises(ValueError):
        coerce(ai, {"max_words": 5}, ai.defaults)
    with pytest.raises(ValueError):
        coerce(ai, {"event_min_state": "9"}, ai.defaults)


def test_secrets_are_masked():
    assert masked(ai, {"api_key": "abc", "model": "m"}) == {"api_key": MASK, "model": "m"}
    assert masked(ai, {"api_key": ""})["api_key"] == ""


def test_system_prompt_includes_settings():
    p = system_prompt({**ai.defaults, "language": "Portuguese", "max_words": 120, "extra_instructions": "We run MikroTik"})
    assert "Portuguese" in p and "120 words" in p and "We run MikroTik" in p


def test_reasoning_is_stripped():
    assert THINK.sub("", "<think>long reasoning</think>\n**What happened** x").strip() == "**What happened** x"
