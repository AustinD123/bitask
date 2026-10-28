/* Visible test for upper_copy: a word, then the empty string, which takes the buggy path. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    char *word = upper_copy("abc");
    CHECK_STREQ(word, "ABC");
    free(word);

    char *empty = upper_copy("");
    CHECK_STREQ(empty, "");
    free(empty);

    verify_tests_passed();
    return 0;
}
