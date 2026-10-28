# Layer 1 Spec: Verification Harness

Oct 22, 2026 · @austin

## Context and goal

Build a Python function `verify(source, case)` that reliably answers one question: does this version of a C/C++ file compile cleanly, run without sanitizer errors, and pass its tests?

This is the foundation of a prototype of ByteAsk's core loop: an LLM proposes a fix, and the toolchain proves it. Later phases add the LLM, the retry loop and a benchmark. **None of that is in this task.** If the harness can't reliably tell broken code from fixed code, everything built on top is meaningless, so correctness and clear documentation matter more than features.

You are building:

1. A reproducible Linux build environment (Docker, pinned clang).
2. A case format: one directory per buggy program, with tests and a known-good fix.
3. The `verify()` function and a small CLI around it.
4. Four hand-written starter cases.
5. A pytest suite proving the harness classifies results correctly.
6. Clear documentation of all of the above.

Work in the order of the sections below. Where this spec gives an exact value (a flag, an env var, a field name), use it exactly. Where it says "you decide," pick the simplest option and document it.

## Scope

**In scope**

- Dockerfile and instructions to build and run inside it
- Case loading and validation (`case.json`)
- `verify()`: compile, run, classify the outcome, clean the output
- CLI command `verify` for running one source file against one case
- Four starter cases, each with buggy code, visible test, hidden test and reference fix
- pytest suite for the harness
- README, `docs/harness.md`, per-case `NOTES.md`, docstrings

**Out of scope (do not build)**

- Any LLM or API code
- The retry loop, attempt logging, diffs
- The benchmark runner and results table
- A standalone `validate` command (the pytest suite covers this for now)
- MemorySanitizer, Valgrind, macOS or Windows support

**Constraints**

- Python 3.11+, standard library only for runtime code (`subprocess`, `dataclasses`, `json`, `pathlib`, `tempfile`, `re`, `os`, `signal`, `shutil`). pytest is the only dev dependency.
- Harness code (excluding tests and cases) should be about 250 lines. Prefer clarity over cleverness.
- Full type hints and a docstring on every public function and dataclass.

## Environment

Everything runs inside a Linux Docker container so results are reproducible. Sanitizer behaviour differs across OSes (LeakSanitizer does not work on macOS), so Docker is the only supported environment.

**Dockerfile requirements**

- Base image `ubuntu:24.04`.
- Install `clang-18`, `llvm-18` (for `llvm-symbolizer`), `python3`, `python3-pip`, `python3-pytest` and `make`.
- Symlink or set `CC=clang-18` and `CXX=clang++-18` as defaults. The harness reads `CC` / `CXX` from the environment, falling back to `clang` / `clang++`.
- Set `ASAN_SYMBOLIZER_PATH` to the `llvm-symbolizer-18` binary so sanitizer stack traces show file and line numbers.
- Working directory `/work`, with the repo mounted there.

**Run command to document in the README**

```bash
docker build -t verify-harness .
docker run --rm -it --cap-add SYS_PTRACE --network none -v "$PWD":/work verify-harness pytest -v
```

**Known issues to handle and document in Troubleshooting**

- **LeakSanitizer fails in Docker** with "LeakSanitizer has encountered a fatal error." Fix: run with `--cap-add SYS_PTRACE` (already in the command above).
- **ThreadSanitizer fails with "unexpected memory mapping"** on recent kernels with high ASLR entropy. Fix: on the host, `sudo sysctl vm.mmap_rnd_bits=28`, or run the test binary under `setarch $(uname -m) -R`. Detect this message in `verify()` and report it as `harness_error` with a pointer to the docs, not as a sanitizer failure.
- `--network none` is deliberate: compiled code is untrusted (later it comes from an LLM) and should never reach the network.

Before writing harness code, confirm inside the container that a trivial ASan, UBSan and TSan program each compile and report correctly. Note the clang version (`clang-18 --version`) in the README.

## Project structure

```
verify-proto/
  Dockerfile
  requirements.txt          # runtime: empty or comment only
  requirements-dev.txt      # pytest
  README.md
  docs/
    harness.md              # full harness reference (see Documentation)
  verifyloop/
    __init__.py
    case.py                 # Case dataclass, load_case(), validation
    toolchain.py            # verify(), VerifyResult, output cleaning
    cli.py                  # `python -m verifyloop.cli verify ...`
  bench/
    common/
      check.h               # CHECK macro + completion marker, shared by all tests
    cases/
      01_heap_overflow/
      02_signed_overflow/
      03_iterator_invalidation/
      04_data_race/
  tests/
    fixtures/
      mini_case/            # tiny synthetic case for harness tests
    test_case_loading.py
    test_toolchain.py
    test_starter_cases.py
```

Keep `case.py` and `toolchain.py` free of CLI concerns (no printing, no `sys.exit`), so the later retry loop can import them directly.

## Case format

Each case is a directory. The harness never modifies anything inside it.

```
bench/cases/01_heap_overflow/
  case.json          # metadata, see schema below
  lib.h              # declarations of the functions under test (read-only)
  buggy.c            # implementation, NO main(). The only file a fix may change.
  reference_fix.c    # known-good version of buggy.c, same functions
  test.c             # visible test: has main(), includes lib.h and check.h
  hidden_test.c      # held-out test, never shown to the LLM later
  NOTES.md           # human explanation of the bug (see Documentation)
```

For C++ cases the extensions are `.cpp` / `.hpp`. The editable file and its reference fix must use the same filename stem convention (`buggy.cpp`, `reference_fix.cpp`).

