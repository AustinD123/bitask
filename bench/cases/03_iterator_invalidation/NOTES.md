# 03: iterator invalidated by push_back

## The bug

`append_doubled_evens` loops with an iterator over `v` and calls `push_back` inside the loop. When the vector is full, `push_back` reallocates, which frees the old buffer. The iterator still points into that freed buffer, so the next `*it` reads freed memory. The loop also reads `v.end()` on every pass, so appended elements are visited too.

## Sanitizer output, buggy version, visible test

The visible test calls `shrink_to_fit()` first, so capacity equals size and the first `push_back` must reallocate. ASan reports the read of the freed buffer.

```
==PID==ERROR: AddressSanitizer: heap-use-after-free on address 0xADDR at pc 0xADDR bp 0xADDR sp 0xADDR
READ of size 4 at 0xADDR thread T0
    #0 0xADDR in append_doubled_evens(std::vector<int, std::allocator<int>>&) buggy.cpp:5:13
    #1 0xADDR in main test.cpp:9:5

0xADDR is located 8 bytes inside of 16-byte region [0xADDR,0xADDR)
freed by thread T0 here:
    #1 0xADDR in std::__new_allocator<int>::deallocate(int*, unsigned long) new_allocator.h:172:2
    #2 0xADDR in std::allocator_traits<std::allocator<int>>::deallocate(std::allocator<int>&, int*, unsigned long) alloc_traits.h:517:13
    #3 0xADDR in std::_Vector_base<int, std::allocator<int>>::_M_deallocate(int*, unsigned long) stl_vector.h:390:4
    #6 0xADDR in std::vector<int, std::allocator<int>>::push_back(int&&) stl_vector.h:1299:9
    #7 0xADDR in append_doubled_evens(std::vector<int, std::allocator<int>>&) buggy.cpp:5:29
    #8 0xADDR in main test.cpp:9:5

previously allocated by thread T0 here:
    #1 0xADDR in std::__new_allocator<int>::allocate(unsigned long, void const*) new_allocator.h:151:27
    #2 0xADDR in std::allocator_traits<std::allocator<int>>::allocate(std::allocator<int>&, unsigned long) alloc_traits.h:482:20
    #3 0xADDR in std::_Vector_base<int, std::allocator<int>>::_M_allocate(unsigned long) stl_vector.h:381:20
    #4 0xADDR in void std::vector<int, std::allocator<int>>::_M_range_initialize<int const*>(int const*, int const*, std::forward_iterator_tag) stl_vector.h:1692:14
    #5 0xADDR in std::vector<int, std::allocator<int>>::vector(std::initializer_list<int>, std::allocator<int> const&) stl_vector.h:682:2
    #6 0xADDR in main test.cpp:7:26

SUMMARY: AddressSanitizer: heap-use-after-free buggy.cpp:5:13 in append_doubled_evens(std::vector<int, std::allocator<int>>&)
```

Frames #4 and #5 of the free stack are dropped by the cleaning rules, because they have no source location. The libstdc++ frames keep their basenames.

## Reference fix

It records `original = v.size()` before the loop and visits only the first `original` elements, using indexes. The loop never reads freed memory, and the appended elements are not processed again, which is what the contract requires.

## Naive fix

Indexing instead of iterators removes the dangling iterator, but the naive version re-reads `v.size()` on every pass. Appended elements get visited, and each even one is doubled again. The values double on every pass until `1073741824 * 2` overflows `int`.

- **Visible test:** caught as `sanitizer`, by UBSan's signed overflow. It does not time out.
- **Hidden test:** caught as `sanitizer` in the same way.

```
buggy.cpp:7:45: runtime error: signed integer overflow: 1073741824 * 2 cannot be represented in type 'int'
    #0 0xADDR in append_doubled_evens(std::vector<int, std::allocator<int>>&) buggy.cpp:7:45
    #1 0xADDR in main test.cpp:9:5

SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior buggy.cpp:7:45 
```

## Stage tables

| Source | Test | Stage | Summary | Exit |
| --- | --- | --- | --- | --- |
| buggy | visible | sanitizer | `AddressSanitizer: heap-use-after-free buggy.cpp:5:13` | 1 |
| buggy | hidden | sanitizer | UBSan overflow `1073741824 * 2` at `buggy.cpp:5:43` | 1 |
| reference | visible | ok | - | 0 |
| reference | hidden | ok | - | 0 |
| naive | visible | sanitizer | UBSan overflow `1073741824 * 2` at `buggy.cpp:7:45` | 1 |
| naive | hidden | sanitizer | UBSan overflow `1073741824 * 2` at `buggy.cpp:7:45` | 1 |
