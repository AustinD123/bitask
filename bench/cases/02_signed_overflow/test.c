/* Visible test for midpoint. The second check overflows int in the buggy version. */
#include <limits.h>
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(midpoint(2, 4), 3);
    CHECK_EQ(midpoint(INT_MAX - 1, INT_MAX), INT_MAX - 1);  /* a + b overflows int */
    verify_tests_passed();
    return 0;
}
