/* Held-out test for upper_copy: the empty string first, then mixed case. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    char *empty = upper_copy("");
    CHECK_STREQ(empty, "");
    free(empty);

    char *text = upper_copy("Hello, World 42");
    CHECK_STREQ(text, "HELLO, WORLD 42");
    free(text);

    verify_tests_passed();
    return 0;
}
