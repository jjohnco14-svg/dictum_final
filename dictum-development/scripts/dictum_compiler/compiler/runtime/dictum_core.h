#ifndef DICTUM_CORE_H
#define DICTUM_CORE_H
/*
 * dictum_core.h — common runtime support for transpiled Dictum programs.
 *
 * Currently this is a thin umbrella header: it pulls in the error-state
 * runtime (dictum_error.h) that `attempt` / `produce failure` rely on, and
 * reserves a place for shared helpers (string/list utilities, etc.) as the
 * stdlib bridge grows. Stdlib module headers (dictum_console.h,
 * dictum_json.h, ...) include this header themselves.
 */

#include "dictum_error.h"
#include <stdint.h>
#include <stdio.h>

/* dictum_flush_stdout — for long-running programs that print periodic
 * progress and need it to actually appear promptly. stdout is fully
 * buffered (not line-buffered) whenever it's redirected/captured rather
 * than connected to an interactive terminal -- exactly the case for a
 * captured notebook cell's output -- so without an explicit flush, prints
 * can sit invisible in the buffer for a long time even though they already
 * executed correctly. */
/* MUST tolerate being included by several translation units. A plain
 * (non-static) definition in a HEADER violates C's one-definition rule:
 * every .c that includes this header emits its own copy and the link fails
 * with "multiple definition of 'dictum_flush_stdout'". That is invisible in
 * a single-file build and breaks EVERY multi-file project -- found by
 * writing a real 2-module program.
 *
 * It cannot simply be `static inline`, because `import from C` binds it by
 * name and needs external linkage. `weak` gives both: external linkage, and
 * duplicate definitions across translation units collapse to one instead of
 * colliding. */
#if defined(__GNUC__) || defined(__clang__)
__attribute__((weak))
#endif
int32_t dictum_flush_stdout(void) {
    fflush(stdout);
    return 0;
}

/* dictum_text — matches the `typedef const char* dictum_text;` emitted at
 * the top of every generated translation unit. Guarded so a program that
 * both emits its own typedef and includes this header doesn't conflict. */
#ifndef DICTUM_TEXT_DEFINED
#define DICTUM_TEXT_DEFINED
typedef const char *dictum_text;
#endif

#endif /* DICTUM_CORE_H */
