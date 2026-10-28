# 07 off-by-one

**Bug.** `sum_values` loops with `i <= n`, so it reads one `int` past the end of
the heap array.

**Sanitizer output (buggy, visible test).**

```
AddressSanitizer: heap-buffer-overflow buggy.c:6:46 in sum_values
SUMMARY: AddressSanitizer: heap-buffer-overflow buggy.c:6:46 in sum_values
```

**Reference fix.** Change the bound to `i < n`.

**Naive fix.** None recorded. The hidden test uses an empty array (a one-byte
block), so the overflow happens even when n is 0.

| run    | visible | hidden |
|--------|---------|--------|
| buggy  | sanitizer | sanitizer |
| reference | ok | ok |
