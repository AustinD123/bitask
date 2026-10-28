"""Tests for the LLM wrapper (verifyloop/llm.py). Only MockProvider is used, so no network.

Each test points the cache at a temporary directory and replaces the sleep,
so retries are instant and nothing is written to out/.
"""

import pytest

from verifyloop import llm
from verifyloop.llm import DailyLimitReached, LLMError, MockProvider, RateLimited

MESSAGES = [{"role": "system", "content": "You fix bugs."}, {"role": "user", "content": "fix it"}]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Send the cache to tmp_path, record sleeps instead of taking them, and set one key."""
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(llm, "_sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setenv("LLM_API_KEY", "key-one")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    sleeps: list[float] = []
    return sleeps


def use(monkeypatch, provider: MockProvider) -> MockProvider:
    """Make complete() use ``provider`` instead of a real backend."""
    monkeypatch.setattr(llm, "_backend", lambda: provider)
    return provider


def minute_limit(retry_after: str = "2") -> RateLimited:
    return RateLimited(f"rate limit, retry in {retry_after}s", daily=False, retry_after=float(retry_after))


def daily_limit() -> RateLimited:
    return RateLimited("Limit 200000 on tokens per day (TPD)", daily=True, retry_after=3600.0)


def test_reply_is_returned_and_usage_recorded(monkeypatch) -> None:
    provider = use(monkeypatch, MockProvider(["hello"]))
    text, usage = llm.complete(MESSAGES, "openai/gpt-oss-20b")
    assert text == "hello"
    assert usage["cache_hit"] is False
    assert provider.calls[0]["key"] == "key-one"


def test_cache_hit_makes_no_second_call(monkeypatch) -> None:
    provider = use(monkeypatch, MockProvider(["first"]))
    llm.complete(MESSAGES, "openai/gpt-oss-20b")
    text, usage = llm.complete(MESSAGES, "openai/gpt-oss-20b")
    assert text == "first"
    assert usage["cache_hit"] is True
    assert len(provider.calls) == 1


def test_cache_key_changes_with_model(monkeypatch) -> None:
    provider = use(monkeypatch, MockProvider(["small", "large"]))
    assert llm.complete(MESSAGES, "openai/gpt-oss-20b")[0] == "small"
    assert llm.complete(MESSAGES, "openai/gpt-oss-120b")[0] == "large"
    assert len(provider.calls) == 2


def test_cache_key_changes_with_trial(monkeypatch) -> None:
    provider = use(monkeypatch, MockProvider(["first", "second"]))
    assert llm.complete(MESSAGES, "m", trial=1)[0] == "first"
    assert llm.complete(MESSAGES, "m", trial=2)[0] == "second"
    assert len(provider.calls) == 2


def test_minute_limit_waits_and_retries_then_succeeds(monkeypatch, isolated) -> None:
    provider = use(monkeypatch, MockProvider([minute_limit("5"), minute_limit("6"), "ok"]))
    assert llm.complete(MESSAGES, "m")[0] == "ok"
    assert isolated == [5.0, 6.0]
    assert len(provider.calls) == 3


def test_minute_limit_gives_up_after_three_retries(monkeypatch) -> None:
    provider = use(monkeypatch, MockProvider([minute_limit()] * 4))
    with pytest.raises(LLMError, match="still rate limited after 3 retries"):
        llm.complete(MESSAGES, "m")
    assert len(provider.calls) == 4  # the first call plus three retries


def test_daily_limit_raises_at_once_without_waiting(monkeypatch, isolated) -> None:
    provider = use(monkeypatch, MockProvider([daily_limit()]))
    with pytest.raises(DailyLimitReached, match="daily limit reached for m"):
        llm.complete(MESSAGES, "m")
    assert isolated == []
    assert len(provider.calls) == 1


def test_no_key_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMError, match="no API key: set LLM_API_KEY or GROQ_API_KEY"):
        llm.complete(MESSAGES, "m")


def test_llm_api_key_is_preferred_over_groq_api_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "from-groq")
    assert llm._key() == "key-one"
    monkeypatch.delenv("LLM_API_KEY")
    assert llm._key() == "from-groq"


def test_key_is_stripped_of_whitespace(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "  key-two \n")
    assert llm._key() == "key-two"


@pytest.mark.parametrize("text, seconds", [
    ("2m59.56s", 179.56), ("7.66s", 7.66), ("20ms", 0.02), ("", 0.0), ("soon", 0.0),
])
def test_duration_parsing(text: str, seconds: float) -> None:
    assert llm._duration(text) == pytest.approx(seconds)


def test_retry_after_header_is_preferred() -> None:
    assert llm._retry_seconds({"retry-after": "12"}) == 12.0
    assert llm._retry_seconds({"x-ratelimit-reset-tokens": "1m2s"}) == 62.0
    assert llm._retry_seconds({}) == llm.DEFAULT_WAIT_S


def test_daily_detection() -> None:
    assert llm._is_daily("Rate limit on tokens per day (TPD): Limit 200000")
    assert llm._is_daily("requests per day exceeded")
    assert not llm._is_daily("Rate limit on tokens per minute (TPM)")


def test_unknown_provider_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(LLMError, match="unknown LLM_PROVIDER"):
        llm.complete(MESSAGES, "m")


def test_anthropic_backend_moves_system_message_out(monkeypatch) -> None:
    """The Anthropic backend is tested with a fake SDK client, not the network."""
    anthropic = pytest.importorskip("anthropic")

    seen = {}

    class FakeMessages:
        def create(self, **kwargs):
            seen.update(kwargs)
            block = type("Block", (), {"type": "text", "text": "fixed"})()
            usage = type("Usage", (), {"input_tokens": 3, "output_tokens": 4})()
            return type("Resp", (), {"content": [block], "usage": usage})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    reply = llm.AnthropicBackend().call(MESSAGES, "claude-x", "k", {})
    assert reply.text == "fixed"
    assert seen["system"] == "You fix bugs."
    assert seen["messages"] == [{"role": "user", "content": "fix it"}]
