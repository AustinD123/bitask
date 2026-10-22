/* Visible test for the mini case. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(add(2, 3), 5);   /* basic sum */
    verify_tests_passed();
    return 0;
}
