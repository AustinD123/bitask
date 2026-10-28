#include <stddef.h>
#include "lib.h"

int sum_values(const int *values, size_t n) {
    int total = 0;
    for (size_t i = 0; i <= n; i++) total += values[i];   /* BUG: <= reads one element past the end */
    return total;
}
