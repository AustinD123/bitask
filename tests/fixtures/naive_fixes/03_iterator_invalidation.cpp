#include "lib.hpp"

// Naive fix: indexes instead of iterators, so there is no dangling iterator.
// BUG: v.size() is re-read on every pass, so appended elements are visited too.
void append_doubled_evens(std::vector<int>& v) {
    for (std::size_t i = 0; i < v.size(); i++) {
        if (v[i] % 2 == 0) v.push_back(v[i] * 2);
    }
}
