"""One chat request to an LLM, with a disk cache, rate-limit retries and key rotation.

complete() is the only entry point the fix loop uses. Replies are cached by a
hash of the request, so a repeated call costs nothing and a run can resume
after a crash. Keys are tried in order from LLM_API_KEYS. When a key has used
up its daily quota for a model, it is skipped for that model until UTC
midnight, and the next key is used. Only the key's hash is stored.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
CACHE_DIR = Path("out/cache")
MAX_RETRIES = 3
DEFAULT_WAIT_S = 10.0
MAX_TOKENS = 4000
_DURATION = re.compile(r"(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+)ms)?")
_DAILY = re.compile(r"per day|\bTPD\b|\bRPD\b")
_NUMBERED = re.compile(r"GROQ_(?:API_)?KEY_(\d+)")
_sleep = time.sleep  # a module attribute so tests can replace it


class LLMError(Exception):
    """The provider failed in a way that retrying will not fix."""


class DailyLimitReached(LLMError):
    """Every key has used up its daily quota for this model. Re-run after the UTC reset."""


class RateLimited(Exception):
    """A backend's HTTP 429. ``daily`` means the quota resets at UTC midnight."""

    def __init__(self, message: str, daily: bool, retry_after: float) -> None:
        super().__init__(message)
        self.daily = daily
        self.retry_after = retry_after


@dataclass
class Reply:
    """The text of one reply and its token counts."""

    text: str
    prompt_tokens: int
    completion_tokens: int


class MockProvider:
    """A backend for tests. Returns scripted replies in order, raising any exception in the script.

    ``calls`` records every request, including the key it was sent with.
    """

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def call(self, messages: list[dict], model: str, key: str, settings: dict) -> Reply:
        """Return the next scripted reply, or raise the scripted exception."""
        self.calls.append({"messages": messages, "model": model, "key": key})
        if not self.script:
            raise LLMError("MockProvider has no scripted reply left")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return Reply(item, 0, 0)


class OpenAIBackend:
    """Any OpenAI-compatible API. The SDK's own retries are off, so 429s reach our retry logic."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def call(self, messages: list[dict], model: str, key: str, settings: dict) -> Reply:
        """Send one chat request. Raises RateLimited on HTTP 429."""
        import openai  # imported here so the tests run without the package

        client = openai.OpenAI(api_key=key, base_url=self.base_url, max_retries=0)
        try:
            resp = client.chat.completions.create(model=model, messages=messages, **settings)
        except openai.RateLimitError as error:
            raise RateLimited(str(error), _is_daily(str(error)), _retry_seconds(error.response.headers)) from error
        usage = resp.usage
        return Reply(resp.choices[0].message.content or "",
                     usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0)


class AnthropicBackend:
    """The Anthropic Messages API. LLM_BASE_URL is not used; the SDK's default endpoint is."""

    def call(self, messages: list[dict], model: str, key: str, settings: dict) -> Reply:
        """Send one request. System messages go to the ``system`` field. Raises RateLimited on HTTP 429."""
        import anthropic  # imported here so the tests run without the package

        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=key, max_retries=0)
        try:
            resp = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=system, messages=turns)
        except anthropic.RateLimitError as error:
            raise RateLimited(str(error), _is_daily(str(error)), _retry_seconds(error.response.headers)) from error
        text = "".join(block.text for block in resp.content if block.type == "text")
        return Reply(text, resp.usage.input_tokens, resp.usage.output_tokens)


def complete(messages: list[dict], model: str, trial: int = 0) -> tuple[str, dict]:
    """Return ``(text, usage)`` for one chat request.

    ``trial`` is not sent to the model. It is part of the cache key, so repeated
    trials of the same request are real repeats, not cache hits.

    ``usage`` has ``prompt_tokens``, ``completion_tokens``, ``latency_s`` (0.0 on
    a cache hit), ``cache_hit`` and ``key`` (the hash of the key used). A cache
    hit makes no API call. Raises DailyLimitReached when every key is out of
    quota for ``model``.
    """
    provider = os.environ.get("LLM_PROVIDER", "openai")
    settings = _settings(model)
    path = _cache_path(provider, model, messages, settings, trial)
    start = time.monotonic()
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        return cached["text"], {**cached["usage"], "latency_s": 0.0, "cache_hit": True}
    reply, key_id = _request(messages, model, settings)
    usage = {"prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
             "latency_s": round(time.monotonic() - start, 3), "cache_hit": False, "key": key_id}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": reply.text, "usage": usage}), encoding="utf-8")
    return reply.text, usage


