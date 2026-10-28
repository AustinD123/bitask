# Harness reference

This is the reference for `verifyloop`, layer 1 of the ByteAsk prototype. For the design and the decisions behind it, see [SPEC.md](../SPEC.md). For the non-obvious toolchain behaviour found while building it, see [findings.md](findings.md).

Every example output in this document is real output captured from the harness. Values that change between runs are shown as placeholders: `0xADDR`, `PID`, `TID`, `BUILDID`.

## 1. Pipeline overview

`verify(source, case)` runs these steps in order. The first failure ends the attempt.

1. **Preflight.** If the case uses `thread`, read `/proc/sys/vm/mmap_rnd_bits`. If it is above 28, return `harness_error` now, without compiling.
2. **Workdir.** Create a fresh temporary directory. Copy the case's header (`lib.h` or `lib.hpp`) and the chosen test file into it. Write the candidate source under the editable filename, so compiler messages say `buggy.c:12`. The case directory is never written.
3. **Compile.** Three steps with identical flags: the test file with `-c` (failure is `harness_error`), the candidate with `-c` (failure is `compile_error`), then the link (failure is `compile_error`).
4. **Run.** Run the test binary `case.runs` times, in its own process group, with a fresh `VERIFY_NONCE` per run. Stop at the first run that does not pass.
5. **Classify.** Each run is classified by `classify_run()`, a pure function, using the rules in section 6.
6. **Clean.** Clean the failing run's output into the LLM-ready `output` field. The raw output is kept in `raw_stdout`, `raw_stderr` and `raw_compile_stderr`. Section 8 lists the rules.
7. **Summarise.** Extract `sanitizer_summary`, one line naming the sanitizer report.

## 2. Case format

Each case is a directory. The harness reads it and never writes to it.

```
bench/cases/01_heap_overflow/
  case.json          metadata (schema below)
  lib.h              declarations of the functions under test (lib.hpp for C++)
  buggy.c            implementation, no main(). The only file a fix may change.
  reference_fix.c    known-good version of buggy.c
  test.c             visible test: has main(), includes lib.h and check.h
  hidden_test.c      held-out test, never shown to a model
  NOTES.md           human explanation of the bug
```

For C++ cases the extensions are `.cpp` and `.hpp`. `buggy.cpp` and `reference_fix.cpp` use the same stem convention.

### `case.json` schema

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | Must equal the directory name |
| `title` | string | yes | Short human title |
| `lang` | `"c"` or `"cpp"` | yes | Selects `CC` or `CXX` |
| `std` | string | yes | Passed as `-std=`, for example `c11` or `c++17` |
| `editable` | string | yes | Filename of the editable source, for example `buggy.c` |
| `reference` | string | yes | Filename of the reference fix |
| `test` | string | yes | Visible test filename |
| `hidden_test` | string | yes | Hidden test filename |
| `sanitizers` | list of strings | yes | Non-empty subset of `address`, `undefined`, `thread` |
| `extra_flags` | list of strings | no, default `[]` | Appended to the compile command, for example `-pthread` |
| `runs` | integer | no, default `1` | How many times the test binary runs. All must pass. |
| `timeout_s` | number | no, default `10` | Per-run timeout in seconds |
| `expected_buggy_stage` | string | yes | Stage the buggy version must fail at. One of `compile_error`, `sanitizer`, `test_fail`, `crash`, `timeout`. |
| `description` | string | yes | One-sentence bug summary for humans |

### Validation rules

`load_case()` raises `CaseError` with a message naming the problem:

- Every required field is present, and every field has the right type. Booleans are not accepted as numbers.
- No unknown fields. This catches typos.
- `id` matches the directory name.
- `lang` is `c` or `cpp`, and `std` matches it: C standards are `c` or `gnu` plus digits, C++ standards are `c++` or `gnu++` plus digits.
- `editable`, `reference`, `test` and `hidden_test` are bare filenames, with no directory parts, that end in the extension for `lang`.
- Every referenced file exists, including the header.
- `sanitizers` is non-empty, has no duplicates, and names only known sanitizers. `thread` cannot be combined with `address`.
- `expected_buggy_stage` is a failure stage. `ok` and `harness_error` are rejected.
- `runs` is at least 1, and `timeout_s` is positive.

## 3. Test conventions

