"""Starter-case suite: every directory in bench/cases/ must meet the spec's guarantees.

The suite is parametrised over the case directories, so a new case is tested
without code changes. A case may have an entry in
tests/fixtures/naive_fixes/manifest.json, which records the exact stage the
naive fix reaches on the visible and hidden tests. Without an entry, the naive
check is skipped.

The NOTES.md check belongs to Phase 6, not here.
"""

import json
from pathlib import Path

import pytest

from verifyloop.case import load_case
from verifyloop.toolchain import verify_file

CASES_DIR = Path(__file__).resolve().parent.parent / "bench" / "cases"
NAIVE_DIR = Path(__file__).parent / "fixtures" / "naive_fixes"
MANIFEST = json.loads((NAIVE_DIR / "manifest.json").read_text(encoding="utf-8"))
CASE_DIRS = sorted(p for p in CASES_DIR.iterdir() if p.is_dir())


@pytest.fixture(params=CASE_DIRS, ids=lambda p: p.name)
def case(request):
    """Load one case directory. A malformed case fails here with a CaseError."""
    return load_case(request.param)


def test_buggy_fails_visible_test_at_expected_stage(case) -> None:
    result = verify_file(case.directory / case.editable, case)
    assert result.stage == case.expected_buggy_stage, result.output


def test_buggy_does_not_pass_hidden_test(case) -> None:
    result = verify_file(case.directory / case.editable, case, test="hidden")
    assert not result.passed, f"buggy version passed the hidden test: {result.output}"


def test_reference_fix_passes_visible_test(case) -> None:
    result = verify_file(case.directory / case.reference, case)
    assert result.stage == "ok", result.output


def test_reference_fix_passes_hidden_test(case) -> None:
    result = verify_file(case.directory / case.reference, case, test="hidden")
    assert result.stage == "ok", result.output


def test_naive_fix_fails_hidden_test_at_recorded_stage(case) -> None:
    if case.id not in MANIFEST:
        pytest.skip(f"no naive fix recorded for {case.id}; the naive check is optional")
    entry = MANIFEST[case.id]
    naive = NAIVE_DIR / entry["file"]
    visible = verify_file(naive, case)
    hidden = verify_file(naive, case, test="hidden")
    assert visible.stage == entry["visible"], visible.output
    assert hidden.stage == entry["hidden"], hidden.output
    assert not hidden.passed


def test_notes_file_exists_and_is_not_empty(case) -> None:
    notes = case.directory / "NOTES.md"
    assert notes.is_file(), f"write {notes.name} for {case.id}"
    assert notes.read_text(encoding="utf-8").strip(), f"{notes.name} for {case.id} is empty"


def test_volatile_variant_of_04_is_caught_by_tsan_on_visible_test() -> None:
    case = load_case(CASES_DIR / "04_data_race")
    result = verify_file(NAIVE_DIR / "04_data_race_volatile.c", case)
    assert result.stage == "sanitizer"
    assert result.sanitizer_summary.startswith("ThreadSanitizer: data race")
