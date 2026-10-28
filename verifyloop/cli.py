"""Command-line interface: ``python -m verifyloop.cli verify --case DIR [options]``.

The human output is for people: a verdict, the sanitizer summary (the line a
reader needs first), the checks, then the cleaned output. ``--json`` prints
VerifyResult.to_dict() for machines. Exit codes: 0 passed, 1 candidate failed,
2 harness error or invalid case.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from verifyloop.case import Case, CaseError, load_case
from verifyloop.toolchain import VerifyResult, verify_file

CHECKS = (("compiled", "compiled"), ("sanitizers_clean", "sanitizers clean"),
          ("ran_to_completion", "ran to completion"), ("tests_passed", "tests passed"))
SYMBOL = {True: "✓", False: "✗", None: "–"}
RED, GREEN, BOLD, RESET = "\x1b[31m", "\x1b[32m", "\x1b[1m", "\x1b[0m"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser. Only the ``verify`` subcommand exists for now."""
    parser = argparse.ArgumentParser(prog="python -m verifyloop.cli")
    verify = parser.add_subparsers(dest="command", required=True).add_parser("verify", help="verify a candidate")
    verify.add_argument("--case", required=True, type=Path, help="case directory")
    source = verify.add_mutually_exclusive_group()
    source.add_argument("--source", type=Path, help="candidate file (default: the case's editable file)")
    source.add_argument("--reference", action="store_true", help="use the case's reference fix")
    verify.add_argument("--hidden", action="store_true", help="run the hidden test instead of the visible one")
    verify.add_argument("--json", action="store_true", help="print the result as JSON")
    verify.add_argument("--keep-workdir", action="store_true", help="keep the workdir and print its path")
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


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code. ``python -m verifyloop.cli`` calls this."""
    args = build_parser().parse_args(argv)
    try:
        case = load_case(args.case)
    except CaseError as error:
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
        print(render(result, case, args.hidden, sys.stdout.isatty() and "NO_COLOR" not in os.environ))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