**`case.json` schema**

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | Must equal the directory name |
| `title` | string | yes | Short human title, e.g. "Heap buffer overflow in join\_words" |
| `lang` | `"c"` or `"cpp"` | yes | Selects `CC` or `CXX` |
| `std` | string | yes | Passed as `-std=`, e.g. `c11`, `c++17` |
| `editable` | string | yes | Filename of the editable source, e.g. `buggy.c` |
| `reference` | string | yes | Filename of the reference fix |
| `test` | string | yes | Visible test filename |
| `hidden_test` | string | yes | Hidden test filename |
| `sanitizers` | list of strings | yes | Subset of `address`, `undefined`, `thread` |
| `extra_flags` | list of strings | no, default `[]` | Appended to compile command, e.g. `-pthread` |
| `runs` | int | no, default `1` | How many times the test binary is run; all must pass |
| `timeout_s` | number | no, default `10` | Per-run timeout |
| `expected_buggy_stage` | string | yes | Stage the buggy version must fail at (see verify section) |
| `description` | string | yes | One-sentence bug summary for humans |

**Validation rules in `load_case()`** (raise `CaseError` with a clear message):

- All required fields present, with correct types.
- `id` matches the directory name.
- Every referenced file exists.
- `thread` is not combined with `address` (clang rejects it; give a friendlier error first).
- `expected_buggy_stage` is one of the failure stages, not `ok`.
- Unknown fields are an error (catches typos).

## Test-file conventions

Every test file uses the shared `bench/common/check.h`. It provides failing checks that report clearly, and a completion marker that stops a "fix" from passing by exiting early.

```c
/* bench/common/check.h */
#ifndef VERIFY_CHECK_H
#define VERIFY_CHECK_H
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* Fail immediately with location. _exit() skips atexit handlers, so
   LeakSanitizer does not run and a plain test failure is never
   misreported as a sanitizer failure. */
#define CHECK(cond) do { if (!(cond)) { \
    fprintf(stderr, "CHECK FAILED: %s at %s:%d\n", #cond, __FILE__, __LINE__); \
    fflush(stderr); _exit(1); } } while (0)

/* Same, but prints both values. Use this wherever values are comparable. */
#define CHECK_EQ(actual, expected) do { \
    long long a_ = (long long)(actual), e_ = (long long)(expected); \
    if (a_ != e_) { fprintf(stderr, "CHECK_EQ FAILED: %s == %s (got %lld, expected %lld) at %s:%d\n", \
        #actual, #expected, a_, e_, __FILE__, __LINE__); fflush(stderr); _exit(1); } } while (0)

/* Call as the LAST statement of main() before return 0. */
static inline void verify_tests_passed(void) {
    const char *nonce = getenv("VERIFY_NONCE");
    printf("VERIFY_OK %s\n", nonce ? nonce : "(missing)");
    fflush(stdout);
}
#endif
```

Add a `CHECK_STREQ` in the same style for string comparisons. The header must compile cleanly as both C11 and C++17 under `-Wall -Werror`.

**Rules for every test file**

- Never use `assert()`. It vanishes if anything defines `NDEBUG`.
- `main()` returns 0 only after calling `verify_tests_passed()`.
- Free everything you allocate, so a correct fix produces zero leak reports.
- Each check should test one behaviour, with a short comment saying which.

**The completion marker.** For each run, the harness generates a random nonce (`secrets.token_hex(8)`), passes it as `VERIFY_NONCE`, and requires stdout to contain `VERIFY_OK <nonce>`. A binary that exits 0 without printing it is classified as `test_fail` with the message "test exited 0 without reaching completion marker." This blocks the most common cheat: calling `exit(0)` from library code.

## verify()

`verify()` compiles a candidate source against a case's test, runs it, and returns a structured verdict. It never raises because of the candidate code. Problems with the environment come back as stage `harness_error`.

```python
def verify(
    source_code: str,
    case: Case,
    *,
    test: Literal["visible", "hidden"] = "visible",
    keep_workdir: bool = False,
) -> VerifyResult: ...

def verify_file(source_path: Path, case: Case, **kwargs) -> VerifyResult: ...
```

### Step 1: isolated workdir

Create a fresh `tempfile.TemporaryDirectory()`. Copy in `lib.h` (or `.hpp`) and the chosen test file. Write `source_code` there under the case's `editable` filename, so compiler errors say `buggy.c:12`, matching what a human or LLM sees. Never write into the case directory. Delete the workdir afterwards unless `keep_workdir=True`, in which case put its path in the result.

### Step 2: compile

Use exactly this command, as an argument list (never `shell=True`):

```
<CC or CXX> -std=<std> -g -O1 -fno-omit-frame-pointer
  -fsanitize=<comma-joined sanitizers> -fno-sanitize-recover=all
  -Wall -Werror <extra_flags...>
  -I <workdir> -I <repo>/bench/common
  <editable> <test> -o <workdir>/test_bin
```

- `-fno-sanitize-recover=all` is essential. Without it UBSan prints an error and the program exits 0, so a signed-overflow bug would "pass."
- Compile timeout: 60 s. Nonzero exit means stage `compile_error`, with the compiler's stderr as output. Store the command in the result.
- Compiler binary not found means `harness_error`.

### Step 3: run

Run `test_bin` `case.runs` times, stopping at the first failing run. For each run, set this environment (inherit `PATH`, nothing else is needed):

