/* Declarations for case 09. Read-only: the editable file implements this. */
#ifndef CASE_LIB_H
#define CASE_LIB_H
#include <stddef.h>

/* Returns the length of the label for level 0, 1 or 2 ("low", "medium", "high").
   Returns 0 for any other level. */
size_t label_length(int level);

#endif
