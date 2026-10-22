/* Held-out test for midpoint: the extremes and the floor semantics. */
#include <limits.h>
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(midpoint(INT_MIN, INT_MAX), -1);   /* exact average is -0.5; floor is -1 */
    CHECK_EQ(midpoint(0, -3), -2);              /* exact average is -1.5; floor is -2 */
    CHECK_EQ(midpoint(-3, 0), -2);              /* the mirror case */
    CHECK_EQ(midpoint(-4, -2), -3);             /* even sum, no rounding */
    CHECK_EQ(midpoint(INT_MIN, INT_MIN), INT_MIN);
    CHECK_EQ(midpoint(1, 2), 1);                /* exact average is 1.5; floor is 1 */
    verify_tests_passed();
    return 0;
}
