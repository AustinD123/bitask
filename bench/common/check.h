/* Shared test helpers. Included by every test.c and hidden_test.c in bench/.
   A failing check reports its location and exits with _exit(), which skips
   atexit handlers, so a plain test failure is never reported as a leak. */
#ifndef VERIFY_CHECK_H
#define VERIFY_CHECK_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Fail immediately with location. _exit() skips atexit handlers, so
   LeakSanitizer does not run and a plain test failure is never
   misreported as a sanitizer failure. */
#define CHECK(cond) do { if (!(cond)) { \
    fprintf(stderr, "CHECK FAILED: %s at %s:%d\n", #cond, __FILE__, __LINE__); \
    fflush(stderr); _exit(1); } } while (0)

/* Same, but prints both values. Use this wherever values are comparable. */
#define CHECK_EQ(actual, expected) do { \
    long long a_ = (long long)(actual), e_ = (long long)(expected); \
    if (a_ != e_) { fprintf(stderr, "CHECK_EQ FAILED: %s == %s (got %lld, expected %lld) at %s:%d\n", \
        #actual, #expected, a_, e_, __FILE__, __LINE__); fflush(stderr); _exit(1); } } while (0)

/* String version of CHECK_EQ. Both arguments must be non-NULL C strings. */
#define CHECK_STREQ(actual, expected) do { \
    const char *a_ = (actual), *e_ = (expected); \
    if (strcmp(a_, e_) != 0) { fprintf(stderr, "CHECK_STREQ FAILED: %s == %s (got \"%s\", expected \"%s\") at %s:%d\n", \
        #actual, #expected, a_, e_, __FILE__, __LINE__); fflush(stderr); _exit(1); } } while (0)

/* Completion marker. Call as the LAST statement of main() before return 0.
   The harness sets VERIFY_NONCE per run and requires "VERIFY_OK <nonce>" on
   stdout. This guards against accidental early exits, not adversarial code. */
static inline void verify_tests_passed(void) {
    const char *nonce = getenv("VERIFY_NONCE");
    printf("VERIFY_OK %s\n", nonce ? nonce : "(missing)");
    fflush(stdout);
}
#endif
