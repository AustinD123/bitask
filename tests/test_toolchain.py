"""Tests for verifyloop/toolchain.py.

Most tests compile and run real candidates against the mini case, so they
exercise the actual clang, sanitizer and process code. Tests that need a
different test file or sanitizer set copy the mini case into tmp_path and
change it there. The real fixture is only read, never written.

The classifier and the cleaning rules are tested with fixed strings, so
they do not need a compiler at all.
"""

import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from verifyloop import toolchain
from verifyloop.case import COMMON_INCLUDE_DIR, Case, load_case
from verifyloop.toolchain import (
    OUTPUT_CAP,
    VerifyResult,
    classify_run,
    clean_output,
    verify,
    verify_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_case"
MINI = load_case(FIXTURE)

# ---- candidate sources ------------------------------------------------------

GOOD = '#include "lib.h"\nint add(int a, int b) { return a + b; }\n'
SUB = '#include "lib.h"\nint add(int a, int b) { return a - b; }\n'
SYNTAX = '#include "lib.h"\nint add(int a, int b) { return a + b }\n'
UNUSED = '#include "lib.h"\nint add(int a, int b) { int n = 0; return a + b; }\n'
RENAMED = '#include "lib.h"\nint add_renamed(int a, int b) { return a + b; }\n'
EXIT0 = '#include <stdlib.h>\n#include "lib.h"\nint add(int a, int b) { exit(0); return a + b; }\n'
LOOP = '#include <unistd.h>\n#include "lib.h"\nint add(int a, int b) { for (;;) sleep(1); return a + b; }\n'
ABORT = '#include <stdlib.h>\n#include "lib.h"\nint add(int a, int b) { abort(); return a + b; }\n'
BAD_BYTE = (
    '#include <stdio.h>\n#include "lib.h"\n'
    "int add(int a, int b) { fputc(0xff, stdout); fputc('\\n', stdout); return a + b; }\n"
)
# The buffer is kept in an external-linkage global, so the optimiser cannot
# delete the malloc or the store. The out-of-bounds read flows into the return value.
WRITE_PAST = """#include <stdlib.h>
#include "lib.h"

int *last_buf;

int add(int a, int b) {
    last_buf = malloc(sizeof(int));
    last_buf[1] = a;  /* BUG: writes past the 4-byte allocation */
    int r = last_buf[1] + b;
    free(last_buf);
    return r;
}
"""
# The pointer escapes into a function defined in the test file (LEAK_TEST).
# That keeps the optimiser from deleting the malloc, and the block is never freed.
LEAK = """#include <stdlib.h>
#include "lib.h"

void sink_ptr(void *p);  /* defined in the test file */

int add(int a, int b) {
    void *p = malloc(16);  /* BUG: never freed */
    sink_ptr(p);
    return a + b;
}
"""
LEAK_TEST = """#include "lib.h"
#include "check.h"

void sink_ptr(void *p) { (void)p; }

int main(void) {
    CHECK_EQ(add(2, 3), 5);
    verify_tests_passed();
    return 0;
}
"""
FLIP_ON_SECOND_RUN = """#include <stdio.h>
#include "lib.h"

/* The first run creates a marker file in the workdir; the second run sees it and fails. */
int add(int a, int b) {
    FILE *f = fopen("seen", "r");
    if (f) { fclose(f); return a - b; }
    f = fopen("seen", "w");
    if (f) fclose(f);
    return a + b;
}
"""
FORK_AND_HANG = """#define _POSIX_C_SOURCE 200809L  /* fork() is hidden under strict -std=c11 without this */
#include <stdio.h>
#include <unistd.h>
#include "lib.h"

int add(int a, int b) {
    pid_t child = fork();
    if (child == 0) { sleep(100); _exit(0); }
    FILE *f = fopen("child.pid", "w");
    if (f) { fprintf(f, "%d\\n", (int)child); fclose(f); }
    for (;;) sleep(1);
    return a + b;
}
"""
RACE = """#include <pthread.h>
#include "lib.h"

static long counter;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < 1000; i++) counter++;  /* BUG: unsynchronised */
    return NULL;
}

int add(int a, int b) {
    pthread_t t1, t2;
    pthread_create(&t1, NULL, worker, NULL);
    pthread_create(&t2, NULL, worker, NULL);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return a + b + (int)counter;  /* the counter reaches the test */
}
"""
BIG_OK = """#include <stdio.h>
#include "lib.h"

int add(int a, int b) {
    static const char line[] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\\n";
    for (int i = 0; i < 80000; i++) fwrite(line, 1, sizeof line - 1, stdout);  /* about 5 MB */
    return a + b;
}
"""
SPAM = """#include <stdio.h>
#include "lib.h"

int add(int a, int b) {
    for (;;) fputs("spam spam spam spam spam spam spam spam\\n", stdout);
    return a + b;
}
"""
# Test file that overflows int. The candidate is plain a + b, so UBSan is the
# only thing that can stop the run.
OVERFLOW_TEST = """#include <limits.h>
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(add(INT_MAX, 1), INT_MIN);  /* signed overflow: UBSan must stop the run */
    verify_tests_passed();
    return 0;
}
"""
SIGNED_ADD = '#include "lib.h"\nint add(int a, int b) { return a + b; }\n'


# ---- helpers ----------------------------------------------------------------


def make_case(tmp_path: Path, *, test_src: str | None = None, **changes) -> Case:
    """Copy the mini case into ``tmp_path``, optionally replace its test, and apply ``changes``."""
    dst = tmp_path / "mini_case"
    shutil.copytree(FIXTURE, dst)
    if test_src is not None:
        (dst / "test.c").write_text(test_src, encoding="utf-8")
    return dataclasses.replace(load_case(dst), **changes)


def tree_digest(directory: Path) -> dict[str, str]:
    """Map every file under ``directory`` to its SHA-256, for read-only checks."""
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*")) if p.is_file()
    }


