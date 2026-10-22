/* Smoke test: heap-buffer-overflow. Expected: ASan report, exit code 1.
   The pointer escapes to a volatile global so the optimiser cannot delete
   the malloc/free pair and the out-of-bounds store. Without the escape,
   clang -O1 removes the whole allocation and ASan reports nothing (exit 0). */
#include <stdlib.h>

static char *volatile sink;

int main(void) {
    char *p = malloc(8);
    sink = p;
    p[8] = 'x';
    free(p);
    return 0;
}
