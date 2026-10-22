#include <pthread.h>
#include "lib.h"

static long counter;
static int g_iters;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < g_iters; i++) counter++;  /* BUG: unsynchronised */
    return NULL;
}

long parallel_count(int threads, int iters) {
    pthread_t tids[64];
    counter = 0;
    g_iters = iters;
    for (int t = 0; t < threads; t++) pthread_create(&tids[t], NULL, worker, NULL);
    for (int t = 0; t < threads; t++) pthread_join(tids[t], NULL);
    return counter;
}
