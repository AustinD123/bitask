"""Tests for the benchmark (verifyloop/bench.py). fix() is replaced, so no model is called."""

import json

import pytest

from verifyloop import bench, cli
from verifyloop.llm import DailyLimitReached
from verifyloop.loop import Attempt, FixRun


def attempt(number: int, stage: str) -> Attempt:
    return Attempt(number=number, prompt=[], response="", code="int x;", stage=stage,
                   output="", usage={"cache_hit": False})


def run_of(case: str, model: str, trial: int, stages: list[str], hidden_first: str | None,
           hidden_final: str | None) -> FixRun:
    run = FixRun(case_id=case, model=model, trial=trial,
                 attempts=[attempt(i + 1, s) for i, s in enumerate(stages)])
    run.hidden_first = {"stage": hidden_first, "passed": hidden_first == "ok"} if hidden_first else None
    run.hidden_final = {"stage": hidden_final, "passed": hidden_final == "ok"} if hidden_final else None
    return run


def test_row_takes_one_shot_from_attempt_one_and_loop_from_the_last() -> None:
    run = run_of("05", "m", 1, ["compile_error", "ok"], hidden_first="compile_error", hidden_final="ok")
    row = bench.row_from(run)
    assert (row.one_visible, row.one_hidden) == (False, False)
    assert (row.loop_visible, row.loop_hidden) == (True, True)
    assert row.attempts == 2


def test_one_shot_can_pass_visible_and_fail_hidden() -> None:
    run = run_of("06", "m", 1, ["ok"], hidden_first="sanitizer", hidden_final="sanitizer")
    row = bench.row_from(run)
    assert row.one_visible and not row.one_hidden


def test_markdown_table_and_overall_rates_from_mocked_rows() -> None:
    rows = [
        bench.Row("05", "m", 1, True, True, True, True, 1),
        bench.Row("05", "m", 2, False, False, True, False, 3),
        bench.Row("06", "m", 1, False, False, False, False, 5),
        bench.Row("06", "m", 2, False, False, True, True, 2),
    ]
    text = bench.markdown(rows, None)
    assert "| 05 | m | 1/2 | 1/2 | 2/2 | 1/2 | 2.0 |" in text
    assert "| 06 | m | 0/2 | 0/2 | 1/2 | 1/2 | 3.5 |" in text
    assert "| m | 1/4 (25%) | 1/4 (25%) | 3/4 (75%) | 2/4 (50%) |" in text
    assert "Stopped early" not in text


def test_markdown_notes_an_early_stop() -> None:
    text = bench.markdown([bench.Row("05", "m", 1, True, True, True, True, 1)],
                          {"model": "m", "message": "daily limit reached"})
    assert "**Stopped early:** daily limit reached" in text


def test_run_bench_runs_each_trial_as_its_own_call(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_fix(case, model, trial):
        calls.append((case, model, trial))
        return run_of(case, model, trial, ["ok"], "ok", "ok")

    monkeypatch.setattr(bench, "fix", fake_fix)
    results = bench.run_bench(["c1"], ["a", "b"], trials=2, results_dir=tmp_path)
    assert calls == [("c1", "a", 1), ("c1", "a", 2), ("c1", "b", 1), ("c1", "b", 2)]
    assert results["stopped"] is None
    assert len(results["rows"]) == 4


def test_daily_limit_stops_the_run_and_saves_what_was_done(monkeypatch, tmp_path) -> None:
    def fake_fix(case, model, trial):
        if model == "b" and trial == 1:
            raise DailyLimitReached("daily limit reached for b")
        return run_of(case, model, trial, ["ok"], "ok", "ok")

    monkeypatch.setattr(bench, "fix", fake_fix)
    results = bench.run_bench(["c1", "c2"], ["a", "b"], trials=1, results_dir=tmp_path)
    assert results["stopped"]["model"] == "b"
    assert len(results["rows"]) == 1  # only the run for model a finished
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["stopped"]["model"] == "b"
    assert "Stopped early" in (tmp_path / "results.md").read_text(encoding="utf-8")


def test_provider_error_is_a_failed_run_and_the_bench_continues(monkeypatch, tmp_path) -> None:
    def fake_fix(case, model, trial):
        if trial == 1:
            run = run_of(case, model, trial, ["llm_error"], None, None)
            run.attempts[0].output = "a: provider error: connection reset"
            return run
        return run_of(case, model, trial, ["ok"], "ok", "ok")

    monkeypatch.setattr(bench, "fix", fake_fix)
    results = bench.run_bench(["c1"], ["a"], trials=2, results_dir=tmp_path)
    assert results["stopped"] is None
    assert len(results["rows"]) == 2
    assert results["rows"][0]["llm_error"] == "a: provider error: connection reset"
    assert results["rows"][0]["loop_visible"] is False
    text = (tmp_path / "results.md").read_text(encoding="utf-8")
    assert "## Provider errors" in text
    assert "| c1 | a | 1 | a: provider error: connection reset |" in text
    assert "| a | 1/2 (50%) | 1/2 (50%) | 1/2 (50%) | 1/2 (50%) |" in text


def test_cli_bench_prints_the_resume_message(monkeypatch, capsys, tmp_path) -> None:
    def fake_fix(case, model, trial):
        raise DailyLimitReached("daily limit reached")

    monkeypatch.setattr(bench, "fix", fake_fix)
    monkeypatch.setattr(bench, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "RESULTS_DIR", tmp_path)
    code = cli.main(["bench", "--cases", "01_*", "--models", "openai/gpt-oss-20b", "--trials", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "daily limit reached for openai/gpt-oss-20b; re-run after reset to resume" in out


def test_load_cases_matches_the_glob() -> None:
    assert [c.id for c in bench.load_cases("0[12]_*")] == ["01_heap_overflow", "02_signed_overflow"]
    assert bench.load_cases("no_such_case*") == []


def test_cli_bench_with_no_matching_cases_is_an_error(capsys) -> None:
    assert cli.main(["bench", "--cases", "no_such_case*"]) == 2
    assert "no cases match" in capsys.readouterr().err


def test_all_ten_starter_cases_are_loaded() -> None:
    assert len(bench.load_cases("*")) == 10

