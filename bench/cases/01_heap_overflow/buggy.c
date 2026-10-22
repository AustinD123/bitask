#include <stdlib.h>
#include <string.h>
#include "lib.h"

char *join_words(const char **words, size_t n, char sep) {
    size_t total = n - 1;                 /* separators */
    for (size_t i = 0; i < n; i++) total += strlen(words[i]);
    char *out = malloc(total);            /* BUG: no room for '\0'; n == 0 underflows */
    char *p = out;
    for (size_t i = 0; i < n; i++) {
        size_t len = strlen(words[i]);
        memcpy(p, words[i], len);
        p += len;
        if (i + 1 < n) *p++ = sep;
    }
    *p = '\0';
    return out;
}