```
VERIFY_NONCE=<fresh secrets.token_hex(8) per run>
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:symbolize=1:color=never
UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1:color=never
TSAN_OPTIONS=halt_on_error=1:second_deadlock_stack=1:color=never
ASAN_SYMBOLIZER_PATH=<from container env, if set>
```

Start the process with `start_new_session=True`. On timeout, kill the whole process group (`os.killpg`) so child threads or processes can't survive. Decode output with `errors="replace"`.

### Step 4: classify each run

Apply these checks **in this order**. The first match decides the stage:

1. Timed out: `timeout`.
2. stderr contains `unexpected memory mapping` (the TSan/ASLR issue): `harness_error`, with a pointer to the Troubleshooting docs.
3. stderr contains a sanitizer marker: `sanitizer`, regardless of exit code. Markers: `ERROR: AddressSanitizer`, `ERROR: LeakSanitizer`, `WARNING: ThreadSanitizer`, `runtime error:`.
4. stderr contains `CHECK FAILED` / `CHECK_EQ FAILED` / `CHECK_STREQ FAILED`, or exit code > 0: `test_fail`.
5. Killed by a signal (negative return code): `crash`. Include the signal name.
6. Exit code 0 but stdout lacks `VERIFY_OK <nonce>`: `test_fail`.
7. Otherwise the run passed.

The sanitizer check comes before the exit code because TSan and LSan can report a problem with a misleading exit code. Note that under ASan a segfault is reported as `ERROR: AddressSanitizer: SEGV`, so it is classified `sanitizer`, not `crash`. That is expected; document it.

### Stages

| Stage | Meaning | Typical output |
| --- | --- | --- |
| `ok` | Compiled, all runs passed | none |
| `compile_error` | Compiler or `-Werror` failure | `buggy.c:14:9: error: unused variable 'n'` |
| `sanitizer` | Any sanitizer report | `ERROR: AddressSanitizer: heap-use-after-free` |
| `test_fail` | A CHECK failed, nonzero exit, or missing completion marker | `CHECK_EQ FAILED: midpoint(-3, 0) == -2 (got -1, expected -2)` |
| `crash` | Killed by a signal not caught by a sanitizer | `killed by SIGABRT` |
| `timeout` | Exceeded `timeout_s` | `timed out after 10s (run 3 of 5)` |
| `harness_error` | Environment problem, not the candidate's fault | `clang-18 not found` |

### Step 5: clean the output

`clean_output(text, workdir, max_chars=4000) -> str` produces the text that will later be fed to the LLM. It must be deterministic, so the same bug gives the same text across runs:

- Strip ANSI colour codes.
- Replace the workdir path with nothing, so paths read `buggy.c:12`.
- Replace hex addresses (`0x[0-9a-f]{6,}`) with `0xADDR`, and `==12345==` PID prefixes with `==PID==`.
- For a sanitizer report, keep from the first report line through its `SUMMARY:` line, and drop the "Shadow bytes around the buggy address" legend.
- Truncate to `max_chars`, appending `[... N chars truncated]`.

Also extract a one-line `sanitizer_summary`: the text after `SUMMARY:` for ASan/LSan/TSan (e.g. `AddressSanitizer: heap-use-after-free buggy.c:31 in pop`), or the first `runtime error:` line for UBSan.

### Result type

```python
@dataclass
class VerifyResult:
    passed: bool
    stage: str                   # one of the stages above
    checks: dict[str, bool | None]  # compiled, ran_to_completion,
                                 # sanitizers_clean, tests_passed;
                                 # None = never reached
    output: str                  # cleaned, LLM-ready
    sanitizer_summary: str | None
    failing_run: int | None      # 1-based
    runs_completed: int
    exit_code: int | None
    compile_cmd: list[str]
    raw_compile_stderr: str      # uncleaned, for logs
    raw_stdout: str
    raw_stderr: str
    duration_s: float
    workdir: str | None          # only when keep_workdir=True

    def to_dict(self) -> dict: ...   # JSON-serialisable, for later logging
```

## CLI

One subcommand for now, built with `argparse` so later phases can add `fix` and `bench` beside it.

```bash
python -m verifyloop.cli verify --case bench/cases/01_heap_overflow \
    [--source path/to/candidate.c]   # default: the case's editable file
    [--reference]                    # use the case's reference fix as source
    [--hidden]                       # run the hidden test instead
    [--json]                         # print VerifyResult.to_dict() as JSON
    [--keep-workdir]
```

- Human output: a one-line verdict (`PASS` in green, `FAIL [sanitizer]` in red), the checks with ✓ / ✗ / –, the sanitizer summary if any, then the cleaned output. Disable colour when stdout is not a TTY or `NO_COLOR` is set.
- Exit codes: `0` passed, `1` candidate failed, `2` harness error or invalid case.

Example of the expected human output:

```
FAIL [sanitizer]  01_heap_overflow (visible test, 0.84s)
  ✓ compiled   ✗ sanitizers clean   – ran to completion   – tests passed
  AddressSanitizer: heap-buffer-overflow buggy.c:22 in join_words
  ---
  ==PID==ERROR: AddressSanitizer: heap-buffer-overflow on address 0xADDR ...
```

## Starter cases

Four cases cover C and C++, and all three sanitizer setups. Each is designed so the **obvious fix is wrong**: the hidden test catches the naive patch. Use the buggy code below exactly. Write the visible test, hidden test and reference fix to match the requirements given. Each buggy version must compile cleanly under `-Wall -Werror` and fail at its `expected_buggy_stage`. If it fails at a different stage, fix the case, not the harness.

