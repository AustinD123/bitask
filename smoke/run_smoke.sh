#!/bin/bash
# Sanitizer smoke check, run inside the container before any harness code.
# Compiles each program with the exact flags from SPEC.md Step 2 and reports
# the exit code, wall time, sanitizer markers and SUMMARY line of each run.
# Usage (inside container): bash smoke/run_smoke.sh [tsan|asan|asan-only|ubsan|lsan|all]
set -u
which=${1:-all}
out=$(mktemp -d /tmp/smoke.XXXXXX)
src=$(cd "$(dirname "$0")" && pwd)

echo "clang: $($CC --version | head -1)"
echo "kernel: $(uname -r)  mmap_rnd_bits: $(cat /proc/sys/vm/mmap_rnd_bits)"

# run_one <source stem> <sanitizers> <extra compile flags>
run_one() {
    name=$1; sanitizers=$2; extra=$3
    bin="$out/$name.$(echo "$sanitizers" | tr ',' '_')"
    # Same flag set as the harness compile step (SPEC.md, Step 2).
    if ! $CC -std=c11 -g -O1 -fno-omit-frame-pointer \
            -fsanitize="$sanitizers" -fno-sanitize-recover=all \
            -Wall -Werror $extra "$src/$name.c" -o "$bin"; then
        echo "[$name | $sanitizers] COMPILE FAILED"; return 1
    fi
    export ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:symbolize=1:color=never
    export UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1:color=never
    export TSAN_OPTIONS=halt_on_error=1:second_deadlock_stack=1:color=never
    start=$(date +%s.%N)
    "$bin" > "$bin.stdout" 2> "$bin.stderr"
    code=$?
    end=$(date +%s.%N)
    printf '[%s | %s] exit=%d time=%.2fs\n' "$name" "$sanitizers" "$code" "$(echo "$end - $start" | bc)"
    if grep -q 'CHECK failed' "$bin.stderr"; then
        echo "    HARNESS_ERROR (TSan startup CHECK, not a candidate failure):"
        grep -m1 'CHECK failed' "$bin.stderr" | sed 's/^/      /'
    fi
    grep -m2 -E 'ERROR: AddressSanitizer|ERROR: LeakSanitizer|WARNING: ThreadSanitizer|runtime error:' "$bin.stderr" | sed 's/^/    marker: /'
    grep -m1 '^SUMMARY:' "$bin.stderr" | sed 's/^/    /'
    return 0
}

[ "$which" = all -o "$which" = tsan ]     && run_one tsan thread "-pthread"
[ "$which" = all -o "$which" = asan ]     && run_one asan address,undefined ""
[ "$which" = all -o "$which" = asan-only ] && run_one asan address ""
[ "$which" = all -o "$which" = ubsan ]   && run_one ubsan address,undefined ""
[ "$which" = all -o "$which" = lsan ]    && run_one leak address ""
echo "logs: $out"
