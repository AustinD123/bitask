#include "lib.h"

int midpoint(int a, int b) {
    /* Widen so the sum cannot overflow. C's / truncates toward zero, so a
       negative odd sum must be rounded down by hand to get the floor. */
    long long sum = (long long)a + b;
    long long half = sum / 2;
    if (sum % 2 != 0 && sum < 0) half -= 1;
    return (int)half;
}
