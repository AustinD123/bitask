#include "lib.hpp"

void append_doubled_evens(std::vector<int>& v) {
    for (auto it = v.begin(); it != v.end(); ++it) {
        if (*it % 2 == 0) v.push_back(*it * 2);  // BUG: push_back may reallocate
    }
}
