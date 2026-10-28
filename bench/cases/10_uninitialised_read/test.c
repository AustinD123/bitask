/* Visible test for sum_upto: a normal sum, and n == 1, which reads the accumulator once. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(sum_upto(5), 10);
    CHECK_EQ(sum_upto(1), 0);
    verify_tests_passed();
    return 0;
}
