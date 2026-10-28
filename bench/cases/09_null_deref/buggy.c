#include <string.h>
#include "lib.h"

static const char *const labels[] = {"low", "medium", "high"};

/* Returns the label for level, or NULL for any level outside 0..2. */
const char *label_for(int level) {
    if (level < 0 || level > 2) return NULL;
    return labels[level];
}

size_t label_length(int level) {
    return strlen(label_for(level));   /* BUG: label_for can return NULL */
}