| Case | Lang | Sanitizers | Extra flags | Runs | Buggy fails at |
| --- | --- | --- | --- | --- | --- |
| `01_heap_overflow` | C11 | address, undefined | none | 1 | `sanitizer` |
| `02_signed_overflow` | C11 | address, undefined | none | 1 | `sanitizer` |
| `03_iterator_invalidation` | C++17 | address, undefined | `-D_GLIBCXX_ASSERTIONS` | 1 | `sanitizer` |
| `04_data_race` | C11 | thread | `-pthread` | 5 (timeout 20 s) | `sanitizer` |

### 01\_heap\_overflow

Contract in `lib.h`: `char *join_words(const char **words, size_t n, char sep);` returns a newly `malloc`ed string joining the words with `sep`. The caller frees it. For `n == 0` it returns an empty string, still `malloc`ed.

```c
#include <stdlib.h>
#include <string.h>
#include "lib.h"

char *join_words(const char **words, size_t n, char sep) {
    size_t total = n - 1;                 /* separators */
    for (size_t i = 0; i < n; i++) total += strlen(words[i]);
    char *out = malloc(total);            /* BUG: no room for '\0'; n == 0 underflows */
    char *p = out;
    for (size_t i = 0; i < n; i++) {
        size_t len = strlen(words[i]);
        memcpy(p, words[i], len);
        p += len;
        if (i + 1 < n) *p++ = sep;
    }
    *p = '\0';
    return out;
}
```

- **Visible test:** `{"a", "bc", "def"}` with `','` gives `"a,bc,def"`. ASan reports heap-buffer-overflow.
- **Hidden test:** `n == 0` gives `""`; `n == 1` gives the word with no separator; `{"", ""}` gives `","`.
- **Why the naive fix fails:** `malloc(total + 1)` makes `total + 1 == 0` when `n == 0`, so the `'\0'` write overflows a zero-byte allocation.

### 02\_signed\_overflow

Contract: `int midpoint(int a, int b);` returns the mathematical floor of `(a + b) / 2`, for all `int` inputs, with no overflow. Document the floor semantics in `lib.h` so the hidden test is fair.

```c
#include "lib.h"

int midpoint(int a, int b) {
    return (a + b) / 2;                   /* BUG: overflows; truncates toward zero */
}
```

- **Visible test:** `midpoint(2, 4) == 3`, then `midpoint(INT_MAX - 1, INT_MAX) == INT_MAX - 1`. UBSan reports signed integer overflow.
- **Hidden test:** `midpoint(INT_MIN, INT_MAX) == -1`, `midpoint(0, -3) == -2`, `midpoint(-3, 0) == -2`, `midpoint(-4, -2) == -3`, `midpoint(INT_MIN, INT_MIN) == INT_MIN`, `midpoint(1, 2) == 1`.
- **Why naive fixes fail:** `a + (b - a) / 2` overflows on `(INT_MIN, INT_MAX)` and gives -1 for `(0, -3)`. Widening to `long long` but keeping `/ 2` truncates toward zero, giving -1 for `(-3, 0)`.

### 03\_iterator\_invalidation

Contract in `lib.hpp`: `void append_doubled_evens(std::vector<int>& v);` appends double of each even element of the **original** vector, in order. Appended elements are not processed again.

```cpp
#include "lib.hpp"

void append_doubled_evens(std::vector<int>& v) {
    for (auto it = v.begin(); it != v.end(); ++it) {
        if (*it % 2 == 0) v.push_back(*it * 2);  // BUG: push_back may reallocate
    }
}
```

- **Visible test:** `v = {1, 2, 3, 4}`, then `v.shrink_to_fit()` so the first `push_back` must reallocate. Expected result `{1, 2, 3, 4, 4, 8}`. ASan reports heap-use-after-free.
- **Hidden test:** an empty vector; an all-odd vector (unchanged); `{2}` after `v.reserve(100)` gives `{2, 4}`; `{-2, 3}` gives `{-2, 3, -4}`.
- **Why the naive fix fails:** re-deriving the iterator from an index after `push_back` stops the crash but still walks into appended elements. With spare capacity, appended evens keep generating more, so the run times out or the result is wrong.

### 04\_data\_race

Contract: `long parallel_count(int threads, int iters);` starts `threads` threads (1 to 64), each incrementing a shared counter `iters` times, and returns the total. Calls are independent: state resets each call.

```c
#include <pthread.h>
#include "lib.h"

static long counter;
static int g_iters;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < g_iters; i++) counter++;  /* BUG: unsynchronised */
    return NULL;
}

long parallel_count(int threads, int iters) {
    pthread_t tids[64];
    counter = 0;
    g_iters = iters;
    for (int t = 0; t < threads; t++) pthread_create(&tids[t], NULL, worker, NULL);
    for (int t = 0; t < threads; t++) pthread_join(tids[t], NULL);
    return counter;
}
```

- **Visible test:** `parallel_count(4, 10000) == 40000`. TSan reports a data race.
- **Hidden test:** `(1, 1000) == 1000`; `(8, 5000) == 40000`; `(3, 0) == 0`; two consecutive calls with the same arguments return the same value.
- **Why the naive fix fails:** `volatile long counter` is still a data race and TSan still reports it. The reference fix uses `<stdatomic.h>` (`atomic_fetch_add`) or a mutex.
- `runs: 5` checks the reference fix is stable, not just lucky once.

## Tests for the harness

The pytest suite proves the harness classifies correctly. All tests run inside the container with `pytest -v`.

