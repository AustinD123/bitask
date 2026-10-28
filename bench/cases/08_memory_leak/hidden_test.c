/* Held-out test for word_count: leading and repeated spaces. */
#include "lib.h"
#include "check.h"

int main(void) {
    CHECK_EQ(word_count("  a  b "), 2);
    CHECK_EQ(word_count("   "), 0);
    verify_tests_passed();
    return 0;
}
