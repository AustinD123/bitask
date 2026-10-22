#include "lib.hpp"

void append_doubled_evens(std::vector<int>& v) {
    // Fix the count first, so only the original elements are visited.
    const std::size_t original = v.size();
    for (std::size_t i = 0; i < original; i++) {
        if (v[i] % 2 == 0) v.push_back(v[i] * 2);
    }
}
