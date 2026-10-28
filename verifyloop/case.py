"""Case loading and validation.

A case is a directory holding ``case.json`` and the source and test files it
names. This module reads and validates that metadata and returns a ``Case``.
It never runs a compiler and never writes to disk, so it is safe to call on
the read-only repo mount.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Shared test helpers (bench/common/check.h), resolved from the package location
# so the harness finds them wherever it is invoked from.
COMMON_INCLUDE_DIR = Path(__file__).resolve().parent.parent / "bench" / "common"

SANITIZERS = ("address", "undefined", "thread")
FAILURE_STAGES = ("compile_error", "sanitizer", "test_fail", "crash", "timeout")
REQUIRED_STRINGS = (
    "id", "kind", "title", "lang", "std", "editable", "reference",
    "test", "hidden_test", "expected_buggy_stage", "description",
)
# Immutable on purpose: a shared mutable default would leak between cases.
DEFAULT_EXTRA_FLAGS: tuple[str, ...] = ()
DEFAULT_RUNS = 1
DEFAULT_TIMEOUT_S = 10
ALL_FIELDS = frozenset(REQUIRED_STRINGS) | {"sanitizers", "extra_flags", "runs", "timeout_s"}
EXTENSION = {"c": ".c", "cpp": ".cpp"}
STD_PATTERN = {"c": r"(c|gnu)\d+x?", "cpp": r"(c\+\+|gnu\+\+)\d+"}


class CaseError(Exception):
    """Raised when a case directory is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Case:
    """A validated benchmark case.

    Attributes:
        id: Case identifier. Equal to the directory name.
        title: Short human-readable title.
        lang: ``"c"`` or ``"cpp"``. Selects ``CC`` or ``CXX``.
        std: Value passed to ``-std=``, for example ``c11`` or ``c++17``.
        editable: Filename of the editable source. The only file a fix may change.
        reference: Filename of the known-good fix.
        test: Filename of the visible test.
        hidden_test: Filename of the held-out test.
        sanitizers: Subset of ``address``, ``undefined``, ``thread``.
        extra_flags: Extra compile flags, appended to the compile command.
        runs: How many times the test binary runs. All runs must pass.
        timeout_s: Per-run timeout in seconds.
        expected_buggy_stage: Stage the buggy version must fail at.
        description: One-sentence bug summary for humans.
        directory: The case directory. The harness never writes to it.
    """

    id: str
    kind: str
    title: str
    lang: str
    std: str
    editable: str
    reference: str
    test: str
    hidden_test: str
    sanitizers: tuple[str, ...]
    extra_flags: tuple[str, ...]
    runs: int
    timeout_s: float
    expected_buggy_stage: str
    description: str
    directory: Path

    @property
    def header(self) -> str:
        """Filename of the declarations header: ``lib.hpp`` for C++, else ``lib.h``."""
        return "lib.hpp" if self.lang == "cpp" else "lib.h"


