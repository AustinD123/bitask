# 02: signed overflow in midpoint

## The bug

`(a + b) / 2` adds two `int`s first. The sum can exceed `INT_MAX` or fall below `INT_MIN`, which is undefined behaviour in C. The division also truncates toward zero, so for a negative odd sum the result is one above the floor that the contract requires.

## Sanitizer output, buggy version, visible test

The second visible check, `midpoint(INT_MAX - 1, INT_MAX)`, overflows the sum. UBSan reports it, and `-fno-sanitize-recover=all` stops the run there.

```
buggy.c:4:15: runtime error: signed integer overflow: 2147483646 + 2147483647 cannot be represented in type 'int'
    #0 0xADDR in midpoint buggy.c:4:15
    #1 0xADDR in main test.c:8:5

SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.c:4:15 
```

## Reference fix

It widens the sum to `long long`, so it cannot overflow. It divides by 2, then subtracts 1 when the sum is negative and odd, because C's `/` truncates toward zero and the contract asks for the floor.

## Naive fix

`a + (b - a) / 2` avoids the overflow of `a + b`, so it passes the visible test: `midpoint(INT_MAX - 1, INT_MAX)` gives `b - a = 1`, which is harmless.

- **Hidden test:** caught as `sanitizer`. `midpoint(INT_MIN, INT_MAX)` overflows `b - a`. The division still truncates, so `(0, -3)` would also give -1.

```
buggy.c:7:19: runtime error: signed integer overflow: 2147483647 - -2147483648 cannot be represented in type 'int'
    #0 0xADDR in midpoint buggy.c:7:19
    #1 0xADDR in main hidden_test.c:7:5

SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.c:7:19 
```

## Note on the buggy version's hidden test

The buggy version fails the hidden test with `test_fail`, not a sanitizer. `INT_MIN + INT_MAX` is -1, which does not overflow, so the buggy code returns 0 where -1 is expected:

```
CHECK_EQ FAILED: midpoint(INT_MIN, INT_MAX) == -1 (got 0, expected -1) at hidden_test.c:7
```

The sanitizer is still the first thing the visible test hits, so the expected stage on the visible test is `sanitizer`.

## Stage tables

| Source | Test | Stage | Summary | Exit |
| --- | --- | --- | --- | --- |
| buggy | visible | sanitizer | `buggy.c:4:15: runtime error: signed integer overflow: 2147483646 + 2147483647` | 1 |
| buggy | hidden | test_fail | `CHECK_EQ`: `midpoint(INT_MIN, INT_MAX)` gives 0, expected -1 | 1 |
| reference | visible | ok | - | 0 |
| reference | hidden | ok | - | 0 |
| naive | visible | ok | - | 0 |
| naive | hidden | sanitizer | `buggy.c:7:19: runtime error: signed integer overflow: 2147483647 - -2147483648` | 1 |
