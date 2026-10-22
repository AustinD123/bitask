"""Compile a candidate against one case, run it, and classify the outcome.

Entry points are verify() and verify_file(). Stages run in this order and the
first failure ends the attempt: TSan preflight, three-step compile, then one
run per case.runs, each classified by classify_run(). Candidate code never
raises out of verify(). Environment problems come back as stage harness_error.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from verifyloop.case import COMMON_INCLUDE_DIR, Case

COMPILE_TIMEOUT_S = 60
OUTPUT_CAP = 1024 * 1024  # bytes kept per stream: the first and last half (see _Stream)
MAX_OUTPUT_CHARS = 4000
TSAN_MAX_MMAP_RND_BITS = 28
MMAP_RND_BITS_PATH = Path("/proc/sys/vm/mmap_rnd_bits")
TSAN_HELP = "TSan needs vm.mmap_rnd_bits <= 28; run scripts/fix-aslr.sh (or .ps1)"
HARNESS_MARKERS = ("Sanitizer: CHECK failed", "unexpected memory mapping")
SANITIZER_MARKERS = (
    "ERROR: AddressSanitizer", "ERROR: LeakSanitizer", "WARNING: ThreadSanitizer", "runtime error:",
)
TEST_FAIL_MARKERS = ("CHECK FAILED", "CHECK_EQ FAILED", "CHECK_STREQ FAILED")
# Sanitizer options. These are per-run settings, not compile flags; see docs/harness.md.
SANITIZER_OPTIONS = {
    "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:symbolize=1:color=never",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1:color=never",
    "TSAN_OPTIONS": "halt_on_error=1:second_deadlock_stack=1:color=never",
}
_CHECK_NAMES = ("compiled", "ran_to_completion", "sanitizers_clean", "tests_passed")
# Run checks per stage: (ran_to_completion, sanitizers_clean, tests_passed).
# compiled is True for every stage that reached a binary, so it is not listed here.
_STAGE_CHECKS = {
    "ok": (True, True, True),
    "sanitizer": (None, False, None),
    "test_fail": (True, True, False),
    "crash": (False, True, None),
    "timeout": (False, True, None),
}

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_HEX_ADDR = re.compile(r"0x[0-9a-f]{6,}")
_PID_PREFIX = re.compile(r"==\d+==")
_PID = re.compile(r"\bpid=\d+")
_TID = re.compile(r"\btid=\d+")
# The build ID hashes the binary, and the binary embeds the workdir path in its
# debug info, so it differs between runs of identical source. Masked; see docs/harness.md.
_BUILD_ID = re.compile(r"BuildId: [0-9a-f]+")
_REPORT_START = re.compile(r"ERROR: (AddressSanitizer|LeakSanitizer)|WARNING: ThreadSanitizer|runtime error:")
_SHADOW_START = "Shadow bytes around the buggy address:"


@dataclass
class VerifyResult:
    """The verdict for one candidate against one case.

    Attributes:
        passed: True only when stage is ``ok``.
        stage: ``ok``, ``compile_error``, ``sanitizer``, ``test_fail``, ``crash``,
            ``timeout`` or ``harness_error``.
        checks: ``compiled``, ``ran_to_completion``, ``sanitizers_clean`` and
            ``tests_passed``. ``None`` means the check was never reached.
        output: Cleaned, deterministic text for the LLM, at most 4000 characters.
            Empty when stage is ``ok``.
        sanitizer_summary: One line naming the sanitizer report, or None.
        failing_run: 1-based number of the run that failed, or None.
        runs_completed: Number of runs that passed before the failure.
        exit_code: Return code of the failing run (or last run). Negative means
            killed by that signal.
        compile_cmd: The command that failed, or the link command if all compile
            steps passed. Empty if the candidate was never compiled.
        raw_compile_stderr: Uncleaned compiler stderr, for logs.
        raw_stdout: Uncleaned stdout of the failing run (capped, see OUTPUT_CAP).
        raw_stderr: Uncleaned stderr of the failing run (capped, see OUTPUT_CAP).
        duration_s: Wall time of the whole verify() call.
        workdir: Path of the kept workdir, only when keep_workdir=True.
    """

    passed: bool
    stage: str
    checks: dict[str, bool | None]
    output: str
    sanitizer_summary: str | None
    failing_run: int | None
    runs_completed: int
    exit_code: int | None
    compile_cmd: list[str]
    raw_compile_stderr: str
    raw_stdout: str
    raw_stderr: str
    duration_s: float
    workdir: str | None

    def to_dict(self) -> dict:
        """Return the result as a plain dict that json.dumps accepts."""
        return asdict(self)


def verify(
    source_code: str,
    case: Case,
    *,
    test: Literal["visible", "hidden"] = "visible",
    keep_workdir: bool = False,
) -> VerifyResult:
    """Compile ``source_code`` against ``case``'s test, run it, and classify the outcome.

    Stage order: TSan preflight (when the case uses thread), then the three
    compile steps, then one run per ``case.runs``. The first failure stops the
    attempt. The case directory is only read, never written.

    Args:
        source_code: Full text of the candidate editable file.
        case: The validated case to test against.
        test: ``"visible"`` runs ``case.test``; ``"hidden"`` runs ``case.hidden_test``.
        keep_workdir: If True, keep the temporary directory and return its path.

    Returns:
        A VerifyResult. This function does not raise because of candidate code.
    """
    start = time.monotonic()
    if "thread" in case.sanitizers and (problem := _tsan_preflight()):
        return _result(case, None, "harness_error", start, keep_workdir, message=problem)
    test_name = case.hidden_test if test == "hidden" else case.test
    with contextlib.ExitStack() as stack:
        if keep_workdir:
            workdir = Path(tempfile.mkdtemp(prefix="verify-"))
        else:
            workdir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="verify-")))
        return _verify_in(workdir, case, source_code, test_name, start, keep_workdir)


def verify_file(source_path: str | Path, case: Case, **kwargs) -> VerifyResult:
    """Read a candidate from ``source_path`` and call verify() on it.

    Args:
        source_path: Path to the candidate editable file.
        case: The validated case to test against.
        **kwargs: Passed through to verify().

    Returns:
        The VerifyResult from verify(). Bytes that are not valid UTF-8 are
        replaced, so a bad file gives a compile error, not an exception.
    """
    source = Path(source_path).read_text(encoding="utf-8", errors="replace")
    return verify(source, case, **kwargs)


def classify_run(
    stdout: str, stderr: str, exit_code: int | None, timed_out: bool, nonce: str,
) -> tuple[str, str]:
    """Classify one run's outcome. This is a pure function with no I/O.

    Rules are applied in the order given in SPEC.md, Step 4. The first match decides.
    ``harness_error`` is checked before the sanitizer markers because TSan's own
    startup failures also print to stderr.

    Args:
        stdout: Decoded stdout of the run.
        stderr: Decoded stderr of the run.
        exit_code: Process return code. A negative value means killed by that signal.
        timed_out: True if the harness killed the run for exceeding its timeout.
        nonce: The ``VERIFY_NONCE`` value given to this run.

    Returns:
        ``(stage, message)``. ``message`` is a one-line reason for stages whose
        cleaned output would not otherwise say why. It may be empty.
    """
    if timed_out:
        return "timeout", ""
    line = _find_line(stderr, HARNESS_MARKERS)
    if line:
        return "harness_error", f"sanitizer internal failure: {line.strip()}"
    if _find_line(stderr, SANITIZER_MARKERS):
        return "sanitizer", ""
    if _find_line(stderr, TEST_FAIL_MARKERS):
        return "test_fail", ""
    if exit_code is not None and exit_code > 0:
        return "test_fail", f"exit code {exit_code}"
    if exit_code is not None and exit_code < 0:
        return "crash", f"killed by {_signal_name(-exit_code)}"
    if f"VERIFY_OK {nonce}" not in stdout.splitlines():
        return "test_fail", "test exited 0 without reaching completion marker"
    return "ok", ""


def clean_output(text: str, workdir: Path | None, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Make sanitizer or compiler output deterministic and short enough for an LLM.

    Strips ANSI colour, the workdir path, per-run addresses and PIDs, and the
    shadow-byte legend. For a sanitizer report, keeps only the text from its
    first report line through its SUMMARY line. Truncates to ``max_chars``.

    Args:
        text: Raw combined output.
        workdir: The temporary directory the run used. Its path is removed.
        max_chars: Maximum length of the returned text.

    Returns:
        The cleaned text, followed by ``[... N chars truncated]`` if it was cut.
    """
    return _truncate(_clean(text, workdir), max_chars)


