# Findings

Non-obvious toolchain behaviour found while building layer 1. Each entry gives what we expected, what happened, the evidence (real captured output), and what changed as a result.

## 1. ASan accepts the naive malloc(0) fix; `-fsanitize=unsigned-integer-overflow` catches it

**Expected.** The case 01 naive fix, `malloc(total + 1)` with `total = n - 1` kept, fails the hidden test, which calls `join_words(NULL, 0, ',')`. The spec said the terminator write would overflow a zero-byte allocation.

**What happened.** It does not, under ASan. For `n == 0`, `total` is `SIZE_MAX`, so `total + 1` wraps to 0. `malloc(0)` returns a one-byte block, and the terminator write lands inside it. ASan reports nothing. The naive fix passes the hidden test. The behaviour is still undefined by the C standard, but no sanitizer sees it.

**Evidence.** Before the flag (same naive fix, `extra_flags` empty):

```
naive (spec), hidden, WITHOUT unsigned flag  stage=ok
```

With the flag:

```
naive (spec), hidden   stage=sanitizer
buggy.c:15:22: runtime error: unsigned integer overflow: 0 - 1 cannot be represented in type 'size_t' (aka 'unsigned long')
    #0 0xADDR in join_words buggy.c:15:22
    #1 0xADDR in main hidden_test.c:7:17

SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.c:15:22 
```

**What changed.** Case 01's `case.json` adds `-fsanitize=unsigned-integer-overflow`. The naive fix in `tests/fixtures/naive_fixes/01_heap_overflow.c` is the spec's version, with a comment recording this blind spot. The reference fix never wraps, so it needed no change. The README notes the gap.

## 2. UBSan's object-size check pre-empts ASan's heap-buffer-overflow

**Expected.** With `-fsanitize=address,undefined`, a heap overflow is reported as ASan's `heap-buffer-overflow`, which includes the allocation stack.

**What happened.** UBSan's object-size check fires first, on the same store, with the weaker message `insufficient space for an object`. It has no allocation stack.

**Evidence.** The same write-past-malloc candidate, with and without `-fno-sanitize=object-size`, from the Phase 3 ablation:

With `-fno-sanitize=object-size` (the harness default when `address` and `undefined` are both on):

```
==PID==ERROR: AddressSanitizer: heap-buffer-overflow on address 0xADDR at pc 0xADDR bp 0xADDR sp 0xADDR
WRITE of size 4 at 0xADDR thread T0
    #0 0xADDR in add buggy.c:8:17
    ...
SUMMARY: AddressSanitizer: heap-buffer-overflow buggy.c:8:17 in add
```

Without it:

```
SUMMARY: buggy.c:8:5: runtime error: store to address 0xADDR with insufficient space for an object of type 'int'
```

**What changed.** `_compile_flags()` adds `-fno-sanitize=object-size` when both `address` and `undefined` are on. A test checks this for four sanitizer sets, and the write-past-malloc test checks for `heap-buffer-overflow`.

## 3. -O1 deletes buggy code whose result never escapes

**Expected.** A candidate that writes one byte past a `malloc` block reports a heap overflow under ASan.

**What happened.** At `-O1`, clang deletes the unused `malloc`/`free` pair along with the out-of-bounds store. The binary has nothing left to report. ASan's instrumentation runs after this deletion, so it never sees the access.

**Evidence.** The same program, without and with the pointer escaping:

Pointer never escapes (`p` is used only for the store):

```
exit=0 stderr=''
```

Pointer stored in a volatile global, so the allocation must survive (this variant appears only in a scratch test, never in candidate code):

```
exit=1 first_line='================================================================='
```

**What changed.** Every fixture meant to trigger a sanitizer makes its effect observable. Either the pointer or value is returned to the test, or it goes to an external-linkage global, which the optimiser must keep. The write-past fixture in `tests/test_toolchain.py` uses an external-linkage global. The leak fixture passes its pointer to a function defined in the test file. No candidate uses `volatile`. The starter-case suite catches any regression: each buggy version must fail at its expected stage.

## 4. TSan fails at mmap_rnd_bits=32 with "CHECK failed", not "unexpected memory mapping"

**Expected.** The spec said TSan fails on high-entropy kernels with `unexpected memory mapping`, which the harness would report as `harness_error`. The documented fix was `setarch $(uname -m) -R`.

**What happened.** On the Docker Desktop WSL2 kernel, with `vm.mmap_rnd_bits=32`, TSan aborts during startup with a CHECK failure. The process dies with SIGSEGV. `setarch -R` does not help, because Docker's default seccomp profile blocks `personality(ADDR_NO_RANDOMIZE)`.

**Evidence.** With the default value of 32:

