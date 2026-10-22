#include "lib.h"

int midpoint(int a, int b) {
    return (a + b) / 2;                   /* BUG: overflows; truncates toward zero */
}