def new_nonce() -> str:
    """Return a fresh completion-marker nonce: 16 hex characters."""
    return secrets.token_hex(8)


def _verify_in(
    workdir: Path, case: Case, source_code: str, test_name: str, start: float, keep: bool,
) -> VerifyResult:
    """Run the compile and run stages inside an existing workdir."""
    shutil.copy(case.directory / case.header, workdir / case.header)
    shutil.copy(case.directory / test_name, workdir / test_name)
    (workdir / case.editable).write_text(source_code, encoding="utf-8")

    stage, message, compile_stderr, cmd = _build(case, workdir)
    if stage:
        compiled = False if stage == "compile_error" else None
        return _result(case, workdir, stage, start, keep, message=message,
                       compile_stderr=compile_stderr, cmd=cmd, compiled=compiled)

    completed = 0
    stdout = stderr = ""
    code: int | None = None
    for run in range(1, case.runs + 1):
        nonce = new_nonce()
        stdout, stderr, code, timed_out = _run_once(workdir, nonce, case.timeout_s)
        stage, message = classify_run(stdout, stderr, code, timed_out, nonce)
        if stage == "timeout":
            message = f"timed out after {case.timeout_s:g}s (run {run} of {case.runs})"
        if stage != "ok":
            return _result(case, workdir, stage, start, keep, message=message, stdout=stdout,
                           stderr=stderr, exit_code=code, failing_run=run, runs_completed=completed,
                           cmd=cmd, compiled=True)
        completed += 1
    return _result(case, workdir, "ok", start, keep, stdout=stdout, stderr=stderr, exit_code=code,
                   runs_completed=completed, cmd=cmd, compiled=True)


