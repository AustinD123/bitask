/* Declarations for case 07. Read-only: the editable file implements this. */
#ifndef CASE_LIB_H
#define CASE_LIB_H
#include <stddef.h>

/* Returns the sum of values[0..n-1]. values points to n ints; n may be 0. */
int sum_values(const int *values, size_t n);

#endif
