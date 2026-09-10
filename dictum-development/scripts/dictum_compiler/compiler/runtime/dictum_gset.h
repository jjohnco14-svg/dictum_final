#ifndef DICTUM_GSET_H
#define DICTUM_GSET_H
/*
 * dictum_gset.h — real open-addressing hash set for `set of whole
 * number` on the C backend (gap #9's final C-side piece).
 *
 * SCOPE: whole-number (int32_t) elements only, same reasoning as
 * dictum_glist.h -- C has no generics, so a hand-rolled per-type
 * implementation is required; other element types are rejected by
 * validator.py before reaching this header. See dictum_map.h for the
 * companion `map of text to whole number` implementation.
 *
 * Real open addressing with linear probing + tombstones (not a naive
 * O(n) scan): insert/contains are amortized O(1), matching what a
 * genuine hash set is expected to provide, not just a growable list
 * with a "no duplicates" rule bolted on top.
 */
#include "dictum_core.h"
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>

typedef struct {
    int32_t *keys;
    bool *occupied;
    bool *tombstone;
    size_t cap;
    size_t count;   /* live entries (excludes tombstones) */
} dictum_gset_t;

/* A simple, real integer hash (splitmix32-style finalizer) -- not just
 * `key % cap`, which would cluster badly for sequential keys (a common
 * real input pattern: 0,1,2,3,...). */
static inline uint32_t _dictum_gset_hash(int32_t key) {
    uint32_t x = (uint32_t)key;
    x ^= x >> 16;
    x *= 0x7feb352dU;
    x ^= x >> 15;
    x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}

static inline dictum_gset_t dictum_gset_new(void) {
    dictum_gset_t s;
    s.keys = NULL;
    s.occupied = NULL;
    s.tombstone = NULL;
    s.cap = 0;
    s.count = 0;
    return s;
}

/* Forward-declared so _dictum_gset_grow and dictum_gset_add can call
 * each other (grow re-inserts every live key into a fresh table). */
static inline bool dictum_gset_contains(const dictum_gset_t *s, int32_t key);
static inline void dictum_gset_add(dictum_gset_t *s, int32_t key);

static inline void _dictum_gset_grow(dictum_gset_t *s) {
    size_t new_cap = s->cap == 0 ? 8 : s->cap * 2;
    dictum_gset_t fresh;
    fresh.keys = (int32_t *)calloc(new_cap, sizeof(int32_t));
    fresh.occupied = (bool *)calloc(new_cap, sizeof(bool));
    fresh.tombstone = (bool *)calloc(new_cap, sizeof(bool));
    if (!fresh.keys || !fresh.occupied || !fresh.tombstone) {
        dictum_error_set("set: out of memory on grow");
        free(fresh.keys); free(fresh.occupied); free(fresh.tombstone);
        return;
    }
    fresh.cap = new_cap;
    fresh.count = 0;
    for (size_t i = 0; i < s->cap; i++) {
        if (s->occupied[i] && !s->tombstone[i]) {
            dictum_gset_add(&fresh, s->keys[i]);
        }
    }
    free(s->keys); free(s->occupied); free(s->tombstone);
    *s = fresh;
}

static inline bool dictum_gset_contains(const dictum_gset_t *s, int32_t key) {
    if (!s || s->cap == 0) return false;
    uint32_t h = _dictum_gset_hash(key);
    size_t idx = h % s->cap;
    for (size_t probe = 0; probe < s->cap; probe++) {
        size_t i = (idx + probe) % s->cap;
        if (!s->occupied[i]) return false;  /* empty slot: not present, probe chain ends */
        if (!s->tombstone[i] && s->keys[i] == key) return true;
    }
    return false;
}

/* Real amortized-growth insert (load factor > 0.7 triggers a resize),
 * bucket search via linear probing, no-op if the key is already
 * present (a set's defining property, not just "add anyway"). */
static inline void dictum_gset_add(dictum_gset_t *s, int32_t key) {
    if (!s) return;
    if (dictum_gset_contains(s, key)) return;
    if (s->cap == 0 || (double)(s->count + 1) / (double)s->cap > 0.7) {
        _dictum_gset_grow(s);
    }
    uint32_t h = _dictum_gset_hash(key);
    size_t idx = h % s->cap;
    for (size_t probe = 0; probe < s->cap; probe++) {
        size_t i = (idx + probe) % s->cap;
        if (!s->occupied[i] || s->tombstone[i]) {
            s->keys[i] = key;
            s->occupied[i] = true;
            s->tombstone[i] = false;
            s->count += 1;
            return;
        }
    }
    /* Unreachable given the 0.7 load-factor grow trigger above, but
     * fail loudly rather than silently dropping the insert if it ever
     * is reached. */
    dictum_error_set("set: no free slot found (load-factor invariant violated)");
}

static inline size_t dictum_gset_len(const dictum_gset_t *s) {
    return s ? s->count : 0;
}

static inline void dictum_gset_free(dictum_gset_t *s) {
    if (!s) return;
    free(s->keys); free(s->occupied); free(s->tombstone);
    s->keys = NULL; s->occupied = NULL; s->tombstone = NULL;
    s->cap = 0; s->count = 0;
}

#endif /* DICTUM_GSET_H */
