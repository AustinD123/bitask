/* Declarations for case 05. Read-only: the editable file implements this. */
#ifndef CASE_LIB_H
#define CASE_LIB_H

/* Returns a newly malloc'ed "name=value" string. The caller frees it. */
char *format_pair(const char *name, int value);

#endif
