#include <ctype.h>
#include <stdlib.h>
#include <string.h>
#include "lib.h"

char *upper_copy(const char *s) {
    size_t n = strlen(s);
    char *out = malloc(n + 1);
    for (size_t i = 0; i < n; i++) out[i] = (char)toupper((unsigned char)s[i]);
    out[n] = '\0';
    return out;
}
