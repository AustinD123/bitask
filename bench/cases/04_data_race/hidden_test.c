/* Held-out test for parallel_count: several calls in one process, so state
   that is not reset between calls shows up. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(parallel_count(1, 1000), 1000);
    CHECK_EQ(parallel_count(8, 5000), 40000);   /* the second call must start from zero */
    CHECK_EQ(parallel_count(3, 0), 0);
    long first = parallel_count(4, 250);
    long second = parallel_count(4, 250);       /* same arguments, same result */
    CHECK_EQ(first, second);
    CHECK_EQ(second, 1000);
    verify_tests_passed();
    return 0;
}
