/* Smoke test: unsynchronised increment from two threads.
   Expected: TSan "data race" warning, exit code 66. */
#include <pthread.h>
#include <stdio.h>

static long counter;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < 1000; i++) counter++;
    return NULL;
}

int main(void) {
    pthread_t a, b;
    pthread_create(&a, NULL, worker, NULL);
    pthread_create(&b, NULL, worker, NULL);
    pthread_join(a, NULL);
    pthread_join(b, NULL);
    printf("counter=%ld\n", counter);
    return 0;
}
