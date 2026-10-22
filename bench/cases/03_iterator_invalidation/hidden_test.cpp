// Held-out test: empty input, no evens, spare capacity, and mixed signs.
#include <vector>
#include "lib.hpp"
#include "check.h"

static void check_vec(std::vector<int> v, const std::vector<int>& want) {
    CHECK_EQ(v.size(), want.size());
    for (std::size_t i = 0; i < want.size(); i++) CHECK_EQ(v[i], want[i]);
}

int main() {
    std::vector<int> empty;
    append_doubled_evens(empty);
    check_vec(empty, {});

    std::vector<int> odd = {1, 3, 5};        // nothing to append
    append_doubled_evens(odd);
    check_vec(odd, {1, 3, 5});

    std::vector<int> spare = {2};            // spare capacity: no reallocation
    spare.reserve(100);
    append_doubled_evens(spare);
    check_vec(spare, {2, 4});

    std::vector<int> mixed = {-2, 3};        // negative even numbers double too
    append_doubled_evens(mixed);
    check_vec(mixed, {-2, 3, -4});

    verify_tests_passed();
    return 0;
}
