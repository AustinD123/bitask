# 08 memory leak

**Bug.** `word_count` copies its input and never frees the copy. Nothing reads
the copy after the function returns, so the leak is only visible at exit.

**Sanitizer output (buggy, visible test).** LeakSanitizer reports at exit, after
the test has printed its completion marker. The CLI shows it as:

```
LeakSanitizer: 15 byte(s) leaked in 2 allocation(s).
```

The count includes the copy made for the empty string.

**Reference fix.** Add `free(copy);` before the return.

**Naive fix.** None recorded. A candidate that only removes the copy and counts
the input directly passes both tests.

| run    | visible | hidden |
|--------|---------|--------|
| buggy  | sanitizer | sanitizer |
| reference | ok | ok |