def process_alive(pid: int) -> bool:
    """Return True if ``pid`` is running. A zombie counts as not running."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] not in ("Z", "X")


# ---- real compile and run ---------------------------------------------------


def test_correct_candidate_passes() -> None:
    result = verify(GOOD, MINI)
    assert result.passed and result.stage == "ok"
    assert result.checks == {
        "compiled": True, "ran_to_completion": True, "sanitizers_clean": True, "tests_passed": True,
    }
    assert result.output == ""
    assert result.runs_completed == 1 and result.failing_run is None
    assert "VERIFY_OK" in result.raw_stdout
    assert result.duration_s > 0


def test_syntax_error_is_compile_error() -> None:
    result = verify(SYNTAX, MINI)
    assert result.stage == "compile_error"
    assert "buggy.c:" in result.output and "error:" in result.output
    assert result.checks == {
        "compiled": False, "ran_to_completion": None, "sanitizers_clean": None, "tests_passed": None,
    }


def test_unused_variable_is_compile_error_under_werror() -> None:
    result = verify(UNUSED, MINI)
    assert result.stage == "compile_error"
    assert "unused variable" in result.output


def test_link_error_when_function_is_renamed() -> None:
    result = verify(RENAMED, MINI)
    assert result.stage == "compile_error"
    assert "undefined reference" in result.output
    assert result.compile_cmd[-1] == "test_bin"  # the link step failed


def test_wrong_result_is_test_fail_with_clean_sanitizers() -> None:
    result = verify(SUB, MINI)
    assert result.stage == "test_fail"
    assert "CHECK_EQ FAILED" in result.output
    assert result.checks == {
        "compiled": True, "ran_to_completion": True, "sanitizers_clean": True, "tests_passed": False,
    }


def test_exit_zero_without_marker_is_test_fail() -> None:
    result = verify(EXIT0, MINI)
    assert result.stage == "test_fail"
    assert "completion marker" in result.output


def test_infinite_loop_is_timeout() -> None:
    start = time.monotonic()
    result = verify(LOOP, MINI)
    assert result.stage == "timeout"
    assert time.monotonic() - start < MINI.timeout_s + 3
    assert result.output == "timed out after 2s (run 1 of 1)"
    assert result.checks["ran_to_completion"] is False


def test_abort_is_crash_naming_the_signal() -> None:
    result = verify(ABORT, MINI)
    assert result.stage == "crash"
    assert "SIGABRT" in result.output
    assert result.exit_code == -6


def test_write_past_malloc_reports_heap_buffer_overflow() -> None:
    result = verify(WRITE_PAST, MINI)
    assert result.stage == "sanitizer"
    assert result.sanitizer_summary.startswith("AddressSanitizer: heap-buffer-overflow")
    assert "heap-buffer-overflow" in result.output


def test_signed_overflow_is_stopped_by_no_recover(tmp_path: Path) -> None:
    case = make_case(tmp_path, test_src=OVERFLOW_TEST)
    result = verify(SIGNED_ADD, case)
    assert result.stage == "sanitizer"
    assert "signed integer overflow" in result.sanitizer_summary
    # Without -fno-sanitize-recover=all, UBSan would report and carry on, and the test would print the marker.
    assert "VERIFY_OK" not in result.raw_stdout


def test_leak_summary_names_lsan(tmp_path: Path) -> None:
    result = verify(LEAK, make_case(tmp_path, test_src=LEAK_TEST))
    assert result.stage == "sanitizer"
    assert result.sanitizer_summary.startswith("LeakSanitizer: ")
    assert "leaked" in result.sanitizer_summary


def test_runs_stop_at_first_failure(tmp_path: Path) -> None:
    case = make_case(tmp_path, runs=3)
    result = verify(FLIP_ON_SECOND_RUN, case)
    assert result.stage == "test_fail"
    assert result.failing_run == 2
    assert result.runs_completed == 1


def test_all_runs_passing_counts_every_run(tmp_path: Path) -> None:
    case = make_case(tmp_path, runs=3)
    result = verify(GOOD, case)
    assert result.stage == "ok" and result.runs_completed == 3


def test_invalid_utf8_from_candidate_is_replaced_not_raised() -> None:
    result = verify(BAD_BYTE, MINI)
    assert result.stage == "ok"
    assert "�" in result.raw_stdout


def test_large_output_is_capped_and_marker_survives() -> None:
    result = verify(BIG_OK, MINI)
    assert result.stage == "ok"  # the marker is printed last, so it is in the kept tail
    assert "stream truncated" in result.raw_stdout
    assert len(result.raw_stdout) <= OUTPUT_CAP + 200


def test_infinite_printer_stays_bounded() -> None:
    case = dataclasses.replace(MINI, timeout_s=2)
    result = verify(SPAM, case)
    assert result.stage == "timeout"
    assert len(result.raw_stdout) <= OUTPUT_CAP + 200


def test_timed_out_child_process_is_killed(tmp_path: Path) -> None:
    case = dataclasses.replace(MINI, timeout_s=1)
    result = verify(FORK_AND_HANG, case, keep_workdir=True)
    try:
        assert result.stage == "timeout"
        child = int((Path(result.workdir) / "child.pid").read_text().strip())
        assert not process_alive(child)
    finally:
        shutil.rmtree(result.workdir, ignore_errors=True)


def test_deterministic_output_for_asan() -> None:
    first = verify(WRITE_PAST, MINI)
    second = verify(WRITE_PAST, MINI)
    assert first.output == second.output
    assert "verify-" not in first.output  # no workdir path
    assert not re.search(r"0x[0-9a-f]{6,}", first.output)


def test_deterministic_output_for_tsan(tmp_path: Path) -> None:
    case = make_case(tmp_path, sanitizers=("thread",), extra_flags=("-pthread",), timeout_s=20)
    first = verify(RACE, case)
    second = verify(RACE, case)
    assert first.stage == "sanitizer" and second.stage == "sanitizer"
    assert first.output == second.output
    assert "pid=PID" in first.output and "tid=TID" in first.output
    assert not re.search(r"\b(pid|tid)=\d", first.output)


# ---- files and paths --------------------------------------------------------


def test_case_directory_is_never_written() -> None:
    before = tree_digest(FIXTURE)
    for source in (GOOD, SUB, SYNTAX, WRITE_PAST):
        verify(source, MINI)
    assert tree_digest(FIXTURE) == before


def test_keep_workdir_keeps_the_directory() -> None:
    result = verify(GOOD, MINI, keep_workdir=True)
    try:
        assert result.workdir is not None and Path(result.workdir).is_dir()
    finally:
        shutil.rmtree(result.workdir, ignore_errors=True)


def test_default_removes_the_workdir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    result = verify(GOOD, MINI)
    assert result.workdir is None
    assert list(tmp_path.iterdir()) == []


def test_verify_file_matches_verify(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.c"
    candidate.write_text(SUB, encoding="utf-8")
    from_file = verify_file(candidate, MINI)
    from_text = verify(SUB, MINI)
    assert from_file.stage == from_text.stage == "test_fail"
    assert from_file.output == from_text.output


def test_garbage_source_does_not_raise() -> None:
    result = verify("\x00\x01 not C at all \xff\n", MINI)
    assert result.stage == "compile_error"


def test_result_round_trips_through_json() -> None:
    data = verify(SUB, MINI).to_dict()
    assert json.loads(json.dumps(data)) == data


# ---- compile steps and flags ------------------------------------------------


def test_broken_test_file_is_harness_error(tmp_path: Path) -> None:
    case = make_case(tmp_path, test_src='#include "lib.h"\nint main(void) { return add(2 3); }\n')
    result = verify(GOOD, case)
    assert result.stage == "harness_error"
    assert "test file failed to compile, this is a case bug" in result.output
    assert result.checks["compiled"] is None


def test_missing_compiler_is_harness_error(monkeypatch) -> None:
    monkeypatch.setenv("CC", "/nonexistent/clang")
    result = verify(GOOD, MINI)
    assert result.stage == "harness_error"
    assert "compiler not found: /nonexistent/clang" in result.output


def test_compiler_falls_back_to_clang(monkeypatch) -> None:
    monkeypatch.delenv("CC", raising=False)
    monkeypatch.delenv("CXX", raising=False)
    assert toolchain._compiler_for(MINI) == "clang"
    assert toolchain._compiler_for(dataclasses.replace(MINI, lang="cpp")) == "clang++"


def test_compiler_comes_from_cc_and_cxx(monkeypatch) -> None:
    monkeypatch.setenv("CC", "clang-18")
    monkeypatch.setenv("CXX", "clang++-18")
    assert toolchain._compiler_for(MINI) == "clang-18"
    assert toolchain._compiler_for(dataclasses.replace(MINI, lang="cpp")) == "clang++-18"


def test_exact_compile_flags_for_mini_case() -> None:
    flags = toolchain._compile_flags(MINI, Path("/w"))
    assert flags == [
        "-std=c11", "-g", "-O1", "-fno-omit-frame-pointer",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-Wall", "-Werror",
        "-fno-sanitize=object-size",
        "-I", "/w", "-I", str(COMMON_INCLUDE_DIR),
    ]


@pytest.mark.parametrize(
    ("sanitizers", "expect_object_size_off"),
    [(("address", "undefined"), True), (("address",), False), (("undefined",), False), (("thread",), False)],
)
def test_object_size_check_is_disabled_only_with_address_and_undefined(
    sanitizers: tuple[str, ...], expect_object_size_off: bool,
) -> None:
    case = dataclasses.replace(MINI, sanitizers=sanitizers)
    flags = toolchain._compile_flags(case, Path("/w"))
    assert ("-fno-sanitize=object-size" in flags) is expect_object_size_off
    assert "-fno-sanitize-recover=all" in flags


def test_all_three_compile_steps_share_the_same_flags(monkeypatch) -> None:
    calls: list[list[str]] = []
    real = toolchain._run_compiler

    def spy(cmd, cwd):
        calls.append(cmd)
        return real(cmd, cwd)

    monkeypatch.setattr(toolchain, "_run_compiler", spy)
    assert verify(GOOD, MINI).stage == "ok"
    assert len(calls) == 3
    for cmd in calls:
        workdir = Path(cmd[cmd.index("-I") + 1])
        flags = toolchain._compile_flags(MINI, workdir)
        start = cmd.index("-std=c11")
        assert cmd[start:start + len(flags)] == flags


def test_compile_timeout_in_candidate_is_compile_error(monkeypatch) -> None:
    real = toolchain._run_compiler

    def fake(cmd, cwd):
        if "-c" in cmd and cmd[cmd.index("-c") + 1] == "buggy.c":
            raise subprocess.TimeoutExpired(cmd, toolchain.COMPILE_TIMEOUT_S)
        return real(cmd, cwd)

    monkeypatch.setattr(toolchain, "_run_compiler", fake)
    result = verify(GOOD, MINI)
    assert result.stage == "compile_error"
    assert "compile timed out after 60s" in result.output


def test_compile_timeout_in_test_file_is_harness_error(monkeypatch) -> None:
    real = toolchain._run_compiler

    def fake(cmd, cwd):
        if "-c" in cmd and cmd[cmd.index("-c") + 1] == "test.c":
            raise subprocess.TimeoutExpired(cmd, toolchain.COMPILE_TIMEOUT_S)
        return real(cmd, cwd)

    monkeypatch.setattr(toolchain, "_run_compiler", fake)
    result = verify(GOOD, MINI)
    assert result.stage == "harness_error"
    assert "case bug" in result.output


# ---- TSan preflight ---------------------------------------------------------


def test_tsan_preflight_blocks_before_compiling(monkeypatch, tmp_path: Path) -> None:
    case = make_case(tmp_path, sanitizers=("thread",), extra_flags=("-pthread",))
    monkeypatch.setattr(toolchain, "_read_mmap_rnd_bits", lambda: 32)

    def must_not_compile(cmd, cwd):
        raise AssertionError("preflight must stop before any compile")

    monkeypatch.setattr(toolchain, "_run_compiler", must_not_compile)
    result = verify(GOOD, case)
    assert result.stage == "harness_error"
    assert "TSan needs vm.mmap_rnd_bits <= 28; run scripts/fix-aslr.sh (or .ps1)" in result.output
    assert result.compile_cmd == []
    assert result.checks["compiled"] is None


def test_tsan_preflight_allows_28(monkeypatch, tmp_path: Path) -> None:
    case = make_case(tmp_path, sanitizers=("thread",), extra_flags=("-pthread",))
    monkeypatch.setattr(toolchain, "_read_mmap_rnd_bits", lambda: 28)
    compiled = []
    real = toolchain._run_compiler
    monkeypatch.setattr(toolchain, "_run_compiler", lambda cmd, cwd: compiled.append(cmd) or real(cmd, cwd))
    verify(GOOD, case)
    assert compiled, "preflight must let a 28-bit kernel through to the compiler"


def test_tsan_preflight_is_skipped_when_value_is_unreadable(monkeypatch, tmp_path: Path) -> None:
    case = make_case(tmp_path, sanitizers=("thread",), extra_flags=("-pthread",))

    def unreadable():
        raise OSError("no /proc here")

    monkeypatch.setattr(toolchain, "_read_mmap_rnd_bits", unreadable)
    compiled = []
    real = toolchain._run_compiler
    monkeypatch.setattr(toolchain, "_run_compiler", lambda cmd, cwd: compiled.append(cmd) or real(cmd, cwd))
    result = verify(GOOD, case)
    assert compiled, "an unreadable value must skip the preflight, not block the run"
    assert "TSan needs" not in result.output


def test_tsan_preflight_only_applies_to_thread_cases(monkeypatch) -> None:
    monkeypatch.setattr(toolchain, "_read_mmap_rnd_bits", lambda: 32)
    result = verify(GOOD, MINI)  # address,undefined: the preflight must not run
    assert result.stage == "ok"


# ---- classifier: pure, fixed strings ---------------------------------------

NONCE = "abc"


@pytest.mark.parametrize(
    ("stdout", "stderr", "code", "timed_out", "stage"),
    [
        ("", "", 0, True, "timeout"),
        ("", "ThreadSanitizer: CHECK failed: tsan_platform_linux.cpp:282 personality\n", 139, False, "harness_error"),
        ("", "FATAL: ThreadSanitizer: unexpected memory mapping 0x7f\n", 1, False, "harness_error"),
        ("", "AddressSanitizer: CHECK failed: asan_x.cpp:1\n", 1, False, "harness_error"),
        ("", "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address\n", 1, False, "sanitizer"),
        ("", "==1==ERROR: LeakSanitizer: detected memory leaks\n", 1, False, "sanitizer"),
        ("", "WARNING: ThreadSanitizer: data race (pid=23)\n", 66, False, "sanitizer"),
        ("", "buggy.c:8:19: runtime error: signed integer overflow\n", 1, False, "sanitizer"),
        ("", "==1==ERROR: AddressSanitizer: SEGV on unknown address\n", -11, False, "sanitizer"),
        ("", "CHECK FAILED: x at test.c:3\n", 1, False, "test_fail"),
        ("", "CHECK_EQ FAILED: add(2, 3) == 5 (got -1, expected 5)\n", 1, False, "test_fail"),
        ("", "CHECK_STREQ FAILED: a == b\n", 1, False, "test_fail"),
        ("", "", 3, False, "test_fail"),
        ("", "", -6, False, "crash"),
        ("", "", 0, False, "test_fail"),
        ("VERIFY_OK wrong\n", "", 0, False, "test_fail"),
        (f"VERIFY_OK {NONCE}\n", "", 0, False, "ok"),
    ],
)
def test_classify_run_rules(stdout, stderr, code, timed_out, stage) -> None:
    assert classify_run(stdout, stderr, code, timed_out, NONCE)[0] == stage


@pytest.mark.parametrize(
    ("stderr", "code", "stage"),
    [
        ("ERROR: AddressSanitizer: x\nCHECK_EQ FAILED: y\n", 1, "sanitizer"),  # sanitizer beats test_fail
        ("ERROR: AddressSanitizer: x\n", 0, "sanitizer"),  # sanitizer beats exit code
        ("ThreadSanitizer: CHECK failed\nWARNING: ThreadSanitizer: data race\n", 66, "harness_error"),
    ],
)
def test_classifier_precedence(stderr, code, stage) -> None:
    assert classify_run("", stderr, code, False, NONCE)[0] == stage


def test_timeout_beats_everything() -> None:
    stage, _ = classify_run("", "ERROR: AddressSanitizer: x\n", -9, True, NONCE)
    assert stage == "timeout"


def test_tsan_startup_segfault_is_harness_error_not_crash() -> None:
    stage, message = classify_run(
        "", "ThreadSanitizer: CHECK failed: tsan_platform_linux.cpp:282 personality\n", -11, False, NONCE,
    )
    assert stage == "harness_error"
    assert "sanitizer internal failure" in message


@pytest.mark.parametrize(("code", "name"), [(-6, "SIGABRT"), (-11, "SIGSEGV"), (-999, "signal 999")])
def test_crash_message_names_the_signal(code: int, name: str) -> None:
    assert classify_run("", "", code, False, NONCE) == ("crash", f"killed by {name}")


# ---- cleaning: fixed strings ------------------------------------------------


def test_ansi_codes_are_stripped() -> None:
    assert clean_output("\x1b[31mred\x1b[0m", None) == "red"


def test_workdir_is_removed_with_its_trailing_separator() -> None:
    text = "/tmp/verify-abc/buggy.c:12:5: error: bad\n/tmp/verify-abc/lib.h:1:1: note: here"
    assert clean_output(text, Path("/tmp/verify-abc")) == "buggy.c:12:5: error: bad\nlib.h:1:1: note: here"


def test_hex_addresses_of_six_or_more_digits_are_masked() -> None:
    assert clean_output("at 0x502000000018 and 0x2a1c9", None) == "at 0xADDR and 0x2a1c9"


def test_sanitizer_pid_prefix_is_masked() -> None:
    assert clean_output("==12345==ERROR: x", None).startswith("==PID==ERROR")


def test_pid_and_tid_numbers_are_masked() -> None:
    cleaned = clean_output("WARNING: ThreadSanitizer: data race (pid=23)\n  Thread T2 (tid=26, running)", None)
    assert "pid=PID" in cleaned and "tid=TID" in cleaned


def test_shadow_byte_legend_is_removed() -> None:
    report = (
        "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000018\n"
        "    #0 0x1 in main buggy.c:22:5\n"
        "Shadow bytes around the buggy address:\n"
        "  0x0c: fa fa 00 00\n"
        "Shadow byte legend (one shadow byte represents 8 application bytes):\n"
        "  Addressable:           00\n"
        "SUMMARY: AddressSanitizer: heap-buffer-overflow buggy.c:22:5 in main\n"
        "trailing noise after the summary\n"
    )
    cleaned = clean_output(report, None)
    assert "Shadow" not in cleaned and "trailing noise" not in cleaned
    assert cleaned.endswith("SUMMARY: AddressSanitizer: heap-buffer-overflow buggy.c:22:5 in main")


def test_text_before_the_report_is_dropped() -> None:
    report = (
        "compiler noise before the report\n"
        "==1==ERROR: AddressSanitizer: heap-use-after-free\n"
        "    #0 pop\n"
        "SUMMARY: AddressSanitizer: heap-use-after-free buggy.c:31 in pop\n"
    )
    cleaned = clean_output(report, None)
    assert cleaned.startswith("==PID==ERROR: AddressSanitizer: heap-use-after-free")
    assert "compiler noise" not in cleaned


def test_truncation_appends_the_count() -> None:
    assert clean_output("a" * 100, None, max_chars=10) == "a" * 10 + "\n[... 90 chars truncated]"


@pytest.mark.parametrize(
    ("raw", "summary"),
    [
        (
            "==1==ERROR: AddressSanitizer: heap-use-after-free\n"
            "SUMMARY: AddressSanitizer: heap-use-after-free buggy.c:31 in pop\n",
            "AddressSanitizer: heap-use-after-free buggy.c:31 in pop",
        ),
        (
            "==1==ERROR: LeakSanitizer: detected memory leaks\n"
            "SUMMARY: AddressSanitizer: 16 byte(s) leaked in 1 allocation(s).\n",
            "LeakSanitizer: 16 byte(s) leaked in 1 allocation(s)",
        ),
        (
            "buggy.c:8:19: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'\n"
            "    #0 0x1 in main buggy.c:8:19\n"
            "SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.c:8:19 \n",
            "buggy.c:8:19: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'",
        ),
    ],
)
def test_sanitizer_summary_per_sanitizer(raw: str, summary: str) -> None:
    assert toolchain._summary(toolchain._clean(raw, None)) == summary
