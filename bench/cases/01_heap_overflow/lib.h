/* Declarations for case 01. Read-only: the editable file implements this. */
#ifndef CASE_LIB_H
#define CASE_LIB_H
#include <stddef.h>

/* Returns a newly malloc'ed string joining words[0..n-1] with sep.
   The caller frees it. For n == 0 it returns an empty string, still malloc'ed. */
char *join_words(const char **words, size_t n, char sep);

#endif
