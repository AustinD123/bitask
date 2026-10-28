/* Held-out test for sum_upto: the empty range and a longer range. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(sum_upto(0), 0);
    CHECK_EQ(sum_upto(10), 45);
    verify_tests_passed();
    return 0;
}
