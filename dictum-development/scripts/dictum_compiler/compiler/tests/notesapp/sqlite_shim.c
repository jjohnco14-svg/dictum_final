/* sqlite_shim.c — thin wrappers so Dictum can drive sqlite3.
 *
 * WHY: sqlite3_open takes `sqlite3 **ppDb` (an out-parameter) and
 * sqlite3_exec takes a callback pointer. Dictum's `import from C` has no
 * address-of operator and no function-pointer type, so those signatures
 * cannot be called directly from .dict source. This is the same documented
 * situation as blessed/raygui_wrappers.c: bind a wrapper, not the raw API.
 */
#include <sqlite3.h>
#include <stdlib.h>
#include <string.h>

void *notes_open(const char *path) {
    sqlite3 *db = NULL;
    if (sqlite3_open(path, &db) != SQLITE_OK) return NULL;
    return (void *)db;
}

int notes_exec(void *db, const char *sql) {
    char *err = NULL;
    int rc = sqlite3_exec((sqlite3 *)db, sql, NULL, NULL, &err);
    if (err) sqlite3_free(err);
    return rc;
}

/* Runs a query expected to yield a single integer (e.g. COUNT(*)). */
int notes_query_int(void *db, const char *sql) {
    sqlite3_stmt *st = NULL;
    int out = -1;
    if (sqlite3_prepare_v2((sqlite3 *)db, sql, -1, &st, NULL) != SQLITE_OK) return -1;
    if (sqlite3_step(st) == SQLITE_ROW) out = sqlite3_column_int(st, 0);
    sqlite3_finalize(st);
    return out;
}

int notes_close(void *db) { return sqlite3_close((sqlite3 *)db); }
