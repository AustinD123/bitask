"""Tests for the command-line interface (verifyloop/cli.py).

The exit-code matrix runs every starter case with and without --reference,
--hidden and --json. The rest checks the human output format, colour rules,
the harness-error exit code, and one real ``python -m verifyloop.cli`` run.
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from verifyloop import cli

REPO = Path(__file__).resolve().parent.parent
CASES = sorted(p for p in (REPO / "bench" / "cases").iterdir() if p.is_dir())
CASE_01 = REPO / "bench" / "cases" / "01_heap_overflow"


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
@pytest.mark.parametrize(
    ("flags", "expected"),
    [([], 1), (["--reference"], 0), (["--hidden"], 1), (["--reference", "--hidden"], 0)],
)
def test_exit_codes_for_every_case(case_dir: Path, flags: list[str], expected: int) -> None:
    assert cli.main(["verify", "--case", str(case_dir), *flags]) == expected


@pytest.mark.parametrize("case_dir", CASES, ids=lambda p: p.name)
@pytest.mark.parametrize(("flags", "expected"), [([], 1), (["--reference"], 0)])
def test_json_output_is_valid_and_matches_the_exit_code(
    case_dir: Path, flags: list[str], expected: int, capsys,
) -> None:
    assert cli.main(["verify", "--case", str(case_dir), "--json", *flags]) == expected
    data = json.loads(capsys.readouterr().out)
    assert data["passed"] is (expected == 0)
    assert set(data["checks"]) == {"compiled", "ran_to_completion", "sanitizers_clean", "tests_passed"}


def test_invalid_case_directory_is_exit_2(tmp_path: Path, capsys) -> None:
    assert cli.main(["verify", "--case", str(tmp_path)]) == 2
    assert "case.json not found" in capsys.readouterr().err


def test_missing_source_file_is_exit_2(capsys) -> None:
    assert cli.main(["verify", "--case", str(CASE_01), "--source", "/nonexistent/candidate.c"]) == 2
    assert "source file not found" in capsys.readouterr().err


def test_harness_error_is_exit_2(monkeypatch, capsys) -> None:
    monkeypatch.setenv("CC", "/nonexistent/clang")
    assert cli.main(["verify", "--case", str(CASE_01), "--reference"]) == 2
    assert "ERROR [harness_error]" in capsys.readouterr().out


def test_failing_output_puts_the_summary_under_the_verdict(capsys) -> None:
    assert cli.main(["verify", "--case", str(CASE_01)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("FAIL [sanitizer]  01_heap_overflow (visible test, ")
    assert lines[1].strip() == "AddressSanitizer: heap-buffer-overflow buggy.c:16:8 in join_words"
    assert "✓ compiled" in lines[2] and "✗ sanitizers clean" in lines[2]
    assert "– ran to completion" in lines[2] and "– tests passed" in lines[2]
    assert "  ---" in lines


def test_passing_output_has_no_summary_or_output_block(capsys) -> None:
    assert cli.main(["verify", "--case", str(CASE_01), "--reference"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("PASS  01_heap_overflow (visible test, ")
    assert "---" not in out


def test_hidden_flag_is_reported(capsys) -> None:
    cli.main(["verify", "--case", str(CASE_01), "--reference", "--hidden"])
    assert "(hidden test, " in capsys.readouterr().out


class _Terminal(io.StringIO):
    """A stand-in for stdout that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


def test_colour_on_a_terminal_and_off_with_no_color(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stdout", _Terminal())
    cli.main(["verify", "--case", str(CASE_01)])
    assert "\x1b[31mFAIL [sanitizer]\x1b[0m" in sys.stdout.getvalue()

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys, "stdout", _Terminal())
    cli.main(["verify", "--case", str(CASE_01)])
    assert "\x1b[" not in sys.stdout.getvalue()


def test_colour_is_off_when_stdout_is_not_a_terminal(capsys) -> None:
    cli.main(["verify", "--case", str(CASE_01)])
    assert "\x1b[" not in capsys.readouterr().out


def test_python_dash_m_runs_the_cli() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "verifyloop.cli", "verify", "--case", str(CASE_01)],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 1
    assert proc.stdout.startswith("FAIL [sanitizer]  01_heap_overflow")
