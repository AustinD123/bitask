#include <stdlib.h>
#include <string.h>
#include "lib.h"

/* Naive fix (the spec's): adds room for the NUL and keeps the n - 1 underflow.
   Passes the visible test (n == 3, no wrap). With n == 0, total is SIZE_MAX and
   total + 1 wraps to 0, so malloc(0) gets a one-byte block and ASan accepts the
   terminator write. Only -fsanitize=unsigned-integer-overflow (set in case.json)
   reports the wrap, at the n - 1 line, before any allocation.

   Rejected variant, kept as a note: a guard "if (n == 0) return NULL;" also
   fails the hidden test, but via UBSan's nonnull check on strcmp(NULL, ""). It
   is a different bug, so it is not used as the case's naive fix. */
char *join_words(const char **words, size_t n, char sep) {
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