def _build(case: Case, workdir: Path) -> tuple[str | None, str, str, list[str]]:
    """Compile the test, then the candidate, then link. Returns (stage, message, stderr, cmd).

    ``stage`` is None when all three steps succeed. ``cmd`` is the step that
    failed, or the link command when everything succeeded.
    """
    cc = _compiler_for(case)
    flags = _compile_flags(case, workdir)
    steps = [
        ("test", [cc, *flags, "-c", case.test, "-o", "test.o"]),
        ("candidate", [cc, *flags, "-c", case.editable, "-o", "candidate.o"]),
        ("link", [cc, *flags, "candidate.o", "test.o", "-o", "test_bin"]),
    ]
    for step, cmd in steps:
        try:
            done = _run_compiler(cmd, workdir)
        except FileNotFoundError:
            return "harness_error", f"compiler not found: {cc}", "", cmd
        except subprocess.TimeoutExpired:
            if step == "test":
                return "harness_error", f"test file compile timed out after {COMPILE_TIMEOUT_S}s (case bug)", "", cmd
            return "compile_error", f"compile timed out after {COMPILE_TIMEOUT_S}s", "", cmd
        if done.returncode != 0:
            if step == "test":
                return "harness_error", "test file failed to compile, this is a case bug", done.stderr, cmd
            return "compile_error", "", done.stderr, cmd
    return None, "", "", cmd


