# bitask: verification harness (layer 1)

Layer 1 of the ByteAsk prototype. `verifyloop` decides whether a C or C++
candidate compiles under `-Wall -Werror`, runs without sanitizer reports,
and passes its tests. Later layers add an LLM that proposes fixes and a
retry loop; neither is in this layer. The full spec is in [SPEC.md](SPEC.md).

## Environment

Everything runs in Docker. Results are only meaningful inside the container.

- Base image: `ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac`
- clang: `clang-18` package `1:18.1.3-1ubuntu1` (reports `Ubuntu clang version 18.1.3`)
- Sanitizer runtimes: `libclang-rt-18-dev` `1:18.1.3-1ubuntu1`
- Tested on Windows 11, Docker Desktop 29.1.5, WSL2 kernel `6.6.87.2-microsoft-standard-WSL2`

## Quickstart

```bash
docker build -t verify-harness .
docker run --rm --cap-add SYS_PTRACE --network none -v "$PWD":/work:ro verify-harness bash smoke/run_smoke.sh all
```

Run the tests with (after Phase 4):

```bash
docker run --rm --cap-add SYS_PTRACE --network none -v "$PWD":/work:ro verify-harness pytest -v -p no:cacheprovider
```

Flags: `--cap-add SYS_PTRACE` is needed for LeakSanitizer. `--network none` is
deliberate: compiled code is untrusted and must not reach the network. The
repo is mounted read-only, and workdirs live in `/tmp`.

On Git Bash, prefix the command with `MSYS_NO_PATHCONV=1` so the volume path
is not rewritten.

## Troubleshooting

**ThreadSanitizer aborts at startup with `CHECK failed ... personality`
(or `unexpected memory mapping`).** TSan needs ASLR entropy at or below 28
bits. The Docker Desktop VM kernel defaults to 32. Lower it with:

```bash
sh scripts/fix-aslr.sh          # Git Bash, WSL, Linux or macOS host
```

```powershell
.\scripts\fix-aslr.ps1          # Windows PowerShell
```

The setting is held by the Docker Desktop VM kernel. It resets when Docker
Desktop restarts, so run the script again after each restart.

Two things that do **not** work here:

- `setarch $(uname -m) -R` fails with `Operation not permitted`, because
  Docker's default seccomp profile blocks `personality(ADDR_NO_RANDOMIZE)`.
- Running `sudo sysctl` on Windows does nothing. The kernel that matters is
  the Docker Desktop VM's.

**How this surfaces in the harness.** Until the classifier handles it, a TSan
startup `CHECK failed` makes the process die by SIGSEGV (exit 139), which
looks like a candidate `crash`. It is an environment problem and must be
reported as `harness_error` once the classifier exists.

**LeakSanitizer fails with "encountered a fatal error".** Run with
`--cap-add SYS_PTRACE`, as in the commands above.

## Sanitizer behaviour verified in this environment

Captured by `smoke/run_smoke.sh all` at `mmap_rnd_bits=28`:

| Program | Flags | Exit | Marker | SUMMARY line |
| --- | --- | --- | --- | --- |
| `smoke/tsan.c` | `thread -pthread` | 66 | `WARNING: ThreadSanitizer: data race` | `SUMMARY: ThreadSanitizer: data race ...` |
| `smoke/asan.c` | `address` | 1 | `ERROR: AddressSanitizer: heap-buffer-overflow` | `SUMMARY: AddressSanitizer: heap-buffer-overflow ...` |
| `smoke/asan.c` | `address,undefined` | 1 | `runtime error: store to address ... insufficient space` (UBSan) | `SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior ...` |
| `smoke/ubsan.c` | `address,undefined` | 1 | `runtime error: signed integer overflow` | `SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior ...` |
| `smoke/leak.c` | `address` | 1 | `ERROR: LeakSanitizer: detected memory leaks` | `SUMMARY: AddressSanitizer: 16 byte(s) leaked ...` |

Notes:

- The LeakSanitizer `SUMMARY:` line says `AddressSanitizer`, not
  `LeakSanitizer`. Match on the `ERROR: LeakSanitizer` line.
- With `address,undefined`, UBSan's object-size check fires before ASan does
  on a heap overflow. ASan alone reports `heap-buffer-overflow`.
- A heap overflow whose pointer never escapes is deleted at `-O1` (with the
  malloc/free pair), and no sanitizer fires. The smoke program stores the
  pointer in a volatile global to prevent this.
- TSan's report includes per-run `pid=` and `tid=` numbers. Output cleaning must mask them.
- Unsigned wraparound is legal C, so `-fsanitize=undefined` does not report it. Case 01 adds `-fsanitize=unsigned-integer-overflow` (clang only). Without it, ASan accepts the naive fix `malloc(total + 1)` with `total = n - 1`: for `n == 0`, `total + 1` wraps to 0, so `malloc(0)` returns a one-byte block and the terminator write is in bounds. With the flag, the wrap is reported at the `n - 1` line.
