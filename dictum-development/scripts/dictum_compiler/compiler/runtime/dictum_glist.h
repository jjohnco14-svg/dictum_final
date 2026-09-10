#ifndef DICTUM_GLIST_H
#define DICTUM_GLIST_H
/*
 * dictum_glist.h — real dynamic-array implementation for `growable list
 * of T` (gap #9, dynamic collections).
 *
 * SCOPE: this pass only implements `growable list of whole number`
 * (int32_t elements). type_to_c() in emit_c.py raises a clear
 * NotImplementedError for any other element type rather than silently
 * mis-compiling it -- there is no dictum_glist_t for text/real
 * number/shapes yet. Map and set are entirely separate, still-open
 * parts of gap #9; this header does not touch them.
 *
 * dictum_glist_t is a real value type (not an opaque handle, unlike
 * dictum_mutex_handle_t) -- callers hold it directly and pass its
 * address (&name) into every function here, matching how the emitter
 * declares it: `dictum_glist_t name = dictum_glist_new();`.
 */
#include "dictum_core.h"
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    int32_t *data;
    size_t len;
    size_t cap;
} dictum_glist_t;

/* Always starts genuinely empty -- no pre-allocation, no uninitialized
 * memory. The first dictum_glist_add() call allocates the initial
 * backing buffer. */
static inline dictum_glist_t dictum_glist_new(void) {
    dictum_glist_t g;
    g.data = NULL;
    g.len = 0;
    g.cap = 0;
    return g;
}

/* Real amortized-growth append: doubles capacity (starting at 4) via
 * realloc whenever the backing buffer is full. */
static inline void dictum_glist_add(dictum_glist_t *g, int32_t value) {
    if (!g) return;
    if (g->len >= g->cap) {
        size_t new_cap = g->cap == 0 ? 4 : g->cap * 2;
        int32_t *new_data = (int32_t *)realloc(g->data, new_cap * sizeof(int32_t));
        if (!new_data) {
            dictum_error_set("growable list: out of memory on add");
            return;
        }
        g->data = new_data;
        g->cap = new_cap;
    }
    g->data[g->len] = value;
    g->len += 1;
}

/* Bounds-checked read. Out-of-range reads set a real error (via the
 * same dictum_error_set/DICTUM_HAS_ERROR() mechanism `attempt` blocks
 * already use) and return 0, rather than reading past the buffer. */
static inline int32_t dictum_glist_get(const dictum_glist_t *g, size_t index) {
    if (!g || index >= g->len) {
        dictum_error_set("growable list: index out of bounds");
        return 0;
    }
    return g->data[index];
}

static inline size_t dictum_glist_len(const dictum_glist_t *g) {
    return g ? g->len : 0;
}

/* Not yet wired to a Dictum-level `release`/`defer release` statement
 * for growable lists (that plumbing wasn't part of this pass) -- but a
 * real free function exists so a caller/future pass can use it, rather
 * than there being no way at all to release the backing buffer. */
static inline void dictum_glist_free(dictum_glist_t *g) {
    if (!g) return;
    free(g->data);
    g->data = NULL;
    g->len = 0;
    g->cap = 0;
}

#endif /* DICTUM_GLIST_H */