Every `test.c` and `hidden_test.c` includes `bench/common/check.h`. It provides:

- `CHECK(cond)`, `CHECK_EQ(actual, expected)` and `CHECK_STREQ(actual, expected)`. Each prints its location and exits.
- `verify_tests_passed()`, the completion marker. Call it as the last statement of `main()`.

Why `_exit()` and not `exit()`: `_exit()` skips `atexit` handlers, so LeakSanitizer does not run after a failed check. A plain test failure is never reported as a leak.

Why the nonce marker: the harness passes a fresh `VERIFY_NONCE` for each run and requires `VERIFY_OK <nonce>` on stdout. A binary that exits 0 without printing it is `test_fail`. This guards against accidental early exits such as a library calling `exit(0)`. **It does not stop adversarial code**, which can read the nonce from its environment. See the limitations in the README.

Rules for every test file: never use `assert()` (it disappears under `NDEBUG`), free everything you allocate, and make each check test one behaviour.

## 4. Compile flags

These flags are passed to every compile step. The reason for each is in the table.

| Flag | Why |
| --- | --- |
| `-std=<std>` | From `case.json`. Must match `lang`. |
| `-g` | Debug info, so sanitizer reports carry `file:line`. |
| `-O1` | Optimised enough to be realistic, not so much that the sanitizers miss bugs. Note: at `-O1`, a heap bug whose result never escapes can be optimised away entirely. See [findings.md](findings.md), finding 3. |
| `-fno-omit-frame-pointer` | Clean stack traces in sanitizer reports. |
| `-fsanitize=<list>` | From `case.json`, comma-joined. |
| `-fno-sanitize-recover=all` | Without it, UBSan reports and carries on, and the program exits 0. This flag is what makes UBSan fail. `halt_on_error` in `UBSAN_OPTIONS` is mostly redundant for this reason. |
| `-Wall -Werror` | A warning in the candidate is a `compile_error`. |
| `-fno-sanitize=object-size` | Added only when `address` and `undefined` are both on. UBSan's object-size check fires first on a heap overflow, with the weaker message `insufficient space`. ASan reports the same write as `heap-buffer-overflow`, with the allocation stack. See [findings.md](findings.md), finding 2. |
| `<extra_flags>` | From `case.json`. Case 01 adds `-fsanitize=unsigned-integer-overflow`, which catches unsigned wraparound. Case 03 adds `-D_GLIBCXX_ASSERTIONS`. Case 04 adds `-pthread`. |
| `-I <workdir>` | So `#include "lib.h"` finds the header copied into the workdir. |
| `-I <bench/common>` | So `#include "check.h"` finds the shared test header. Resolved from the package location. |

### Why case 01 needs `-fsanitize=unsigned-integer-overflow`

Unsigned wraparound is legal C, so `-fsanitize=undefined` does not report it. Without this flag, ASan accepts the naive fix `malloc(total + 1)` with `total = n - 1`. For `n == 0`, `total + 1` wraps to 0, `malloc(0)` returns a one-byte block, and the terminator write is in bounds. The flag reports the wrap at the `n - 1` line, before any allocation. See [findings.md](findings.md), finding 1.

## 5. Environment variables

Set for each run of the test binary. Nothing else is inherited except `PATH`, and `ASAN_SYMBOLIZER_PATH` when it is set in the container.

| Variable | Value | Why |
| --- | --- | --- |
| `VERIFY_NONCE` | fresh `secrets.token_hex(8)` per run | Read by `verify_tests_passed()`. See section 3. |
| `ASAN_OPTIONS` | `detect_leaks=1:halt_on_error=1:symbolize=1:color=never` | Leak detection on. Symbolised stacks. No colour codes. |
| `UBSAN_OPTIONS` | `print_stacktrace=1:halt_on_error=1:color=never` | Prints a stack trace and a `SUMMARY:` line. `halt_on_error` is mostly redundant; see the compile flags. |
| `TSAN_OPTIONS` | `halt_on_error=1:second_deadlock_stack=1:color=never` | Stop at the first race. Show both stacks for deadlocks. |
| `ASAN_SYMBOLIZER_PATH` | from the container, if set | Points ASan at `llvm-symbolizer-18`, so stacks have file and line. |

## 6. Classification

