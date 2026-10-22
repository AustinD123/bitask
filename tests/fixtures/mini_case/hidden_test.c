/* Held-out test for the mini case. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(add(0, 0), 0);      /* zero */
    CHECK_EQ(add(-2, -3), -5);   /* negatives */
    CHECK_EQ(add(7, 0), 7);      /* identity */
    verify_tests_passed();
    return 0;
}
