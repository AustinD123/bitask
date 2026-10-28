# 09 null dereference

**Bug.** `label_for` returns NULL for an unknown level, and `label_length` passes
that NULL to `strlen` without checking it.

**Sanitizer output (buggy, visible test).** UBSan's nonnull check fires first,
because `strlen` is declared to take a non-null argument. ASan has no report:

```
SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.c:13:19 
```

**Reference fix.** Check the NULL and return 0.

**Naive fix.** None recorded.

| run    | visible | hidden |
|--------|---------|--------|
| buggy  | sanitizer | sanitizer |
| reference | ok | ok |
