/* Visible test for word_count: a sentence and the empty string. No allocation here,
   so any leak comes from the candidate. LeakSanitizer reports at exit. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(word_count("the quick fox"), 3);
    CHECK_EQ(word_count(""), 0);
    verify_tests_passed();
    return 0;
}
