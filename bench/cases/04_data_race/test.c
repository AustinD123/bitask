/* Visible test for parallel_count: one call, four threads. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(parallel_count(4, 10000), 40000);
    verify_tests_passed();
    return 0;
}
