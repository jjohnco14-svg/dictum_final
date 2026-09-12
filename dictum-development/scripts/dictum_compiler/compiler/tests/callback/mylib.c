/* A third-party-style C library taking a callback -- the real pattern */
typedef int (*cmp_fn)(int a, int b);

int apply_reduce(const int *xs, int n, cmp_fn pick) {
    int best = xs[0];
    for (int i = 1; i < n; i++) best = pick(best, xs[i]);
    return best;
}
