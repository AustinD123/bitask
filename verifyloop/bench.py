"""The benchmark: one-shot against the fix loop, over every case, model and trial.

One-shot is attempt 1 of the same run, so it costs no extra call. Trials are
part of the cache key, so they are real repeats. A re-run of the same command
reads the cache, so it costs nothing and resumes where a stopped run ended.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from verifyloop.case import Case, load_case
from verifyloop.llm import DailyLimitReached
from verifyloop.loop import FixRun, fix

CASES_DIR = Path(__file__).resolve().parent.parent / "bench" / "cases"
RESULTS_DIR = Path("out/results")


@dataclass
class Row:
    """The four pass or fail verdicts for one case, model and trial, and how many attempts the loop used."""

    case: str
    model: str
    trial: int
    one_visible: bool
    one_hidden: bool
    loop_visible: bool
    loop_hidden: bool
    attempts: int


def row_from(run: FixRun) -> Row:
    """Read the one-shot verdicts from attempt 1 and the loop verdicts from the final attempt."""
    first = run.attempts[0]
    return Row(
        case=run.case_id, model=run.model, trial=run.trial,
        one_visible=first.stage == "ok",
        one_hidden=_passed(run.hidden_first),
        loop_visible=run.passed,
        loop_hidden=_passed(run.hidden_final),
        attempts=len(run.attempts),
    )


def run_bench(
    cases: list[Case],
    models: list[str],
    trials: int,
    progress: Callable[[Row], None] | None = None,
    results_dir: Path | None = None,
) -> dict:
    """Run every case × model × trial, then write results.json and results.md.

    A DailyLimitReached stops the run. The results so far are still saved, and
    the stop is recorded in the results instead of being raised.
    """
    results_dir = results_dir or RESULTS_DIR
    rows: list[Row] = []
    stopped = None
    model = ""
    try:
        for case in cases:
            for model in models:
                for trial in range(1, trials + 1):
                    row = row_from(fix(case, model, trial=trial))
                    rows.append(row)
                    if progress:
                        progress(row)
    except DailyLimitReached as error:
        stopped = {"model": model, "message": str(error)}
    results = {
        "generated": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "stopped": stopped,
        "rows": [asdict(row) for row in rows],
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (results_dir / "results.md").write_text(markdown(rows, stopped), encoding="utf-8")
    return results


def markdown(rows: list[Row], stopped: dict | None) -> str:
    """Return the results as markdown: one table per case and model, then the overall pass rates per model."""
    lines = ["# Results", ""]
    if stopped:
        lines += [f"**Stopped early:** {stopped['message']}", ""]
    lines += [
        "| case | model | one-shot visible | one-shot hidden | loop visible | loop hidden | avg attempts |",
        "|---|---|---|---|---|---|---|",
    ]
    for case, model in _groups(rows, lambda r: (r.case, r.model)):
        group = [r for r in rows if (r.case, r.model) == (case, model)]
        lines.append(
            f"| {case} | {model} | {_count(group, 'one_visible')} | {_count(group, 'one_hidden')} "
            f"| {_count(group, 'loop_visible')} | {_count(group, 'loop_hidden')} "
            f"| {sum(r.attempts for r in group) / len(group):.1f} |"
        )
    lines += ["", "## Overall pass rates", "",
              "| model | one-shot visible | one-shot hidden | loop visible | loop hidden |",
              "|---|---|---|---|---|"]
    for model in _groups(rows, lambda r: r.model):
        group = [r for r in rows if r.model == model]
        lines.append(
            f"| {model} | {_percent(group, 'one_visible')} | {_percent(group, 'one_hidden')} "
            f"| {_percent(group, 'loop_visible')} | {_percent(group, 'loop_hidden')} |"
        )
    return "\n".join(lines) + "\n"


def load_cases(pattern: str) -> list[Case]:
    """Load every case directory under bench/cases whose name matches the glob ``pattern``."""
    return [load_case(path) for path in sorted(CASES_DIR.glob(pattern)) if (path / "case.json").is_file()]


def _passed(result: dict | None) -> bool:
    return result is not None and result["stage"] == "ok"


def _groups(rows: list[Row], key) -> list:
    """The distinct keys, in first-seen order."""
    return list(dict.fromkeys(key(row) for row in rows))


def _count(group: list[Row], field: str) -> str:
    return f"{sum(getattr(r, field) for r in group)}/{len(group)}"


def _percent(group: list[Row], field: str) -> str:
    passed = sum(getattr(r, field) for r in group)
    return f"{passed}/{len(group)} ({100 * passed / len(group):.0f}%)"
