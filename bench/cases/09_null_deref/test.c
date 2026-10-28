/* Visible test for label_length: two known levels and one unknown level, which
   takes the NULL path. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(label_length(0), 3);   /* "low" */
    CHECK_EQ(label_length(2), 4);   /* "high" */
    CHECK_EQ(label_length(7), 0);   /* unknown level */
    verify_tests_passed();
    return 0;
}
