#include "lib.h"

int sum_upto(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) total += i;
    return total;
}
