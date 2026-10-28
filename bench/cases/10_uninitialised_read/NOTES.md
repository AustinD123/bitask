# 10 uninitialised read

**Bug.** `sum_upto` never initialises `total`, so the first `+=` reads an
indeterminate value.

**Why it is a compile error, not a sanitizer report.** ASan does not track
stack variables that are never written, and UBSan does not see this read. The
compiler does, and `-Wall -Werror` makes its warning fatal:

```
buggy.c:5:33: error: variable 'total' is uninitialized when used here [-Werror,-Wuninitialized]
buggy.c:4:14: note: initialize the variable 'total' to silence this warning
```

The visible test calls `sum_upto(1)`, which runs the loop body once, so the
behaviour is exercised. The buggy version fails before any test runs.

**Reference fix.** Initialise `total` to 0.

**Naive fix.** None recorded.

| run    | visible | hidden |
|--------|---------|--------|
| buggy  | compile_error | compile_error |
| reference | ok | ok |
