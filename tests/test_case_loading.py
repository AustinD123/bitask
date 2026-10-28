"""Tests for case loading and validation (verifyloop/case.py).

Each negative test copies the mini fixture into a temporary directory, breaks
one thing in it, and checks that load_case() raises CaseError with a message
naming the problem. Nothing is written to the repo.
"""

import json
import shutil
from pathlib import Path

import pytest

from verifyloop.case import CaseError, load_case

FIXTURE = Path(__file__).parent / "fixtures" / "mini_case"
REQUIRED = [
    "id", "kind", "title", "lang", "std", "editable", "reference",
    "test", "hidden_test", "sanitizers", "expected_buggy_stage", "description",
]


@pytest.fixture
def case_dir(tmp_path: Path) -> Path:
    """Return a writable copy of the mini case, named so its id matches the directory."""
    target = tmp_path / "mini_case"
    shutil.copytree(FIXTURE, target)
    return target


def read_meta(case_dir: Path) -> dict:
    """Return the parsed case.json in ``case_dir``."""
    return json.loads((case_dir / "case.json").read_text(encoding="utf-8"))


def write_meta(case_dir: Path, meta: dict) -> None:
    """Overwrite case.json in ``case_dir`` with ``meta``."""
    (case_dir / "case.json").write_text(json.dumps(meta), encoding="utf-8")


def test_fixture_loads() -> None:
    case = load_case(FIXTURE)
    assert case.id == "mini_case"
    assert case.sanitizers == ("address", "undefined")
    assert case.header == "lib.h"
    assert case.directory == FIXTURE


def test_defaults_applied_when_optional_fields_absent(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    del meta["timeout_s"]  # present in the fixture; removed here to test the default
    write_meta(case_dir, meta)
    case = load_case(case_dir)
    assert case.extra_flags == ()
    assert case.runs == 1
    assert case.timeout_s == 10


def test_explicit_optional_fields_are_kept(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta.update(extra_flags=["-pthread"], runs=5, timeout_s=20)
    write_meta(case_dir, meta)
    case = load_case(case_dir)
    assert case.extra_flags == ("-pthread",)
    assert case.runs == 5
    assert case.timeout_s == 20


def test_cpp_case_uses_hpp_header(case_dir: Path) -> None:
    for old, new in [
        ("buggy.c", "buggy.cpp"), ("reference_fix.c", "reference_fix.cpp"),
        ("test.c", "test.cpp"), ("hidden_test.c", "hidden_test.cpp"), ("lib.h", "lib.hpp"),
    ]:
        (case_dir / old).rename(case_dir / new)
    meta = read_meta(case_dir)
    meta.update(
        lang="cpp", std="c++17", editable="buggy.cpp", reference="reference_fix.cpp",
        test="test.cpp", hidden_test="hidden_test.cpp",
    )
    write_meta(case_dir, meta)
    case = load_case(case_dir)
    assert case.header == "lib.hpp"


@pytest.mark.parametrize("field", REQUIRED)
def test_missing_required_field(case_dir: Path, field: str) -> None:
    meta = read_meta(case_dir)
    del meta[field]
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match=f"missing required field.*{field}"):
        load_case(case_dir)


def test_unknown_field_is_rejected(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["timout_s"] = 3  # typo for timeout_s
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="unknown field.*timout_s"):
        load_case(case_dir)


def test_id_must_match_directory_name(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["id"] = "other_case"
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="does not match directory name"):
        load_case(case_dir)


@pytest.mark.parametrize("filename", ["buggy.c", "reference_fix.c", "test.c", "hidden_test.c", "lib.h"])
def test_referenced_file_must_exist(case_dir: Path, filename: str) -> None:
    (case_dir / filename).unlink()
    with pytest.raises(CaseError, match=f"'{filename}' does not exist"):
        load_case(case_dir)


def test_address_with_thread_is_rejected(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["sanitizers"] = ["address", "thread"]
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="'thread' cannot be combined with 'address'"):
        load_case(case_dir)


@pytest.mark.parametrize("stage", ["ok", "harness_error", "not_a_stage"])
def test_expected_buggy_stage_must_be_a_failure_stage(case_dir: Path, stage: str) -> None:
    meta = read_meta(case_dir)
    meta["expected_buggy_stage"] = stage
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="'expected_buggy_stage' must be one of"):
        load_case(case_dir)


def test_empty_sanitizers_rejected(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["sanitizers"] = []
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="must not be empty"):
        load_case(case_dir)


def test_unknown_sanitizer_rejected(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["sanitizers"] = ["memory"]  # MSan is out of scope
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="unknown sanitizer.*memory"):
        load_case(case_dir)


def test_duplicate_sanitizer_rejected(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["sanitizers"] = ["address", "address"]
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="duplicates"):
        load_case(case_dir)


def test_std_must_match_lang(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["std"] = "c++17"  # lang is still "c"
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="does not match lang 'c'"):
        load_case(case_dir)


def test_source_extension_must_match_lang(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["editable"] = "buggy.cpp"  # lang is still "c"
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="must end in '.c'"):
        load_case(case_dir)


def test_filename_must_be_bare(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["test"] = "../test.c"
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="must be a bare filename"):
        load_case(case_dir)


@pytest.mark.parametrize("value", ["3", True, 2.5])
def test_runs_must_be_an_integer(case_dir: Path, value: object) -> None:
    meta = read_meta(case_dir)
    meta["runs"] = value
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="'runs' must be an integer"):
        load_case(case_dir)


def test_runs_must_be_at_least_one(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["runs"] = 0
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="at least 1"):
        load_case(case_dir)


@pytest.mark.parametrize("value", ["2", True])
def test_timeout_must_be_a_number(case_dir: Path, value: object) -> None:
    meta = read_meta(case_dir)
    meta["timeout_s"] = value
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="'timeout_s' must be a number"):
        load_case(case_dir)


def test_sanitizers_must_be_a_list_of_strings(case_dir: Path) -> None:
    meta = read_meta(case_dir)
    meta["sanitizers"] = "address"
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match="must be a list of strings"):
        load_case(case_dir)


def test_invalid_json_is_a_case_error(case_dir: Path) -> None:
    (case_dir / "case.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CaseError, match="invalid JSON"):
        load_case(case_dir)


def test_missing_case_json_is_a_case_error(case_dir: Path) -> None:
    (case_dir / "case.json").unlink()
    with pytest.raises(CaseError, match="case.json not found"):
        load_case(case_dir)


def test_top_level_must_be_an_object(case_dir: Path) -> None:
    (case_dir / "case.json").write_text("[]", encoding="utf-8")
    with pytest.raises(CaseError, match="top level must be a JSON object"):
        load_case(case_dir)


@pytest.mark.parametrize("kind", ["project", "single-file"])
def test_unsupported_case_kind_is_rejected(case_dir: Path, kind: str) -> None:
    meta = read_meta(case_dir)
    meta["kind"] = kind
    write_meta(case_dir, meta)
    with pytest.raises(CaseError, match=f"case kind '{kind}' is not supported yet"):
        load_case(case_dir)


def test_single_file_kind_loads(case_dir: Path) -> None:
    assert load_case(case_dir).kind == "single_file"
