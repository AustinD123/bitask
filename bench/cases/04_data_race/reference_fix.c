#include <pthread.h>
#include <stdatomic.h>
#include "lib.h"

static atomic_long counter;
static int g_iters;

static void *worker(void *arg) {
    (void)arg;
    for (int i = 0; i < g_iters; i++) atomic_fetch_add(&counter, 1);
    return NULL;
}

long parallel_count(int threads, int iters) {
    pthread_t tids[64];
    atomic_store(&counter, 0);   /* reset: each call is independent */
    g_iters = iters;
    for (int t = 0; t < threads; t++) pthread_create(&tids[t], NULL, worker, NULL);
    for (int t = 0; t < threads; t++) pthread_join(tids[t], NULL);
    return atomic_load(&counter);
}
