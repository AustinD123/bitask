/* Smoke test: leaked allocation. Expected: LeakSanitizer report at exit,
   exit code 23. The pointer is stored in a volatile global and then
   cleared, so it is unreachable at exit but the malloc is not deleted. */
#include <stdlib.h>

static char *volatile sink;

int main(void) {
    sink = malloc(16);
    sink = NULL;
    return 0;
}