**`tests/fixtures/mini_case/`** is a tiny synthetic case: `int add(int a, int b)`, a test checking `add(2, 3) == 5`, sanitizers `address, undefined`, `timeout_s: 2`. Most toolchain tests pass hand-written source strings against it.

**`test_case_loading.py`**

- A valid case loads with defaults applied.
- Each of these raises `CaseError` with a helpful message: missing required field, unknown field, `id` not matching directory, referenced file missing, `address` with `thread`, `expected_buggy_stage` of `ok` or an unknown stage.

**`test_toolchain.py`**, one test per row:

| Candidate source | Expected stage | Also assert |
| --- | --- | --- |
| Correct `add` | `ok` | all four checks `True` |
| Syntax error | `compile_error` | output contains `error:`; run checks `None` |
| Unused local variable | `compile_error` | proves `-Werror` is active |
| Returns `a - b` | `test_fail` | output contains `CHECK_EQ FAILED`; `sanitizers_clean` is `True` |
| Calls `exit(0)` inside `add` | `test_fail` | message mentions the completion marker |
| Infinite loop | `timeout` | wall time under `timeout_s + 3` s |
| Calls `abort()` | `crash` | output names `SIGABRT` |
| Writes past a `malloc`ed buffer | `sanitizer` | summary contains `heap-buffer-overflow` |
| Signed overflow on `INT_MAX` | `sanitizer` | proves `-fno-sanitize-recover` works |
| Leaks a `malloc` | `sanitizer` | summary mentions `LeakSanitizer` |

Plus:

- The case directory is byte-for-byte unchanged after `verify()` (hash every file before and after).
- Determinism: verifying the same failing source twice gives identical `output`, which contains no workdir path and no raw `0x` addresses.
- `clean_output()` unit tests on fixed input strings: ANSI stripping, address and PID masking, shadow-bytes removal, truncation marker.
- `CC=/nonexistent` (via `monkeypatch`) gives `harness_error`, not an exception.
- `VerifyResult.to_dict()` round-trips through `json.dumps`.

**`test_starter_cases.py`**, parametrised over every directory in `bench/cases/`:

- Buggy version, visible test: fails at exactly `expected_buggy_stage`.
- Buggy version, hidden test: does not pass.
- Reference fix, visible test: `ok`.
- Reference fix, hidden test: `ok`.
- Naive fix (stored in `tests/fixtures/naive_fixes/<case_id>.<ext>`, written as described under each case): does not pass the hidden test. This proves the hidden tests earn their place.

Adding a new case directory must automatically add it to this suite, with no code changes.

## Documentation

Documentation is a deliverable, not an afterthought. A new engineer should be able to understand why every flag exists and add a case without reading the code. Write plainly and concisely. Every example output in the docs must be **real output captured from the harness**, never invented.

**`README.md`** (short, under 150 lines)

- What this is, in two or three sentences, and that it is layer 1 of a larger prototype.
- Quickstart: build the image, run the tests, run `verify` on a starter case.
- CLI usage with two real example outputs: one failing buggy case, one passing reference fix.
- Project layout (the tree from this spec).
- How a pass is decided, in five bullet points, linking to `docs/harness.md`.
- Clang version used, and current limitations (Linux/Docker only, no MSan, no Valgrind).

**`docs/harness.md`** (the full reference)

1. **Pipeline overview:** workdir, compile, run, classify, clean, as a numbered list.
2. **Case format:** the `case.json` schema table and the validation rules.
3. **Test conventions:** `check.h`, why `_exit()` instead of `exit()`, why the nonce marker exists.
4. **Compile flags:** a table with one row per flag and a column saying why it is there (e.g. `-fno-sanitize-recover=all`: without it UBSan reports but the program exits 0).
5. **Environment variables:** a table with each sanitizer option and why.
6. **Classification:** the ordered rules and the reasoning for the order.
7. **Stages:** the stage table, with a real cleaned output example for each stage.
8. **Output cleaning:** the rules, with one before/after example from a real ASan report.
9. **Troubleshooting:** LSan in Docker, TSan memory mapping, compiler not found.
10. **Adding a new case:** a checklist, ending with "run `pytest tests/test_starter_cases.py -k <case_id>` and confirm all five checks pass."

**Per-case `NOTES.md`** (for each of the four cases)

- The bug and its root cause, in two or three sentences.
- The real cleaned sanitizer output from the buggy version.
- The reference fix and why it is correct.
- The naive fix, and which hidden check catches it, with the real failing output.

**In the code**

- A module docstring at the top of each file explaining its role.
- Docstrings on every public function and dataclass, with Args, Returns and, for `verify()`, a short note on the stage order.
- An inline comment on every compile flag and sanitizer option.
- No commented-out code, no TODOs left without an explanation.

## Acceptance criteria

The task is done when all of these hold:

- [ ] `docker build` succeeds from a clean checkout.
- [ ] `pytest -v` passes inside the container, **three times in a row** (catches flaky TSan or timeout tests).
- [ ] Every starter case: buggy fails at its expected stage, reference passes visible and hidden tests, naive fix fails the hidden test.
- [ ] `python -m verifyloop.cli verify` works for every case with and without `--reference`, `--hidden` and `--json`, and returns the right exit codes.
- [ ] Harness code in `verifyloop/` is about 250 lines (`wc -l`).
- [ ] No file in `bench/cases/` is modified by any run.
- [ ] README, `docs/harness.md` and all four `NOTES.md` files exist and contain only real captured outputs.