`classify_run(stdout, stderr, exit_code, timed_out, nonce)` applies these rules in order. The first match decides. It has no I/O, so it can be tested with fixed strings.

1. **Timed out:** `timeout`.
2. **A line contains `Sanitizer: CHECK failed` or `unexpected memory mapping`:** `harness_error`. This comes before the sanitizer markers because a TSan startup failure also writes to stderr, and the candidate is not at fault.
3. **A sanitizer marker is present** (`ERROR: AddressSanitizer`, `ERROR: LeakSanitizer`, `WARNING: ThreadSanitizer`, `runtime error:`): `sanitizer`, whatever the exit code. The sanitizer check comes before the exit code, because TSan and LSan can report a problem with a misleading exit code.
4. **A `CHECK FAILED`, `CHECK_EQ FAILED` or `CHECK_STREQ FAILED` line is present, or the exit code is above 0:** `test_fail`.
5. **Killed by a signal** (negative return code): `crash`, naming the signal.
6. **Exit code 0 without `VERIFY_OK <nonce>` on stdout:** `test_fail`.
7. **Otherwise:** the run passed.

Two consequences worth knowing:

- Under ASan, a segfault is reported as `ERROR: AddressSanitizer: SEGV`, so it is `sanitizer`, not `crash`. `crash` is mainly for `abort()` and similar.
- A TSan startup failure that dies with SIGSEGV (exit 139) is rule 2, `harness_error`, not rule 5, `crash`. See section 9.

## 7. Stages

| Stage | Meaning | `passed` |
| --- | --- | --- |
| `ok` | Compiled, and every run passed | yes |
| `compile_error` | Candidate failed to compile or link | no |
| `sanitizer` | A sanitizer report, from any run | no |
| `test_fail` | A check failed, the exit code was above 0, or the completion marker was missing | no |
| `crash` | Killed by a signal that no sanitizer caught | no |
| `timeout` | Exceeded `timeout_s` | no |
| `harness_error` | An environment problem, not the candidate's fault | no |

`VerifyResult.checks` records how far the attempt got. Each check is `true`, `false`, or `null` if it was never reached.

| Stage | compiled | ran_to_completion | sanitizers_clean | tests_passed |
| --- | --- | --- | --- | --- |
| `ok` | true | true | true | true |
| `compile_error` | false | null | null | null |
| `sanitizer` | true | null | false | null |
| `test_fail` | true | true | true | false |
| `crash` | true | false | true | null |
| `timeout` | true | false | true | null |
| `harness_error` | true or null | null | null | null |

Real cleaned output for each stage. Each example comes from a real run of the harness.

**`ok`.** The output is empty, because there is nothing to report.

**`compile_error`.** The candidate `buggy.c` has `return a + b }`, which is missing a semicolon:

```
buggy.c:2:37: error: expected ';' after return statement
    2 | int add(int a, int b) { return a + b }
      |                                     ^
      |                                     ;
1 error generated.
```

**`sanitizer`.** The first example in section 8 shows a real ASan report.

**`test_fail`.** A visible check failed:

```
CHECK_EQ FAILED: add(2, 3) == 5 (got -1, expected 5) at test.c:6
```

A candidate that calls `exit(0)` before the test finishes gives this message instead:

```
test exited 0 without reaching completion marker
```

**`crash`.** The candidate calls `abort()`:

```
killed by SIGABRT
```

**`timeout`.** The candidate loops forever, with `timeout_s` set to 2:

```
timed out after 2s (run 1 of 1)
```

**`harness_error`.** The compiler named by `CC` does not exist:

```
compiler not found: /nonexistent/clang
```

A TSan startup failure, on a kernel with `vm.mmap_rnd_bits` at 32, is also `harness_error`. Its stderr contains this line, which the classifier reports as `sanitizer internal failure: ...`:

```
ThreadSanitizer: CHECK failed: tsan_platform_linux.cpp:282 "((personality(old_personality | ADDR_NO_RANDOMIZE))) != ((-1))" (0xffffffffffffffff, 0xffffffffffffffff) (tid=10)
```

## 8. Output cleaning

`clean_output()` makes the output deterministic and short enough for a model. Its rules apply in this order:

