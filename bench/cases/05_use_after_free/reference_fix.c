#include <stdio.h>
#include <stdlib.h>
#include "lib.h"

char *format_pair(const char *name, int value) {
    char *text = malloc(64);
    snprintf(text, 64, "%s=%d", name, value);
    return text;   /* the caller owns it and frees it */
}
