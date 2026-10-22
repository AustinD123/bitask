# Harness reference

This page is partial. It covers the parts of the harness that exist after Phase 3. The full reference is completed in Phase 6.

## Compile flags

Every flag the harness passes to the compiler, and why it is there. The same flags are used in all three compile steps (test object, candidate object, link).

| Flag | Why |
| --- | --- |
| `-std=<std>` | From `case.json`. The language standard must match `lang`. |
| `-g` | Debug info, so sanitizer reports carry `file:line`. |
| `-O1` | Optimised enough to be realistic, not so much that the sanitizers miss bugs. |
| `-fno-omit-frame-pointer` | Clean stack traces in sanitizer reports. |
| `-fsanitize=<list>` | From `case.json`, comma-joined. |
| `-fno-sanitize-recover=all` | Without it, UBSan reports and carries on, and the program exits 0. This flag is what makes UBSan fail. `halt_on_error` in `UBSAN_OPTIONS` is mostly redundant for the same reason. |
| `-Wall -Werror` | A warning in the candidate is a `compile_error`. |
| `-fno-sanitize=object-size` | Added only when both `address` and `undefined` are enabled. UBSan's object-size check fires first on a heap overflow, with a weaker message ("insufficient space"). ASan already reports the same write as `heap-buffer-overflow`, with the allocation stack. Verified: without this flag, the write-past-malloc case reports UBSan. With it, ASan reports. |
| `<extra_flags>` | From `case.json`, for example `-pthread`. |
| `-I <workdir>` | So `#include "lib.h"` finds the case header copied into the workdir. |
| `-I <bench/common>` | So `#include "check.h"` finds the shared test header. Resolved from the package location. |

## Environment variables

Set for each run of the test binary. Nothing else is inherited except `PATH` and, if it is set in the container, `ASAN_SYMBOLIZER_PATH`.

| Variable | Value | Why |
| --- | --- | --- |
| `VERIFY_NONCE` | fresh `secrets.token_hex(8)` per run | The test prints `VERIFY_OK <nonce>` at the end. This guards against accidental early exits. It does not stop adversarial code, which can read the nonce from its environment. |
| `ASAN_OPTIONS` | `detect_leaks=1:halt_on_error=1:symbolize=1:color=never` | Leak detection on. Symbolised stacks. No colour codes in the output. |
| `UBSAN_OPTIONS` | `print_stacktrace=1:halt_on_error=1:color=never` | UBSan prints a stack trace and a `SUMMARY:` line. `halt_on_error` is mostly redundant; see the compile flags above. |
| `TSAN_OPTIONS` | `halt_on_error=1:second_deadlock_stack=1:color=never` | Stop at the first race. Show both stacks for deadlocks. |

## Output cleaning

`clean_output()` makes sanitizer and compiler output deterministic, so the same bug gives the same text on every run.

Rules, applied in this order:

1. Strip ANSI colour codes.
2. Remove the workdir path, with its trailing separator.
3. For a sanitizer report, keep from its first report line through its `SUMMARY:` line. Text before and after is dropped.
4. Drop the shadow-byte block (one regex: from "Shadow bytes around the buggy address" to the `SUMMARY:` line).
5. Mask per-run values, listed below.
6. Drop stack frames that have no source location. A frame is a line starting `#N `. A frame without a `file.c:`, `file.cpp:`, `file.h:` or `file.hpp:` location is libc, the allocator or startup code, and is dropped. Frames that remain have their `(test_bin+0x...)` and `(BuildId: ...)` suffixes stripped. Frame numbers are kept as printed, so gaps show where frames were dropped.
7. Truncate to `max_chars`, appending `[... N chars truncated]`.

The raw output is never changed. It is kept in `raw_stdout` and `raw_stderr`.

Per-run values that are masked:

| Pattern | Replacement | Source |
| --- | --- | --- |
| `0x[0-9a-f]{6,}` | `0xADDR` | Heap and stack addresses, which change with ASLR. |
| `==\d+==` | `==PID==` | ASan and LSan line prefix. |
| `pid=\d+` | `pid=PID` | TSan report header. |
| `tid=\d+` | `tid=TID` | TSan thread lines. |
| `BuildId: [0-9a-f]+` | `BuildId: BUILDID` | Found by the determinism test. The binary embeds the workdir path in its debug info, so its build ID differs between runs of identical source. |

Not masked, because they are deterministic: code offsets such as `test_bin+0xdeca6`, `libc.so.6+0x2a1c9`, and short hex values under six digits.

## Output capture

Each of stdout and stderr keeps at most 1 MB. If the stream is longer, the first 512 KB and the last 512 KB are kept, with a note between them saying how many bytes were omitted. The last half is kept so the completion marker, printed last, survives. The rest of the stream is still drained, so the candidate never blocks on a full pipe.

## Classification

Rules are applied in order by `classify_run()`. The first match decides:

1. Timed out: `timeout`.
2. Any line containing `Sanitizer: CHECK failed` or `unexpected memory mapping`: `harness_error`. This comes before the sanitizer markers, because TSan's own startup failure also writes to stderr, and it is not a candidate failure.
3. Any sanitizer marker (`ERROR: AddressSanitizer`, `ERROR: LeakSanitizer`, `WARNING: ThreadSanitizer`, `runtime error:`): `sanitizer`, whatever the exit code.
4. Any `CHECK FAILED` / `CHECK_EQ FAILED` / `CHECK_STREQ FAILED`, or exit code above 0: `test_fail`.
5. Killed by a signal (negative return code): `crash`, naming the signal.
6. Exit code 0 without `VERIFY_OK <nonce>` on stdout: `test_fail`.
7. Otherwise the run passed.

Under ASan a segfault is reported as `ERROR: AddressSanitizer: SEGV`, so it is `sanitizer`, not `crash`. `crash` is mainly for `abort()` and similar.
