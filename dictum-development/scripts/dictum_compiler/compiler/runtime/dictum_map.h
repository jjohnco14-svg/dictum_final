#ifndef DICTUM_MAP_H
#define DICTUM_MAP_H
/*
 * dictum_map.h — real open-addressing hash map for `map of text to
 * whole number` on the C backend (gap #9's final C-side piece).
 *
 * SCOPE: text keys (const char*), whole-number (int32_t) values only --
 * same reasoning as dictum_glist.h/dictum_gset.h: C has no generics.
 * `map of text to whole number` is the one key/value pairing this pass
 * implements; other combinations are rejected by validator.py before
 * reaching this header.
 *
 * Keys are owned: dictum_map_put() strdup()s the key so the map's
 * lifetime doesn't depend on the caller's string outliving it (a
 * literal is safe either way, but a caller-built/heap text value is
 * not). dictum_map_free() releases them.
 */
#include "dictum_core.h"
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char **keys;
    int32_t *values;
    bool *occupied;
    bool *tombstone;
    size_t cap;
    size_t count;
} dictum_map_t;

/* Real FNV-1a string hash -- a genuine, well-distributed hash function,
 * not a placeholder like summing character codes (which clusters badly
 * for realistic keys, e.g. anagrams/permutations hashing identically). */
static inline uint32_t _dictum_map_hash(const char *key) {
    uint32_t h = 2166136261u;
    for (const unsigned char *p = (const unsigned char *)key; *p; p++) {
        h ^= *p;
        h *= 16777619u;
    }
    return h;
}

static inline dictum_map_t dictum_map_new(void) {
    dictum_map_t m;
    m.keys = NULL; m.values = NULL; m.occupied = NULL; m.tombstone = NULL;
    m.cap = 0; m.count = 0;
    return m;
}

static inline bool dictum_map_contains(const dictum_map_t *m, const char *key);
static inline void dictum_map_put(dictum_map_t *m, const char *key, int32_t value);

static inline void _dictum_map_grow(dictum_map_t *m) {
    size_t new_cap = m->cap == 0 ? 8 : m->cap * 2;
    dictum_map_t fresh;
    fresh.keys = (char **)calloc(new_cap, sizeof(char *));
    fresh.values = (int32_t *)calloc(new_cap, sizeof(int32_t));
    fresh.occupied = (bool *)calloc(new_cap, sizeof(bool));
    fresh.tombstone = (bool *)calloc(new_cap, sizeof(bool));
    if (!fresh.keys || !fresh.values || !fresh.occupied || !fresh.tombstone) {
        dictum_error_set("map: out of memory on grow");
        free(fresh.keys); free(fresh.values); free(fresh.occupied); free(fresh.tombstone);
        return;
    }
    fresh.cap = new_cap;
    fresh.count = 0;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->occupied[i] && !m->tombstone[i]) {
            /* Re-own each key string directly into the fresh table
             * rather than going through dictum_map_put's strdup (which
             * would leak the original key we're about to free below). */
            uint32_t h = _dictum_map_hash(m->keys[i]);
            size_t idx = h % fresh.cap;
            for (size_t probe = 0; probe < fresh.cap; probe++) {
                size_t j = (idx + probe) % fresh.cap;
                if (!fresh.occupied[j]) {
                    fresh.keys[j] = m->keys[i];
                    fresh.values[j] = m->values[i];
                    fresh.occupied[j] = true;
                    fresh.count += 1;
                    break;
                }
            }
        }
    }
    free(m->keys); free(m->values); free(m->occupied); free(m->tombstone);
    *m = fresh;
}

static inline bool dictum_map_contains(const dictum_map_t *m, const char *key) {
    if (!m || m->cap == 0 || !key) return false;
    uint32_t h = _dictum_map_hash(key);
    size_t idx = h % m->cap;
    for (size_t probe = 0; probe < m->cap; probe++) {
        size_t i = (idx + probe) % m->cap;
        if (!m->occupied[i]) return false;
        if (!m->tombstone[i] && strcmp(m->keys[i], key) == 0) return true;
    }
    return false;
}

/* Real amortized-growth put: updates in place if the key already
 * exists (a map's defining semantics -- distinct from the set's
 * "insert is a no-op if present"), otherwise inserts a new owned copy
 * of the key. */
static inline void dictum_map_put(dictum_map_t *m, const char *key, int32_t value) {
    if (!m || !key) return;
    if (m->cap > 0) {
        uint32_t h0 = _dictum_map_hash(key);
        size_t idx0 = h0 % m->cap;
        for (size_t probe = 0; probe < m->cap; probe++) {
            size_t i = (idx0 + probe) % m->cap;
            if (!m->occupied[i]) break;
            if (!m->tombstone[i] && strcmp(m->keys[i], key) == 0) {
                m->values[i] = value;  /* real update-in-place, not a duplicate insert */
                return;
            }
        }
    }
    if (m->cap == 0 || (double)(m->count + 1) / (double)m->cap > 0.7) {
        _dictum_map_grow(m);
    }
    uint32_t h = _dictum_map_hash(key);
    size_t idx = h % m->cap;
    for (size_t probe = 0; probe < m->cap; probe++) {
        size_t i = (idx + probe) % m->cap;
        if (!m->occupied[i] || m->tombstone[i]) {
            char *owned_key = (char *)malloc(strlen(key) + 1);
            if (!owned_key) { dictum_error_set("map: out of memory on put"); return; }
            memcpy(owned_key, key, strlen(key) + 1);
            m->keys[i] = owned_key;
            m->values[i] = value;
            m->occupied[i] = true;
            m->tombstone[i] = false;
            m->count += 1;
            return;
        }
    }
    dictum_error_set("map: no free slot found (load-factor invariant violated)");
}

/* Bounds/presence-checked read. A missing key sets a real runtime error
 * (same dictum_error_set mechanism `attempt` blocks use) and returns 0,
 * rather than silently returning a default value the way a raw C
 * lookup or std::map's operator[] would. */
static inline int32_t dictum_map_get(const dictum_map_t *m, const char *key) {
    if (!m || !key || m->cap == 0) {
        dictum_error_set("map: key not found");
        return 0;
    }
    uint32_t h = _dictum_map_hash(key);
    size_t idx = h % m->cap;
    for (size_t probe = 0; probe < m->cap; probe++) {
        size_t i = (idx + probe) % m->cap;
        if (!m->occupied[i]) break;
        if (!m->tombstone[i] && strcmp(m->keys[i], key) == 0) return m->values[i];
    }
    dictum_error_set("map: key not found");
    return 0;
}

static inline size_t dictum_map_len(const dictum_map_t *m) {
    return m ? m->count : 0;
}

static inline void dictum_map_free(dictum_map_t *m) {
    if (!m) return;
    for (size_t i = 0; i < m->cap; i++) {
        if (m->occupied[i]) free(m->keys[i]);
    }
    free(m->keys); free(m->values); free(m->occupied); free(m->tombstone);
    m->keys = NULL; m->values = NULL; m->occupied = NULL; m->tombstone = NULL;
    m->cap = 0; m->count = 0;
}

#endif /* DICTUM_MAP_H */
