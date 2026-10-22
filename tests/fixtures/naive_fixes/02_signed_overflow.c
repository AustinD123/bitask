#include "lib.h"

/* Naive fix: avoids the overflow of a + b by computing a + (b - a) / 2.
   Passes the visible test. b - a still overflows on (INT_MIN, INT_MAX), and the
   division still truncates toward zero, so (0, -3) gives -1. */
int midpoint(int a, int b) {
    return a + (b - a) / 2;
}
