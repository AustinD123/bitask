/* Held-out test for join_words: the edge cases the naive fix gets wrong. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    char *out = join_words(NULL, 0, ',');   /* n == 0 gives an empty string */
    CHECK_STREQ(out, "");
    free(out);

    const char *one[] = {"solo"};            /* n == 1: no separator */
    out = join_words(one, 1, ',');
    CHECK_STREQ(out, "solo");
    free(out);

    const char *blanks[] = {"", ""};         /* two empty words: just the separator */
    out = join_words(blanks, 2, ',');
    CHECK_STREQ(out, ",");
    free(out);

    verify_tests_passed();
    return 0;
}