```
ThreadSanitizer: CHECK failed: tsan_platform_linux.cpp:282 "((personality(old_personality | ADDR_NO_RANDOMIZE))) != ((-1))" (0xffffffffffffffff, 0xffffffffffffffff) (tid=10)
Segmentation fault (core dumped)
```

The `setarch` workaround:

```
setarch: failed to set personality to x86_64: Operation not permitted
```

After `scripts/fix-aslr.sh` sets the value to 28:

```
[tsan | thread] exit=66 time=0.28s
    marker: WARNING: ThreadSanitizer: data race (pid=22)
    SUMMARY: ThreadSanitizer: data race /work/smoke/tsan.c:10:43 in worker
```

**What changed.** The preflight in `verify()` reads `/proc/sys/vm/mmap_rnd_bits` and returns `harness_error` before compiling, if the value is above 28. The classifier also treats any `Sanitizer: CHECK failed` line as `harness_error`, so the startup crash is never reported as a candidate `crash`. `scripts/fix-aslr.{sh,ps1}` lower the value, and the README and `docs/harness.md` describe the reset-on-restart behaviour. The `unexpected memory mapping` message is still detected, but this environment never produces it.

## 5. BuildId varies with the workdir path and breaks determinism

**Expected.** Running identical source twice gives identical sanitizer output, once the PIDs and addresses are masked.

**What happened.** The build ID is a hash of the binary. The binary embeds the workdir path in its debug info, and each run uses a new workdir, so the build ID differs between runs.

**Evidence.** The determinism test failed on this diff, comparing two runs of the same write-past source:

```
- (BuildId: c442906302f0e36f5af55b3736c5a8adc87e159b)
+ (BuildId: b3773942f8f7135d7c2ae5827f239bd0dce1be60)
```

**What changed.** `BuildId: [0-9a-f]+` is masked to `BuildId: BUILDID`. The frame-suffix rule then strips `(BuildId: ...)` from stack frames. The masked list is in `docs/harness.md`. Code offsets such as `test_bin+0xdeca6` are deterministic and are not masked.

## 6. LSan's SUMMARY line says AddressSanitizer

**Expected.** The LeakSanitizer summary names LeakSanitizer.

**What happened.** The summary line is `SUMMARY: AddressSanitizer: ...`, because LSan shares ASan's reporting code. The `ERROR:` line names it correctly.

**Evidence.**

```
==10==ERROR: LeakSanitizer: detected memory leaks
SUMMARY: AddressSanitizer: 16 byte(s) leaked in 1 allocation(s).
```

LSan also exits 1 by default, not 23.

**What changed.** Leaks are detected from the `ERROR: LeakSanitizer` line. `sanitizer_summary` reads `LeakSanitizer: 16 byte(s) leaked in 1 allocation(s)`, with the sanitizer name taken from the `ERROR:` line. Two tests check this.

## 7. Strict -std=c11 hides fork() and other POSIX functions

**Expected.** A candidate can call `fork()` under `-std=c11`, because `unistd.h` is included.

**What happened.** Under strict ISO mode, glibc hides POSIX declarations unless a feature macro such as `_POSIX_C_SOURCE` is set. Without it, `fork()`, `pid_t` and `_exit` are undeclared, and the candidate fails to compile.

**Evidence.**

```
c.c:6:5: error: use of undeclared identifier 'pid_t'
    6 |     pid_t child = fork();
      |     ^
c.c:7:9: error: use of undeclared identifier 'child'; did you mean 'while'?
...
4 errors generated.
```

**What changed.** Test fixtures that call `fork()` define `_POSIX_C_SOURCE 200809L` at the top. The timeout test depends on this. The finding matters for LLM-written candidates, which will use POSIX calls. The harness does not add the macro itself, so the standard stays as the case sets it.

## 8. The hidden-test bug: caught by the starter cases, not by the unit tests

**Expected.** The Phase 3 unit tests covered the hidden path, so `test="hidden"` was checked.

**What happened.** `_build()` always compiled `case.test`, the visible test, even when `test="hidden"` was asked for. The hidden test was never compiled. Two things made it invisible:

- The unit tests only ever passed the visible test name, so the hidden path was never exercised.
- The check "buggy does not pass the hidden test" passed for the wrong reason. The visible test file was missing from the workdir, so every hidden run reported `harness_error`, which counts as not passing.

**Evidence.** A starter-case run before the fix:

```
test file failed to compile, this is a case bug
clang-18: error: no such file or directory: 'test.c'
clang-18: error: no input files
assert 'harness_error' == 'ok'
```

**What changed.** `_build()` takes the test filename, and the compile steps use it. The regression test `test_hidden_test_is_the_one_compiled_and_run` passes a candidate that is correct on the visible test and wrong on the hidden one, and checks that the hidden result says `test_fail` with `add(0, 0) == 0`. A lesson for the process: a check that passes for the wrong reason is worse than a missing check. The starter-case suite was the first place where the hidden path ran at all.
