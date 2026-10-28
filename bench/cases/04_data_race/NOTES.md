# 04: unsynchronised counter in parallel_count

## The bug

Every worker thread does `counter++` on the same `static long`, with no lock and no atomic operation. The increments race: two threads can read the same value and both write back the same result, so updates are lost. TSan reports the unsynchronised write.

## Sanitizer output, buggy version, visible test

TSan halts on the first race. It exits 66, which is TSan's default code.

```
WARNING: ThreadSanitizer: data race (pid=PID)
  Write of size 8 at 0xADDR by thread T2:
    #0 worker buggy.c:9:46

  Previous write of size 8 at 0xADDR by thread T1:
    #0 worker buggy.c:9:46

  Location is global 'counter' of size 8 at 0xADDR (test_bin+0xADDR)

  Thread T2 (tid=TID, running) created by main thread at:
    #1 parallel_count buggy.c:17:39
    #2 main test.c:6:5

  Thread T1 (tid=TID, finished) created by main thread at:
    #1 parallel_count buggy.c:17:39
    #2 main test.c:6:5

SUMMARY: ThreadSanitizer: data race buggy.c:9:46 in worker
```

The `pid=`, `tid=` and build-ID values are masked, which is what makes the output deterministic across runs.

## Reference fix

It uses `atomic_long`. Each worker calls `atomic_fetch_add`, and each call resets the counter with `atomic_store(&counter, 0)`. The reset makes every call independent, which the contract requires.

## Naive fix

The naive fix makes the counter atomic but never resets it. It passes the visible test, which makes a single call. The hidden test makes several calls in one process, and the counter carries over from one call to the next.

- **Visible test:** passes.
- **Hidden test:** `test_fail`. The second call, `parallel_count(8, 5000)`, returns the first call's 1000 plus 40000.

```
CHECK_EQ FAILED: parallel_count(8, 5000) == 40000 (got 41000, expected 40000) at hidden_test.c:8
```

## The volatile variant

`tests/fixtures/naive_fixes/04_data_race_volatile.c` makes the counter `volatile long`. That is the one fixture where `volatile` is the point of the case. It does not synchronise anything, so TSan still reports the race on the visible test:

```
sanitizer ThreadSanitizer: data race buggy.c:11:46 in worker
```

The volatile variant shows why the case relies on TSan's report, not only on the total. `volatile` stops the compiler from caching the counter, but it does not make the increments atomic, so the race is still there.

## Stage tables

| Source | Test | Stage | Summary | Exit |
| --- | --- | --- | --- | --- |
| buggy | visible | sanitizer | `ThreadSanitizer: data race buggy.c:9:46 in worker` | 66 |
| buggy | hidden | sanitizer | `ThreadSanitizer: data race buggy.c:9:46 in worker` | 66 |
| reference | visible | ok (5 runs) | - | 0 |
| reference | hidden | ok (5 runs) | - | 0 |
| naive (atomic, no reset) | visible | ok | - | 0 |
| naive (atomic, no reset) | hidden | test_fail | `CHECK_EQ`: `parallel_count(8, 5000)` gives 41000, expected 40000 | 1 |
| volatile variant | visible | sanitizer | `ThreadSanitizer: data race buggy.c:11:46 in worker` | 66 |