def _compile_flags(case: Case, workdir: Path) -> list[str]:
    """Flags shared by all three compile steps (SPEC.md, Step 2)."""
    flags = [
        f"-std={case.std}",
        "-g",  # debug info, so sanitizer reports carry file and line
        "-O1",  # optimised enough to be realistic, not so much that bugs vanish
        "-fno-omit-frame-pointer",  # clean stack traces in sanitizer reports
        "-fsanitize=" + ",".join(case.sanitizers),
        "-fno-sanitize-recover=all",  # UBSan exits nonzero instead of continuing
        "-Wall", "-Werror",  # a warning in the candidate is a compile error
    ]
    if "address" in case.sanitizers and "undefined" in case.sanitizers:
        # ASan already reports out-of-bounds heap writes with allocation stacks.
        # With both enabled, UBSan's object-size check would fire first with a
        # weaker message, so it is turned off.
        flags.append("-fno-sanitize=object-size")
    flags += list(case.extra_flags)
    flags += ["-I", str(workdir), "-I", str(COMMON_INCLUDE_DIR)]
    return flags


def _compiler_for(case: Case) -> str:
    """Return the compiler from CXX (C++ cases) or CC (C cases), falling back to clang."""
    if case.lang == "cpp":
        return os.environ.get("CXX") or "clang++"
    return os.environ.get("CC") or "clang"


