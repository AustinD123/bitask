# 01: heap buffer overflow in join_words

## The bug

`join_words` sizes its buffer as the separators plus the word lengths. That leaves no byte for the terminating `'\0'`, so the final store lands one byte past the block. With `n == 0` there is a second fault: `n - 1` underflows to `SIZE_MAX`, and `malloc(SIZE_MAX)` returns NULL, which the terminator store then dereferences.

## Sanitizer output, buggy version, visible test

The visible test joins three words, so the overflow is an ASan heap-buffer-overflow. The `-fno-sanitize=object-size` flag (added by the harness when `address` and `undefined` are both on) is what keeps UBSan from reporting it first.

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

## Reference fix

`total = n == 0 ? 0 : n - 1`, then `malloc(total + 1)`. The guard stops the underflow, and the `+ 1` makes room for the NUL. Nothing wraps for any input, so the case's `-fsanitize=unsigned-integer-overflow` flag never fires on it.

## Naive fix

The spec's naive fix is `malloc(total + 1)` with `total = n - 1` kept. It is the most natural half-fix: it adds the NUL byte and leaves the underflow.

- **Visible test (n == 3):** passes. No wraparound happens.
- **Hidden test (n == 0):** caught as `sanitizer`, by `-fsanitize=unsigned-integer-overflow`. The `n - 1` line wraps before any allocation.

```
buggy.c:15:22: runtime error: unsigned integer overflow: 0 - 1 cannot be represented in type 'size_t' (aka 'unsigned long')
    #0 0xADDR in join_words buggy.c:15:22
    #1 0xADDR in main hidden_test.c:7:17

SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.c:15:22 
```

### Why the flag is needed: malloc(0) blind spot

Without `-fsanitize=unsigned-integer-overflow`, ASan accepts the naive fix. For `n == 0`, `total` is `SIZE_MAX`, so `total + 1` wraps to 0. `malloc(0)` then returns a one-byte block, and the terminator store into it is in bounds, so nothing is reported. The naive fix passes the hidden test. The flag closes that gap by reporting the wrap at the `n - 1` line, before any allocation.

A different naive fix, `if (n == 0) return NULL;`, also fails the hidden test, but through UBSan's nonnull check on `strcmp(NULL, "")`. That is a different bug, so it is not the case's naive fix. It is recorded in a comment in `tests/fixtures/naive_fixes/01_heap_overflow.c`.

## Before and after the unsigned-overflow flag

| Check | Without the flag | With the flag |
| --- | --- | --- |
| buggy, visible | sanitizer: `heap-buffer-overflow buggy.c:16:8` | same |
| buggy, hidden | sanitizer (`malloc(SIZE_MAX)` size check) | sanitizer: unsigned overflow `0 - 1` at `buggy.c:6:22` |
| naive, visible | ok | ok |
| naive, hidden | **ok: the naive fix passes** | sanitizer: unsigned overflow `0 - 1` at `buggy.c:15:22` |
| reference, visible / hidden | ok / ok | ok / ok |

## Stage tables

| Source | Test | Stage | Summary | Exit |
| --- | --- | --- | --- | --- |
| buggy | visible | sanitizer | `AddressSanitizer: heap-buffer-overflow buggy.c:16:8 in join_words` | 1 |
| buggy | hidden | sanitizer | unsigned overflow `0 - 1` at `buggy.c:6:22` | 1 |
| reference | visible | ok | - | 0 |
| reference | hidden | ok | - | 0 |
| naive | visible | ok | - | 0 |
| naive | hidden | sanitizer | unsigned overflow `0 - 1` at `buggy.c:15:22` | 1 |