**Order of work.** Build in this order, getting each step green before the next: Dockerfile and sanitizer smoke check, then `case.py` and its tests, then `verify()` against `mini_case`, then the four starter cases one at a time, then the CLI, then documentation last (so captured outputs are final).

**Report back with:**

1. The final `pytest -v` summary.
2. CLI output for each buggy case (visible test) and each reference fix (hidden test).
3. Line counts for each file in `verifyloop/`.
4. Any place you deviated from this spec, and why.
5. Anything surprising about sanitizer behaviour you found, and open questions for the next phase (the LLM retry loop).

## Decisions (Phase 0)

These decisions override the sections above where they conflict.

**Repo setup**

- The spec lives at the repo root as `SPEC.md`. The repo root is `bitask/`, and the package is `verifyloop`. The `verify-proto/` name is retired.
- The repo is a git repo with a `.gitattributes` containing `* text=auto eol=lf`, because development happens on Windows. Commit at the end of every green phase and push to github.com/AustinD123/bitask.

**Line budget**

- Target: about 300 lines of code in `verifyloop/`, excluding docstrings, comments and blank lines. Report both that count and the total line count. `cli.py` stays thin.

**Naive fixes (cases 03 and 04)**

- Every naive fix must fail. For cases 01, 02 and 04 it must pass the visible test and fail only the hidden test. That proves the hidden tests earn their place.
- Case 04: the naive fix is an atomic counter that is never reset between calls. It passes the visible test on the first call and fails the hidden consecutive-calls check. The `volatile` variant is recorded in `NOTES.md` as a fix that TSan catches on the visible test.
- Case 03: the visible test may catch the naive fix. `NOTES.md` records which stage catches it. No loop cap is added; a timeout is a legitimate outcome.

**Test files that fail to compile**

Compilation runs in three steps with identical flags in each step:

1. Compile the test file with `-c`. Failure means `harness_error` with the message "test file failed to compile, this is a case bug".
2. Compile the candidate with `-c`. Failure means `compile_error`.
3. Link. Failure means `compile_error`, for example a missing or renamed function.

Do not match filenames in compiler output.

**Validation additions**

- Reject an empty `sanitizers` list, unknown sanitizer names, and a `std` that does not match `lang`.
- `expected_buggy_stage` must not be `ok` or `harness_error`.
- A `Case` stores its own directory. `bench/common` is resolved from the package location.

**Output cleaning**

- UBSan branch: keep from the first `runtime error:` line through the end of its stack trace.
- Mask `tid=\d+` and any other per-run numbers found during the determinism test.
- Strip the workdir plus its trailing separator.
- Cap captured stdout and stderr at 1 MB each. Note the truncation in the output.

**Documentation points (no code change)**

- The completion marker guards against accidental early exits, not adversarial code. A later phase may add a static check for `VERIFY_NONCE`.
- `crash` is mainly for `abort()` and similar. Under ASan, segfaults are reported as `sanitizer`.
- A candidate can escape `killpg` with `setsid`. The real fix is one container per run, which is out of scope.
- `halt_on_error` is mostly redundant. `-fno-sanitize-recover=all` is what makes UBSan fail.

**Environment**

- The repo is mounted read-only: `-v "$PWD":/work:ro`. Set `PYTHONDONTWRITEBYTECODE=1` and run pytest with `-p no:cacheprovider`, so nothing writes to `/work`. Workdirs stay in `/tmp`.
- pytest is installed via apt only (`python3-pytest`). `requirements-dev.txt` is kept for non-Docker use, with a comment saying so.
- The base image is pinned by digest. The exact clang-18 package version is recorded in the README.
- The documented `docker run` command drops `-it`.

## Decisions (Phase 1)

**Accepted as written**

- `libclang-rt-18-dev` and `bc` in the Dockerfile, the branch rename to `main`, and the read-only mount.
- `--cap-add SYS_PTRACE` stays. It is harmless here and needed on other hosts.
- Case 04 keeps `timeout_s: 20`.

**Sanitizer internal failures are `harness_error` (Phase 3)**

- Any line matching `Sanitizer: CHECK failed` (any sanitizer) or `unexpected memory mapping` is `harness_error`. This is checked before the sanitizer-marker rule.
- Preflight: if the case uses `thread` and `/proc/sys/vm/mmap_rnd_bits` is above 28, `verify()` returns `harness_error` immediately, without compiling. The message is "TSan needs vm.mmap_rnd_bits <= 28; run scripts/fix-aslr.sh (or .ps1)". If the file cannot be read, the preflight is skipped.

**ASan and UBSan object-size (Phase 3)**

- When `address` and `undefined` are both enabled, the compile command adds `-fno-sanitize=object-size`. UBSan's "insufficient space" report is replaced by ASan's `heap-buffer-overflow` with allocation stack, and ASan already covers that check. The flag gets a comment and a row in the flags table in `docs/harness.md`.
- The "writes past a malloc'd buffer" test row and case 01 must both report `heap-buffer-overflow`. This is verified, not assumed.

**Dead-store elision (Phases 3 and 4)**

- Every fixture and test meant to trigger a sanitizer must make the bad effect observable: the pointer or value is returned to the test, stored in a global, or read back by the test.
- Candidate code must not use `volatile` unless the case is explicitly about it, because an LLM will later edit that code.
- Candidate and test are separate translation units and there is no LTO, so values crossing the function boundary cannot be elided. This is relied on.
- The starter-case suite checks that each buggy version fails at its expected stage. That check stays strict.

