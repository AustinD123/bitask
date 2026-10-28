# bitask: verification harness (layer 1)

Layer 1 of the ByteAsk prototype. `verifyloop` decides whether a C or C++ candidate compiles under `-Wall -Werror`, runs without sanitizer reports, and passes its tests. Later layers add a model that proposes fixes and a retry loop around this check; neither is in this layer. The design is in [SPEC.md](SPEC.md). The reference is [docs/harness.md](docs/harness.md), and the non-obvious toolchain findings are in [docs/findings.md](docs/findings.md).

## Environment

Everything runs in Docker. Results are only meaningful inside the container.

- Base image: `ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac`
- clang: `clang-18` package `1:18.1.3-1ubuntu1` (reports `Ubuntu clang version 18.1.3`)
- Sanitizer runtimes: `libclang-rt-18-dev` `1:18.1.3-1ubuntu1`
- Tested on Windows 11, Docker Desktop 29.1.5, WSL2 kernel `6.6.87.2-microsoft-standard-WSL2`

## Quickstart

```bash
docker build -t verify-harness .
docker run --rm --cap-add SYS_PTRACE --network none -v "$PWD":/work:ro verify-harness \
    python3 -m pytest -v -p no:cacheprovider
```

`python3 -m pytest` rather than `pytest`: the image has a venv with the LLM SDKs, and the bare `pytest` binary runs outside it.

Run the sanitizer smoke check, which compiles five small programs with the harness's flags:

```bash
docker run --rm --cap-add SYS_PTRACE --network none -v "$PWD":/work:ro verify-harness \
    bash smoke/run_smoke.sh all
```

Run the CLI on a starter case:

```bash
docker run --rm --cap-add SYS_PTRACE --network none -v "$PWD":/work:ro verify-harness \
    python3 -m verifyloop.cli verify --case bench/cases/01_heap_overflow
```

Flags. `--cap-add SYS_PTRACE` is needed for LeakSanitizer on some hosts. `--network none` is deliberate: compiled code is untrusted and must not reach the network. The repo is mounted read-only, and workdirs live in `/tmp`. On Git Bash, prefix commands with `MSYS_NO_PATHCONV=1` so the volume path is not rewritten.

## CLI

```bash
python -m verifyloop.cli verify --case DIR [--source FILE | --reference] [--hidden] [--json] [--keep-workdir]
```

