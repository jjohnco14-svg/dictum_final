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

/* ---------------------------------------------------------------------
 * TYPED VARIANTS (gap #9, second pass)
 *
 * The original dictum_glist_t hardcodes int32_t, so `growable list of
 * text` / `of decimal number` / ... were rejected outright by the C
 * backend -- while C++ (std::vector) and Nim (seq) supported them fine,
 * making dynamic collections a C-only limitation rather than a language
 * one. C has no generics, so define the same real API per element type
 * via a macro. Each variant is a genuine typed struct with the identical
 * amortized-growth behaviour, not a void* cast.
 * ------------------------------------------------------------------ */
#define DICTUM_GLIST_DEFINE(SUFFIX, T, ZERO)                                  \
typedef struct { T *data; size_t len; size_t cap; } dictum_glist##SUFFIX##_t; \
                                                                              \
static inline dictum_glist##SUFFIX##_t dictum_glist##SUFFIX##_new(void) {     \
    dictum_glist##SUFFIX##_t g; g.data = NULL; g.len = 0; g.cap = 0;          \
    return g;                                                                 \
}                                                                             \
                                                                              \
static inline void dictum_glist##SUFFIX##_add(                                \
        dictum_glist##SUFFIX##_t *g, T value) {                               \
    if (!g) return;                                                           \
    if (g->len >= g->cap) {                                                   \
        size_t ncap = g->cap ? g->cap * 2 : 4;                                \
        T *nd = (T *)realloc(g->data, ncap * sizeof(T));                      \
        if (!nd) { dictum_error_set("growable list: out of memory"); return; }\
        g->data = nd; g->cap = ncap;                                          \
    }                                                                         \
    g->data[g->len] = value;                                                  \
    g->len += 1;                                                              \
}                                                                             \
                                                                              \
static inline T dictum_glist##SUFFIX##_get(                                   \
        const dictum_glist##SUFFIX##_t *g, size_t index) {                    \
    if (!g || index >= g->len) {                                              \
        dictum_error_set("growable list: index out of bounds");               \
        return ZERO;                                                          \
    }                                                                         \
    return g->data[index];                                                    \
}                                                                             \
                                                                              \
static inline size_t dictum_glist##SUFFIX##_len(                              \
        const dictum_glist##SUFFIX##_t *g) { return g ? g->len : 0; }         \
                                                                              \
static inline void dictum_glist##SUFFIX##_free(                               \
        dictum_glist##SUFFIX##_t *g) {                                        \
    if (!g) return;                                                           \
    free(g->data); g->data = NULL; g->len = 0; g->cap = 0;                    \
}

DICTUM_GLIST_DEFINE(_text, dictum_text, NULL)
DICTUM_GLIST_DEFINE(_dec,  double,      0.0)
DICTUM_GLIST_DEFINE(_bool, bool,        false)
DICTUM_GLIST_DEFINE(_byte, uint8_t,     0)

#endif /* DICTUM_GLIST_H */
