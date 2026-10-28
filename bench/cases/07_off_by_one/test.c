/* Visible test for sum_values: a heap array of five ints. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    int *values = malloc(5 * sizeof *values);
    for (int i = 0; i < 5; i++) values[i] = i + 1;   /* 1..5 */
    CHECK_EQ(sum_values(values, 5), 15);
    free(values);
    verify_tests_passed();
    return 0;
}