**Leak reporting (Phase 3)**

- A leak is detected by the `ERROR: LeakSanitizer` line. `sanitizer_summary` is built as `LeakSanitizer: <text after "SUMMARY: AddressSanitizer: ">`, for example `LeakSanitizer: 16 byte(s) leaked in 1 allocation(s)`.

**Per-run numbers (Phase 3)**

- Mask `pid=\d+`, `tid=\d+` and `==\d+==`. The determinism test is the arbiter. Any other varying number it finds is masked and listed in `docs/harness.md`.

## Decisions (Phase 2)

- The loader requires the declarations header to exist: `lib.h` for C cases, `lib.hpp` for C++ cases. The spec lists it in the directory layout but not in `case.json`, so the loader derives it from `lang`.
- All four named files (`editable`, `reference`, `test`, `hidden_test`) must end in the extension for `lang` (`.c` or `.cpp`). Filenames must be bare names, with no directory parts, so a case cannot point outside its own directory.
- `std` must match `lang`: C standards `c` or `gnu` followed by digits, optionally with `x`; C++ standards `c++` or `gnu++` followed by digits.
- `expected_buggy_stage` must be one of `compile_error`, `sanitizer`, `test_fail`, `crash`, `timeout`.
- `NOTES.md` is not checked by the loader. It is a documentation file, and the starter-case suite will check it later.
- `Case` stores its directory. The repo root is resolved from the package location, as `REPO_ROOT` in `verifyloop/case.py`.
- `bench/common/check.h` is created in Phase 2, because the `mini_case` fixture includes it. Phase 3 verifies that it compiles as C11 and C++17 under `-Wall -Werror`.
- `pytest.ini` sets `pythonpath = .` and `testpaths = tests`, so `pytest -v` works from `/work` without `python3 -m`.

## Decisions (Phase 3)

**Phase 2 follow-ups, done first**

- `DEFAULTS` is replaced by immutable constants (`DEFAULT_EXTRA_FLAGS` is a tuple). `Case` stays a frozen dataclass.
- `REPO_ROOT` is replaced by `COMMON_INCLUDE_DIR` (`bench/common`, resolved from the package location).
- The `NOTES.md` existence check is deferred to Phase 6. It is not part of `test_starter_cases.py` in Phase 4.

**Compile**

- The three steps are: the test file with `-c` (failure is `harness_error`, "test file failed to compile, this is a case bug"), the candidate with `-c` (failure is `compile_error`), and the link (failure is `compile_error`). All three use the same flag list.
- `VerifyResult.compile_cmd` holds the command that failed, or the link command when all three steps pass.
- A compile timeout is `compile_error` when it happens on the candidate and `harness_error` when it happens on the test file. Both use `COMPILE_TIMEOUT_S = 60`.

**Output capture**

- Each stream keeps at most 1 MB: the first 512 KB and the last 512 KB, with a note in between. The completion marker is printed last, so the tail keeps it visible. This refines the spec's single cap, which would drop the marker from long output.

**Classifier**

- `classify_run(stdout, stderr, exit_code, timed_out, nonce)` is pure. The nonce is a sixth argument, because the marker check needs it.

**Cleaning**

- Masked, in addition to the Phase 0 list: `BuildId: [0-9a-f]+`. The build ID changes between runs because the binary embeds the workdir path in its debug info. It is listed in `docs/harness.md`.
- The `sanitizer_summary` for UBSan is the first `runtime error:` line. The UBSan `SUMMARY:` line is "undefined-behavior" and says little.
- The `sanitizer_summary` for LSan is `LeakSanitizer: <text>`, with the trailing period removed.

**Fixtures for sanitizer tests**

- The buggy effect must cross the function boundary. Write-past-malloc keeps its buffer in an external-linkage global. The leak passes its pointer to `sink_ptr`, defined in the test file. No candidate uses `volatile`.
- Candidates that call `fork()` define `_POSIX_C_SOURCE`, because strict `-std=c11` hides it.

**Budget**

- Original assignment guideline: about 500 lines for the whole core. This covers all core code, not only the harness.
- SPEC.md harness target: the Constraints section says the harness code, excluding tests and cases, should be about 250 lines. The Phase 0 target was about 300 code lines in `verifyloop/`, excluding docstrings, comments and blank lines.
- Actual at the end of Phase 3: 441 code lines (`toolchain.py` 322, `case.py` 119). The Phase 3 report proposed cuts. The Phase 3 review decided not to cut features.
- **New budget: about 450 code lines for `case.py` and `toolchain.py` together.** Both are at about 441 now.
- Why we exceed the original guideline: the verification layer is the product. The spec's own feature list (three-step compile, TSan preflight, bounded output capture, a classifier that stays pure, deterministic cleaning, and the sanitizer summaries) cannot fit in 250 lines without dropping features the spec requires.
- Free cuts already made in Phase 4: `new_nonce` is inlined, and shadow-byte removal is one regex.
- Budgets for later phases: `cli.py` about 60 lines. The LLM client and retry loop about 150 lines. The benchmark runner about 100 lines.

## Decisions (Phase 4)

**Cleaning (start of Phase 4)**

- Stack frames that have no source location are dropped from cleaned output. Those are libc, allocator interceptor and startup frames. Frames with a location keep it, and their `(test_bin+0x...)` and `(BuildId: ...)` suffixes are stripped. Frame numbers are kept as printed. The raw output is unchanged in `raw_stdout` and `raw_stderr`.
- The shadow-byte block is removed with one regex.
- `new_nonce` is inlined.