1. Strip ANSI colour codes.
2. Remove the workdir path, with its trailing separator. Compiler and sanitizer paths then read `buggy.c:12`.
3. For a sanitizer report, keep from the first report line through the `SUMMARY:` line. Text before and after is dropped. In real ASan output the SUMMARY line comes before the shadow-byte block, so this step also drops the block.
4. Remove the shadow-byte block, with one regex from its header to the `SUMMARY:` line.
5. Mask per-run values. The list is below.
6. Shorten absolute paths outside the workdir to their basename with line and column. `/usr/include/string.h:157:33` becomes `string.h:157:33`.
7. Drop stack frames that have no source location. A frame is a line starting `#N `. Frames without a `file.c:`, `file.cpp:`, `file.h:` or `file.hpp:` location are libc, allocator or startup frames. Frames that remain have their `(test_bin+0x...)` and `(BuildId: ...)` suffixes stripped. Frame numbers stay as printed, so a gap shows where a frame was dropped.
8. Truncate to `max_chars` (4000 for `VerifyResult.output`), appending `[... N chars truncated]`. The key line is always kept: the SUMMARY line, or for UBSan the first `runtime error:` line. If the cut removed it, it is appended after the marker.

The raw output is not changed. It is in `raw_stdout`, `raw_stderr` and `raw_compile_stderr`.

### Before and after, from a real ASan report

Raw `raw_stderr`, for case 01's buggy version. The paths and addresses are real:

```
=================================================================
==11==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000018 at pc 0x55bbec6f89ed bp 0x7fff6b002930 sp 0x7fff6b002928
WRITE of size 1 at 0x502000000018 thread T0
    #0 0x55bbec6f89ec in join_words /tmp/verify-insl236v/buggy.c:16:8
    #1 0x55bbec6f8b47 in main /tmp/verify-insl236v/test.c:9:17
    #2 0x7fb76041d1c9  (/lib/x86_64-linux-gnu/libc.so.6+0x2a1c9) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #3 0x7fb76041d28a in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x2a28a) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #4 0x55bbec61f354 in _start (/tmp/verify-insl236v/test_bin+0x2c354) (BuildId: fe34b8ef712b37f8c1cd8b9db3d0ca2165001f94)

0x502000000018 is located 0 bytes after 8-byte region [0x502000000010,0x502000000018)
allocated by thread T0 here:
    #0 0x55bbec6ba1a3 in malloc (/tmp/verify-insl236v/test_bin+0xc71a3) (BuildId: fe34b8ef712b37f8c1cd8b9db3d0ca2165001f94)
    #1 0x55bbec6f8802 in join_words /tmp/verify-insl236v/buggy.c:8:17
    #2 0x55bbec6f8b47 in main /tmp/verify-insl236v/test.c:9:17
    #3 0x7fb76041d1c9  (/lib/x86_64-linux-gnu/libc.so.6+0x2a1c9) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #4 0x7fb76041d28a in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x2a28a) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #5 0x55bbec61f354 in _start (/tmp/verify-insl236v/test_bin+0x2c354) (BuildId: fe34b8ef712b37f8c1cd8b9db3d0ca2165001f94)

SUMMARY: AddressSanitizer: heap-buffer-overflow /tmp/verify-insl236v/buggy.c:16:8 in join_words
Shadow bytes around the buggy address:
  ...
```

Cleaned `output`:

```
==PID==ERROR: AddressSanitizer: heap-buffer-overflow on address 0xADDR at pc 0xADDR bp 0xADDR sp 0xADDR
WRITE of size 1 at 0xADDR thread T0
    #0 0xADDR in join_words buggy.c:16:8
    #1 0xADDR in main test.c:9:17

0xADDR is located 0 bytes after 8-byte region [0xADDR,0xADDR)
allocated by thread T0 here:
    #1 0xADDR in join_words buggy.c:8:17
    #2 0xADDR in main test.c:9:17

SUMMARY: AddressSanitizer: heap-buffer-overflow buggy.c:16:8 in join_words
```

The cleaned version drops the libc frames, the `malloc` frame and `_start`, strips the BuildIds, masks the addresses and PID, and removes the workdir path. The `SUMMARY` line stays.

### Values that are masked

