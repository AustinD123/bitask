"""Command-line interface.

    python -m verifyloop.cli verify --case DIR [options]
    python -m verifyloop.cli fix --case DIR [--model M] [--max-attempts N]

``verify`` prints a verdict, the sanitizer summary (the line a reader needs
first), the checks, then the cleaned output. ``--json`` prints
VerifyResult.to_dict() for machines. ``fix`` runs the LLM loop, prints each
attempt, then a coloured diff and a summary. Exit codes: 0 passed, 1 candidate
or fix failed, 2 harness error, invalid case or LLM error.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

from verifyloop.bench import RESULTS_DIR, Row, load_cases, run_bench
from verifyloop.case import Case, CaseError, load_case
from verifyloop.llm import ConfigError, LLMError
from verifyloop.loop import Attempt, fix
from verifyloop.toolchain import VerifyResult, verify_file

DEFAULT_MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")

CHECKS = (("compiled", "compiled"), ("sanitizers_clean", "sanitizers clean"),
          ("ran_to_completion", "ran to completion"), ("tests_passed", "tests passed"))
SYMBOL = {True: "✓", False: "✗", None: "–"}
RED, GREEN, BOLD, RESET = "\x1b[31m", "\x1b[32m", "\x1b[1m", "\x1b[0m"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser with the ``verify`` and ``fix`` subcommands."""
    parser = argparse.ArgumentParser(prog="python -m verifyloop.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="verify a candidate")
    verify.add_argument("--case", required=True, type=Path, help="case directory")
    source = verify.add_mutually_exclusive_group()
    source.add_argument("--source", type=Path, help="candidate file (default: the case's editable file)")
    source.add_argument("--reference", action="store_true", help="use the case's reference fix")
    verify.add_argument("--hidden", action="store_true", help="run the hidden test instead of the visible one")
    verify.add_argument("--json", action="store_true", help="print the result as JSON")
    verify.add_argument("--keep-workdir", action="store_true", help="keep the workdir and print its path")
    fix_cmd = commands.add_parser("fix", help="run the LLM fix loop on a case")
    fix_cmd.add_argument("--case", required=True, type=Path, help="case directory")
    fix_cmd.add_argument("--model", default=os.environ.get("LLM_MODEL", "openai/gpt-oss-20b"))
    fix_cmd.add_argument("--max-attempts", type=int, default=5)
    bench_cmd = commands.add_parser("bench", help="compare one-shot with the fix loop over the starter cases")
    bench_cmd.add_argument("--models", default=",".join(DEFAULT_MODELS), help="comma-separated models")
    bench_cmd.add_argument("--trials", type=int, default=2)
    bench_cmd.add_argument("--cases", default="*", help="glob over the names in bench/cases")
    return parser


def exit_code(result: VerifyResult) -> int:
    """Return 0 if the candidate passed, 2 for a harness error, otherwise 1."""
    return 0 if result.passed else 2 if result.stage == "harness_error" else 1


def render(result: VerifyResult, case: Case, hidden: bool, colour: bool) -> str:
    """Return the human-readable report for one result."""

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if colour else text

    if result.passed:
        verdict = paint("PASS", GREEN)
    else:
        label = "ERROR" if result.stage == "harness_error" else "FAIL"
        verdict = paint(f"{label} [{result.stage}]", RED)
    lines = [f"{verdict}  {case.id} ({'hidden' if hidden else 'visible'} test, {result.duration_s:.2f}s)"]
    if result.sanitizer_summary:
        lines.append("  " + paint(result.sanitizer_summary, BOLD))
    lines.append("  " + "   ".join(f"{SYMBOL[result.checks[key]]} {label}" for key, label in CHECKS))
    if result.workdir:
        lines.append(f"  workdir: {result.workdir}")
    if result.output:
        lines += ["  ---"] + [("  " + line) if line else "" for line in result.output.splitlines()]
    return "\n".join(lines)


def fix_command(args: argparse.Namespace, colour: bool) -> int:
    """Run the fix loop, print each attempt, then the diff and summary. Returns the exit code."""
    try:
        case = load_case(args.case)
        run = fix(case, args.model, args.max_attempts, progress=_print_attempt)
    except (CaseError, ConfigError, LLMError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    final = run.attempts[-1]
    if final.code is not None:
        buggy = (case.directory / case.editable).read_text(encoding="utf-8").splitlines()
        print(_diff(buggy, final.code.splitlines(), colour))
    checks = final.result["checks"] if final.result else {}
    print(f"{'PASS' if run.passed else 'FAIL'}  {case.id} with {args.model}: "
          f"{len(run.attempts)} attempt(s) of {args.max_attempts}")
    print("  visible: " + "   ".join(f"{SYMBOL[checks.get(key)]} {label}" for key, label in CHECKS))
    print("  hidden:  " + _hidden_line(run.hidden_final))
    return 0 if run.passed else 1


def bench_command(args: argparse.Namespace) -> int:
    """Run the benchmark and print one line per run. A daily limit stops it cleanly, with exit code 0."""
    cases = load_cases(args.cases)
    if not cases:
        print(f"error: no cases match {args.cases!r}", file=sys.stderr)
        return 2
    models = [model.strip() for model in args.models.split(",") if model.strip()]
    results = run_bench(cases, models, args.trials, progress=_print_row)
    if results["stopped"]:
        print(f"daily limit reached for {results['stopped']['model']}; re-run after reset to resume")
    print(f"wrote {RESULTS_DIR / 'results.md'} and {RESULTS_DIR / 'results.json'}")
    return 0


def _print_row(row: Row) -> None:
    """Print one benchmark run on one line."""
    yes = {True: "pass", False: "fail"}
    print(f"{row.case} {row.model} trial {row.trial}: one-shot {yes[row.one_visible]}, "
          f"loop {yes[row.loop_visible]} in {row.attempts} attempt(s), hidden {yes[row.loop_hidden]}")


def _print_attempt(attempt: Attempt) -> None:
    """Print one attempt on one line, noting cache hits."""
    cached = " (cache hit)" if attempt.usage["cache_hit"] else ""
    print(f"attempt {attempt.number}: {attempt.stage}{cached}")


def _hidden_line(hidden: dict | None) -> str:
    """Summarise the hidden-test verdict for the final candidate."""
    if hidden is None:
        return "not run (no candidate)"
    return "PASS" if hidden["passed"] else f"FAIL [{hidden['stage']}]"


def _diff(buggy: list[str], final: list[str], colour: bool) -> str:
    """Return a unified diff from buggy to final, with + and - lines coloured on a terminal."""
    lines = []
    for line in difflib.unified_diff(buggy, final, "buggy", "final", lineterm=""):
        if colour and line[:1] in "+-" and not line.startswith(("+++", "---")):
            line = (GREEN if line[0] == "+" else RED) + line + RESET
        lines.append(line)
    return "\n".join(lines) if lines else "(no changes)"


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code. ``python -m verifyloop.cli`` calls this."""
    args = build_parser().parse_args(argv)
    colour = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if args.command == "fix":
        return fix_command(args, colour)
    if args.command == "bench":
        return bench_command(args)
    try:
        case = load_case(args.case)
    except (CaseError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    source = case.directory / case.reference if args.reference else args.source or case.directory / case.editable
    if not source.is_file():
        print(f"error: source file not found: {source}", file=sys.stderr)
        return 2
    result = verify_file(source, case, test="hidden" if args.hidden else "visible",
                         keep_workdir=args.keep_workdir)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render(result, case, args.hidden, colour))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