def _settings(model: str) -> dict:
    """Request options. gpt-oss models get low reasoning effort to save tokens."""
    settings = {"max_tokens": MAX_TOKENS}
    if model.startswith("openai/gpt-oss"):
        settings["reasoning_effort"] = "low"
    return settings


def _cache_path(provider: str, model: str, messages: list[dict], settings: dict, trial: int) -> Path:
    """The cache file for one request: sha256 of everything that changes the reply."""
    blob = json.dumps([provider, model, messages, settings, trial], sort_keys=True)
    return CACHE_DIR / (hashlib.sha256(blob.encode("utf-8")).hexdigest() + ".json")


def _backend():
    """Return the backend named by LLM_PROVIDER."""
    provider = os.environ.get("LLM_PROVIDER", "openai")
    if provider == "anthropic":
        return AnthropicBackend()
    if provider == "openai":
        return OpenAIBackend(os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL))
    raise LLMError(f"unknown LLM_PROVIDER {provider!r}; use openai or anthropic")


def _keys() -> list[str]:
    """Keys from LLM_API_KEYS (comma-separated), else LLM_API_KEY, else GROQ_API_KEY, else numbered
    GROQ_KEY_1..n (or GROQ_API_KEY_1..n), tried in numeric order."""
    raw = os.environ.get("LLM_API_KEYS") or os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY", "")
    keys = [key.strip() for key in raw.split(",") if key.strip()]
    if not keys:
        numbered = sorted((int(m.group(1)), value.strip()) for name, value in os.environ.items()
                          if (m := _NUMBERED.fullmatch(name)) and value.strip())
        keys = [value for _, value in numbered]
    if not keys:
        raise LLMError("no API key: set LLM_API_KEYS (comma-separated), LLM_API_KEY, GROQ_API_KEY or GROQ_KEY_1..n")
    return keys


def _request(messages: list[dict], model: str, settings: dict) -> tuple[Reply, str]:
    """Send the request with the first key that still has quota. Returns (reply, key hash)."""
    backend = _backend()
    for key in _keys():
        key_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
        if _used_up(key_id, model):
            continue
        for attempt in range(MAX_RETRIES + 1):
            try:
                return backend.call(messages, model, key, settings), key_id
            except RateLimited as error:
                if error.daily:
                    _mark_used_up(key_id, model)  # try the next key
                    break
                if attempt == MAX_RETRIES:
                    raise LLMError(f"still rate limited after {MAX_RETRIES} retries: {error}") from error
                _sleep(error.retry_after)
    raise DailyLimitReached(f"daily limit reached for {model} on every key; re-run after the UTC reset")


def _is_daily(message: str) -> bool:
    """True if a 429 message says the daily quota is used up, rather than a per-minute limit."""
    return bool(_DAILY.search(message))


def _retry_seconds(headers) -> float:
    """Seconds to wait from a 429's headers: retry-after, else the x-ratelimit-reset values, else a default."""
    with contextlib.suppress(TypeError, ValueError):
        if headers.get("retry-after"):
            return float(headers["retry-after"])
    waits = [_duration(headers.get(name) or "") for name in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")]
    return max(waits) or DEFAULT_WAIT_S


def _duration(text: str) -> float:
    """Parse '2m59.56s', '7.66s' or '20ms' into seconds. Returns 0.0 if it does not parse."""
    match = _DURATION.fullmatch(text.strip())
    if not match or not any(match.groups()):
        return 0.0
    minutes, seconds, millis = (float(group or 0) for group in match.groups())
    return minutes * 60 + seconds + millis / 1000


def _quota_file() -> Path:
    return CACHE_DIR / "exhausted.json"


def _today() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def _used_up(key_id: str, model: str) -> bool:
    """True if this key's daily quota for this model was already used up today."""
    with contextlib.suppress(OSError, ValueError):
        return f"{_today()}|{key_id}|{model}" in json.loads(_quota_file().read_text(encoding="utf-8"))
    return False


def _mark_used_up(key_id: str, model: str) -> None:
    """Record that this key's daily quota for this model is used up today."""
    record = {}
    with contextlib.suppress(OSError, ValueError):
        record = json.loads(_quota_file().read_text(encoding="utf-8"))
    record[f"{_today()}|{key_id}|{model}"] = True
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _quota_file().write_text(json.dumps(record, indent=2), encoding="utf-8")
