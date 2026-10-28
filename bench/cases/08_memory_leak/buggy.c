#include <stdlib.h>
#include <string.h>
#include "lib.h"

int word_count(const char *s) {
    char *copy = malloc(strlen(s) + 1);
    strcpy(copy, s);
    int count = 0;
    int in_word = 0;
    for (char *p = copy; *p; p++) {
        if (*p == ' ') in_word = 0;
        else if (!in_word) { in_word = 1; count++; }
    }
    return count;   /* BUG: copy is never freed */
}