`--source` names a candidate file (default: the case's editable file). `--reference` uses the case's reference fix. `--hidden` runs the hidden test. `--json` prints the full result as JSON. Exit codes are `0` passed, `1` candidate failed, `2` harness error or invalid case.

A failing buggy case (visible test):

```
FAIL [sanitizer]  01_heap_overflow (visible test, 0.95s)
  AddressSanitizer: heap-buffer-overflow buggy.c:16:8 in join_words
  ✓ compiled   ✗ sanitizers clean   – ran to completion   – tests passed
  ---
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

The same case with its reference fix:

```
PASS  01_heap_overflow (visible test, 0.55s)
  ✓ compiled   ✓ sanitizers clean   ✓ ran to completion   ✓ tests passed
```

The sanitizer summary sits under the verdict, because it is the line a reader needs first. Colour is used only on a terminal, and `NO_COLOR` turns it off.

## How the fix loop works

Layer 2 asks a language model to fix the buggy file, then checks the fix with the same harness.

1. **Attempt 1** sends a short system prompt, the buggy file, the header and the visible test. The hidden test is never sent.
2. The **last fenced code block** in the reply is the candidate. No block is a failed attempt.
3. **Guardrails** reject a candidate that mentions `no_sanitize`, `__asan`, `VERIFY_NONCE`, or a `#pragma` diagnostic, clang or GCC directive. A rejected candidate is not compiled.
4. Otherwise `verify()` runs the **visible** test. A pass stops the loop.
5. A **retry** sends the original task, the previous attempt, and only the latest cleaned failure. Older attempts are not sent.
6. After the loop (at most `--max-attempts`), the first candidate and the final candidate each run on the **hidden** test, recorded separately.

Every attempt is logged to `out/runs/` with its prompt, reply, code, verdict, tokens, latency and whether it was a cache hit.

**One-shot** is attempt 1 of the same run, so the benchmark costs no extra call. **Trials** are part of the cache key, so trial 2 is a real repeat, not a cache hit. Replies are cached in `out/cache/`, so a re-run of the same command makes no API call.

## Groq setup

The default provider is Groq's free tier through its OpenAI-compatible API. Put the key in `.env`, which is git-ignored:

```bash
cp .env.example .env
# then edit .env and set LLM_API_KEY=gsk_...
```

The fix and bench commands read it with `--env-file .env`. You can also export the variables in your shell instead; the commands accept either.

| variable | default | meaning |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` (any OpenAI-compatible API) or `anthropic` |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | used only by `openai` |
| `LLM_API_KEY` | none | the API key |
| `GROQ_API_KEY` | none | the API key, used if `LLM_API_KEY` is unset |
| `LLM_MODEL` | `openai/gpt-oss-20b` | the default `--model` for `fix` |

**One key.** A single key is used, from `LLM_API_KEY` or `GROQ_API_KEY`. Groq's limits are per organisation, so rotating keys does not add quota.

**Limits.** Roughly 8K tokens per minute and 200K tokens per day per model, resetting at UTC midnight (check the Limits page in the Groq console). Per-minute limits are waited out, using the `retry-after` header, up to three retries.

## Fix and bench commands

Both run LLM-generated code, so they run in a container **with network access**, unlike the tests. The container needs a writable `out/`:

```bash
mkdir -p out
docker run --rm --env-file .env -v "$PWD":/work:ro -v "$PWD/out":/work/out verify-harness \
    python3 -m verifyloop.cli fix --case bench/cases/02_signed_overflow --model openai/gpt-oss-20b

docker run --rm --env-file .env -v "$PWD":/work:ro -v "$PWD/out":/work/out verify-harness \
    python3 -m verifyloop.cli bench --models openai/gpt-oss-20b,openai/gpt-oss-120b --trials 2
```

`--env-file .env` passes every variable in `.env` into the container. Without the file, `-e LLM_API_KEY` passes one host variable. `--network` is not given, so the default bridge network is used.

`fix` prints one line per attempt, then a coloured diff, the checks that passed, and the hidden-test result. Exit code 0 means it passed the visible test. `bench` runs every case × model × trial, and `--cases '0[1-5]*'` selects a subset. It writes `out/results/results.json` and `out/results/results.md`. When the daily limit runs out, it saves progress, prints `daily limit reached for <model>; re-run after reset to resume`, and exits with code 0.

### Results

The results table comes from the real run and is added once that run is complete.

## Project layout

```
bitask/
  Dockerfile                   pinned base image, clang-18, sanitizer runtimes
  SPEC.md                      the spec, with its decisions by phase
  README.md                    this file
  docs/
    harness.md                 full reference: pipeline, case format, flags, cleaning, stages
    findings.md                non-obvious toolchain findings, with evidence
  verifyloop/
    case.py                    Case, load_case(), validation
    toolchain.py               verify(), classify_run(), clean_output(), VerifyResult
    llm.py                     complete(): cache, 429 retries, MockProvider
    loop.py                    fix(): attempts, guardrails, compact retries, hidden test, logs
    bench.py                   run_bench(): one-shot vs loop table and pass rates
    cli.py                     verify, fix and bench subcommands
  bench/
    common/check.h             CHECK macros and the completion marker
    cases/
      01_heap_overflow/        case.json, lib.h, buggy.c, reference_fix.c, test.c, hidden_test.c, NOTES.md
      02_signed_overflow/
      03_iterator_invalidation/
      04_data_race/
  tests/
    test_case_loading.py       loader and validation
    test_toolchain.py          verify(), classifier, cleaning, determinism
    test_starter_cases.py      every case in bench/cases, parametrised
    test_cli.py                exit codes, output format, colour rules
    fixtures/mini_case/        tiny synthetic case for harness tests
    fixtures/naive_fixes/      naive fixes and manifest.json
  smoke/                       sanitizer smoke programs and runner
  scripts/fix-aslr.{sh,ps1}    lowers vm.mmap_rnd_bits in the Docker Desktop VM
```

## How a pass is decided

Full detail is in [docs/harness.md](docs/harness.md), sections 1, 6 and 7.

- **Compile in three steps.** The test file, then the candidate, then the link, all with `-Wall -Werror` and the sanitizer flags. A test file that fails to compile is a case bug (`harness_error`). A candidate that fails is `compile_error`.
- **Run each test once per `runs`.** Each run gets a fresh nonce. The run must print `VERIFY_OK <nonce>` and exit 0.
- **Classify in a fixed order.** Timeout, then harness problems, then sanitizer reports (whatever the exit code), then check failures or a nonzero exit, then signals, then the completion marker.
- **Stop at the first failing run.** The result records which run failed and how many passed before it.
- **Clean the output.** The LLM-ready output drops libc frames, strips per-run addresses and PIDs, and keeps the SUMMARY line, even when truncated. The raw output is kept alongside it.

## Clang version

`clang-18` `1:18.1.3-1ubuntu1`, from the Ubuntu 24.04 archive, with `libclang-rt-18-dev` for the sanitizer runtimes. Run `clang-18 --version` in the container to confirm.

## Key findings

The full list, with evidence, is in [docs/findings.md](docs/findings.md). These three shaped the case design most.

**ASan accepts the spec's naive fix for case 01.** `malloc(total + 1)` with the underflow kept passes the hidden test under ASan, because `malloc(0)` returns a one-byte block and the terminator write is in bounds. `-fsanitize=unsigned-integer-overflow` reports the wrap at the `n - 1` line, so case 01 sets it. See [finding 1](docs/findings.md#1-asan-accepts-the-naive-malloc0-fix-fsanitizeunsigned-integer-overflow-catches-it).

**UBSan's object-size check hides ASan's heap-overflow report.** With both sanitizers on, a heap overflow is reported first as UBSan's weaker "insufficient space". The harness adds `-fno-sanitize=object-size`, so ASan's `heap-buffer-overflow`, with its allocation stack, is the report. The ablation output is in [finding 2](docs/findings.md#2-ubsans-object-size-check-pre-empts-asans-heap-buffer-overflow).

**At `-O1`, a heap bug whose result never escapes is deleted.** The unused `malloc` and the out-of-bounds store are removed before ASan instruments them, so the binary exits 0 with nothing to report. Fixtures must make the effect observable across the function boundary. See [finding 3](docs/findings.md#3--o1-deletes-buggy-code-whose-result-never-escapes).

## Line budget

Actual counts, in `verifyloop/` (code lines, excluding docstrings, comments and blank lines): `case.py` 122, `toolchain.py` 338. Together that is 460 against a budget of about 450, and the Layer 1 spec's `cli.py` budget of about 60 is exceeded at 127 (62 before the `fix` and `bench` subcommands).

Layer 2 modules, against the budgets in its spec: `llm.py` 148 against about 80 , `loop.py` 117 against about 100, `bench.py` 97 against about 100. The budgets were not trimmed to hit.

The original assignment's guideline is about 500 lines for the whole core. The spec's own harness target was about 250. The lines went into verification, because it is the product: the spec's features (three-step compile, a TSan preflight, bounded output capture, a pure classifier, deterministic cleaning, and the sanitizer summaries) cannot be dropped without losing what the harness is for.

## Limitations

- **Linux and Docker only.** Sanitizer behaviour differs across OSes, so macOS and Windows are not supported. The development host is Windows 11 with Docker Desktop on WSL2.
- **No MemorySanitizer and no Valgrind.** Both are out of scope.
- **Single-file cases only.** Each case has one editable file. Multi-file projects are a later kind.
- **The completion marker is not adversarially secure.** `VERIFY_NONCE` is in the candidate's environment, so code that wants to pass can print the marker. The marker guards against accidental early exits, not deliberate cheating. A later phase may add a static check.
- **`setsid` can escape `killpg`.** A candidate that starts a new session can leave its children running after a timeout. The real fix is one container per run, which is out of scope.
- **The TSan ASLR fix resets when Docker Desktop restarts.** Run `scripts/fix-aslr.sh` or `scripts/fix-aslr.ps1` again after each restart. The preflight reports `harness_error` if the value is still too high.
- **The sanitizer options are fixed.** Cases cannot change them, and `halt_on_error` is mostly redundant under `-fno-sanitize-recover=all`.
- **The fix and bench commands run LLM-generated code in a container with network access.** The candidate is compiled and run with the network on, so a bad reply could reach the network. The guardrails reject some patterns, but they are not a sandbox. Use these commands on a machine where that is acceptable. The tests stay offline.
- **The benchmark covers only the ten starter cases.** It is not a real-world corpus, and two trials per model is a small sample. Treat the pass rates as indicative.

## Next steps

The planned next kind is a `project` case, with multi-file code and build systems. The harness would reuse `classify_run()` and the cleaning rules unchanged.

Real-world cases will be picked from the public C/C++ LLM benchmark catalogue at [ByteAsk/C-CppBench](https://github.com/ByteAsk/C-CppBench), which lists 96 benchmarks. It is a README, not runnable cases. The candidates for the real-world track are:

- **ARVO**: reproducible OSS-Fuzz C/C++ memory bugs, sanitizer-driven like ours.
- **Defects4C**: executable real C/C++ bugs with test-based repair validation.
- **BugsCpp**: real C/C++ bugs packaged with build, test and coverage tooling.
- **VulnLoc / ExtractFix**: small C memory-safety repair datasets.

They need a `project` case kind, which is not implemented yet. Layer 1 accepts only `single_file`. The design is in [SPEC.md](SPEC.md), under "Future: real-world track".

## Documentation

- [SPEC.md](SPEC.md): the design, the phases, and the decisions made in each phase.
- [docs/harness.md](docs/harness.md): the full reference. Pipeline, case format, compile flags, environment variables, classification, stages, cleaning, troubleshooting, and how to add a case.
- [docs/findings.md](docs/findings.md): eight findings with evidence and the change each one caused.
- `bench/cases/*/NOTES.md`: for each case, the bug, the sanitizer output, the reference fix, the naive fix, and the stage tables.
