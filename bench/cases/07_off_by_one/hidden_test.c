/* Held-out test for sum_values: an empty array (a one-byte block) and a single element. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    int *none = malloc(1);
    CHECK_EQ(sum_values(none, 0), 0);
    free(none);

    int *one = malloc(sizeof *one);
    one[0] = 7;
    CHECK_EQ(sum_values(one, 1), 7);
    free(one);

    verify_tests_passed();
    return 0;
}
