/* Smoke test: signed overflow. Expected: UBSan report, exit code 1
   (only because -fno-sanitize-recover=all is set). */
#include <limits.h>
#include <stdio.h>

int main(void) {
    volatile int big = INT_MAX;
    int sum = big + 1;
    printf("sum=%d\n", sum);
    return 0;
}
