/* Held-out test for label_length: a negative level and the middle label. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(label_length(-1), 0);
    CHECK_EQ(label_length(1), 6);   /* "medium" */
    verify_tests_passed();
    return 0;
}
