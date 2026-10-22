#include <stdlib.h>
#include <string.h>
#include "lib.h"

/* Naive fix: adds room for the NUL, and special-cases empty input by returning
   NULL. Passes the visible test (n == 3). The hidden test's n == 0 case then
   passes NULL to strcmp, which ASan reports as SEGV.

   Note: the spec's naive fix, malloc(total + 1) with the n - 1 underflow kept,
   is NOT caught under ASan. malloc(0) returns a one-byte allocation there, so
   the terminator write is in bounds. That fix is still undefined behaviour by
   the C standard; see SPEC.md, Decisions (Phase 4). */
char *join_words(const char **words, size_t n, char sep) {
    if (n == 0) return NULL;
    size_t total = n - 1;
    for (size_t i = 0; i < n; i++) total += strlen(words[i]);
    char *out = malloc(total + 1);
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
