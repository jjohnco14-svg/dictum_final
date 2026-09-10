#ifndef DICTUM_TLS_H
#define DICTUM_TLS_H
/*
 * dictum_tls.h — real implementation (closes gap #14: dictum_tls.h's
 * stubs wired to a real TLS library).
 *
 * Backed by OpenSSL (libssl/libcrypto). Requires -lssl -lcrypto at link
 * time -- see project_builder.py / emit_c.py's Tls link-flag plumbing
 * (same pattern already used for `use Mutex` -> -lpthread).
 *
 * Function names/signatures here match STDLIB_ACTION_FAMILIES exactly
 * (dictumc/stdlib_registry.py): Tls.wrap/handshake/send/receive/close ->
 * dictum_tls_wrap/handshake/send/receive/close. The PREVIOUS stub file
 * defined a different, unrelated set of names (dictum_tls_connect/recv)
 * that nothing in the registry ever called -- so even filling in the
 * TODOs on the old file would not have closed the real gap; the actual
 * Dictum-visible surface (Tls.wrap etc.) had no implementation at all.
 */
#include "dictum_core.h"
#include "dictum_net.h"
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <openssl/ssl.h>
#include <openssl/err.h>

/* dictum_tls_context_t — opaque handle, same malloc'd-pointer convention
 * as dictum_mutex_handle_t (dictum_mutex.h) and dictum_thread.h. Holds
 * the real SSL and SSL_CTX pointers plus the underlying socket fd so
 * close() can tear down all three in the right order. */
typedef struct dictum_tls_conn {
    SSL_CTX *ctx;
    SSL *ssl;
    dictum_net_socket_t sock;
} *dictum_tls_context_t;

static inline void _dictum_tls_global_init(void) {
    static int done = 0;
    if (done) return;
    done = 1;
#if OPENSSL_VERSION_NUMBER < 0x10100000L
    SSL_library_init();
    SSL_load_error_strings();
    OpenSSL_add_ssl_algorithms();
#else
    (void)0;
#endif
}

static inline dictum_tls_context_t dictum_tls_wrap(dictum_net_socket_t sock) {
    _dictum_tls_global_init();
    if (sock < 0) {
        dictum_error_set("Tls.wrap: invalid socket");
        return NULL;
    }
    struct dictum_tls_conn *conn = (struct dictum_tls_conn *)malloc(sizeof(struct dictum_tls_conn));
    if (!conn) { dictum_error_set("Tls.wrap: out of memory"); return NULL; }
    conn->sock = sock;
    conn->ctx = SSL_CTX_new(TLS_client_method());
    if (!conn->ctx) {
        dictum_error_set("Tls.wrap: SSL_CTX_new failed");
        free(conn);
        return NULL;
    }
    conn->ssl = SSL_new(conn->ctx);
    if (!conn->ssl) {
        dictum_error_set("Tls.wrap: SSL_new failed");
        SSL_CTX_free(conn->ctx);
        free(conn);
        return NULL;
    }
    if (!SSL_set_fd(conn->ssl, sock)) {
        dictum_error_set("Tls.wrap: SSL_set_fd failed");
        SSL_free(conn->ssl);
        SSL_CTX_free(conn->ctx);
        free(conn);
        return NULL;
    }
    return conn;
}

static inline bool dictum_tls_handshake(dictum_tls_context_t conn) {
    if (!conn || !conn->ssl) {
        dictum_error_set("Tls.handshake: invalid tls context");
        return false;
    }
    int r = SSL_connect(conn->ssl);
    if (r != 1) {
        int err = SSL_get_error(conn->ssl, r);
        char msg[128];
        snprintf(msg, sizeof(msg), "Tls.handshake: SSL_connect failed (SSL error %d)", err);
        dictum_error_set(msg);
        return false;
    }
    return true;
}

static inline int32_t dictum_tls_send(dictum_tls_context_t conn, dictum_text data) {
    if (!conn || !conn->ssl || !data) {
        dictum_error_set("Tls.send: invalid tls context or data");
        return -1;
    }
    int n = SSL_write(conn->ssl, data, (int)strlen(data));
    if (n <= 0) {
        int err = SSL_get_error(conn->ssl, n);
        char msg[128];
        snprintf(msg, sizeof(msg), "Tls.send: SSL_write failed (SSL error %d)", err);
        dictum_error_set(msg);
        return -1;
    }
    return (int32_t)n;
}

static inline dictum_text dictum_tls_receive(dictum_tls_context_t conn) {
    if (!conn || !conn->ssl) {
        dictum_error_set("Tls.receive: invalid tls context");
        return "";
    }
    char buf[4096];
    int n = SSL_read(conn->ssl, buf, sizeof(buf) - 1);
    if (n <= 0) {
        int err = SSL_get_error(conn->ssl, n);
        if (err == SSL_ERROR_ZERO_RETURN) {
            return "";
        }
        char msg[128];
        snprintf(msg, sizeof(msg), "Tls.receive: SSL_read failed (SSL error %d)", err);
        dictum_error_set(msg);
        return "";
    }
    buf[n] = '\0';
    char *out = (char *)malloc((size_t)n + 1);
    if (!out) { dictum_error_set("Tls.receive: out of memory"); return ""; }
    memcpy(out, buf, (size_t)n + 1);
    return out;
}

static inline void dictum_tls_close(dictum_tls_context_t conn) {
    if (!conn) return;
    if (conn->ssl) {
        SSL_shutdown(conn->ssl);
        SSL_free(conn->ssl);
    }
    if (conn->ctx) {
        SSL_CTX_free(conn->ctx);
    }
    if (conn->sock >= 0) {
        dictum_net_close(conn->sock);
    }
    free(conn);
}

#endif /* DICTUM_TLS_H */