| Pattern | Replacement | Source |
| --- | --- | --- |
| `0x[0-9a-f]{6,}` | `0xADDR` | Heap and stack addresses, which change with ASLR. Shorter hex values such as `0x2a1c9` are deterministic and are kept. |
| `==\d+==` | `==PID==` | ASan and LSan line prefix |
| `pid=\d+` | `pid=PID` | TSan report header |
| `tid=\d+` | `tid=TID` | TSan thread lines |
| `BuildId: [0-9a-f]+` | `BuildId: BUILDID` | The build ID hashes the binary, and the binary embeds the workdir path in its debug info, so two runs of identical source give different IDs. Found by the determinism test. |

Not masked, because they are deterministic: code offsets such as `test_bin+0xdeca6`, `libc.so.6+0x2a1c9`, and the `(test_bin+0xADDR)` form in TSan's `Location is` line.

### Output capture

Each of stdout and stderr keeps at most 1 MB: the first 512 KB and the last 512 KB, with a note between them saying how many bytes were omitted. The last half is kept so the completion marker, printed last, survives. The rest of the stream is still read, so the candidate never blocks on a full pipe. Memory use stays bounded, even for a candidate that prints forever.

## 9. Troubleshooting

**LeakSanitizer fails in Docker with "encountered a fatal error".** Run with `--cap-add SYS_PTRACE`, as the README commands do. The flag is harmless where it is not needed.

**ThreadSanitizer aborts at startup.** On Docker Desktop, the default `vm.mmap_rnd_bits` is 32, and TSan needs 28 or lower. The symptom is a SIGSEGV with this line on stderr:

```
ThreadSanitizer: CHECK failed: tsan_platform_linux.cpp:282 "((personality(old_personality | ADDR_NO_RANDOMIZE))) != ((-1))"
```

The harness's preflight catches this before compiling, if it can read the value. If the preflight is skipped, the classifier reports `harness_error`. The fix is to lower the value inside the Docker Desktop VM:

```bash
sh scripts/fix-aslr.sh          # Git Bash, WSL, Linux or macOS host
```

```powershell
.\scripts\fix-aslr.ps1          # Windows PowerShell
```

Two things that do **not** work:

- `setarch $(uname -m) -R` fails with `Operation not permitted`. Docker's default seccomp profile blocks `personality(ADDR_NO_RANDOMIZE)`.
- `sudo sysctl` on the Windows host does nothing. The kernel that matters is the Docker Desktop VM's.

The fix resets when Docker Desktop restarts, so run the script again after each restart.

**Compiler not found.** `harness_error` with `compiler not found: <path>`. Check `CC` (C cases) or `CXX` (C++ cases). When neither is set, the harness falls back to `clang` or `clang++`, and those names exist only in the container if the `-18` symlinks are present.

**A test file does not compile.** `harness_error` with `test file failed to compile, this is a case bug`. The case itself is broken. The compiler's stderr follows in the output.

## 10. Adding a new case

1. Create `bench/cases/NN_name/` with `case.json`, `lib.h` (or `lib.hpp`), `buggy.c`, `reference_fix.c`, `test.c`, `hidden_test.c` and `NOTES.md`.
2. Keep `main()` out of the buggy and reference files. Only the tests have it.
3. Make the bug observable across the function boundary. The test must read back the value the buggy code produces, or the buggy code must return it. Do not use `volatile` in candidate code unless the case is about `volatile`. The optimiser can delete an unused heap allocation at `-O1`. See [findings.md](findings.md), finding 3.
4. Add a naive fix at `tests/fixtures/naive_fixes/<id>.<ext>`. It must pass the visible test (or record which stage it reaches) and fail the hidden test. Add an entry to `tests/fixtures/naive_fixes/manifest.json` with the visible and hidden stages.
5. Write `NOTES.md` with: the bug and its root cause, the real cleaned output of the buggy version, the reference fix and why it is correct, the naive fix and the hidden check that catches it, and the stage table.
6. Run the case's tests:

   ```bash
   docker run --rm --cap-add SYS_PTRACE --network none -v "$PWD":/work:ro verify-harness \
       pytest tests/test_starter_cases.py -k <case_id> -v -p no:cacheprovider
   ```

   Six tests should pass: buggy visible at the expected stage, buggy hidden not passing, reference visible and hidden both `ok`, the naive fix at its manifest stages, and the NOTES.md check.
7. Run the full suite once more, to confirm nothing else changed.

The starter-case suite is parametrised over `bench/cases/`, so a new directory is tested with no code changes. The naive-fix manifest is the one manual step.
