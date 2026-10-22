#include <pthread.h>
#include "lib.h"

/* The volatile variant, kept to show that TSan still reports it. This is the
   one fixture where volatile is deliberate: the case is about it. */
static volatile long counter;
static int g_iters;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < g_iters; i++) counter++;
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
