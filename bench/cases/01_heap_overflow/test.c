/* Visible test for join_words: a normal join. The result is read back, so the
   overflow in the buggy version is observable across the function boundary. */
#include <stdlib.h>
#include "lib.h"
#include "check.h"

int main(void) {
    const char *words[] = {"a", "bc", "def"};
    char *out = join_words(words, 3, ',');
    CHECK_STREQ(out, "a,bc,def");   /* separators between words, no trailing separator */
    free(out);
    verify_tests_passed();
    return 0;
}
