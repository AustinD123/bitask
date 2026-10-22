/* Declarations for case 04. Read-only: the editable file implements this. */
#ifndef CASE_LIB_H
#define CASE_LIB_H

/* Starts `threads` threads (1 to 64), each incrementing a shared counter `iters`
   times, and returns the total. Calls are independent: state resets each call. */
long parallel_count(int threads, int iters);

#endif
