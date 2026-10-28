# 05 use after free

**Bug.** `format_pair` frees its buffer, then returns it. The caller gets a
dangling pointer and reads it.

**Sanitizer output (buggy, visible test).** ASan reports the read inside `strcmp`
in the test, with the free stack in the candidate:

```
SUMMARY: AddressSanitizer: heap-use-after-free (test_bin+0x44b3d) (BuildId: BUILDID) in strcmp
```

**Reference fix.** Return the buffer without freeing it. The caller frees it.

**Naive fix.** None recorded. The natural quick fix, returning a stack copy, is
not valid C for a `malloc`-based API, so no manifest entry is needed.

| run    | visible | hidden |
|--------|---------|--------|
| buggy  | sanitizer | sanitizer |
| reference | ok | ok |
