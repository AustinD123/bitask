#include "lib.h"

int sum_upto(int n) {
    int total;   /* BUG: never initialised, so the first += reads garbage */
    for (int i = 0; i < n; i++) total += i;
    return total;
}
