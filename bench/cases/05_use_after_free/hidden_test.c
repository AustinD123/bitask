/* Held-out test for format_pair: two results alive at once, and a negative value. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    char *first = format_pair("a", 10);
    char *second = format_pair("b", -2);
    CHECK_STREQ(first, "a=10");
    CHECK_STREQ(second, "b=-2");
    free(first);
    free(second);
    verify_tests_passed();
    return 0;
}
