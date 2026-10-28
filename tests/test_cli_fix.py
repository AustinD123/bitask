"""Tests for ``python -m verifyloop.cli fix``. MockProvider replaces the model; no network.

The candidates are compiled for real against the mini fixture case.
"""

from pathlib import Path

import pytest

from verifyloop import cli, llm, loop
from verifyloop.llm import MockProvider

FIXTURE = Path(__file__).parent / "fixtures" / "mini_case"
REFERENCE = (FIXTURE / "reference_fix.c").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(loop, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("LLM_API_KEYS", "key-one")
    monkeypatch.setenv("NO_COLOR", "1")


def use(monkeypatch, script: list) -> None:
    monkeypatch.setattr(llm, "_backend", lambda: MockProvider(script))


def test_successful_fix_prints_attempts_diff_and_summary(monkeypatch, capsys) -> None:
    use(monkeypatch, ["Try this:\n```c\n" + REFERENCE + "```"])
    code = cli.main(["fix", "--case", str(FIXTURE), "--model", "m"])
    out = capsys.readouterr().out
    assert code == 0
    assert "attempt 1: ok" in out
    assert "--- buggy" in out and "+++ final" in out
    assert "-" in out and "a - b" in out  # the buggy line is shown as removed
    assert "PASS  mini_case with m: 1 attempt(s) of 5" in out
    assert "hidden:  PASS" in out


def test_failed_fix_exits_one_and_names_the_stage(monkeypatch, capsys) -> None:
    use(monkeypatch, ["```c\nint broken(\n```"])
    code = cli.main(["fix", "--case", str(FIXTURE), "--model", "m", "--max-attempts", "1"])
    out = capsys.readouterr().out
    assert code == 1
    assert "attempt 1: compile_error" in out
    assert "FAIL  mini_case with m: 1 attempt(s) of 1" in out
    assert "hidden:  FAIL [compile_error]" in out


def test_no_code_block_is_reported_as_an_attempt(monkeypatch, capsys) -> None:
    use(monkeypatch, ["No code here."])
    code = cli.main(["fix", "--case", str(FIXTURE), "--model", "m", "--max-attempts", "1"])
    assert code == 1
    assert "attempt 1: no_code" in capsys.readouterr().out


def test_missing_key_is_an_error_not_a_traceback(monkeypatch, capsys) -> None:
    monkeypatch.delenv("LLM_API_KEYS")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert cli.main(["fix", "--case", str(FIXTURE), "--model", "m"]) == 2
    assert "no API key" in capsys.readouterr().err


def test_bad_case_directory_exits_two(tmp_path, capsys) -> None:
    assert cli.main(["fix", "--case", str(tmp_path), "--model", "m"]) == 2
    assert "error:" in capsys.readouterr().err


def test_colour_is_off_when_not_a_terminal() -> None:
    assert cli._diff(["a"], ["b"], colour=False).count("\x1b") == 0


def test_colour_marks_added_and_removed_lines() -> None:
    text = cli._diff(["a - b"], ["a + b"], colour=True)
    assert f"{cli.RED}-a - b{cli.RESET}" in text
    assert f"{cli.GREEN}+a + b{cli.RESET}" in text