def _run_compiler(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one compiler step with the compile timeout. Output is decoded with replacement."""
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=COMPILE_TIMEOUT_S,
    )


def _run_once(workdir: Path, nonce: str, timeout_s: float) -> tuple[str, str, int | None, bool]:
    """Run the test binary once in its own process group. Returns (stdout, stderr, code, timed_out)."""
    proc = subprocess.Popen(
        [str(workdir / "test_bin")], cwd=workdir, env=_run_env(nonce),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    out, err = _Stream(proc.stdout), _Stream(proc.stderr)
    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
    # Kill the whole group, so children the candidate forked cannot outlive the run.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    return out.text(), err.text(), proc.returncode, timed_out


def _run_env(nonce: str) -> dict[str, str]:
    """Environment for one run. Only PATH, the nonce and the sanitizer options are set."""
    env = {"PATH": os.environ.get("PATH", ""), "VERIFY_NONCE": nonce, **SANITIZER_OPTIONS}
    if "ASAN_SYMBOLIZER_PATH" in os.environ:
        env["ASAN_SYMBOLIZER_PATH"] = os.environ["ASAN_SYMBOLIZER_PATH"]
    return env


def _tsan_preflight() -> str | None:
    """Return TSAN_HELP if the kernel's ASLR entropy is too high for TSan, else None.

    If the value cannot be read, the check is skipped and None is returned.
    """
    try:
        bits = _read_mmap_rnd_bits()
    except (OSError, ValueError):
        return None
    return TSAN_HELP if bits > TSAN_MAX_MMAP_RND_BITS else None


def _read_mmap_rnd_bits() -> int:
    """Return vm.mmap_rnd_bits from /proc. Raises OSError or ValueError if unavailable."""
    return int(MMAP_RND_BITS_PATH.read_text().strip())


def _result(
    case: Case,
    workdir: Path | None,
    stage: str,
    start: float,
    keep: bool,
    *,
    message: str = "",
    stdout: str = "",
    stderr: str = "",
    compile_stderr: str = "",
    cmd: list[str] | None = None,
    exit_code: int | None = None,
    failing_run: int | None = None,
    runs_completed: int = 0,
    compiled: bool | None = None,
) -> VerifyResult:
    """Build the VerifyResult for a finished attempt, cleaning its output once."""
    body = compile_stderr or (stdout + stderr)
    text = "\n".join(part for part in (message, body) if part)
    cleaned = _clean(text, workdir) if stage != "ok" else ""
    if stage == "ok":
        checks = dict.fromkeys(_CHECK_NAMES, True)
    else:
        ran, sanitizers, tests = _STAGE_CHECKS.get(stage, (None, None, None))
        checks = dict(zip(_CHECK_NAMES, (compiled, ran, sanitizers, tests)))
    return VerifyResult(
        passed=stage == "ok",
        stage=stage,
        checks=checks,
        output=_truncate(cleaned, MAX_OUTPUT_CHARS),
        sanitizer_summary=_summary(cleaned),
        failing_run=failing_run,
        runs_completed=runs_completed,
        exit_code=exit_code,
        compile_cmd=list(cmd or []),
        raw_compile_stderr=compile_stderr,
        raw_stdout=stdout,
        raw_stderr=stderr,
        duration_s=round(time.monotonic() - start, 3),
        workdir=str(workdir) if keep and workdir else None,
    )


def _clean(text: str, workdir: Path | None) -> str:
    """Apply every cleaning rule except truncation. Shared by clean_output() and _result()."""
    text = _ANSI.sub("", text)
    if workdir:
        text = text.replace(f"{workdir}/", "").replace(str(workdir), "")
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _REPORT_START.search(line)), None)
    if start is not None:
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("SUMMARY:")), len(lines) - 1)
        lines = lines[start:end + 1]
    kept, skipping = [], False
    for line in lines:
        if _SHADOW_START in line:
            skipping = True
        if line.startswith("SUMMARY:"):
            skipping = False
        if not skipping:
            kept.append(line)
    text = "\n".join(kept)
    text = _HEX_ADDR.sub("0xADDR", text)
    text = _PID_PREFIX.sub("==PID==", text)
    text = _PID.sub("pid=PID", text)
    text = _BUILD_ID.sub("BuildId: BUILDID", text)
    return _TID.sub("tid=TID", text)


def _truncate(text: str, max_chars: int) -> str:
    """Cut ``text`` to ``max_chars`` and say how much was removed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[... {len(text) - max_chars} chars truncated]"


def _summary(cleaned: str) -> str | None:
    """Return the one-line sanitizer summary from already-cleaned output, or None."""
    lines = cleaned.splitlines()
    summary = next((line[len("SUMMARY: "):] for line in lines if line.startswith("SUMMARY: ")), None)
    runtime = next((line.strip() for line in lines if "runtime error:" in line), None)
    if "ERROR: LeakSanitizer" in cleaned and summary:
        # LSan's SUMMARY line says "AddressSanitizer:", so name the real sanitizer.
        return "LeakSanitizer: " + summary.removeprefix("AddressSanitizer: ").rstrip(".")
    if summary and not summary.startswith("UndefinedBehaviorSanitizer"):
        return summary
    return runtime or summary


def _find_line(text: str, markers: tuple[str, ...]) -> str | None:
    """Return the first line of ``text`` containing any of ``markers``, or None."""
    for line in text.splitlines():
        if any(marker in line for marker in markers):
            return line
    return None


def _signal_name(number: int) -> str:
    """Return the name of a signal number, such as SIGABRT, or 'signal N' if unknown."""
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


class _Stream:
    """Reads one pipe in a background thread, keeping at most OUTPUT_CAP bytes.

    The first OUTPUT_CAP bytes are kept verbatim. If the stream is longer, the
    middle is replaced by a note, and the last half is kept. The completion
    marker is printed last, so this is what keeps it visible. The rest of the
    stream is still drained, so the child never blocks on a full pipe.
    """

    def __init__(self, pipe) -> None:
        self._pipe = pipe
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        """Consume the pipe to EOF, keeping only the bounded head and tail."""
        half = OUTPUT_CAP // 2
        for chunk in iter(lambda: self._pipe.read(65536), b""):
            self._total += len(chunk)
            room = OUTPUT_CAP - len(self._head)
            if room > 0:
                self._head += chunk[:room]
            self._tail += chunk
            if len(self._tail) > half:
                del self._tail[: len(self._tail) - half]

    def text(self) -> str:
        """Return the captured text. Waits at most 5 s for EOF, since a grandchild may hold the pipe."""
        self._thread.join(timeout=5)
        if self._total <= OUTPUT_CAP:
            data = bytes(self._head)
        else:
            half = OUTPUT_CAP // 2
            note = f"\n[... stream truncated: {self._total - OUTPUT_CAP} bytes omitted ...]\n"
            data = bytes(self._head[:half]) + note.encode() + bytes(self._tail)
        return data.decode("utf-8", errors="replace")
