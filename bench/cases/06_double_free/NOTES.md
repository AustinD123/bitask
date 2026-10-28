# 06 double free

**Bug.** `upper_copy` frees its result when the input is empty, and the caller
frees it again. Only the empty input takes the bad path.

**Sanitizer output (buggy, visible test).** The first reads of the freed result
are reported as use after free, before the second free:

```
SUMMARY: AddressSanitizer: heap-use-after-free test.c:12:5 in main
```

**Reference fix.** Remove the `if (n == 0) free(out);` line.

**Naive fix.** None recorded. The hidden test also uses the empty string, so a
candidate that only fixes the non-empty path fails both tests.

| run    | visible | hidden |
|--------|---------|--------|
| buggy  | sanitizer | sanitizer |
| reference | ok | ok |