def load_case(directory: str | Path) -> Case:
    """Load and validate the case stored in ``directory``.

    Args:
        directory: Path to a case directory containing ``case.json``.

    Returns:
        The validated ``Case``, with optional fields filled from defaults.

    Raises:
        CaseError: If ``case.json`` is missing, is not valid JSON, has a
            missing, unknown or mistyped field, or breaks a validation rule.
    """
    path = Path(directory)
    meta_path = path / "case.json"
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseError(f"{meta_path}: case.json not found") from exc
    except json.JSONDecodeError as exc:
        raise CaseError(f"{meta_path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CaseError(f"{meta_path}: top level must be a JSON object")

    _check_fields(raw, meta_path)
    case = Case(
        id=raw["id"], kind=raw["kind"], title=raw["title"], lang=raw["lang"], std=raw["std"],
        editable=raw["editable"], reference=raw["reference"], test=raw["test"],
        hidden_test=raw["hidden_test"], sanitizers=tuple(raw["sanitizers"]),
        extra_flags=tuple(raw.get("extra_flags", DEFAULT_EXTRA_FLAGS)),
        runs=raw.get("runs", DEFAULT_RUNS), timeout_s=raw.get("timeout_s", DEFAULT_TIMEOUT_S),
        expected_buggy_stage=raw["expected_buggy_stage"], description=raw["description"],
        directory=path,
    )
    _validate(case, meta_path)
    return case


def _check_fields(raw: dict[str, Any], source: Path) -> None:
    """Check that required fields are present, unknown fields are absent, and types match."""
    missing = [key for key in REQUIRED_STRINGS + ("sanitizers",) if key not in raw]
    if missing:
        raise CaseError(f"{source}: missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(raw) - ALL_FIELDS)
    if unknown:
        raise CaseError(f"{source}: unknown field(s): {', '.join(unknown)}")
    for key in REQUIRED_STRINGS:
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise CaseError(f"{source}: '{key}' must be a non-empty string")
    if not _is_str_list(raw["sanitizers"]):
        raise CaseError(f"{source}: 'sanitizers' must be a list of strings")
    if "extra_flags" in raw and not _is_str_list(raw["extra_flags"]):
        raise CaseError(f"{source}: 'extra_flags' must be a list of strings")
    # bool is a subclass of int in Python, so exclude it explicitly.
    if "runs" in raw and (isinstance(raw["runs"], bool) or not isinstance(raw["runs"], int)):
        raise CaseError(f"{source}: 'runs' must be an integer")
    if "timeout_s" in raw and (
        isinstance(raw["timeout_s"], bool) or not isinstance(raw["timeout_s"], (int, float))
    ):
        raise CaseError(f"{source}: 'timeout_s' must be a number")


def _validate(case: Case, source: Path) -> None:
    """Apply the cross-field validation rules to a type-checked ``Case``."""
    if case.id != case.directory.name:
        raise CaseError(f"{source}: id '{case.id}' does not match directory name '{case.directory.name}'")
    if case.kind != "single_file":
        raise CaseError(f"{source}: case kind '{case.kind}' is not supported yet")
    if case.lang not in EXTENSION:
        raise CaseError(f"{source}: 'lang' must be 'c' or 'cpp', got '{case.lang}'")
    if not re.fullmatch(STD_PATTERN[case.lang], case.std):
        raise CaseError(f"{source}: 'std' '{case.std}' does not match lang '{case.lang}'")

    if not case.sanitizers:
        raise CaseError(f"{source}: 'sanitizers' must not be empty")
    unknown = [s for s in case.sanitizers if s not in SANITIZERS]
    if unknown:
        raise CaseError(f"{source}: unknown sanitizer(s): {', '.join(unknown)}")
    if len(set(case.sanitizers)) != len(case.sanitizers):
        raise CaseError(f"{source}: 'sanitizers' contains duplicates")
    if "thread" in case.sanitizers and "address" in case.sanitizers:
        raise CaseError(f"{source}: 'thread' cannot be combined with 'address' (clang rejects it)")

    if case.expected_buggy_stage not in FAILURE_STAGES:
        raise CaseError(
            f"{source}: 'expected_buggy_stage' must be one of {', '.join(FAILURE_STAGES)}, "
            f"got '{case.expected_buggy_stage}'"
        )
    if case.runs < 1:
        raise CaseError(f"{source}: 'runs' must be at least 1")
    if case.timeout_s <= 0:
        raise CaseError(f"{source}: 'timeout_s' must be positive")

    for key in ("editable", "reference", "test", "hidden_test"):
        name = getattr(case, key)
        if Path(name).name != name:
            raise CaseError(f"{source}: '{key}' must be a bare filename, got '{name}'")
        if not name.endswith(EXTENSION[case.lang]):
            raise CaseError(f"{source}: '{key}' must end in '{EXTENSION[case.lang]}' for lang '{case.lang}'")
    for name in (case.editable, case.reference, case.test, case.hidden_test, case.header):
        if not (case.directory / name).is_file():
            raise CaseError(f"{case.directory}: referenced file '{name}' does not exist")


def _is_str_list(value: Any) -> bool:
    """Return True if ``value`` is a list whose items are all strings."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
