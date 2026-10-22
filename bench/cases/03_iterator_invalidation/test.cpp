// Visible test: shrink_to_fit makes the first push_back reallocate.
#include <vector>
#include "lib.hpp"
#include "check.h"

int main() {
    std::vector<int> v = {1, 2, 3, 4};
    v.shrink_to_fit();
    append_doubled_evens(v);
    CHECK_EQ(v.size(), 6);
    CHECK_EQ(v[4], 4);   // double of the original 2
    CHECK_EQ(v[5], 8);   // double of the original 4
    verify_tests_passed();
    return 0;
}
