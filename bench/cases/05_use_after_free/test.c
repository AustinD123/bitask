/* Visible test for format_pair: one call, read back, then freed by the caller. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    char *text = format_pair("x", 1);
    CHECK_STREQ(text, "x=1");
    free(text);
    verify_tests_passed();
    return 0;
}