**Harness bug found by the starter cases (fixed)**

- `_build` compiled `case.test` even when `test="hidden"` was asked for, so the hidden test was never compiled. Starter tests showed it as `harness_error`. Earlier, the "buggy does not pass hidden" check had passed for that wrong reason. `_build` now takes the test filename. A regression test (`test_hidden_test_is_the_one_compiled_and_run`) proves that the hidden test is the one compiled and run.

**Naive fix for case 01 (changed from the spec)**

- The spec's naive fix is `malloc(total + 1)` with `total = n - 1` kept. It is **not caught** under ASan: with `n == 0`, `total + 1` is 0, and `malloc(0)` returns a one-byte allocation that ASan accepts, so the terminator write is in bounds and nothing is reported. It is still undefined behaviour by the C standard. The fixture is kept as a note in `naive_fixes/01_heap_overflow.c`.
- The naive fix used for the suite is a common over-correction: `if (n == 0) return NULL;` in front of the otherwise correct length calculation. It passes the visible test, and the hidden test's `n == 0` case dereferences NULL. The hidden stage is `sanitizer` (UBSan's nonnull check fires first).

**Recorded naive stages** (`tests/fixtures/naive_fixes/manifest.json`)

| Case | Visible | Hidden | Notes |
| --- | --- | --- | --- |
| 01 | ok | sanitizer | NULL guard; UBSan nonnull check |
| 02 | ok | sanitizer | `a + (b - a) / 2`; UBSan overflow on `b - a` |
| 03 | sanitizer | sanitizer | Index loop re-reads `size()`; UBSan overflow on doubling |
| 04 | ok | test_fail | Atomic, not reset; second call returns 41000 |

- For 03 the naive fix fails the visible test, not by timing out. It visits appended elements, the value doubles on each pass, and it overflows.
- The `volatile` variant of 04 (`04_data_race_volatile.c`) is kept deliberately. It fails the visible test under TSan with a data race. This is the one fixture where `volatile` is the point of the case.

**Buggy stages worth noting**

- 02 buggy: the visible test gives UBSan `signed integer overflow`. The hidden test gives `test_fail` (`midpoint(INT_MIN, INT_MAX)` returns 0), not a sanitizer report, because `INT_MIN + INT_MAX` does not overflow.
- 01 buggy, hidden: stage `sanitizer`, from `allocation-size-too-big` in `malloc(SIZE_MAX)`. The visible test gives `heap-buffer-overflow` with the object-size flag in place.
- 03 buggy, hidden: stage `sanitizer`, from UBSan overflow on the spare-capacity case, not from a use-after-free.

**Standards**

- All cases keep the standard from the spec: c11 for 01, 02 and 04, and c++17 for 03. Nothing needed changing.

**Deferred**

- `NOTES.md` is written in Phase 6, after the outputs are final. The starter-case suite does not check for it.

## Decisions (Phase 5)

**Case 01: unsigned wraparound**

- `case.json` for 01 adds `"extra_flags": ["-fsanitize=unsigned-integer-overflow"]`. Unsigned wraparound is legal C, so `-fsanitize=undefined` does not report it. The flag is clang-only. The NOTES.md for 01 will mention it in Phase 6.
- The case 01 naive fix is the spec's: `malloc(total + 1)` with `total = n - 1` kept. The NULL-guard variant is kept only as a comment in the fixture.
- Before and after, from `verify`:

| Check | Before (NULL-guard naive, no flag) | After (spec naive, with flag) |
| --- | --- | --- |
| buggy, visible | sanitizer: `heap-buffer-overflow` | same |
| buggy, hidden | sanitizer: `allocation-size-too-big` (`malloc(SIZE_MAX)`) | sanitizer: UBSan `unsigned integer overflow: 0 - 1` at `buggy.c:6:22` |
| naive, visible | ok | ok |
| naive, hidden | sanitizer: UBSan nonnull, on `strcmp(NULL)` | sanitizer: UBSan `unsigned integer overflow: 0 - 1` at `buggy.c:15:22` |
| reference, visible / hidden | ok / ok | ok / ok |

- Without the flag, the spec's naive fix passes the hidden test. ASan accepts it because `malloc(0)` gets a one-byte block. This is recorded for the README.

**Cleaning**

- Absolute paths outside the workdir are shortened to `basename:line[:col]`, for example `/usr/include/string.h:157:33` becomes `string.h:157:33`. The rule is `_ABS_LOC`.
- Truncation always keeps the key line. The key line is the SUMMARY line, or for UBSan the first `runtime error:` line. If the cut removed it, it is appended after the truncation marker. Tests cover a cut of case 03's real output and a long UBSan runtime line.

**CLI**

- `verifyloop/cli.py` exposes `main(argv) -> int`. `python -m verifyloop.cli` runs it.
- Exit codes: 0 passed, 1 candidate failed, 2 harness error or invalid case, including a missing case directory or source file.
- Human output: verdict line, then the sanitizer summary in bold directly under it, then the checks, then the cleaned output after `---`. This moves the summary above the checks, from the spec's example, because the summary is what a reader needs first.
- Colour is used only when stdout is a TTY and `NO_COLOR` is unset. Blank lines in the output are not indented.
- `--json` prints `VerifyResult.to_dict()` as indented JSON. Its exit code is the same as the human output's.

**Budget**

- `case.py` and `toolchain.py` together: 451 code lines, one over the ~450 target.
- `cli.py`: 62 code lines, against the ~60 budget.
