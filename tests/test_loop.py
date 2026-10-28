"""Tests for the fix loop (verifyloop/loop.py). MockProvider replaces the model.

The candidates are compiled for real against the mini fixture case, so these
tests need clang and run in the Docker image. They never touch the network,
and out/ is redirected to a temporary directory.
"""

import json
from pathlib import Path

import pytest

from verifyloop import llm, loop
from verifyloop.case import load_case
from verifyloop.llm import MockProvider

FIXTURE = Path(__file__).parent / "fixtures" / "mini_case"
REFERENCE = (FIXTURE / "reference_fix.c").read_text(encoding="utf-8")
HIDDEN = (FIXTURE / "hidden_test.c").read_text(encoding="utf-8")


def fenced(code: str) -> str:
    return f"Here is the fix.\n```c\n{code}\n```"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keep the cache and the run logs in tmp_path, and use two keys so the key pool is exercised."""
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(loop, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("LLM_API_KEYS", "key-one")


def use(monkeypatch, script: list) -> MockProvider:
    provider = MockProvider(script)
    monkeypatch.setattr(llm, "_backend", lambda: provider)
    return provider


@pytest.fixture
def case():
    return load_case(FIXTURE)


# Code extraction

def test_extract_code_takes_the_last_block() -> None:
    text = "first:\n```c\nint a;\n```\nthen:\n```c\nint b;\n```\n"
    assert loop.extract_code(text) == "int b;\n"


def test_extract_code_without_a_block_is_none() -> None:
    assert loop.extract_code("I could not find the bug.") is None


# Guardrails

@pytest.mark.parametrize("code", [
    "__attribute__((no_sanitize(\"address\"))) int f(void) { return 1; }",
    "#pragma clang diagnostic ignored \"-Wall\"",
    "#pragma GCC diagnostic ignored \"-Werror\"",
    "int f(void) { return __asan_report_load1(0), 1; }",
    "const char *m = getenv(\"VERIFY_NONCE\");",
])
def test_guardrail_rejects_banned_content(code: str) -> None:
    assert loop.guardrail(code)


def test_guardrail_allows_ordinary_code() -> None:
    assert loop.guardrail("#pragma once\nint add(int a, int b) { return a + b; }") is None


def test_rejected_candidate_is_not_compiled(case, monkeypatch) -> None:
    banned = fenced("int add(int a, int b) { return a + b; } /* VERIFY_NONCE */")
    use(monkeypatch, [banned, banned])
    run = loop.fix(case, "m", max_attempts=1)
    attempt = run.attempts[0]
    assert attempt.stage == "rejected"
    assert "VERIFY_NONCE" in attempt.output
    assert attempt.result is None
    assert run.hidden_first is None


def test_missing_code_block_fails_the_attempt(case, monkeypatch) -> None:
    use(monkeypatch, ["Sorry, no code today."])
    run = loop.fix(case, "m", max_attempts=1)
    assert run.attempts[0].stage == "no_code"
    assert run.attempts[0].output == "no code block in response"


# The loop

def test_stops_on_first_pass(case, monkeypatch) -> None:
    provider = use(monkeypatch, [fenced(REFERENCE), "never requested"])
    run = loop.fix(case, "m")
    assert len(run.attempts) == 1
    assert run.passed
    assert len(provider.calls) == 1


def test_stops_at_max_attempts(case, monkeypatch) -> None:
    provider = use(monkeypatch, [fenced("int broken("), fenced("int broken(")])
    run = loop.fix(case, "m", max_attempts=2)
    assert len(run.attempts) == 2
    assert not run.passed
    assert len(provider.calls) == 2


def test_retry_prompt_has_only_the_latest_failure(case, monkeypatch) -> None:
    attempt_a = fenced("/* A_MARK */ int broken_a(")
    attempt_b = fenced("/* B_MARK */ int broken_b(")
    provider = use(monkeypatch, [attempt_a, attempt_b, fenced(REFERENCE)])
    run = loop.fix(case, "m")
    assert run.passed
    third_prompt = provider.calls[2]["messages"][-1]["content"]
    assert "B_MARK" in third_prompt, "the previous attempt must be in the retry"
    assert "A_MARK" not in third_prompt, "older attempts must not be sent"
    assert "It failed at stage compile_error:" in third_prompt
    assert run.attempts[1].output in third_prompt  # the cleaned error of attempt 2


def test_hidden_test_is_never_in_any_prompt(case, monkeypatch) -> None:
    provider = use(monkeypatch, [fenced("int broken("), fenced(REFERENCE)])
    loop.fix(case, "m")
    for call in provider.calls:
        for message in call["messages"]:
            assert HIDDEN not in message["content"]
            assert "hidden" not in message["content"].lower()


def test_hidden_verdicts_are_recorded_separately(case, monkeypatch) -> None:
    use(monkeypatch, [fenced("int broken("), fenced(REFERENCE)])
    run = loop.fix(case, "m")
    assert run.hidden_first["stage"] == "compile_error"  # it reached the compiler and failed there
    assert run.hidden_final["stage"] == "ok"


def test_one_passing_attempt_gives_the_same_hidden_result_for_first_and_final(case, monkeypatch) -> None:
    use(monkeypatch, [fenced(REFERENCE)])
    run = loop.fix(case, "m")
    assert run.hidden_first == run.hidden_final
    assert run.hidden_first["stage"] == "ok"


def test_progress_is_called_per_attempt(case, monkeypatch) -> None:
    use(monkeypatch, [fenced("int broken("), fenced(REFERENCE)])
    seen = []
    loop.fix(case, "m", progress=lambda attempt: seen.append(attempt.stage))
    assert seen == ["compile_error", "ok"]


def test_every_run_is_logged(case, monkeypatch, tmp_path) -> None:
    use(monkeypatch, [fenced(REFERENCE)])
    loop.fix(case, "openai/gpt-oss-20b")
    (path,) = (tmp_path / "runs").glob("*.json")
    assert "openai-gpt-oss-20b" in path.name
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["attempts"][0]["usage"]["cache_hit"] is False
    assert data["attempts"][0]["result"]["passed"] is True


# Cache and trials

def test_cache_prevents_a_second_call(case, monkeypatch) -> None:
    use(monkeypatch, [fenced(REFERENCE)])
    loop.fix(case, "m")
    provider = use(monkeypatch, [])  # nothing scripted: any call would fail
    run = loop.fix(case, "m")
    assert run.passed
    assert provider.calls == []


def test_trials_are_real_repeats_not_cache_hits(case, monkeypatch) -> None:
    provider = use(monkeypatch, [fenced(REFERENCE), fenced(REFERENCE)])
    loop.fix(case, "m", trial=0)
    loop.fix(case, "m", trial=1)
    assert len(provider.calls) == 2
