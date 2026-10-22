#include <stdlib.h>
#include <string.h>
#include "lib.h"

char *join_words(const char **words, size_t n, char sep) {
    size_t total = n == 0 ? 0 : n - 1;   /* separators; none when n == 0 */
    for (size_t i = 0; i < n; i++) total += strlen(words[i]);
    char *out = malloc(total + 1);       /* +1 for the terminating '\0' */
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
