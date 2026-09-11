#!/usr/bin/env python3
"""
run_selftest.py — Dictum compiler self-test.

Three tiers, in order:

  §1 STATIC INVENTORY   — for every entry in STDLIB_ACTION_FAMILIES, checks
                           whether the corresponding C function in runtime/
                           has a real body, a stub body, or doesn't exist at
                           all. This is what previously reported "3 real /
                           32 stub / 57 missing".

  §2 BEHAVIORAL TESTS    — actually compiles and RUNS small real C/gcc
                           programs against each implemented runtime header,
                           exercising real files, real sockets, real
                           mutexes+threads (a genuine race-condition test,
                           not just a syntax check), and a real HTTP
                           request/response over a loopback socket. A
                           module only counts as PASS here if its behavior
                           is independently verified, not just "compiles".

  §3 REGRESSION TESTS    — one test per concrete, previously-silent bug
                           found and fixed this session, so none of them
                           can silently come back:
                             R1  link-flag plumbing (#[link]/module ldflags
                                 actually reach the Makefile / --compile /
                                 the VS Code extension's compile-check gate)
                             R2  stdlib FuncCall return-type inference
                                 (was always int32_t — silent pointer
                                 truncation for handle-returning calls)
                             R3  string escape handling (\\" in Dictum
                                 source must survive as a real quote and
                                 be re-escaped correctly for C)
                             R4  preamble-ordering bug that ate the
                                 _DEFAULT_SOURCE POSIX feature-test macro
                             R5  project_builder.py multi-file projects
                             R6  parse_deps colon-less module/program/shape syntax
                             R7  parse_keep 'with no value' / 'with all values' dangling-token bug
                             R8  emit_c.py list-of-T action parameter (T*, size_t) propagation
                             R9  emit_cpp.py list-of-T maps to real std::vector<T>
                             R10 dict_syntax_check.py agrees with the real parser
                                 use StdlibTranspiler (not plain
                                 Transpiler), so stdlib calls validate at
                                 all in a multi-file build
                             R11 cross-file `use` of a shape validates
                                 (Validator.validate extra_shapes/
                                 extra_actions)
                             R12 cross-file `import from C` action
                                 validates (collect_globals ImportC/
                                 ImportCpp)
                             R13 module-scope global initialized from
                                 another module-scope constant is
                                 constant-folded (not an illegal C
                                 global initializer, and not silently
                                 dropped for module-only files with no
                                 main())
                             R14 dictum_text typedef ordered before
                                 cross-file `use` #includes
                             R15 `use` statements don't leak a raw
                                 #include into main()'s body
                             R16 a local var inside an action body,
                                 initialized via a function call, is
                                 declared+initialized directly, not
                                 deferred into main() (which corrupts
                                 scope for module-only-caller cases)
                             R17 cross-file call-name mangling: unqualified
                                 calls to a `use`d sibling module's action
                                 resolve to that module's real prefixed C
                                 symbol (project_builder.py's local_modules/
                                 project_modules split)
                             R18 an `import from C` alias colliding with a
                                 libc-reserved name (sqrt, sin, cos, ...) is
                                 called under its real name at the call site
                             R19 (severe) FFI prototypes appear in the
                                 per-module cross-file shared header --
                                 previously silently missing, causing
                                 implicit-int fallback and pointer
                                 truncation for any FFI call returning a
                                 non-int type from another file
                             R50 emit_nim.py string literals use real
                                 Nim double-quoted syntax, not Python's
                                 repr() (which emits single-quoted
                                 output -- a Nim *character* literal,
                                 a hard compile error for anything but
                                 one codepoint)
                             R51 emit_nim.py `print` stringifies every
                                 non-string-literal part with `$` before
                                 `&`-concatenating, so mixed text+number
                                 prints actually compile
                             R52 emit_nim.py `repeat N times using i`
                                 anchors the range to int32 explicitly,
                                 so the loop var's type matches every
                                 other `whole number` in the program
                             R53 emit_nim.py maps the `%` operator
                                 (what `X modulo Y` actually parses to)
                                 to Nim's `mod` -- Nim has no integer `%`
                             R54 emit_nim.py `the count of X` is a
                                 UnaryOp, not a FuncCall -- the old
                                 FuncCall-only special case never fired
                             R55 emit_nim.py Table[K, V]/HashSet[T]
                                 default-value construction no longer
                                 double-closes the generic brackets
                             R56 emit_nim.py `add to X` calls `.incl()`
                                 for HashSet targets, `.add()` for seq
                                 targets, based on the declared type
                             R57 emit_nim.py auto-imports std/tables
                                 and std/sets as a final pass over the
                                 emitted source, since Table[]/HashSet[]
                                 types are only known after the single
                                 up-front `use`-based import pass runs
                             R58 real end-to-end FFI proof: a genuine
                                 `import from C` call against a real
                                 system library (-lsqlite3) through the
                                 Nim backend, requiring three more real
                                 fixes -- no `--link LIBNAME` flag
                                 existed at all before this (nothing
                                 ever passed -l<lib> to gcc/g++/nim on
                                 any backend); emit_nim.py's ImportC
                                 fabricated a nonexistent header
                                 filename; and `text`-returning FFI
                                 calls segfaulted assigning a raw
                                 `cstring` into a GC `string` slot
                             R59 emit_c.py/emit_cpp.py stray dictum_main()
                                 call with no definition -- broke linking
                                 for every bare single-file program on
                                 both backends
                             R60 dictumc_cli.py --compile missing -I
                                 <runtime dir> -- broke any program using
                                 a runtime-header-dependent stdlib feature
                             R61 dictumc_cli.py --compile now persists the
                                 intermediate C/C++ source at <binary>.<ext>
                                 instead of deleting an ephemeral tempfile
                             R62 guide_c_verify.py: a GUI verify_script
                                 that can never fail is caught via its
                                 declared mutation_fixture, not silently
                                 trusted
                             R63 guide_c_verify.py: a failing console_check
                                 now SKIPs gui_checks in the same manifest
                                 instead of still paying the Xvfb cost
                             R64 emit_cpp.py _format_spec: a text variable
                                 from `call FUNC giving VAR` on an imported
                                 C function now prints with %s, not the
                                 numeric %d default

Exit code is 0 only if every behavioral test and every regression test
passes. Inventory numbers are reported but don't fail the run by
themselves — modules nobody has gotten to yet (Tls, Channel, Shm, ...)
are expected to still show as stub/missing.

Usage: python3 run_selftest.py [--verbose]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, "runtime")
CLI = os.path.join(HERE, "dictumc_cli.py")
PROJECT_BUILDER = os.path.join(HERE, "project_builder.py")
PROJECT_BUILDER = os.path.join(HERE, "project_builder.py")
VERBOSE = "--verbose" in sys.argv

sys.path.insert(0, HERE)
from dictumc.stdlib_registry import STDLIB_ACTION_FAMILIES  # noqa: E402


def log(msg=""):
    print(msg)


def vlog(msg):
    if VERBOSE:
        print("    " + msg)


# ─────────────────────────────────────────────────────────────────────────
# §1 Static inventory
# ─────────────────────────────────────────────────────────────────────────

_STUB_MARKERS = (
    "not yet implemented",
    "/* stub */",
    "// stub",
    "TODO",
)


def _find_c_function_body(c_name: str) -> Optional[str]:
    """Grep every runtime/*.h for a definition of `c_name` and return its
    body text (from the opening `{` to the matching top-level `}`), or
    None if not found anywhere."""
    pattern = re.compile(
        r'\b(?:static\s+inline\s+)?[\w\*\s]+?\b' + re.escape(c_name) + r'\s*\([^;{]*\)\s*\{'
    )
    for fname in sorted(os.listdir(RUNTIME_DIR)):
        if not fname.endswith(".h"):
            continue
        path = os.path.join(RUNTIME_DIR, fname)
        text = open(path, encoding="utf-8").read()
        m = pattern.search(text)
        if not m:
            continue
        # Walk forward from the opening brace to find the matching close.
        depth = 0
        i = m.end() - 1
        start_body = m.end()
        for j in range(m.end() - 1, len(text)):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
                if depth == 0:
                    return text[start_body:j]
        return text[start_body:]
    return None


def run_inventory():
    log("=" * 70)
    log("§1 STATIC STDLIB INVENTORY")
    log("=" * 70)

    real, stub, missing = [], [], []
    for key, (c_name, params, ret) in sorted(STDLIB_ACTION_FAMILIES.items()):
        # Some registry entries (Math.sqrt -> "sqrt", Math.abs -> "fabs", ...)
        # deliberately call a real libc/libm function directly rather than
        # going through a dictum_*.h wrapper — there's nothing to wrap, the
        # real implementation already exists in a system library the
        # program links against. Counting these as "missing" (because no
        # runtime/*.h defines a body for them) would understate real
        # coverage, so any c_name without the project's `dictum_` prefix
        # is treated as a real, already-implemented passthrough.
        if not c_name.startswith("dictum_"):
            real.append(key)
            continue
        body = _find_c_function_body(c_name)
        if body is None:
            missing.append(key)
            continue
        is_stub = any(marker in body for marker in _STUB_MARKERS)
        # A body under ~3 non-blank lines that's just a bare return of a
        # constant (0 / NULL / (void*)0) with no other logic is also
        # effectively a stub even without an explicit marker comment.
        meaningful_lines = [l.strip() for l in body.splitlines() if l.strip()]
        trivial_return = (
            len(meaningful_lines) <= 1
            and re.match(r'return\s*(\(void\*\)\s*0|0|NULL)\s*;?\s*$', meaningful_lines[0] if meaningful_lines else '')
        )
        if is_stub or trivial_return:
            stub.append(key)
        else:
            real.append(key)

    total = len(STDLIB_ACTION_FAMILIES)
    log(f"stdlib inventory: {total} registered functions")
    log(f"  real implementation : {len(real):3d}  ({100*len(real)//total}%)")
    log(f"  stub only            : {len(stub):3d}")
    log(f"  missing entirely     : {len(missing):3d}")
    log("")
    if VERBOSE:
        log("real:    " + ", ".join(real))
        log("stub:    " + ", ".join(stub))
        log("missing: " + ", ".join(missing))
        log("")

    by_module = {}
    for key in STDLIB_ACTION_FAMILIES:
        mod = key.split(".")[0]
        by_module.setdefault(mod, {"real": 0, "stub": 0, "missing": 0})
    for key in real:
        by_module[key.split(".")[0]]["real"] += 1
    for key in stub:
        by_module[key.split(".")[0]]["stub"] += 1
    for key in missing:
        by_module[key.split(".")[0]]["missing"] += 1

    log(f"{'module':<12}{'real':>6}{'stub':>6}{'missing':>9}")
    for mod in sorted(by_module):
        c = by_module[mod]
        log(f"{mod:<12}{c['real']:>6}{c['stub']:>6}{c['missing']:>9}")
    log("")
    return real, stub, missing


# ─────────────────────────────────────────────────────────────────────────
# §2 Behavioral tests — real gcc compile + real execution
# ─────────────────────────────────────────────────────────────────────────

def _gcc(src_path: str, out_path: str, extra_flags=None) -> subprocess.CompletedProcess:
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-I", RUNTIME_DIR]
    if extra_flags:
        flags += extra_flags
    return subprocess.run(
        ["gcc", *flags, src_path, "-o", out_path],
        capture_output=True, text=True, timeout=30,
    )


def _run(bin_path: str, timeout=8, env=None, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run([bin_path], capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)


BEHAVIORAL_TESTS = []


def behavioral(name):
    def deco(fn):
        BEHAVIORAL_TESTS.append((name, fn))
        return fn
    return deco


@behavioral("Text: real string ops (concat/slice/trim/case/replace/split/utf8)")
def test_text(tmp):
    src = os.path.join(tmp, "t.c")
    open(src, "w").write(r'''
#include "dictum_text.h"
#include <assert.h>
int main(void) {
    assert(dictum_text_length("hello") == 5);
    assert(dictum_text_utf8_length("h\xc3\xa9llo") == 5);
    dictum_text c = dictum_text_concat("foo", "bar");
    assert(strcmp(c, "foobar") == 0); free((void*)c);
    dictum_text r = dictum_text_replace("aXbXc", "X", "-");
    assert(strcmp(r, "a-b-c") == 0); free((void*)r);
    dictum_text *parts = dictum_text_split("a,b,c", ",");
    assert(strcmp(parts[0], "a") == 0 && strcmp(parts[2], "c") == 0 && parts[3] == NULL);
    for (int i = 0; parts[i]; i++) free((void*)parts[i]);
    free(parts);
    return 0;
}
''')
    bin_ = os.path.join(tmp, "t")
    r = _gcc(src, bin_)
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"
    r = _run(bin_)
    if r.returncode != 0:
        return False, f"runtime failure (exit {r.returncode}):\n{r.stderr}"
    return True, "ok"


@behavioral("File: real read/write/exists/delete/list against the real filesystem")
def test_file(tmp):
    src = os.path.join(tmp, "t.c")
    target = os.path.join(tmp, "sample.txt")
    open(src, "w").write(f'''
#include "dictum_file.h"
#include <assert.h>
int main(void) {{
    const char *path = "{target}";
    assert(dictum_file_write(path, "hello\\nworld"));
    assert(dictum_file_exists(path));
    dictum_text c = dictum_file_read(path);
    assert(c && strcmp(c, "hello\\nworld") == 0);
    free((void*)c);
    assert(dictum_file_delete(path));
    assert(!dictum_file_exists(path));
    return 0;
}}
''')
    bin_ = os.path.join(tmp, "t")
    r = _gcc(src, bin_)
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"
    r = _run(bin_)
    if r.returncode != 0:
        return False, f"runtime failure (exit {r.returncode}):\n{r.stderr}"
    return True, "ok"


@behavioral("Json: real recursive-descent parse/get/set/stringify round-trip")
def test_json(tmp):
    src = os.path.join(tmp, "t.c")
    open(src, "w").write(r'''
#include "dictum_json.h"
#include <assert.h>
int main(void) {
    int h = dictum_json_parse("{\"name\":\"Jeff\",\"age\":19,\"tags\":[\"a\",\"b\"]}");
    assert(h >= 0);
    dictum_text n = dictum_json_get_string(h, "name");
    assert(n && strcmp(n, "Jeff") == 0); free((void*)n);
    assert(dictum_json_get_int(h, "age") == 19);
    assert(dictum_json_array_length(h, "tags") == 2);
    assert(dictum_json_parse("{not json") == -1);
    dictum_json_destroy(h);
    return 0;
}
''')
    bin_ = os.path.join(tmp, "t")
    r = _gcc(src, bin_)
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"
    r = _run(bin_)
    if r.returncode != 0:
        return False, f"runtime failure (exit {r.returncode}):\n{r.stderr}"
    return True, "ok"


@behavioral("Mutex+Thread: real race condition — fails without a working mutex")
def test_mutex_thread(tmp):
    src = os.path.join(tmp, "t.c")
    open(src, "w").write(r'''
#include "dictum_mutex.h"
#include "dictum_thread.h"
#include <assert.h>
static int counter = 0;
static dictum_mutex_handle_t g_mutex;
void bump(void) {
    for (int i = 0; i < 20000; i++) {
        dictum_mutex_lock(g_mutex);
        counter++;
        dictum_mutex_unlock(g_mutex);
    }
}
int main(void) {
    g_mutex = dictum_mutex_create();
    assert(g_mutex);
    dictum_thread_handle_t t1 = dictum_thread_start(bump);
    dictum_thread_handle_t t2 = dictum_thread_start(bump);
    dictum_thread_join(t1);
    dictum_thread_join(t2);
    assert(counter == 40000);  /* fails/flakes without a real mutex */
    dictum_mutex_destroy(g_mutex);
    return 0;
}
''')
    bin_ = os.path.join(tmp, "t")
    r = _gcc(src, bin_, extra_flags=["-pthread"])
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"
    r = _run(bin_)
    if r.returncode != 0:
        return False, f"runtime failure (exit {r.returncode}):\n{r.stderr}"
    return True, "ok"


@behavioral("Net: real loopback client/server round-trip over POSIX sockets")
def test_net(tmp):
    src = os.path.join(tmp, "t.c")
    open(src, "w").write(r'''
#include "dictum_net.h"
#include "dictum_thread.h"
#include <assert.h>
#include <unistd.h>
static dictum_net_socket_t g_server;
void server_thread(void) {
    dictum_net_socket_t c = dictum_net_accept(g_server);
    dictum_text msg = dictum_net_receive(c);
    assert(msg && strcmp(msg, "ping") == 0);
    free((void*)msg);
    dictum_net_send(c, "pong");
    dictum_net_close(c);
}
int main(void) {
    g_server = dictum_net_listen(58921);
    assert(g_server >= 0);
    dictum_thread_handle_t t = dictum_thread_start(server_thread);
    usleep(50000);
    dictum_net_socket_t c = dictum_net_connect("127.0.0.1", 58921);
    assert(c >= 0);
    assert(dictum_net_send(c, "ping") == 4);
    dictum_text resp = dictum_net_receive(c);
    assert(resp && strcmp(resp, "pong") == 0);
    free((void*)resp);
    dictum_net_close(c);
    dictum_thread_join(t);
    dictum_net_close(g_server);
    return 0;
}
''')
    bin_ = os.path.join(tmp, "t")
    r = _gcc(src, bin_, extra_flags=["-pthread"])
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"
    r = _run(bin_)
    if r.returncode != 0:
        return False, f"runtime failure (exit {r.returncode}):\n{r.stderr}"
    return True, "ok"


@behavioral("Http: real GET/POST over loopback against a live Python HTTP server")
def test_http(tmp):
    port = 58933
    server_src = os.path.join(tmp, "srv.py")
    open(server_src, "w").write(f'''
import http.server, socketserver
socketserver.TCPServer.allow_reuse_address = True
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/plain'); self.end_headers()
        self.wfile.write(b"hello world")
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(n)
        self.send_response(200); self.end_headers()
        self.wfile.write(b"received: " + data)
with socketserver.TCPServer(("127.0.0.1", {port}), H) as httpd:
    httpd.serve_forever()
''')
    src = os.path.join(tmp, "t.c")
    open(src, "w").write(f'''
#include "dictum_http.h"
#include <assert.h>
int main(void) {{
    dictum_text r = dictum_http_get("http://127.0.0.1:{port}/x");
    assert(r && strstr(r, "hello world"));
    free((void*)r);
    dictum_text r2 = dictum_http_post("http://127.0.0.1:{port}/x", "payload", "text/plain");
    assert(r2 && strstr(r2, "payload"));
    free((void*)r2);
    dictum_text r3 = dictum_http_get("https://example.com/");
    assert(r3 == NULL);  /* documented limitation, must fail loudly not silently */
    return 0;
}}
''')
    bin_ = os.path.join(tmp, "t")
    r = _gcc(src, bin_, extra_flags=["-pthread"])
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"
    server = subprocess.Popen(
        [sys.executable, "-u", server_src], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        import time
        time.sleep(1)
        r = _run(bin_)
    finally:
        server.kill()
        server.wait(timeout=3)
    if r.returncode != 0:
        return False, f"runtime failure (exit {r.returncode}):\n{r.stderr}"
    return True, "ok"


def run_behavioral():
    log("=" * 70)
    log("§2 BEHAVIORAL TESTS (real gcc compile + real execution)")
    log("=" * 70)
    results = []
    for name, fn in BEHAVIORAL_TESTS:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                ok, detail = fn(tmp)
            except Exception as e:
                ok, detail = False, f"exception: {e}"
        status = "PASS" if ok else "FAIL"
        log(f"[{status}] {name}")
        if not ok:
            log(f"       {detail}")
        elif VERBOSE:
            vlog(detail)
        results.append((name, ok))
    log("")
    return results


# ─────────────────────────────────────────────────────────────────────────
# §3 Regression tests — one per bug fixed this session
# ─────────────────────────────────────────────────────────────────────────

REGRESSION_TESTS = []


def regression(name):
    def deco(fn):
        REGRESSION_TESTS.append((name, fn))
        return fn
    return deco


@regression("R1 link-flag plumbing: --print-ldflags reflects `use Mutex` (-lpthread), not just -lm")
def test_r1_ldflags(tmp):
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "use Mutex\n\nprogram Main\n"
        "    call Mutex.create giving m\n"
        "    call Console.write_line with \"ok\"\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--stdlib", "--print-ldflags"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"CLI failed: {r.stderr}"
    flags = r.stdout.strip()
    if "-lpthread" not in flags:
        return False, f"expected -lpthread in computed ldflags, got: {flags!r}"
    return True, flags


@regression("R1b link-flag plumbing: a program using ONLY Math gets -lm and nothing extra")
def test_r1b_ldflags_minimal(tmp):
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "program Main\n"
        "    call Console.write_line with \"ok\"\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--stdlib", "--print-ldflags"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"CLI failed: {r.stderr}"
    flags = r.stdout.strip()
    if "-lpthread" in flags:
        return False, f"did not expect -lpthread for a Mutex/Thread-free program, got: {flags!r}"
    if "-lm" not in flags:
        return False, f"expected baseline -lm always present, got: {flags!r}"
    return True, flags


@regression("R2 stdlib return-type inference: `call Mutex.create giving m` types m as a handle, not int32_t")
def test_r2_return_type(tmp):
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "use Mutex\n\nprogram Main\n"
        "    call Mutex.create giving m\n"
        "    call Mutex.lock with m\n"
        "    call Mutex.unlock with m\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--stdlib"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"CLI failed: {r.stderr}"
    code = r.stdout
    if "int32_t m = dictum_mutex_create" in code:
        return False, "m was declared int32_t — pointer-truncating regression is back"
    if "dictum_mutex_handle_t m" not in code:
        return False, f"expected `dictum_mutex_handle_t m`, got:\n{code}"
    return True, "ok"


@regression("R3 string escaping: an embedded \\\" in Dictum source survives as valid, correctly-escaped C")
def test_r3_string_escape(tmp):
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        'program Main\n'
        '    call Console.write_line with "{\\"name\\":\\"Jeff\\"}"\n'
        'end program\n'
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--stdlib"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"CLI failed: {r.stderr}"
    code = r.stdout
    out_c = os.path.join(tmp, "out.c")
    open(out_c, "w").write(code)
    comp = _gcc(out_c, os.path.join(tmp, "out"))
    if comp.returncode != 0:
        return False, f"generated C failed to compile:\n{comp.stderr}\n---\n{code}"
    run = _run(os.path.join(tmp, "out"))
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if '{"name":"Jeff"}' not in run.stdout:
        return False, f"expected the literal JSON text in output, got: {run.stdout!r}"
    return True, "ok"


@regression("R4 preamble ordering: #define _DEFAULT_SOURCE stays before the first #include")
def test_r4_preamble_order(tmp):
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "use File\nuse Json\n\nprogram Main\n"
        "    call File.write with \"/tmp/_dictum_selftest.json\" and \"{}\"\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--stdlib"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"CLI failed: {r.stderr}"
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    first_include_idx = next((i for i, l in enumerate(lines) if l.strip().startswith("#include")), None)
    define_idx = next((i for i, l in enumerate(lines) if "_DEFAULT_SOURCE" in l), None)
    if define_idx is None:
        return False, "no _DEFAULT_SOURCE define found in output at all"
    if first_include_idx is None or define_idx > first_include_idx:
        return False, f"_DEFAULT_SOURCE (line {define_idx}) is not before the first #include (line {first_include_idx})"
    return True, "ok"


@regression("R5 project_builder.py uses StdlibTranspiler, so multi-file projects validate stdlib calls")
def test_r5_project_builder_stdlib(tmp):
    src = open(PROJECT_BUILDER, encoding="utf-8").read()
    if "StdlibTranspiler" not in src:
        return False, "project_builder.py no longer imports/uses StdlibTranspiler"
    if re.search(r'\bt\s*=\s*Transpiler\(', src):
        return False, "project_builder.py still constructs a plain Transpiler() somewhere"
    return True, "ok"


@regression("R6 project_builder.py parse_deps recognizes real (colon-less) module/program/shape syntax and generates cross-file headers")
def test_r6_parse_deps_no_colon(tmp):
    # Real Dictum syntax has no trailing colon after `module Name`, `program
    # Name`, or `shape Name holds` — parse_deps() used to require one
    # (`r'^\s*module\s+(\w+)\s*:'` etc), so fi['modules'] was always empty
    # for real source, header generation silently never fired, and any
    # cross-file call failed to link with a missing-header compile error.
    os.makedirs(tmp, exist_ok=True)
    mod_path = os.path.join(tmp, "mask_utils.dict")
    main_path = os.path.join(tmp, "main.dict")
    open(mod_path, "w").write(
        "module mask_utils\n"
        "    action toggle_flags takes a as whole number and b as whole number produces whole number\n"
        "        return the bitwise xor of a and b\n"
        "    end action\n"
        "end module\n"
    )
    open(main_path, "w").write(
        "program mask_demo\n"
        "    use mask_utils\n"
        "    keep result as whole number with value 0\n"
        "    call mask_utils.toggle_flags with 12 and 10 giving result\n"
        "    print the text \"result:\" and result\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    header_path = os.path.join(out_dir, "dictum_mask_utils.h")
    if not os.path.exists(header_path):
        return False, "dictum_mask_utils.h was never generated — module went undetected again"

    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "mask_demo"),
        extra_flags=[os.path.join(out_dir, "mask_utils.c"), "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"linked build failed:\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "mask_demo"))
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "result:6" not in run.stdout:
        return False, f"expected 'result:6' (12 XOR 10), got: {run.stdout!r}"
    return True, run.stdout


@regression("R7 parse_keep: 'with no value' and 'with all values X' consume both words, not just the first")
def test_r7_keep_no_value_all_values(tmp):
    # match_word(*words) is variadic-OR ("does the current token match ANY
    # of these"), not a sequential-AND matcher. `match_word('no', 'value')`
    # and `match_word('all', 'values')` were misused as if they meant
    # "match 'no' THEN 'value'" — in reality each call consumes exactly one
    # token. For `with no value`, matching 'no' left a dangling 'value'
    # token that then broke the *next* statement's parse. Same shape of
    # bug for `with all values X`.
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "shape Point holds\n"
        "    x as whole number\n"
        "end shape\n\n"
        "program Main\n"
        "    keep p as Point with no value\n"
        "    set x of p to 3\n"
        "    print the text \"x:\" and x of p\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--compile", "--output", os.path.join(tmp, "out")],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"'with no value' failed to compile: {r.stdout}\n{r.stderr}"
    run = _run(os.path.join(tmp, "out"))
    if run.returncode != 0 or "x:3" not in run.stdout:
        return False, f"unexpected output: {run.stdout!r} / {run.stderr!r}"

    src2 = os.path.join(tmp, "m2.dict")
    open(src2, "w").write(
        "program Main2\n"
        "    keep n as whole number with value 5\n"
        "    keep total as whole number with value 0\n"
        "    put n plus 1 into total\n"
        "    print the text \"total:\" and total\n"
        "end program\n"
    )
    # (all-values path needs a real collection target to be meaningful at
    # runtime; here we just confirm the *parser* consumes both 'all' and
    # 'values' by checking a minimal with-all-values declaration parses
    # without leaving a dangling token that corrupts the next statement.)
    src3 = os.path.join(tmp, "m3.dict")
    open(src3, "w").write(
        "program Main3\n"
        "    keep n as whole number with value 3\n"
        "    keep nums as list of whole number with all values n\n"
        "    print the text \"ok\"\n"
        "end program\n"
    )
    r3 = subprocess.run(
        [sys.executable, CLI, src3, "--backend", "c"],
        capture_output=True, text=True, timeout=20,
    )
    if r3.returncode != 0:
        return False, f"'with all values' failed to compile: {r3.stdout}\n{r3.stderr}"
    if "Use of undeclared variable 'values'" in r3.stdout or "'n' is not a recognized statement" in r3.stdout:
        return False, f"dangling 'values'/'n' token regression is back: {r3.stdout}"
    return True, "ok"


@regression("R8 emit_c.py: `list of T` action parameter propagates array+count into the C signature, not a bare scalar")
def test_r8_list_param_propagates_count(tmp):
    # Found, previously documented as known-but-not-fixed (CHANGELOG.md /
    # docs §12): type_to_c() strips 'list of T' down to the bare element
    # type T, so an action parameter declared `takes nums as list of T`
    # emitted as a scalar `T nums` in the C signature instead of a real
    # `T* nums, size_t nums_count` pair -- silently dropping both the
    # pointer-ness and the count. Any use of the parameter as a real list
    # inside the callee (indexing, `for each x in nums`, `the count of
    # nums`) then referenced a `nums_count` that was never declared,
    # a hard "'nums_count' undeclared" compile error -- and the call site
    # never passed a matching count argument either.
    #
    # This exercises the full round trip: a locally-declared list passed
    # to a separate action, the action iterating it with `for each` (which
    # depends on the `_count` companion internally) and returning a real
    # computed value, proving the (T*, size_t) pair reaches the callee
    # correctly and the call site supplies both parts.
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "program ListParamDemo\n"
        "    action sum_list takes nums as list of whole number produces whole number\n"
        "        keep total as whole number with value 0\n"
        "        for each n in nums repeat\n"
        "            set total to total plus n\n"
        "        end for\n"
        "        return total\n"
        "    end action\n\n"
        "    keep values as list of whole number with values 3 and 5 and 7 and 10\n"
        "    keep result as whole number with value 0\n"
        "    call sum_list with values giving result\n"
        "    print the text \"sum:\" and result and newline\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--compile", "--output", os.path.join(tmp, "out")],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"list-of-T action parameter failed to compile: {r.stdout}\n{r.stderr}"
    run = _run(os.path.join(tmp, "out"))
    if run.returncode != 0 or "sum:25" not in run.stdout:
        return False, f"unexpected output (expected sum:25): {run.stdout!r} / {run.stderr!r}"

    # Also confirm the emitted C signature itself, not just runtime
    # behavior, so a future change that happens to get the right answer
    # via some other coincidental path still gets caught if it regresses
    # the actual (T*, size_t) shape of the signature.
    r2 = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c"],
        capture_output=True, text=True, timeout=20,
    )
    if r2.returncode != 0:
        return False, f"plain (non-compile) emit failed: {r2.stdout}\n{r2.stderr}"
    code = r2.stdout
    if "int32_t* nums, size_t nums_count" not in code:
        return False, f"expected expanded (T*, size_t) signature not found in emitted C:\n{code}"
    if "sum_list(values, values_count)" not in code:
        return False, f"expected call site to pass both value and count arg:\n{code}"
    return True, "ok"


@regression("R9 emit_cpp.py: `list of T` maps to a real std::vector<T>, not a bogus type name or a raw-repr-leaking array literal")
def test_r9_cpp_list_param_uses_vector(tmp):
    # Found while verifying R8's C-only fix against the C++ backend
    # independently (the C fix did not touch emit_cpp.py at all).
    # type_to_cpp() only matched the suffix spelling ('TYPE list'/'TYPE
    # array') when mapping to std::vector<T> -- the prefix spelling
    # ('list of TYPE'/'array of TYPE'), which is what Dictum source
    # actually uses everywhere (parser.py's parse_type), fell through to
    # the generic identifier fallback and produced a non-existent type
    # name like `list_of_whole_number`. Separately, and unmasked once the
    # first bug was fixed and this code path became reachable at all: the
    # list-literal VarDecl branch called bare str(v) on each element,
    # which is correct for a raw primitive but produced the Python repr
    # of the underlying AST node (literally `Literal(line=10, value=1)`)
    # when elements arrive as nested Literal nodes instead of raw values
    # -- so even a same-scope local list literal didn't compile.
    #
    # This exercises the same round trip as R8 (local list -> action
    # parameter -> for-each -> computed result) but on --backend cpp,
    # and additionally asserts the emitted signature is a real
    # std::vector<T>, not a bare scalar and not the old bogus name.
    src = os.path.join(tmp, "m.dict")
    open(src, "w").write(
        "program ListParamDemoCpp\n"
        "    action sum_list takes nums as list of whole number produces whole number\n"
        "        keep total as whole number with value 0\n"
        "        for each n in nums repeat\n"
        "            set total to total plus n\n"
        "        end for\n"
        "        return total\n"
        "    end action\n\n"
        "    keep values as list of whole number with values 3 and 5 and 7 and 10\n"
        "    keep result as whole number with value 0\n"
        "    call sum_list with values giving result\n"
        "    print the text \"sum:\" and result and newline\n"
        "end program\n"
    )
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "cpp", "--compile", "--output", os.path.join(tmp, "out")],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"list-of-T action parameter failed to compile on C++ backend: {r.stdout}\n{r.stderr}"
    run = _run(os.path.join(tmp, "out"))
    if run.returncode != 0 or "sum:25" not in run.stdout:
        return False, f"unexpected output (expected sum:25): {run.stdout!r} / {run.stderr!r}"

    r2 = subprocess.run(
        [sys.executable, CLI, src, "--backend", "cpp"],
        capture_output=True, text=True, timeout=20,
    )
    if r2.returncode != 0:
        return False, f"plain (non-compile) emit failed: {r2.stdout}\n{r2.stderr}"
    code = r2.stdout
    if "std::vector<int32_t> nums" not in code:
        return False, f"expected a real std::vector<int32_t> parameter type, not found:\n{code}"
    if "list_of_whole_number" in code:
        return False, f"bogus non-existent type name regressed back in:\n{code}"
    if "Literal(" in code:
        return False, f"raw AST-repr leak into list literal regressed back in:\n{code}"
    return True, "ok"


def run_regressions():
    log("=" * 70)
    log("§3 REGRESSION TESTS (one per bug fixed this session)")
    log("=" * 70)
    results = []
    for name, fn in REGRESSION_TESTS:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                ok, detail = fn(tmp)
            except Exception as e:
                ok, detail = False, f"exception: {e}"
        # ok can be True (PASS), False (FAIL — a real bug), or None (SKIP —
        # the *environment* isn't set up for this test, e.g. a missing pip
        # package; this is deliberately NOT the same bucket as a real code
        # bug, so a stale environment can never masquerade as a regression
        # and a real regression can never hide behind "oh it's probably env").
        status = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
        log(f"[{status}] {name}")
        if ok is False:
            log(f"       {detail}")
        elif ok is None:
            log(f"       (environment gap, not a code bug — {detail})")
        elif VERBOSE:
            vlog(str(detail))
        results.append((name, ok))
    log("")
    return results


# ─────────────────────────────────────────────────────────────────────────

def _run_triage(argv):
    """`run_selftest.py --triage <file.dict> [dict_triage.py options...]`
    Delegates to dict_triage.py's own CLI so Guide B triage lives next to
    the suite it feeds regression stubs into, without duplicating any
    logic here. See dict_triage.py's module docstring for what this does."""
    import dict_triage
    sys.argv = ["dict_triage.py", *argv]
    return dict_triage.main()


def _run_verify_target(argv):
    """`run_selftest.py --verify-target <guide_c_manifest.json> [--json]`
    Delegates to verify/guide_c_verify.py's own CLI -- the mechanical half
    of Guide C, same relationship dict_triage.py has to Guide B. See that
    script's module docstring for what this does."""
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import guide_c_verify
    manifest, *rest = argv
    sys.argv = ["guide_c_verify.py", "--manifest", manifest, *rest]
    return guide_c_verify.main()


def _run_check_coverage(argv):
    """`run_selftest.py --check-coverage <SOURCE_OF_TRUTH.md> <guide_c_manifest.json> [--json]`
    Delegates to verify/guide_a_coverage_check.py -- confirms every roadmap
    claim in Guide A's Phase 1 has a check (or a declared gap) in Guide C's
    Phase 2 manifest, so a claim can't silently have zero coverage."""
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import guide_a_coverage_check
    sot, manifest, *rest = argv
    sys.argv = ["guide_a_coverage_check.py", "--source-of-truth", sot, "--manifest", manifest, *rest]
    return guide_a_coverage_check.main()


def _run_check_guide_a_sync(argv):
    """`run_selftest.py --check-guide-a-sync <GUIDE_A.md> [--json]`
    Delegates to verify/guide_a_sync_check.py -- flags real, parseable
    keywords (from dictumc/grammar.py's actual KEYWORDS set) that Guide A's
    prose never mentions at all, so doc drift is a shortlist to check
    instead of something an AI discovers by writing broken .dict code."""
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import guide_a_sync_check
    guide_a, *rest = argv
    sys.argv = ["guide_a_sync_check.py", "--guide-a", guide_a, "--dictumc-dir",
                os.path.join(HERE, "dictumc"), *rest]
    return guide_a_sync_check.main()


def _run_full_check(argv):
    """`run_selftest.py --full-check --project <dir> [--manifest ...] [--source-of-truth ...] [--json]`
    Delegates to run_pipeline.py -- Guide B, then Guide C, then the Guide A
    coverage check, in one call, stopping early at Guide B on a real
    failure. See run_pipeline.py's module docstring."""
    import run_pipeline
    sys.argv = ["run_pipeline.py", *argv]
    return run_pipeline.main()


def _run_check_reproducibility(argv):
    """`run_selftest.py --check-reproducibility --project <dir> [--static] [--backend c|cpp] [--json]`
    Delegates to verify/reproducibility_check.py -- builds a project twice
    and confirms byte-identical output, stamping a compiler fingerprint
    (and git commit, if available) for build provenance."""
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import reproducibility_check
    sys.argv = ["reproducibility_check.py", *argv]
    return reproducibility_check.main()


def main():
    if "--triage" in sys.argv:
        i = sys.argv.index("--triage")
        return _run_triage(sys.argv[i + 1:])

    if "--verify-target" in sys.argv:
        i = sys.argv.index("--verify-target")
        return _run_verify_target(sys.argv[i + 1:])

    if "--check-coverage" in sys.argv:
        i = sys.argv.index("--check-coverage")
        return _run_check_coverage(sys.argv[i + 1:])

    if "--check-guide-a-sync" in sys.argv:
        i = sys.argv.index("--check-guide-a-sync")
        return _run_check_guide_a_sync(sys.argv[i + 1:])

    if "--full-check" in sys.argv:
        i = sys.argv.index("--full-check")
        return _run_full_check(sys.argv[i + 1:])

    if "--check-reproducibility" in sys.argv:
        i = sys.argv.index("--check-reproducibility")
        return _run_check_reproducibility(sys.argv[i + 1:])

    if shutil.which("gcc") is None:
        log("gcc not found on PATH — §2/§3 tests that compile C cannot run.")
        return 1

    real, stub, missing = run_inventory()
    behavioral_results = run_behavioral()
    regression_results = run_regressions()

    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)
    b_pass = sum(1 for _, ok in behavioral_results if ok)
    r_pass = sum(1 for _, ok in regression_results if ok)
    r_skip = sum(1 for _, ok in regression_results if ok is None)
    r_fail = sum(1 for _, ok in regression_results if ok is False)
    r_gradable = len(regression_results) - r_skip
    log(f"Behavioral: {b_pass}/{len(behavioral_results)} passed")
    skip_note = f" ({r_skip} skipped — environment gap, not counted against the total)" if r_skip else ""
    log(f"Regression: {r_pass}/{r_gradable} passed{skip_note}")
    log(f"Stdlib inventory: {len(real)} real / {len(stub)} stub / {len(missing)} missing "
        f"(of {len(STDLIB_ACTION_FAMILIES)})")

    all_ok = (b_pass == len(behavioral_results)) and (r_fail == 0)
    if not all_ok:
        log("")
        log("FAILED — see [FAIL] lines above.")
    return 0 if all_ok else 1


@regression("R10 dict_syntax_check.py (standalone, no-emission syntax checker) agrees with the real parser on both valid and invalid source")
def test_r10_dict_syntax_check_standalone(tmp):
    # dict_syntax_check.py is a separate, standalone single-file tool
    # (repo root) that reuses the REAL lexer.py + ast_nodes.py +
    # type_registry.py + parser.py verbatim (concatenated, only the
    # package-relative import lines stripped) rather than a fresh
    # reimplementation of the grammar rules -- deliberately, so it can
    # never silently drift from what the real compiler accepts. This
    # test exercises it exactly the way it's meant to be used: as a
    # subprocess, on a real file, checking both the exit code and that
    # it agrees with the real parser's own verdict.
    tool = os.path.join(HERE, "..", "dict_syntax_check.py")
    if not os.path.exists(tool):
        return False, f"dict_syntax_check.py not found at {tool}"

    good = os.path.join(tmp, "good.dict")
    open(good, "w").write(
        "program good_test\n"
        "    keep a as whole number with value 12\n"
        "    keep b as whole number with value 10\n"
        "    keep result as whole number with value the bitwise xor of a and b\n"
        "    print the text \"result:\" and result\n"
        "end program\n"
    )
    bad = os.path.join(tmp, "bad.dict")
    open(bad, "w").write(
        "program bad_test\n"
        "    keep result as whole number with value 5\n"
        "    print result\n"  # missing 'the text' -- a real, previously-seen mistake
        "end program\n"
    )

    r_good = subprocess.run([sys.executable, tool, good], capture_output=True, text=True, timeout=20)
    if r_good.returncode != 0:
        return False, f"standalone checker rejected genuinely valid Dictum:\n{r_good.stdout}\n{r_good.stderr}"

    r_bad = subprocess.run([sys.executable, tool, bad], capture_output=True, text=True, timeout=20)
    if r_bad.returncode == 0:
        return False, f"standalone checker accepted genuinely invalid Dictum (missing 'the text'):\n{r_bad.stdout}"
    if "SYNTAX ERROR" not in r_bad.stdout:
        return False, f"standalone checker failed for the right reason but didn't report it clearly:\n{r_bad.stdout}"

    # Cross-check against the real CLI to confirm the two tools actually
    # agree, not just that each independently produced *a* pass/fail.
    r_real_good = subprocess.run(
        [sys.executable, CLI, good, "--backend", "c"],
        capture_output=True, text=True, timeout=20,
    )
    if r_real_good.returncode != 0:
        return False, f"disagreement: standalone checker passed 'good.dict' but the real compiler rejected it:\n{r_real_good.stdout}\n{r_real_good.stderr}"

    return True, "ok"


@regression("R11 cross-file `use` of a shape: a file that `use`s a sibling file's shape and declares a variable of that type validates instead of erroring 'Unknown type'")
def test_r11_cross_file_shape(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "core_types.dict"), "w").write(
        "module core_types\n"
        "    shape Point holds\n"
        "        x as decimal number\n"
        "        y as decimal number\n"
        "    end shape\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program shape_demo\n"
        "    use core_types\n"
        "    keep p as Point with no value\n"
        "    set p.x to 3.0\n"
        "    set p.y to 4.0\n"
        "    print the text \"shape ok\"\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0 or "Unknown type" in r.stderr:
        return False, f"cross-file shape type still fails validation:\n{r.stdout}\n{r.stderr}"
    comp = _gcc(os.path.join(out_dir, "main.c"), os.path.join(out_dir, "shape_demo"))
    if comp.returncode != 0:
        return False, f"compile failed:\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "shape_demo"))
    if run.returncode != 0 or "shape ok" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    return True, "ok"


@regression("R12 cross-file `import from C` action: a file that `use`s a sibling file's FFI binding validates (no 'unknown action' warning) and links/runs")
def test_r12_cross_file_ffi_action(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "mathish.dict"), "w").write(
        "module mathish\n"
        "    import from C the action my_double takes decimal number produces decimal number as my_double\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program ffi_demo\n"
        "    use mathish\n"
        "    keep r as decimal number with value 0.0\n"
        "    call my_double with 2.5 giving r\n"
        "    print the text \"ffi ok\"\n"
        "end program\n"
    )
    wrapper = os.path.join(tmp, "wrapper.c")
    open(wrapper, "w").write("double my_double(double x) { return x * 2.0; }\n")
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    if "unknown action" in r.stderr.lower():
        return False, f"cross-file FFI action still warns unknown:\n{r.stderr}"
    header_path = os.path.join(out_dir, "dictum_mathish.h")
    if not os.path.exists(header_path) or "my_double" not in open(header_path).read():
        return False, "dictum_mathish.h missing the FFI prototype (R19 regression)"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "ffi_demo"),
        extra_flags=[wrapper, "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed:\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "ffi_demo"))
    if run.returncode != 0 or "ffi ok" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r}"
    return True, "ok"


@regression("R13 module-scope global initialized from another module-scope constant is constant-folded, not emitted as an illegal C global initializer")
def test_r13_module_const_fold(tmp):
    os.makedirs(tmp, exist_ok=True)
    # Deliberately module-only, no `program` block -- this is the case where
    # deferring to main() (the fallback for a truly non-constant initializer)
    # isn't available at all, so constant-folding is the only correct fix.
    open(os.path.join(tmp, "dialect.dict"), "w").write(
        "module dialect_mod\n"
        "    keep DIALECT_FANUC as whole number with value 0\n"
        "    keep current_dialect as whole number with value DIALECT_FANUC\n"
        "    action get_dialect produces whole number\n"
        "        return current_dialect\n"
        "    end action\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program const_fold_demo\n"
        "    use dialect_mod\n"
        "    keep d as whole number with value 0\n"
        "    call dialect_mod.get_dialect giving d\n"
        "    print the text \"d:\" and d\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    dialect_c = open(os.path.join(out_dir, "dialect.c")).read()
    if "= DIALECT_FANUC;" in dialect_c:
        return False, f"still emitting an illegal non-constant global initializer:\n{dialect_c}"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "const_fold_demo"),
        extra_flags=[os.path.join(out_dir, "dialect.c"), "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed (illegal initializer element):\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "const_fold_demo"))
    if run.returncode != 0 or "d:0" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r}"
    return True, "ok"


@regression("R14 dictum_text typedef is emitted before cross-file `use` #includes, not after")
def test_r14_dictum_text_ordering(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "greeter.dict"), "w").write(
        "module greeter\n"
        "    action greet takes name as text produces nothing\n"
        "        print the text \"hello,\" and name\n"
        "    end action\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program greet_demo\n"
        "    use greeter\n"
        "    call greeter.greet with \"world\"\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "greet_demo"),
        extra_flags=[os.path.join(out_dir, "greeter.c"), "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed (dictum_text unknown type -- ordering regression):\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "greet_demo"))
    if run.returncode != 0 or "hello,world" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r}"
    return True, "ok"


@regression("R15 `use` statements don't leak a raw #include line into main()'s body")
def test_r15_use_not_in_main_body(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "helper.dict"), "w").write(
        "module helper_mod\n"
        "    action helper_add takes a as whole number and b as whole number produces whole number\n"
        "        return a plus b\n"
        "    end action\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program use_body_demo\n"
        "    use helper_mod\n"
        "    keep r as whole number with value 0\n"
        "    call helper_mod.helper_add with 2 and 3 giving r\n"
        "    print the text \"r:\" and r\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    main_c = open(os.path.join(out_dir, "main.c")).read()
    if "int main(void) {" not in main_c:
        return False, "main() not found in generated main.c"
    main_body = main_c.split("int main(void) {", 1)[1]
    if "#include" in main_body:
        return False, f"a raw #include leaked into main()'s body:\n{main_body[:300]}"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "use_body_demo"),
        extra_flags=[os.path.join(out_dir, "helper.c"), "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed:\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "use_body_demo"))
    if run.returncode != 0 or "r:5" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r}"
    return True, "ok"


@regression("R16 a local variable inside an action body, initialized by calling another function, is declared+initialized directly -- not wrongly deferred to main()")
def test_r16_local_vardecl_not_deferred(tmp):
    os.makedirs(tmp, exist_ok=True)
    # `action ... produces nothing` with a local `opaque pointer` initialized
    # by an FFI call is exactly the shape of the original bug (`keep file as
    # opaque pointer with value gcode_fopen with filename and "w"` inside
    # generate_demo_job): a perfectly legal local C initializer that must
    # NOT go through the global-scope "must be constant" deferral machinery.
    open(os.path.join(tmp, "alloc.dict"), "w").write(
        "module alloc_mod\n"
        "    import from C the action make_handle takes whole number produces opaque pointer as make_handle\n"
        "    import from C the action sink_handle takes opaque pointer produces nothing as sink_handle\n"
        "    action use_handle takes seed as whole number produces nothing\n"
        "        keep h as opaque pointer with value make_handle with seed\n"
        "        call sink_handle with h\n"
        "        print the text \"handle made\"\n"
        "    end action\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program local_vardecl_demo\n"
        "    use alloc_mod\n"
        "    call alloc_mod.use_handle with 7\n"
        "end program\n"
    )
    wrapper = os.path.join(tmp, "wrapper.c")
    open(wrapper, "w").write(
        "#include <stdlib.h>\n"
        "void* make_handle(int seed) { return (void*)(long)(seed + 1); }\n"
        "void sink_handle(void* h) { (void)h; }\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    alloc_c = open(os.path.join(out_dir, "alloc.c")).read()
    if "init deferred to main()" in alloc_c:
        return False, f"local variable was wrongly deferred to main():\n{alloc_c}"
    main_c = open(os.path.join(out_dir, "main.c")).read()
    if "make_handle" in main_c.split("int main(void) {", 1)[-1] and "h =" in main_c.split("int main(void) {", 1)[-1]:
        return False, "the local var's init leaked into main(), using out-of-scope names"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "local_vardecl_demo"),
        extra_flags=[os.path.join(out_dir, "alloc.c"), wrapper, "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed:\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "local_vardecl_demo"))
    if run.returncode != 0 or "handle made" not in run.stdout:
        return False, f"runtime failure (likely a segfault from a leaked/undeclared var): rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    return True, "ok"


@regression("R17 cross-file call-name mangling: an unqualified call to a `use`d sibling module's action resolves to that module's real (prefixed) C symbol at both the call site and link time")
def test_r17_cross_file_call_mangling(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "greeter2.dict"), "w").write(
        "module greeter2\n"
        "    action say_hi takes name as text produces nothing\n"
        "        print the text \"hi\" and name\n"
        "    end action\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program mangling_demo\n"
        "    use greeter2\n"
        "    action run_job takes n as text produces nothing\n"
        "        call say_hi with n\n"
        "    end action\n"
        "    call run_job with \"there\"\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "mangling_demo"),
        extra_flags=[os.path.join(out_dir, "greeter2.c"), "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"link/compile failed (call-name mangling mismatch):\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "mangling_demo"))
    if run.returncode != 0 or "hithere" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r}"
    return True, "ok"


@regression("R18 an `import from C` alias that collides with a libc-reserved name (sqrt, sin, cos, ...) is called under its real name, not silently renamed to dictum_<name> only at the call site")
def test_r18_ffi_alias_no_libc_rename_mismatch(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "mymath.dict"), "w").write(
        "module core_math_demo\n"
        "    import from C the action sqrt takes decimal number produces decimal number as sqrt\n"
        "    action root takes v as decimal number produces decimal number\n"
        "        keep result as decimal number with value 0.0\n"
        "        call sqrt with v giving result\n"
        "        return result\n"
        "    end action\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program sqrt_demo\n"
        "    use core_math_demo\n"
        "    keep r as decimal number with value 0.0\n"
        "    call core_math_demo.root with 9.0 giving r\n"
        "    print the text \"r:\" and r\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "sqrt_demo"),
        extra_flags=[os.path.join(out_dir, "mymath.c"), "-I", out_dir, "-lm"],
    )
    if comp.returncode != 0:
        return False, f"link failed -- declared name and call-site name for the FFI alias disagreed:\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "sqrt_demo"))
    if run.returncode != 0 or "r:3" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r}"
    return True, "ok"


@regression("R19 (severe) FFI (`import from C`) prototypes appear in the per-module cross-file shared header, so a module of ONLY FFI imports doesn't force implicit-int fallback (silent pointer truncation) on every caller in another file")
def test_r19_ffi_prototypes_in_shared_header(tmp):
    os.makedirs(tmp, exist_ok=True)
    # A module consisting PURELY of `import from C` bindings, no genuine
    # `action` blocks at all -- exactly the shape of io_file.dict, whose
    # generated header used to come out completely empty, and whose real
    # bug was a `void*`-returning FFI call losing its prototype in a caller
    # file, silently truncated to 32 bits by gcc's implicit-int fallback.
    open(os.path.join(tmp, "handleio.dict"), "w").write(
        "module handleio\n"
        "    import from C the action open_thing takes text produces opaque pointer as open_thing\n"
        "    import from C the action close_thing takes opaque pointer produces nothing as close_thing\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program handle_demo\n"
        "    use handleio\n"
        "    keep h as opaque pointer with value open_thing with \"x\"\n"
        "    call close_thing with h\n"
        "    print the text \"done\"\n"
        "end program\n"
    )
    wrapper = os.path.join(tmp, "wrapper.c")
    open(wrapper, "w").write(
        "#include <stdlib.h>\n"
        "/* Returns a pointer value that does NOT fit in 32 bits when the\n"
        " * high bits are dropped, so silent truncation is unambiguous. */\n"
        "void* open_thing(const char* path) { (void)path; return (void*)0x100000005L; }\n"
        "void close_thing(void* h) { (void)h; }\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    header = os.path.join(out_dir, "dictum_handleio.h")
    if not os.path.exists(header):
        return False, "dictum_handleio.h was never generated"
    header_src = open(header).read()
    if "open_thing" not in header_src or "close_thing" not in header_src:
        return False, f"FFI prototypes missing from the shared header (the original bug):\n{header_src}"
    # -Werror in _gcc turns the implicit-declaration warning into a hard
    # compile failure, which is exactly what we want this test to catch if
    # the fix regresses.
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "handle_demo"),
        extra_flags=[wrapper, "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed (implicit-declaration -- FFI prototype missing from shared header):\n{comp.stderr}"
    run = _run(os.path.join(out_dir, "handle_demo"))
    if run.returncode != 0 or "done" not in run.stdout:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    return True, "ok"


@regression("R20 cnc_vibecoder material/tool calculator: real FFI values reach the .dict caller, distinct per material (not a hardcoded constant)")
def test_r20_material_calc(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "material.dict"), "w").write(
        "module material_lookup\n"
        "    import from C the action material_calc_rpm takes whole number and whole number and whole number produces whole number as material_calc_rpm\n"
        "    import from C the action material_calc_feed takes whole number and whole number and whole number produces decimal number as material_calc_feed\n"
        "end module\n"
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program material_demo\n"
        "    use material_lookup\n"
        "    keep rpm_aluminum as whole number with value material_calc_rpm with 0 and 0 and 6\n"
        "    keep rpm_steel as whole number with value material_calc_rpm with 1 and 0 and 6\n"
        "    print the text \"aluminum:\" and rpm_aluminum\n"
        "    print the text \"steel:\" and rpm_steel\n"
        "end program\n"
    )
    # Real formula: RPM = 1000 * Vc / (pi * D). Deliberately independent of
    # the production Vc table in cnc_wrappers.c so this test still catches
    # a regression to hardcoded RPM even if those constants are retuned.
    wrapper = os.path.join(tmp, "wrapper.c")
    open(wrapper, "w").write(
        "static const double VC[3][2] = { {90.0,200.0}, {25.0,90.0}, {120.0,150.0} };\n"
        "static const double PI_CONST = 3.14159265358979323846;\n"
        "int material_calc_rpm(int material_id, int tool_id, int diameter_mm) {\n"
        "    double vc = VC[material_id][tool_id];\n"
        "    return (int)((1000.0 * vc) / (PI_CONST * (double)diameter_mm));\n"
        "}\n"
        "double material_calc_feed(int material_id, int tool_id, int rpm) {\n"
        "    (void)material_id; (void)tool_id;\n"
        "    return (double)rpm * 2.0 * 0.05;\n"
        "}\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    comp = _gcc(
        os.path.join(out_dir, "main.c"), os.path.join(out_dir, "material_demo"),
        extra_flags=[wrapper, "-lm", "-I", out_dir],
    )
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    run = _run(os.path.join(out_dir, "material_demo"))
    if run.returncode != 0:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    out = run.stdout
    if "aluminum:4774" not in out or "steel:1326" not in out:
        return False, f"expected real distinct per-material RPM values, got: {out!r}"
    if "aluminum:1326" in out:
        return False, "aluminum and steel produced the same RPM -- looks like a hardcoded constant, not the real FFI calculation"
    return True, "ok"


@regression("R21 nested `if` inside a plain `otherwise` block no longer mis-parses as that if's own `otherwise if` clause (was: silently stole tokens meant for the enclosing block, desyncing the parser)")
def test_r21_nested_if_in_otherwise(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program nesttest\n"
        "    keep a as whole number with value 1\n"
        "    keep b as whole number with value 0\n"
        "\n"
        "    if a is equal to 0 then\n"
        "        print the text \"outer zero\"\n"
        "    otherwise\n"
        "        if b is equal to 0 then\n"
        "            print the text \"inner zero\"\n"
        "        otherwise\n"
        "            print the text \"inner nonzero\"\n"
        "        end if\n"
        "        print the text \"after inner\"\n"
        "    end if\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed (nested if-in-otherwise should parse): {r.stdout}\n{r.stderr}"
    comp = _gcc(os.path.join(out_dir, "main.c"), os.path.join(out_dir, "nesttest"))
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    run = _run(os.path.join(out_dir, "nesttest"))
    if run.returncode != 0:
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    if run.stdout != "inner zeroafter inner":
        return False, f"expected 'inner zeroafter inner' (a!=0 -> otherwise branch; b==0 -> inner-if branch; then the trailing statement after the nested if), got: {run.stdout!r}"
    return True, "ok"


@regression("R22 sized shape-field types f64/i16 exist and map to real double/int16_t (were simply missing from the primitive table, unlike their siblings u8/u16/u32/u64/i32/i64/f32)")
def test_r22_sized_types_f64_i16(tmp):
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "main.dict"), "w").write(
        "program shapetypetest\n"
        "    shape Mixed holds\n"
        "        a as f32\n"
        "        b as f64\n"
        "        c as i16\n"
        "        d as u8\n"
        "    end shape\n"
        "\n"
        "    keep m as Mixed with no value\n"
        "    set a of m to 1.5\n"
        "    set b of m to 2.25\n"
        "    set c of m to 42\n"
        "    set d of m to 7\n"
        "    print the text \"ok\"\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed (f64/i16 should be valid shape field types): {r.stdout}\n{r.stderr}"
    generated_c = open(os.path.join(out_dir, "main.c")).read()
    if "double b;" not in generated_c:
        return False, f"expected 'f64' to emit a real C 'double' field, generated struct did not contain it:\n{generated_c}"
    if "int16_t c;" not in generated_c:
        return False, f"expected 'i16' to emit a real C 'int16_t' field, generated struct did not contain it:\n{generated_c}"
    comp = _gcc(os.path.join(out_dir, "main.c"), os.path.join(out_dir, "shapetypetest"))
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    run = _run(os.path.join(out_dir, "shapetypetest"))
    if run.returncode != 0 or run.stdout != "ok":
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    return True, "ok"


@regression("R23 generate_import_c.py: real bridge-generation tool produces correct output for a direct binding, a struct-by-value shape, and an out-param function needing a wrapper")
def test_r23_generate_import_c(tmp):
    os.makedirs(tmp, exist_ok=True)
    header = os.path.join(tmp, "sample.h")
    open(header, "w").write(
        "typedef struct Point { float x; float y; } Point;\n"
        "int demo_add(int a, int b);\n"
        "float demo_scale(Point p, float factor);\n"
        "void demo_pick(Point bounds, int *active);\n"
    )
    out_dict = os.path.join(tmp, "sample_bridge.dict")
    gen_script = os.path.join(HERE, "scripts", "generate_import_c.py")
    r = subprocess.run(
        [sys.executable, gen_script, header, "--module-name", "sample_bridge", "--output", out_dict],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        # Distinguish "this machine hasn't run `pip install libclang
        # --break-system-packages` yet" (environment gap — SKIP) from a
        # real bridge-generation bug (FAIL). Same signal generate_import_c.py
        # itself prints when _load_libclang() can't find the module.
        if "pip install libclang" in r.stderr:
            return None, "libclang not installed — run: pip install libclang --break-system-packages"
        return False, f"generate_import_c.py failed: {r.stdout}\n{r.stderr}"
    if not os.path.exists(out_dict):
        return False, "expected output .dict file was not created"
    content = open(out_dict).read()

    if "shape Point holds" not in content or "x as f32" not in content or "y as f32" not in content:
        return False, f"expected a correct Point shape with f32 fields (matching the real float layout), got:\n{content}"
    if "import from C the action demo_add takes i32 and i32 produces i32 as demo_add" not in content:
        return False, f"expected a direct binding for demo_add, got:\n{content}"
    if "import from C the action demo_scale takes Point and f32 produces f32 as demo_scale" not in content:
        return False, f"expected demo_scale to bind Point by value and f32 (not decimal number) for the real C float, got:\n{content}"
    if "demo_pick" not in content or "wrapper" not in content.lower():
        return False, f"expected demo_pick (real int* out-param) to be flagged as needing a wrapper, not bound directly, got:\n{content}"
    if "import from C the action demo_pick" in content:
        return False, f"demo_pick has a real out-parameter and must NOT be bound directly, got:\n{content}"
    return True, "ok"


@regression("R24 project_builder.py build_project() honors an explicit backend/cpp_standard argument (and therefore the CLI's --backend/--cpp-standard flags) on a workspace with no pre-existing dictum.project.json, instead of silently reverting to the auto-discover default")
def test_r24_project_builder_backend_override(tmp):
    # Found while building an automated Guide-B triage pipeline: a fresh
    # workspace (no dictum.project.json yet) always got 'backend': 'c'
    # baked into load_or_create_manifest()'s auto-discover dict, so
    # build_project()'s `manifest.get('backend', backend)` always found
    # that value first and never fell through to the caller's real
    # backend argument. Symptom: `project_builder.py <dir> --backend cpp`
    # silently wrote main.c (not main.cpp) with zero error or warning --
    # a real project explicitly asking for the C++ backend quietly got C
    # instead, and would only be noticed much later by a human reading
    # the wrong file extension or wondering why a C++-only construct
    # failed. No exception, no exit code change -- this is exactly the
    # "silent miscompile" shape Guide B §0 says "the error went away" can
    # never stand in for.
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "r24test.dict"), "w").write(
        "program r24test\n"
        "    print the text \"ok\"\n"
        "end program\n"
    )
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "cpp", "--out", out_dir],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed on a trivial project: {r.stdout}\n{r.stderr}"
    if not os.path.exists(os.path.join(out_dir, "r24test.cpp")):
        return False, (
            "--backend cpp was silently ignored -- expected r24test.cpp, "
            f"got: {os.listdir(out_dir) if os.path.isdir(out_dir) else '(no build dir)'}"
        )
    if os.path.exists(os.path.join(out_dir, "r24test.c")):
        return False, "found a stray r24test.c alongside r24test.cpp -- backend selection is still inconsistent"

    project_json = os.path.join(tmp, "dictum.project.json")
    if not os.path.exists(project_json):
        return False, "expected dictum.project.json to be written after a successful build"
    import json as _json
    saved = _json.load(open(project_json))
    if saved.get("backend") != "cpp":
        return False, f"expected the resolved backend ('cpp') to be persisted, got: {saved.get('backend')!r}"

    comp = subprocess.run(
        ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", RUNTIME_DIR,
         os.path.join(out_dir, "r24test.cpp"), "-o", os.path.join(out_dir, "r24test")],
        capture_output=True, text=True, timeout=30,
    )
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    run = _run(os.path.join(out_dir, "r24test"))
    if run.returncode != 0 or run.stdout != "ok":
        return False, f"runtime failure: rc={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}"
    return True, "ok"


@regression("R25 verify/guide_c_verify.py: console-class check runs a real binary, "
             "diffs its stdout against an expected file (CRLF-normalized), and reports "
            "RUN-VERIFIED on a clean match / FAIL on exit-code or content mismatch")
def test_r25_guide_c_verify_console(tmp):
    # Xvfb-independent by design (only exercises the console_checks path) so
    # this test is deterministic in any CI environment, unlike the GUI path
    # (which correctly SKIPs, not FAILs, where Xvfb isn't available).
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "ok.c")
    open(src, "w").write('#include <stdio.h>\nint main(){ printf("ok\\n"); return 0; }\n')
    comp = _gcc(src, os.path.join(tmp, "ok_bin"))
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    open(os.path.join(tmp, "expected.txt"), "w").write("ok\n")

    manifest = os.path.join(tmp, "guide_c_manifest.json")
    import json as _json
    _json.dump({
        "project": "r25test", "target": "linux", "gui": False, "binary": "ok_bin",
        "console_checks": [{"name": "prints_ok", "args": [],
                             "expected_stdout_file": "expected.txt", "expect_exit_code": 0}],
        "project_specific_scripts": [], "known_limitations": [],
    }, open(manifest, "w"))

    verify_script = os.path.join(HERE, "verify", "guide_c_verify.py")
    r = subprocess.run([sys.executable, verify_script, "--manifest", manifest, "--json"],
                        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return False, f"expected overall_ok on a clean console check: {r.stdout}\n{r.stderr}"
    report = _json.loads(r.stdout)
    if report["summary"] != {"pass": 1, "fail": 0, "skip": 0, "total": 1}:
        return False, f"unexpected summary: {report['summary']}"

    # Now break the expected value and confirm it correctly reports FAIL,
    # not a false PASS -- a verifier that can't fail isn't verifying anything.
    open(os.path.join(tmp, "expected.txt"), "w").write("not ok\n")
    r2 = subprocess.run([sys.executable, verify_script, "--manifest", manifest, "--json"],
                         capture_output=True, text=True, timeout=30)
    if r2.returncode == 0:
        return False, "expected a nonzero exit / overall_ok=False on a real content mismatch"
    report2 = _json.loads(r2.stdout)
    if report2["overall_ok"] is not False or report2["summary"]["fail"] != 1:
        return False, f"expected exactly one FAIL, got: {report2['summary']}"
    return True, "ok"


@regression("R26 verify/guide_a_coverage_check.py: a roadmap claim tagged [Rn] in "
            "SOURCE_OF_TRUTH.md with no covering check and no declared known_gaps entry "
            "is reported UNCOVERED (exit 1); a 'covers' reference to an ID absent from "
            "the markdown is reported as drift; a fully-covered manifest reports OK (exit 0)")
def test_r26_guide_a_coverage_check(tmp):
    import json as _json
    os.makedirs(tmp, exist_ok=True)
    sot = os.path.join(tmp, "SOURCE_OF_TRUTH_test.md")
    open(sot, "w").write(
        "# Test\n\n## Roadmap\n"
        "- [R1] covered claim\n"
        "- [R2] uncovered claim\n"
        "- [R3] declared-gap claim\n"
    )
    checker = os.path.join(HERE, "verify", "guide_a_coverage_check.py")

    bad_manifest = os.path.join(tmp, "bad.json")
    _json.dump({
        "roadmap_ids": {"R1": "x", "R2": "x", "R3": "x"},
        "console_checks": [{"name": "c1", "covers": ["R1"]}],
        "gui_checks": [], "project_specific_scripts": [],
        "known_gaps": [{"roadmap_id": "R3", "reason": "not built yet"}],
    }, open(bad_manifest, "w"))
    r = subprocess.run([sys.executable, checker, "--source-of-truth", sot,
                        "--manifest", bad_manifest, "--json"],
                       capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return False, "expected nonzero exit: R2 has no check and no declared gap"
    rep = _json.loads(r.stdout)
    if rep["uncovered"] != ["R2"]:
        return False, f"expected uncovered=['R2'], got {rep['uncovered']}"

    good_manifest = os.path.join(tmp, "good.json")
    _json.dump({
        "roadmap_ids": {"R1": "x", "R2": "x", "R3": "x"},
        "console_checks": [{"name": "c1", "covers": ["R1"]}],
        "gui_checks": [{"name": "c2", "covers": ["R2"]}],
        "project_specific_scripts": [],
        "known_gaps": [{"roadmap_id": "R3", "reason": "not built yet"}],
    }, open(good_manifest, "w"))
    r2 = subprocess.run([sys.executable, checker, "--source-of-truth", sot,
                         "--manifest", good_manifest, "--json"],
                        capture_output=True, text=True, timeout=15)
    if r2.returncode != 0:
        return False, f"expected exit 0 on a fully-covered manifest: {r2.stdout}"
    rep2 = _json.loads(r2.stdout)
    if rep2["uncovered"]:
        return False, f"expected no uncovered IDs, got {rep2['uncovered']}"
    return True, "ok"


@regression("R27 dictumc/import_c_registry.py + dict_triage.py Case D: an unrecorded "
            "<library>/<target> pair reports blessed=None (unverifiable, not unblessed); "
            "after a real --register call it reports the recorded true/false; a DIFFERENT "
            "target for the same library stays unverifiable (no cross-target leakage)")
def test_r27_import_c_registry_case_d(tmp):
    import dict_triage
    registry_json = os.path.join(HERE, "dictumc", "import_c_registry.json")
    backup = None
    if os.path.exists(registry_json):
        backup = open(registry_json).read()
    try:
        if os.path.exists(registry_json):
            os.remove(registry_json)

        before = dict_triage.check_library_blessing(["r27testlib"], "linux")
        if before[0]["blessed"] is not None:
            return False, f"expected None (unverifiable) before any registration, got {before}"

        registry_script = os.path.join(HERE, "dictumc", "import_c_registry.py")
        r = subprocess.run([sys.executable, registry_script, "--register", "r27testlib", "linux",
                             "--toolchain", "gcc-test", "--note", "R27 regression test entry"],
                            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return False, f"registration failed: {r.stderr}"

        after = dict_triage.check_library_blessing(["r27testlib"], "linux")
        if after[0]["blessed"] is not True:
            return False, f"expected True after registering as blessed, got {after}"

        other_target = dict_triage.check_library_blessing(["r27testlib"], "windows")
        if other_target[0]["blessed"] is not None:
            return False, f"a different target must stay unverifiable (no cross-target leakage), got {other_target}"

        return True, "ok"
    finally:
        if backup is not None:
            open(registry_json, "w").write(backup)
        elif os.path.exists(registry_json):
            os.remove(registry_json)


@regression("R28 verify/guide_a_sync_check.py: a real keyword absent from Guide A's "
            "prose (even loosely, case-insensitive, anywhere in the doc) is reported "
            "UNDOCUMENTED; one that appears anywhere in ordinary prose is not")
def test_r28_guide_a_sync_check(tmp):
    # Uses a synthetic grammar fixture, not the real (evolving) KEYWORDS set,
    # so this regression test doesn't need updating every time a keyword is
    # legitimately added to the language -- it only needs to prove the
    # comparison logic itself is correct.
    os.makedirs(tmp, exist_ok=True)
    fixture_dictumc = os.path.join(tmp, "dictumc")
    os.makedirs(fixture_dictumc, exist_ok=True)
    open(os.path.join(fixture_dictumc, "grammar.py"), "w").write(
        "class DictumGrammar:\n"
        "    KEYWORDS = {'keep', 'put', 'destructor'}\n"
    )
    guide_a = os.path.join(tmp, "guide_a.md")
    open(guide_a, "w").write(
        "# Guide A\n\nUse `keep` to declare a variable. Use `put` to assign.\n"
        "(cleanup-on-scope-exit support is not documented anywhere in this file)\n"
    )

    checker = os.path.join(HERE, "verify", "guide_a_sync_check.py")
    r = subprocess.run([sys.executable, checker, "--guide-a", guide_a,
                        "--dictumc-dir", fixture_dictumc, "--json"],
                        capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return False, "expected nonzero exit: 'destructor' is genuinely undocumented"
    import json as _json
    rep = _json.loads(r.stdout)
    if rep["undocumented"] != ["destructor"]:
        return False, f"expected undocumented=['destructor'], got {rep['undocumented']}"
    return True, "ok"


@regression("R29 dict_triage.py --cache: an unchanged .dict file + args + compiler "
            "internals serves the cached verdict (from_cache=true) on a repeat run; "
            "editing the file forces a fresh recompute (from_cache=false)")
def test_r29_dict_triage_cache(tmp):
    import json as _json
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "t.dict")
    open(src, "w").write('program t\n    print the text "hello"\nend program\n')
    triage_script = os.path.join(HERE, "dict_triage.py")

    r1 = subprocess.run([sys.executable, triage_script, src, "--cache", "--json"],
                        capture_output=True, text=True, timeout=30)
    rep1 = _json.loads(r1.stdout)
    if rep1.get("from_cache") is not False:
        return False, f"expected from_cache=false on the first (cold) run, got {rep1.get('from_cache')}"

    r2 = subprocess.run([sys.executable, triage_script, src, "--cache", "--json"],
                        capture_output=True, text=True, timeout=30)
    rep2 = _json.loads(r2.stdout)
    if rep2.get("from_cache") is not True:
        return False, f"expected from_cache=true on the identical repeat run, got {rep2.get('from_cache')}"
    if rep2.get("case") != rep1.get("case"):
        return False, "cached verdict's case differs from the original real verdict"

    open(src, "w").write('program t\n    print the text "hello CHANGED"\nend program\n')
    r3 = subprocess.run([sys.executable, triage_script, src, "--cache", "--json"],
                        capture_output=True, text=True, timeout=30)
    rep3 = _json.loads(r3.stdout)
    if rep3.get("from_cache") is not False:
        return False, f"expected from_cache=false after editing the file, got {rep3.get('from_cache')}"
    return True, "ok"


@regression("R30 verify/guide_c_verify.py --cache: an unchanged console-class check "
            "(same binary + same spec) is served from cache on a repeat run; a project- "
            "specific script is NEVER cached (only console_checks are); rebuilding the "
            "binary forces a fresh run")
def test_r30_guide_c_verify_cache(tmp):
    import json as _json
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "ok.c")
    open(src, "w").write('#include <stdio.h>\nint main(){ printf("ok\\n"); return 0; }\n')
    comp = _gcc(src, os.path.join(tmp, "ok_bin"))
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    open(os.path.join(tmp, "expected.txt"), "w").write("ok\n")

    dummy_script = os.path.join(tmp, "dummy.py")
    open(dummy_script, "w").write('import json\nprint(json.dumps({"ok": True, "detail": "x"}))\n')

    manifest = os.path.join(tmp, "guide_c_manifest.json")
    _json.dump({
        "project": "r30test", "target": "linux", "gui": False, "binary": "ok_bin",
        "console_checks": [{"name": "prints_ok", "args": [],
                             "expected_stdout_file": "expected.txt", "expect_exit_code": 0}],
        "project_specific_scripts": [{"name": "dummy", "script": "dummy.py", "args": []}],
        "known_limitations": [],
    }, open(manifest, "w"))

    verify_script = os.path.join(HERE, "verify", "guide_c_verify.py")

    def _from_cache_map(json_stdout):
        d = _json.loads(json_stdout)
        return {r["name"]: r["evidence"].get("from_cache", False) for r in d["results"]}

    r1 = subprocess.run([sys.executable, verify_script, "--manifest", manifest, "--cache", "--json"],
                        capture_output=True, text=True, timeout=30)
    m1 = _from_cache_map(r1.stdout)
    if m1.get("prints_ok") is not False or m1.get("dummy") is not False:
        return False, f"expected both uncached on the first run, got {m1}"

    r2 = subprocess.run([sys.executable, verify_script, "--manifest", manifest, "--cache", "--json"],
                        capture_output=True, text=True, timeout=30)
    m2 = _from_cache_map(r2.stdout)
    if m2.get("prints_ok") is not True:
        return False, f"expected the console check cached on the repeat run, got {m2}"
    if m2.get("dummy") is not False:
        return False, "project_specific_scripts must NEVER be cached by this orchestrator"

    import time as _time
    _time.sleep(1.1)
    comp2 = _gcc(src, os.path.join(tmp, "ok_bin"))
    if comp2.returncode != 0:
        return False, f"rebuild failed: {comp2.stderr}"
    r3 = subprocess.run([sys.executable, verify_script, "--manifest", manifest, "--cache", "--json"],
                        capture_output=True, text=True, timeout=30)
    m3 = _from_cache_map(r3.stdout)
    if m3.get("prints_ok") is not False:
        return False, f"expected cache to invalidate after the binary was rebuilt, got {m3}"
    return True, "ok"


@regression("R31 verify/selftest_lib.py: a project's own @deterministic_check suite "
            "aggregates PASS/FAIL correctly in both human and --json modes, and its JSON "
            "verdict matches the exact {ok, detail} contract guide_c_verify.py's "
            "project_specific_scripts entries expect")
def test_r31_selftest_lib(tmp):
    import json as _json
    os.makedirs(tmp, exist_ok=True)
    project_selftest = os.path.join(tmp, "project_selftest.py")
    verify_dir = os.path.join(HERE, "verify")
    open(project_selftest, "w").write(f'''
import sys
sys.path.insert(0, {verify_dir!r})
from selftest_lib import deterministic_check, main

@deterministic_check("one passing check")
def test_pass(tmp):
    return True, "ok"

@deterministic_check("one failing check")
def test_fail(tmp):
    return False, "deliberate failure for R31"

if __name__ == "__main__":
    sys.exit(main())
''')
    r = subprocess.run([sys.executable, project_selftest, "--json"],
                        capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return False, "expected nonzero exit -- one check deliberately fails"
    verdict = _json.loads(r.stdout)
    if set(verdict.keys()) < {"ok", "detail"}:
        return False, f"verdict missing required 'ok'/'detail' keys: {verdict.keys()}"
    if verdict["ok"] is not False:
        return False, f"expected ok=false, got {verdict}"
    if "R31" not in verdict["detail"]:
        return False, f"expected the failure detail to surface in the aggregated verdict: {verdict}"
    return True, "ok"


@regression("R32 verify/guide_c_verify.py class linting: a console_check marked "
            "class='visual' (structurally wrong -- console checks are exact-diff) is "
            "flagged as an advisory warning without blocking a run that otherwise passes")
def test_r32_guide_c_verify_class_lint(tmp):
    import json as _json
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "ok.c")
    open(src, "w").write('#include <stdio.h>\nint main(){ printf("ok\\n"); return 0; }\n')
    comp = _gcc(src, os.path.join(tmp, "ok_bin"))
    if comp.returncode != 0:
        return False, f"compile failed: {comp.stderr}"
    open(os.path.join(tmp, "expected.txt"), "w").write("ok\n")

    manifest = os.path.join(tmp, "guide_c_manifest.json")
    _json.dump({
        "project": "r32test", "target": "linux", "gui": False, "binary": "ok_bin",
        "console_checks": [{"name": "prints_ok", "class": "visual", "args": [],
                             "expected_stdout_file": "expected.txt", "expect_exit_code": 0}],
        "project_specific_scripts": [], "known_limitations": [],
    }, open(manifest, "w"))

    verify_script = os.path.join(HERE, "verify", "guide_c_verify.py")
    r = subprocess.run([sys.executable, verify_script, "--manifest", manifest, "--json"],
                        capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return False, f"a class mismatch must not block an otherwise-passing run: {r.stdout}"
    report = _json.loads(r.stdout)
    if not any("console_check 'prints_ok'" in w for w in report.get("class_warnings", [])):
        return False, f"expected a class_warnings entry for prints_ok, got {report.get('class_warnings')}"
    return True, "ok"


@regression("R33 run_pipeline.py: a clean project runs Guide B -> Guide C -> coverage "
            "and reports overall_ok=true; a project with a real Case A .dict mistake "
            "stops at Guide B (guide_c/coverage never attempted, stopped_at='guide_b')")
def test_r33_run_pipeline(tmp):
    import json as _json
    os.makedirs(tmp, exist_ok=True)

    # -- clean project: full 3-stage chain should pass --
    clean_dir = os.path.join(tmp, "clean_proj")
    os.makedirs(clean_dir, exist_ok=True)
    open(os.path.join(clean_dir, "main.dict"), "w").write(
        'program main\n    print the text "hi"\nend program\n'
    )
    open(os.path.join(clean_dir, "expected.txt"), "w").write("hi")
    _json.dump({
        "project": "r33test", "target": "linux", "gui": False, "binary": "PLACEHOLDER",
        "roadmap_ids": {"R1": "prints hi"},
        "console_checks": [{"name": "prints_hi", "class": "deterministic", "covers": ["R1"],
                             "args": [], "expected_stdout_file": "expected.txt", "expect_exit_code": 0}],
        "gui_checks": [], "project_specific_scripts": [], "known_gaps": [], "known_limitations": [],
    }, open(os.path.join(clean_dir, "manifest.json"), "w"))
    open(os.path.join(clean_dir, "SOURCE_OF_TRUTH.md"), "w").write(
        "# Test\n## Roadmap\n- [R1] Prints hi.\n"
    )

    pipeline_script = os.path.join(HERE, "run_pipeline.py")
    r = subprocess.run([sys.executable, pipeline_script, "--project", clean_dir,
                        "--manifest", os.path.join(clean_dir, "manifest.json"),
                        "--source-of-truth", os.path.join(clean_dir, "SOURCE_OF_TRUTH.md"),
                        "--json"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return False, f"expected a clean project to pass end-to-end: {r.stdout}\n{r.stderr}"
    rep = _json.loads(r.stdout)
    if not rep["overall_ok"] or not rep["guide_b_ok"] or not rep["guide_c_ok"] or not rep["coverage_ok"]:
        return False, f"expected all three stages OK: {rep}"

    # -- broken project: must stop at Guide B, never attempt Guide C/coverage --
    broken_dir = os.path.join(tmp, "broken_proj")
    os.makedirs(broken_dir, exist_ok=True)
    open(os.path.join(broken_dir, "main.dict"), "w").write(
        'program main\n    let x be text\n    let x be text\nend program\n'
    )
    r2 = subprocess.run([sys.executable, pipeline_script, "--project", broken_dir,
                        "--manifest", "/nonexistent/manifest.json", "--json"],
                        capture_output=True, text=True, timeout=60)
    if r2.returncode == 0:
        return False, "expected nonzero exit -- this project has a real Case A error"
    rep2 = _json.loads(r2.stdout)
    if rep2["guide_b_ok"] is not False or rep2["stopped_at"] != "guide_b":
        return False, f"expected guide_b_ok=false, stopped_at='guide_b', got {rep2}"
    if rep2["guide_c"] is not None or rep2["coverage"] is not None:
        return False, "Guide C / coverage must never be attempted after a Guide B failure"
    return True, "ok"


@regression("R34 project_builder.py --static + verify/verify_static_link.py: a project "
            "built with --static actually produces a binary `ldd` confirms is not a "
            "dynamic executable, and it still runs correctly; dict_triage.py's "
            "--static gates the overall verdict on the REAL ldd result, not just on "
            "whether -static was passed to the compiler")
def test_r34_static_linking(tmp):
    import dict_triage
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "main.dict"), "w").write(
        'program main\n    print the text "static test"\nend program\n'
    )

    report = dict_triage.triage_project(tmp, expected_output="static test",
                                         keep_artifacts=True, static=True)
    if report.get("case") != "clean":
        return False, f"expected a clean static build: {report}"
    slc = report.get("static_link_check")
    if not slc or slc.get("ok") is not True:
        return False, f"expected a real, confirmed static-link check: {slc}"
    if "not a dynamic executable" not in slc.get("detail", "") and "vdso" not in slc.get("detail", ""):
        return False, f"unexpected static-link detail: {slc}"

    bin_path = report.get("bin_path")
    if not bin_path or not os.path.exists(bin_path):
        return False, "expected the built binary to persist with keep_artifacts=True"
    run = _run(bin_path)
    if run.returncode != 0 or run.stdout != "static test":
        return False, f"static binary didn't run correctly: rc={run.returncode} stdout={run.stdout!r}"

    # Negative case: verify_static_link.py must correctly FAIL on an
    # ordinary dynamic binary -- a checker that can only ever say "yes"
    # isn't checking anything.
    import sys as _sys
    checker = os.path.join(HERE, "verify", "verify_static_link.py")
    dyn_bin = os.path.join(tmp, "dyn_bin")
    dyn_src = os.path.join(tmp, "dyn.c")
    open(dyn_src, "w").write("int main(){return 0;}\n")
    subprocess.run(["gcc", "-o", dyn_bin, dyn_src], check=True, timeout=15)
    r = subprocess.run([_sys.executable, checker, dyn_bin, "--json"],
                       capture_output=True, text=True, timeout=15)
    import json as _json
    verdict = _json.loads(r.stdout)
    if verdict["ok"] is not False:
        return False, f"expected verify_static_link.py to FAIL on a real dynamic binary: {verdict}"
    return True, "ok"


@regression("R35 verify/package_for_client.py: packages a real static binary + README + "
            "client-facing test report (scrubbed of Dictum/triage/guide jargon) from a "
            "passing pipeline report; the hard .dict guard fires even when called "
            "directly against a directory a copy-filter bug might have let one through "
            "into; refuses to package a failing report or one missing a persisted binary")
def test_r35_package_for_client(tmp):
    import dict_triage
    import json as _json
    os.makedirs(tmp, exist_ok=True)
    proj = os.path.join(tmp, "proj")
    os.makedirs(proj, exist_ok=True)
    open(os.path.join(proj, "main.dict"), "w").write(
        'program main\n    print the text "r35 test"\nend program\n'
    )

    report = dict_triage.triage_project(proj, expected_output="r35 test", keep_artifacts=True)
    pipeline_report = {
        "project_dir": proj, "guide_b": report, "guide_b_ok": report.get("case") == "clean",
        "guide_c": None, "guide_c_ok": None, "coverage": None, "coverage_ok": None,
        "overall_ok": report.get("case") == "clean", "stopped_at": None,
    }
    if not pipeline_report["overall_ok"]:
        return False, f"expected a clean triage build: {report}"

    sys.path.insert(0, os.path.join(HERE, "verify"))
    import package_for_client

    # -- success path --
    out_zip = os.path.join(tmp, "deliverable.zip")
    result = package_for_client.package(pipeline_report, "r35-tool", "desc", "./r35-tool", out_zip)
    if not result["ok"] or not os.path.exists(out_zip):
        return False, f"expected a successful package: {result}"
    if any(c.endswith(".dict") for c in result["contents"]):
        return False, f"a .dict file made it into the deliverable: {result['contents']}"
    if "README.md" not in result["contents"] or "TEST_REPORT.md" not in result["contents"]:
        return False, f"missing README/TEST_REPORT: {result['contents']}"

    import zipfile
    with zipfile.ZipFile(out_zip) as zf:
        readme_text = zf.read("README.md").decode()
        report_text = zf.read("TEST_REPORT.md").decode()
    for banned in ("dictum", ".dict", "guide a", "guide b", "guide c", "triage"):
        if banned in readme_text.lower() or banned in report_text.lower():
            return False, f"internal jargon '{banned}' leaked into a client-facing file"

    # -- hard guard fires even bypassing the copy-filter entirely --
    leak_dir = os.path.join(tmp, "leak_dir")
    os.makedirs(leak_dir, exist_ok=True)
    open(os.path.join(leak_dir, "leaked.dict"), "w").write("program leak\nend program\n")
    try:
        package_for_client._assert_no_dict_files(leak_dir)
        return False, "hard guard failed to raise on a directory containing a .dict file"
    except RuntimeError:
        pass

    # -- refuses a failing report --
    failing = dict(pipeline_report, overall_ok=False)
    try:
        package_for_client.package(failing, "x", "x", "x", os.path.join(tmp, "should_not_exist.zip"))
        return False, "expected package() to refuse a non-overall_ok report"
    except RuntimeError:
        pass
    if os.path.exists(os.path.join(tmp, "should_not_exist.zip")):
        return False, "a zip was written despite the report being refused"

    # -- refuses a report with no persisted binary --
    no_bin = dict(pipeline_report, guide_b=dict(pipeline_report["guide_b"], bin_path=None))
    try:
        package_for_client.package(no_bin, "x", "x", "x", os.path.join(tmp, "should_not_exist2.zip"))
        return False, "expected package() to refuse a report with no bin_path"
    except RuntimeError:
        pass

    return True, "ok"


@regression("R36 verify/reproducibility_check.py: two independent real builds of the "
            "same .dict project produce byte-identical binaries (sha256 match) and a "
            "compiler fingerprint + git-commit (or None) get stamped; a genuinely "
            "mismatched pair of builds is correctly detected as NOT reproducible")
def test_r36_reproducibility_check(tmp):
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import reproducibility_check as rc
    os.makedirs(tmp, exist_ok=True)
    open(os.path.join(tmp, "main.dict"), "w").write(
        'program main\n    print the text "r36 test"\nend program\n'
    )

    result = rc.check(tmp)
    if result["ok"] is not True:
        return False, f"expected two real builds of unchanged source to be byte-identical: {result}"
    if not result.get("binary_sha256"):
        return False, f"expected a real sha256 to be stamped on success: {result}"
    if not result.get("compiler_fingerprint"):
        return False, "expected a real compiler_fingerprint to always be stamped"
    if "git_commit" not in result:
        return False, "expected a git_commit key to always be present (real hash or None)"

    # Negative path: inject a controlled mismatch (simulating a real class
    # of regression -- e.g. an embedded timestamp -- without needing to
    # actually break the compiler's determinism to prove detection works).
    orig_build_once = rc._build_once
    try:
        f1 = os.path.join(tmp, "fakebin1")
        f2 = os.path.join(tmp, "fakebin2")
        open(f1, "wb").write(b"binary content A")
        open(f2, "wb").write(b"binary content B (different)")
        calls = [f1, f2]
        rc._build_once = lambda *a, **kw: calls.pop(0)
        bad_result = rc.check(tmp)
        if bad_result["ok"] is not False:
            return False, f"expected a genuine mismatch to be detected as NOT reproducible: {bad_result}"
    finally:
        rc._build_once = orig_build_once

    return True, "ok"


@regression("R37 dictumc/line_directives.py + debug_mapper.py: a genuine Case C error "
            "(valid Dictum, invalid C -- a C-keyword collision) nested inside a while-loop "
            "body is mapped to the exact real .dict line via gcc's OWN #line-native output "
            "(source='line_directive', the fast path — no line-map needed for this "
            "diagnostic), through the real triage_file() flow end-to-end; both the real "
            "#line directive and the original @dictum-line comment marker are present "
            "in the emitted C (additive, not a replacement)")
def test_r37_line_directive_case_c_mapping(tmp):
    import dict_triage
    os.makedirs(tmp, exist_ok=True)
    dict_path = os.path.join(tmp, "t.dict")
    open(dict_path, "w").write(
        'program t\n'
        '    keep i as whole number with value 0\n'
        '    while i is less than 3 repeat\n'
        '        print the text "loop"\n'
        '        keep int as whole number with value 5\n'
        '        keep i as whole number with value i plus 1\n'
        '    end while\n'
        'end program\n'
    )

    report = dict_triage.triage_file(dict_path)
    if report.get("case") != "C":
        return False, f"expected a genuine Case C (compiler-level) failure, got: {report}"

    diags = report.get("diagnostics", [])
    line_directive_diags = [d for d in diags if d.get("source") == "line_directive"]
    if not line_directive_diags:
        return False, f"expected at least one diagnostic via the #line-native fast path, got: {diags}"
    if any(d["dict_line"] != 5 for d in line_directive_diags):
        return False, f"expected every line_directive diagnostic to map to real .dict line 5: {diags}"

    generated = report.get("generated_code", "")
    if '#line 5 "t.dict"' not in generated:
        return False, "expected a real #line directive with the actual .dict filename in the generated code"
    if "/* @dictum-line:5 */" not in generated:
        return False, "expected the original comment marker to still be present (additive, not replaced)"

    return True, "ok"


@regression("R38 CEmitter/CppEmitter._emit_own_line: a multi-line statement emitted "
            "directly by its own handler (Attempt's `/* attempt */` / "
            "`dictum_error_clear();` / result-assignment / `if (...) {` lines on the C "
            "backend) re-asserts #line before EACH of its own lines, not just the "
            "first -- confirmed via a real repro that was 2 lines off (landing on an "
            "unrelated 'end program' line with a misleading quoted snippet) before "
            "this fix, and lands on the exact correct line after it")
def test_r38_attempt_own_line_mapping(tmp):
    import dict_triage
    os.makedirs(tmp, exist_ok=True)
    dict_path = os.path.join(tmp, "t.dict")
    open(dict_path, "w").write(
        'program t\n'
        '    action get_value takes nothing produces whole number\n'
        '        produce success with 42\n'
        '    end action\n'
        '\n'
        '    attempt call get_value giving int\n'
        '    end attempt\n'
        'end program\n'
    )
    # Line 6 is the `attempt call get_value giving int` statement -- `int`
    # is a C keyword used as the result name, a genuine Case C collision.

    report = dict_triage.triage_file(dict_path)
    if report.get("case") != "C":
        return False, f"expected a genuine Case C failure, got: {report}"

    diags = report.get("diagnostics", [])
    line_directive_diags = [d for d in diags if d.get("source") == "line_directive"]
    if not line_directive_diags:
        return False, f"expected the #line-native fast path to fire, got: {diags}"
    wrong_lines = [d["dict_line"] for d in line_directive_diags if d["dict_line"] != 6]
    if wrong_lines:
        return False, (f"expected every diagnostic to map to the real attempt statement's "
                        f"line (6), got these wrong line(s) instead: {wrong_lines} -- this is "
                        f"exactly the multi-line-statement regression _emit_own_line fixes")

    generated = report.get("generated_code", "")
    # Every one of Attempt's own directly-emitted lines must carry its own
    # #line 6, not auto-increment past it.
    for expected_snippet in ("/* attempt */", "dictum_error_clear();",
                              "int32_t int = get_value();", "if (!DICTUM_HAS_ERROR()) {"):
        idx = generated.find(expected_snippet)
        if idx == -1:
            return False, f"expected generated code to contain: {expected_snippet!r}"
        preceding = generated[:idx]
        last_line_directive = preceding.rfind('#line 6 "')
        if last_line_directive == -1:
            return False, f"expected a '#line 6' directive immediately before: {expected_snippet!r}"

    return True, "ok"


@regression("R39 CppEmitter._emit_own_line (C++ backend mirror of R38): an Attempt "
            "block's try/catch lines (`try {`, the result assignment, `} catch (...) "
            "{`) each get their own #line, not an auto-incremented one -- confirmed "
            "via a real C++-keyword collision (`giving class`) through the real "
            "dict_triage.py --backend cpp CLI, closing the 'applied the same "
            "structural fix but only tested the C side' gap")
def test_r39_attempt_own_line_mapping_cpp(tmp):
    import dict_triage
    os.makedirs(tmp, exist_ok=True)
    dict_path = os.path.join(tmp, "t.dict")
    open(dict_path, "w").write(
        'program t\n'
        '    action get_value takes nothing produces whole number\n'
        '        produce success with 42\n'
        '    end action\n'
        '\n'
        '    attempt call get_value giving class\n'
        '    end attempt\n'
        'end program\n'
    )
    # `class` is a C++ keyword used as the result name -- valid Dictum,
    # invalid C++, a genuine Case C collision on the cpp backend.

    report = dict_triage.triage_file(dict_path, backend="cpp")
    if report.get("case") != "C":
        return False, f"expected a genuine Case C failure on the cpp backend, got: {report}"

    diags = report.get("diagnostics", [])
    line_directive_diags = [d for d in diags if d.get("source") == "line_directive"]
    if not line_directive_diags:
        return False, f"expected the #line-native fast path to fire, got: {diags}"
    wrong_lines = [d["dict_line"] for d in line_directive_diags if d["dict_line"] != 6]
    if wrong_lines:
        return False, (f"expected every diagnostic to map to the real attempt statement's "
                        f"line (6), got these wrong line(s) instead: {wrong_lines}")

    generated = report.get("generated_code", "")
    for expected_snippet in ("try {", "auto class = get_value();",
                              "} catch (const std::exception& e) {"):
        idx = generated.find(expected_snippet)
        if idx == -1:
            return False, f"expected generated code to contain: {expected_snippet!r}"
        preceding = generated[:idx]
        if preceding.rfind('#line 6 "') == -1:
            return False, f"expected a '#line 6' directive immediately before: {expected_snippet!r}"

    return True, "ok"


@regression("R40 project_builder.py: a top-level `export shape`/`export action` in a "
            "real multi-file-path project build now writes a real, AST-based public "
            "export header (<file>_export.h, from the same emitter.get_header_output() "
            "the single-file CLI already used) instead of silently discarding it -- "
            "confirmed by having a genuinely separate external C program #include the "
            "generated header, link against the compiled Dictum object, and produce the "
            "correct runtime value (closing gap #7, header export)")
def test_r40_project_builder_export_header(tmp):
    import project_builder

    os.makedirs(tmp, exist_ok=True)
    dict_path = os.path.join(tmp, "mathlib.dict")
    open(dict_path, "w").write(
        'export shape Point holds\n'
        '    x as whole number\n'
        '    y as whole number\n'
        'end shape\n'
        '\n'
        'export action add takes a as whole number and b as whole number produces whole number\n'
        '    produce a plus b\n'
        'end action\n'
    )

    result = project_builder.build_project(tmp, backend="c", cpp_standard=17, verbose=False)
    build_dir = os.path.join(tmp, "build")
    export_header = os.path.join(build_dir, "mathlib_export.h")
    if not os.path.exists(export_header):
        return False, (f"expected build_project() to write mathlib_export.h; "
                        f"result={result}")

    header_src = open(export_header).read()
    if "int32_t add(int32_t a, int32_t b)" not in header_src:
        return False, f"expected a real 'add' prototype in the export header, got:\n{header_src}"
    if "} Point;" not in header_src:
        return False, f"expected the Point struct in the export header, got:\n{header_src}"

    # Real end-to-end proof: an entirely separate external C program
    # #includes the generated header and links against the compiled
    # object -- not just a string check on the header's contents.
    consumer_path = os.path.join(build_dir, "external_consumer.c")
    open(consumer_path, "w").write(
        '#include "mathlib_export.h"\n'
        'int main() {\n'
        '    Point p = {10, 20};\n'
        '    int result = add(p.x, p.y);\n'
        '    return result == 30 ? 0 : 1;\n'
        '}\n'
    )
    obj_path = os.path.join(build_dir, "mathlib.o")
    r1 = subprocess.run(["gcc", "-c", os.path.join(build_dir, "mathlib.c"),
                          "-o", obj_path, "-I", build_dir],
                         capture_output=True, text=True, timeout=20)
    if r1.returncode != 0:
        return False, f"compiling the generated mathlib.c failed:\n{r1.stderr}"

    exe_path = os.path.join(build_dir, "external_test")
    r2 = subprocess.run(["gcc", consumer_path, obj_path, "-o", exe_path, "-I", build_dir],
                         capture_output=True, text=True, timeout=20)
    if r2.returncode != 0:
        return False, (f"external consumer failed to link against the exported header "
                        f"(the actual point of gap #7):\n{r2.stderr}")

    r3 = _run(exe_path)
    if r3.returncode != 0:
        return False, f"external consumer ran but returned {r3.returncode}, expected 0 (add(10,20)==30)"

    return True, "ok"


@regression("R41 dictum_tls.h: real OpenSSL-backed Tls.wrap/handshake/send/receive/close "
            "(previously a stub file whose function names -- dictum_tls_connect/recv -- "
            "didn't even match STDLIB_ACTION_FAMILIES' real dictum_tls_wrap/handshake/"
            "send/receive/close, so nothing in the registry could have called it even "
            "with the TODOs filled in). Confirmed via a genuine TLS handshake, encrypted "
            "send, and encrypted receive against a real Python ssl-wrapped loopback "
            "server with a real self-signed cert -- not a stub check (closing gap #14)")
def test_r41_real_tls(tmp):
    if shutil.which("openssl") is None:
        return None, "SKIP: openssl CLI not available to generate a test cert"

    os.makedirs(tmp, exist_ok=True)
    cert_path = os.path.join(tmp, "cert.pem")
    key_path = os.path.join(tmp, "key.pem")
    r0 = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key_path,
         "-out", cert_path, "-days", "1", "-nodes", "-subj", "/CN=localhost"],
        capture_output=True, text=True, timeout=30,
    )
    if r0.returncode != 0:
        return None, f"SKIP: could not generate a test cert: {r0.stderr}"

    port = 58999
    server_src = os.path.join(tmp, "srv.py")
    open(server_src, "w").write(f'''
import socket, ssl
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain({cert_path!r}, {key_path!r})
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", {port}))
sock.listen(1)
conn, addr = sock.accept()
tls_conn = ctx.wrap_socket(conn, server_side=True)
data = tls_conn.recv(4096)
tls_conn.sendall(b"echo:" + data)
tls_conn.close()
sock.close()
''')

    src = os.path.join(tmp, "t.c")
    open(src, "w").write(f'''
#include "dictum_net.h"
#include "dictum_tls.h"
#include <string.h>
int main(void) {{
    dictum_net_socket_t sock = dictum_net_connect("127.0.0.1", {port});
    if (sock < 0) return 2;
    dictum_tls_context_t ctx = dictum_tls_wrap(sock);
    if (!ctx) return 3;
    if (!dictum_tls_handshake(ctx)) return 4;
    int n = dictum_tls_send(ctx, "hello over tls");
    if (n != 14) return 5;
    dictum_text resp = dictum_tls_receive(ctx);
    int result = (resp && strcmp(resp, "echo:hello over tls") == 0) ? 0 : 6;
    dictum_tls_close(ctx);
    return result;
}}
''')
    bin_ = os.path.join(tmp, "t")
    include_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")
    r = subprocess.run(
        ["gcc", "-I", include_dir, src, "-o", bin_, "-lssl", "-lcrypto"],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"compile failed:\n{r.stderr}"

    server = subprocess.Popen(
        [sys.executable, "-u", server_src], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        import time
        time.sleep(1)
        r2 = _run(bin_)
    finally:
        server.kill()
        server.wait(timeout=3)

    if r2.returncode != 0:
        return False, (f"real TLS client returned {r2.returncode} (expected 0 -- a genuine "
                        f"handshake + encrypted round-trip against a real server): "
                        f"stdout={r2.stdout!r} stderr={r2.stderr!r}")
    return True, "ok"


@regression("R42 `growable list of whole number` (gap #9, dynamic collections -- scoped "
            "this pass to whole-number elements on the C backend only, not C++/map/set): "
            "add/item-N-of/count-of all wired through the real dictumc_cli.py --compile "
            "entry point and a real dictum_glist.h dynamic array (realloc-based amortized "
            "growth, bounds-checked reads). Two real bugs were caught by gcc itself while "
            "building this and are fixed here: (1) a program-level growable list variable "
            "was silently dropped from the emitter's main()-body statement whitelist, "
            "producing zero code for every `add` statement with no error; (2) "
            "dictum_glist_new() at global scope produced an illegal non-constant C "
            "initializer, needing the same defer-to-main() pattern already used for "
            "room_for/NewExpr globals")
def test_r42_growable_list(tmp):
    os.makedirs(tmp, exist_ok=True)
    dict_path = os.path.join(tmp, "main.dict")
    open(dict_path, "w").write(
        'program Main\n'
        '    keep nums as growable list of whole number with no value\n'
        '    add 10 to nums\n'
        '    add 20 to nums\n'
        '    add 30 to nums\n'
        '    print the text "count:" and the count of nums\n'
        '    print the text "item0:" and item 0 of nums\n'
        '    print the text "item2:" and item 2 of nums\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "glist_test_bin")
    r = subprocess.run(
        [sys.executable, "dictumc_cli.py", "--compile", dict_path,
         "--backend", "c", "--out", out_bin],
        capture_output=True, text=True, timeout=30,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    if r.returncode != 0:
        return False, f"real CLI compile failed:\n{r.stdout}\n{r.stderr}"

    r2 = _run(out_bin)
    if r2.returncode != 0:
        return False, f"compiled binary exited {r2.returncode}: {r2.stdout!r} {r2.stderr!r}"
    out = r2.stdout
    if "count:3" not in out or "item0:10" not in out or "item2:30" not in out:
        return False, f"unexpected output from a real run: {out!r}"

    # Real negative-path checks: an unsupported element type and adding
    # to a non-list variable must both be caught by the validator, not
    # silently mis-compiled.
    bad_type = os.path.join(tmp, "bad_type.dict")
    open(bad_type, "w").write(
        'program Main\n'
        '    keep names as growable list of text with no value\n'
        '    add "hi" to names\n'
        'end program\n'
    )
    r3 = subprocess.run(
        [sys.executable, "dictumc_cli.py", "--compile", bad_type,
         "--backend", "c", "--out", os.path.join(tmp, "bad1")],
        capture_output=True, text=True, timeout=15,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    # UPDATED: this used to assert `growable list of text` was REJECTED,
    # encoding the old int32_t-only limitation of runtime/dictum_glist.h.
    # That limitation was itself the bug -- C++ (std::vector) and Nim (seq)
    # supported every element type, so dynamic collections were a C-backend
    # restriction masquerading as a language one. The runtime now defines a
    # real typed struct per element type via DICTUM_GLIST_DEFINE, so the
    # correct assertion is the opposite: it must now WORK.
    if r3.returncode != 0:
        return False, (f"'growable list of text' should now compile on the C "
                        f"backend (typed glist variants): {r3.stdout[-300:]}")

    bad_target = os.path.join(tmp, "bad_target.dict")
    open(bad_target, "w").write(
        'program Main\n'
        '    keep x as whole number with value 5\n'
        '    add 10 to x\n'
        'end program\n'
    )
    r4 = subprocess.run(
        [sys.executable, "dictumc_cli.py", "--compile", bad_target,
         "--backend", "c", "--out", os.path.join(tmp, "bad2")],
        capture_output=True, text=True, timeout=15,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    if r4.returncode == 0:
        return False, "expected 'add ... to x' on a non-list variable to be rejected"

    return True, "ok"


@regression("R43 `map of K to V` / `set of T` (gap #9, dynamic collections, C++ backend -- "
            "real std::unordered_map/unordered_set for ANY key/value/element type, unlike "
            "growable list's C-side whole-number-only scoping, since C++ has real generics): "
            "put-at-in/the-value-at-in/contains/add(set)/count all wired through the real "
            "dictumc_cli.py --compile entry point. Also closes two more real, pre-existing "
            "bugs found while building growable-list-on-C++ support for this same gap: "
            "'the count of' a std::vector-backed list used the C sizeof(x)/sizeof(x[0]) "
            "trick (meaningless for std::vector's layout -- confirmed returning 6 for a "
            "genuinely empty list), and 'item N of' a text-element list always printed with "
            "%d regardless of element type (confirmed printing a garbage int instead of the "
            "actual string)")
def test_r43_map_set_and_cpp_vector_fixes(tmp):
    os.makedirs(tmp, exist_ok=True)
    cli_dir = os.path.dirname(os.path.abspath(__file__))

    def compile_and_run(src, name):
        dict_path = os.path.join(tmp, f"{name}.dict")
        open(dict_path, "w").write(src)
        out_bin = os.path.join(tmp, f"{name}_bin")
        r = subprocess.run(
            [sys.executable, "dictumc_cli.py", "--compile", dict_path,
             "--backend", "cpp", "--out", out_bin],
            capture_output=True, text=True, timeout=30, cwd=cli_dir,
        )
        return r, out_bin

    # 1. Map + set, real end-to-end run.
    r, out_bin = compile_and_run('''
program Main
    keep ages as map of text to whole number with no value
    put 30 at "alice" in ages
    put 25 at "bob" in ages
    print the text "alice age:" and the value at "alice" in ages
    print the text "count:" and the count of ages
    if ages contains "alice" then
        print the text "has alice"
    end if
    if ages contains "carol" then
        print the text "has carol"
    otherwise
        print the text "no carol"
    end if
    keep tags as set of whole number with no value
    add 1 to tags
    add 2 to tags
    add 1 to tags
    print the text "tag count:" and the count of tags
    if tags contains 2 then
        print the text "has 2"
    end if
end program
''', "mapset")
    if r.returncode != 0:
        return False, f"real CLI compile failed:\n{r.stdout}\n{r.stderr}"
    r2 = _run(out_bin)
    out = r2.stdout
    expected = ["alice age:30", "count:2", "has alice", "no carol", "tag count:2", "has 2"]
    for e in expected:
        if e not in out:
            return False, f"expected {e!r} in real run output, got: {out!r}"
    if "has carol" in out:
        return False, "map should NOT report containing 'carol' -- it was never put in"

    # 2. Growable list of TEXT on C++ (proves real generality beyond the
    #    C backend's whole-number-only scoping) -- also the repro for the
    #    %d-for-text-index bug.
    r, out_bin = compile_and_run('''
program Main
    keep names as growable list of text with no value
    add "alice" to names
    add "bob" to names
    print the text "count:" and the count of names
    print the text "item0:" and item 0 of names
end program
''', "cpptext")
    if r.returncode != 0:
        return False, f"cpp text-list compile failed:\n{r.stdout}\n{r.stderr}"
    r2 = _run(out_bin)
    if "count:2" not in r2.stdout or "item0:alice" not in r2.stdout:
        return False, f"expected real count/text output, got: {r2.stdout!r} (this is exactly the bug: a garbage int instead of 'alice' means the %d-for-text regression came back)"

    # 3. Negative paths: wrong key type, add-to-map, contains-on-non-collection,
    #    map/set rejected entirely on the C backend (no real implementation there).
    def expect_reject(src, name):
        r, _ = compile_and_run(src, name)
        return r.returncode != 0

    if not expect_reject('program Main\n    keep ages as map of text to whole number with no value\n    put 30 at 5 in ages\nend program\n', "bad1"):
        return False, "expected a wrong-key-type 'put' to be rejected"
    if not expect_reject('program Main\n    keep ages as map of text to whole number with no value\n    add "x" to ages\nend program\n', "bad2"):
        return False, "expected 'add' to a map to be rejected"
    if not expect_reject('program Main\n    keep x as whole number with value 5\n    if x contains 3 then\n        print the text "hm"\n    end if\nend program\n', "bad3"):
        return False, "expected 'contains' on a non-collection to be rejected"

    dict_path = os.path.join(tmp, "badc.dict")
    open(dict_path, "w").write(
        # `map of text to whole number` is now real on C (see R44) -- this
        # checks a key/value combo that's still genuinely unimplemented
        # there (dictum_map.h is text-keyed, int-valued only).
        'program Main\n    keep ages as map of whole number to whole number with no value\nend program\n'
    )
    rc = subprocess.run(
        [sys.executable, "dictumc_cli.py", "--compile", dict_path,
         "--backend", "c", "--out", os.path.join(tmp, "badc_bin")],
        capture_output=True, text=True, timeout=15, cwd=cli_dir,
    )
    if rc.returncode == 0:
        return False, "expected 'map of whole number to whole number' to be rejected on the C backend (only text-keyed maps are implemented there)"

    return True, "ok"


@regression("R44 `map of text to whole number` / `set of whole number` on the C backend "
            "(gap #9's final piece, completing what R42/R43 started): real open-addressing "
            "hash table implementations (runtime/dictum_map.h / dictum_gset.h -- FNV-1a "
            "string hashing, splitmix32-style integer hashing, linear probing with "
            "tombstones, real amortized-growth resize at load factor 0.7), not a linear "
            "scan pretending to be a hash table. Verified through the real dictumc_cli.py "
            "--compile entry point: a text-keyed map and a whole-number set doing put/"
            "get/contains/count/add-with-dedup, a stress test with sequential keys (0..9, "
            "a known bad case for naive `key % cap` hashing) forcing a real resize past the "
            "initial capacity, and a clean AddressSanitizer run catching no memory errors "
            "in either")
def test_r44_c_backend_map_and_set(tmp):
    os.makedirs(tmp, exist_ok=True)
    cli_dir = os.path.dirname(os.path.abspath(__file__))

    def compile_and_run(src, name, backend="c"):
        dict_path = os.path.join(tmp, f"{name}.dict")
        open(dict_path, "w").write(src)
        out_bin = os.path.join(tmp, f"{name}_bin")
        r = subprocess.run(
            [sys.executable, "dictumc_cli.py", "--compile", dict_path,
             "--backend", backend, "--out", out_bin],
            capture_output=True, text=True, timeout=30, cwd=cli_dir,
        )
        return r, out_bin

    r, out_bin = compile_and_run('''
program Main
    keep ages as map of text to whole number with no value
    put 30 at "alice" in ages
    put 25 at "bob" in ages
    print the text "alice age:" and the value at "alice" in ages
    print the text "count:" and the count of ages
    if ages contains "alice" then
        print the text "has alice"
    end if
    if ages contains "carol" then
        print the text "has carol"
    otherwise
        print the text "no carol"
    end if
    keep tags as set of whole number with no value
    add 1 to tags
    add 2 to tags
    add 1 to tags
    print the text "tag count:" and the count of tags
    if tags contains 2 then
        print the text "has 2"
    end if
end program
''', "c_mapset")
    if r.returncode != 0:
        return False, f"real CLI compile failed:\n{r.stdout}\n{r.stderr}"
    r2 = _run(out_bin)
    out = r2.stdout
    expected = ["alice age:30", "count:2", "has alice", "no carol", "tag count:2", "has 2"]
    for e in expected:
        if e not in out:
            return False, f"expected {e!r} in real run output, got: {out!r}"
    if "has carol" in out:
        return False, "map should NOT report containing 'carol'"

    # Stress: sequential keys are a classic bad case for naive `key % cap`
    # hashing (they'd all cluster in the first few buckets); this also
    # forces at least one real resize (12 adds, initial cap 8, 0.7 load
    # factor triggers growth well before 10 unique entries fit).
    r, out_bin = compile_and_run('''
program Main
    keep nums as set of whole number with no value
    add 0 to nums
    add 1 to nums
    add 2 to nums
    add 3 to nums
    add 4 to nums
    add 5 to nums
    add 6 to nums
    add 7 to nums
    add 8 to nums
    add 9 to nums
    add 5 to nums
    add 3 to nums
    print the text "count:" and the count of nums
    if nums contains 7 then
        print the text "has 7"
    end if
    if nums contains 100 then
        print the text "has 100"
    otherwise
        print the text "no 100"
    end if
end program
''', "c_stress")
    if r.returncode != 0:
        return False, f"stress compile failed:\n{r.stdout}\n{r.stderr}"
    r2 = _run(out_bin)
    if "count:10" not in r2.stdout or "has 7" not in r2.stdout or "no 100" not in r2.stdout:
        return False, f"unexpected stress output: {r2.stdout!r}"

    # Real ASan check on the same generated .c -- catches use-after-free/
    # buffer overflows in the hash table's own resize/probe logic, not
    # just "did it print the right thing this one time."
    if shutil.which("gcc") is None:
        return None, "SKIP: gcc not available for a direct ASan compile"
    runtime_dir = os.path.join(cli_dir, "runtime")
    asan_bin = os.path.join(tmp, "c_stress_asan")
    r3 = subprocess.run(
        ["gcc", "-fsanitize=address", "-g", "-I", runtime_dir,
         out_bin + ".c", "-o", asan_bin, "-lm"],
        capture_output=True, text=True, timeout=30,
    )
    if r3.returncode != 0:
        return False, f"ASan compile failed:\n{r3.stderr}"
    r4 = _run(asan_bin)
    if r4.returncode != 0:
        return False, f"ASan run failed (real memory error in the hash table): {r4.stdout!r} {r4.stderr!r}"

    # Negative paths: unsupported key/element type combos on C.
    def expect_reject(src, name):
        r, _ = compile_and_run(src, name)
        return r.returncode != 0

    if not expect_reject('program Main\n    keep ages as map of whole number to whole number with no value\nend program\n', "cbad1"):
        return False, "expected 'map of whole number to whole number' to be rejected on C"
    if not expect_reject('program Main\n    keep names as set of text with no value\nend program\n', "cbad2"):
        return False, "expected 'set of text' to be rejected on C"

    return True, "ok"


@regression("R45 generate_import_c.py: a bool* out-param that resolves to an ENUM canonical "
            "type (raygui.h's own RAYGUI_STANDALONE fallback `typedef enum{false,true}bool`, "
            "not C99 _Bool) is still classified as needing a wrapper, not silently bound "
            "directly as an opaque pointer")
def test_r45_generate_import_c_enum_bool_outparam(tmp):
    # Found bridging the real raygui.h with --define RAYGUI_STANDALONE (the
    # tool's own documented usage example): under that define, raygui's
    # bool is `typedef enum { false, true } bool;`, an ENUM, not _Bool. A
    # `bool *active` parameter (e.g. real GuiToggle, GuiCheckBox) then
    # resolves with pointee.kind == TypeKind.ENUM after canonical
    # resolution, which the out-param check didn't cover -- these got
    # silently classified as "directly bindable" via `opaque pointer`,
    # which isn't actually callable from Dictum (no address-of a local
    # var) -- a confident-looking wrong answer instead of the correct
    # "needs a wrapper" flag every other primitive out-param gets.
    os.makedirs(tmp, exist_ok=True)
    header = os.path.join(tmp, "enumbool.h")
    open(header, "w").write(
        "#ifndef __cplusplus\n"
        "typedef enum { r45_false, r45_true } r45_bool;\n"
        "#endif\n"
        "void r45_toggle(int bounds, const char *text, r45_bool *active);\n"
    )
    out_dict = os.path.join(tmp, "enumbool_bridge.dict")
    gen_script = os.path.join(HERE, "scripts", "generate_import_c.py")
    r = subprocess.run(
        [sys.executable, gen_script, header, "--module-name", "enumbool_bridge", "--output", out_dict],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        if "pip install libclang" in r.stderr:
            return None, "libclang not installed — run: pip install libclang --break-system-packages"
        return False, f"generate_import_c.py failed: {r.stdout}\n{r.stderr}"
    content = open(out_dict).read()
    if "import from C the action r45_toggle" in content:
        return False, f"r45_toggle has an enum-typed out-param and must NOT be bound directly:\n{content}"
    if "r45_toggle" not in content or "wrapper" not in content.lower():
        return False, f"expected r45_toggle to be flagged as needing a wrapper, got:\n{content}"
    return True, "ok"


@regression("R46 emit_c.py: `use Raylib`/`use Raygui` no longer auto-#includes the real system "
            "header, which previously conflicted with a program's own locally-declared "
            "shape (e.g. `shape Color`) -- a real, pre-existing bug independent of any "
            "raygui-specific bindings, verified against real raylib.h/raygui.h fetched "
            "from source")
def test_r46_raylib_no_conflicting_include(tmp):
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "gui_demo.dict")
    open(src, "w").write(
        "program gui_demo\n"
        "    use Raylib\n"
        "    use Raygui\n"
        "    shape Color holds\n"
        "        r as byte\n"
        "        g as byte\n"
        "        b as byte\n"
        "        a as byte\n"
        "    end shape\n"
        "    import from C the action ClearBackground takes Color produces nothing as ClearBackground\n"
        "    keep bg as Color with no value\n"
        "    set r of bg to 0\n"
        "    call ClearBackground with bg\n"
        "end program\n"
    )
    out_c = os.path.join(tmp, "gui_demo.c")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "-o", out_c],
        capture_output=True, text=True, timeout=20,
    )
    if r.returncode != 0:
        return False, f"CLI failed: {r.stderr}"
    generated = open(out_c).read()
    if "raylib.h" in generated or "raygui.h" in generated:
        return False, (
            "emitted C still #includes the real raylib.h/raygui.h alongside a "
            "locally-declared `shape Color` -- this is exactly the conflicting "
            f"struct-redefinition bug this test guards against:\n{generated}"
        )
    flags = subprocess.run(
        [sys.executable, CLI, src, "--print-ldflags"],
        capture_output=True, text=True, timeout=20,
    ).stdout.strip()
    if "-lraylib" not in flags:
        return False, f"expected -lraylib to still be linked (no-auto-include must not drop ldflags): {flags!r}"
    if shutil.which("gcc") is None:
        return None, "SKIP: gcc not available to confirm this actually compiles clean"
    comp = subprocess.run(["gcc", "-fsyntax-only", out_c], capture_output=True, text=True, timeout=20)
    if comp.returncode != 0:
        return False, f"emitted C should syntax-check clean on its own (no real header present): {comp.stderr}"
    return True, "ok"


@regression("R47 project_builder.py's GAP-EXTERN-SHARE fix: a plain top-level .dict file "
            "(no `module` wrapper -- e.g. a blessed-library FFI bridge like blessed/"
            "raylib.dict, copied into a project as-is) with `import from C` declarations "
            "now shares its real extern prototypes project-wide via a new dictum_externs.h "
            "(included by any file with no shapes of its own), not just for module-declared "
            "files. Found via an actual raylib GUI program: a `DrawCircle(x, y, 60.0, "
            "color)` call crossing from main.dict into raylib.dict's declarations rendered "
            "nothing at all (screenshot-verified: the circle's expected center pixel was "
            "plain background) because the missing prototype let gcc's implicit-int "
            "fallback misclassify the float radius argument's register class under the "
            "real x86-64 SysV ABI. Reproduced here with a mixed whole-number/fractional-"
            "number multi-argument function -- a single lone float/double argument does "
            "NOT actually exercise this (it lands in XMM0 via default argument promotion "
            "regardless of prototype visibility), so the repro deliberately mirrors "
            "DrawCircle's real shape (int, int, float, struct) instead. Note: the "
            "generated Makefile's default -Werror would have caught the missing prototype "
            "as a hard error on the *intended* build path -- this reproduces the weaker "
            "case (compiling without -Werror, as a person manually diagnosing or iterating "
            "quickly easily could) where it previously only warned and silently corrupted "
            "the value")
def test_r47_cross_file_extern_sharing(tmp):
    os.makedirs(tmp, exist_ok=True)

    # A plain top-level file, NOT wrapped in `module X` -- same shape as
    # a blessed-library bridge, the exact case that had zero header
    # sharing before this fix.
    open(os.path.join(tmp, "mathlib.dict"), "w").write(
        'import from C the action Combine takes whole number and fractional number '
        'produces whole number as Combine\n'
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        'program Main\n'
        '    call Combine with 3 and 2.5 giving result\n'
        '    print the text "combined:" and result\n'
        'end program\n'
    )
    # Real external implementation, linked in separately -- what a
    # blessed library's actual compiled object would be. Encodes both
    # arguments into one distinguishable result: a misclassified `b`
    # (read from the wrong register/stack slot) produces a value far
    # from 325, not a subtly-off one, making corruption unambiguous.
    impl_path = os.path.join(tmp, "combine_impl.c")
    open(impl_path, "w").write(
        "#include <stdint.h>\n"
        "int32_t Combine(int32_t a, double b) { return a * 100 + (int32_t)(b * 10.0); }\n"
    )

    import project_builder
    result = project_builder.build_project(tmp, backend="c", cpp_standard=17, verbose=False)
    build_dir = os.path.join(tmp, "build")
    externs_h = os.path.join(build_dir, "dictum_externs.h")
    if not os.path.exists(externs_h):
        return False, f"expected dictum_externs.h to be written; result={result}"
    externs_src = open(externs_h).read()
    if "Combine" not in externs_src:
        return False, (f"expected dictum_externs.h to carry a real extern declaration for "
                        f"Combine (the whole point of this fix), got:\n{externs_src}")
    normalized = externs_src.replace(", ", ",")
    if "int32_t Combine(int32_t,double)" not in normalized:
        return False, (f"expected dictum_externs.h's Combine declaration to use the real "
                        f"'int32_t, double' signature (proving it was extracted, not a "
                        f"wrong/default one), got:\n{externs_src}")

    # Copy the hand-written impl into the build dir (project_builder.py
    # only compiles .dict-derived files; this one is linked in as-is,
    # matching how a real blessed library's precompiled object would be).
    impl_in_build = os.path.join(build_dir, "combine_impl.c")
    open(impl_in_build, "w").write(open(impl_path).read())

    main_c = os.path.join(build_dir, "main.c")
    mathlib_c = os.path.join(build_dir, "mathlib.c")
    impl_obj = os.path.join(build_dir, "combine_impl.o")
    r0 = subprocess.run(["gcc", "-c", impl_in_build, "-o", impl_obj],
                         capture_output=True, text=True, timeout=20)
    if r0.returncode != 0:
        return False, f"compiling the external Combine implementation failed:\n{r0.stderr}"

    # Deliberately -Wall -Wextra WITHOUT -Werror, matching how this bug
    # was actually reproduced (a person manually compiling/iterating,
    # not necessarily through the generated Makefile's default -Werror).
    main_obj = os.path.join(build_dir, "main.o")
    r1 = subprocess.run(["gcc", "-Wall", "-Wextra", "-I", build_dir, "-c", main_c, "-o", main_obj],
                         capture_output=True, text=True, timeout=20)
    if r1.returncode != 0:
        return False, f"compiling main.c failed:\n{r1.stderr}"
    if "implicit declaration" in r1.stderr:
        return False, (f"expected NO implicit-declaration warning for Combine (that's "
                        f"exactly what this fix closes) -- got:\n{r1.stderr}")

    mathlib_obj = os.path.join(build_dir, "mathlib.o")
    r1b = subprocess.run(["gcc", "-Wall", "-Wextra", "-I", build_dir, "-c", mathlib_c, "-o", mathlib_obj],
                          capture_output=True, text=True, timeout=20)
    if r1b.returncode != 0:
        return False, f"compiling mathlib.c failed:\n{r1b.stderr}"

    exe = os.path.join(build_dir, "cross_file_test")
    r2 = subprocess.run(["gcc", main_obj, mathlib_obj, impl_obj, "-o", exe, "-lm"],
                         capture_output=True, text=True, timeout=20)
    if r2.returncode != 0:
        return False, f"link failed:\n{r2.stderr}"

    r3 = _run(exe)
    if "combined:325" not in r3.stdout.replace(" ", ""):
        return False, (f"expected the real, ABI-correct result of Combine(3, 2.5)==325 "
                        f"(3*100 + 25), got: {r3.stdout!r} -- a different value here means "
                        f"the fractional-number argument's register class was misclassified "
                        f"crossing the file boundary, i.e. the ABI-corruption bug this fix "
                        f"closes came back")

    return True, "ok"



@regression("R48 `call FUNC giving VAR` type inference for `import from C`/`import from "
            "C++` functions and native actions: VAR's auto-declared C type now comes from "
            "the callee's REAL declared Dictum return type (action_return_types, seeded "
            "project-wide from every file's Action/ImportC/ImportCpp declarations via "
            "StdlibTranspiler.run()'s new extra_import_return_types parameter), instead of "
            "silently defaulting to int32_t. Found while designing R47's repro: `call Halve "
            "with 7.0 giving result` (Halve declared to return `fractional number`) emitted "
            "`int32_t result = Halve(7.0);`, truncating 3.5 to 3 -- a real bug, but a "
            "different one than R47's ABI-corruption bug (a single float/double argument "
            "alone doesn't trigger THAT one; this is a separate return-type-inference gap). "
            "Covers same-file, cross-file, and the C++ backend, which had no "
            "action_return_types registry at all before this fix (broader gap than the C "
            "backend, which at least had it for native actions)")
def test_r48_call_giving_return_type_inference(tmp):
    os.makedirs(tmp, exist_ok=True)

    def build_and_grep(files, backend, name):
        proj_dir = os.path.join(tmp, name)
        os.makedirs(proj_dir, exist_ok=True)
        for fname, src in files.items():
            open(os.path.join(proj_dir, fname), "w").write(src)
        import project_builder
        result = project_builder.build_project(proj_dir, backend=backend, cpp_standard=17, verbose=False)
        return proj_dir, result

    proj_dir, result = build_and_grep({
        "main.dict": (
            'import from C the action Halve takes fractional number produces '
            'fractional number as Halve\n\n'
            'program Main\n'
            '    call Halve with 7.0 giving result\n'
            '    print the text "half:" and result\n'
            'end program\n'
        ),
    }, "c", "same_file_c")
    main_c = os.path.join(proj_dir, "build", "main.c")
    if not os.path.exists(main_c):
        return False, f"expected main.c to be written; result={result}"
    src = open(main_c).read()
    # Accept an explicit cast on the argument: FFI call sites now coerce
    # arguments to the DECLARED parameter type so one `import from C` line
    # works on every backend. `Halve((double)(7.0))` is the same call.
    if not re.search(r"double result = Halve\((\(double\))?\(?7\.0\)?\);", src):
        return False, (f"expected 'result' to be inferred as 'double' (the real return "
                        f"type of a 'fractional number'-returning import), got:\n{src}")

    proj_dir, result = build_and_grep({
        "mathlib.dict": (
            'import from C the action Halve takes fractional number produces '
            'fractional number as Halve\n'
        ),
        "main.dict": (
            'program Main\n'
            '    call Halve with 7.0 giving result\n'
            '    print the text "half:" and result\n'
            'end program\n'
        ),
    }, "c", "cross_file_c")
    main_c = os.path.join(proj_dir, "build", "main.c")
    if not os.path.exists(main_c):
        return False, f"expected main.c to be written; result={result}"
    src = open(main_c).read()
    # Accept an explicit cast on the argument: FFI call sites now coerce
    # arguments to the DECLARED parameter type so one `import from C` line
    # works on every backend. `Halve((double)(7.0))` is the same call.
    if not re.search(r"double result = Halve\((\(double\))?\(?7\.0\)?\);", src):
        return False, (f"expected 'result' to be inferred as 'double' across the file "
                        f"boundary too (mathlib.dict declares Halve, main.dict calls it), "
                        f"got:\n{src}")

    build_dir = os.path.join(proj_dir, "build")
    impl_path = os.path.join(build_dir, "halve_impl.c")
    open(impl_path, "w").write("double Halve(double x) { return x / 2.0; }\n")
    impl_obj = os.path.join(build_dir, "halve_impl.o")
    r0 = subprocess.run(["gcc", "-c", impl_path, "-o", impl_obj],
                         capture_output=True, text=True, timeout=20)
    if r0.returncode != 0:
        return False, f"compiling the external Halve implementation failed:\n{r0.stderr}"
    main_obj = os.path.join(build_dir, "main.o")
    mathlib_obj = os.path.join(build_dir, "mathlib.o")
    r1 = subprocess.run(["gcc", "-I", build_dir, "-c", os.path.join(build_dir, "main.c"), "-o", main_obj],
                         capture_output=True, text=True, timeout=20)
    r1b = subprocess.run(["gcc", "-I", build_dir, "-c", os.path.join(build_dir, "mathlib.c"), "-o", mathlib_obj],
                          capture_output=True, text=True, timeout=20)
    if r1.returncode != 0 or r1b.returncode != 0:
        return False, f"compile failed:\n{r1.stderr}\n{r1b.stderr}"
    exe = os.path.join(build_dir, "cross_file_giving_test")
    r2 = subprocess.run(["gcc", main_obj, mathlib_obj, impl_obj, "-o", exe, "-lm"],
                         capture_output=True, text=True, timeout=20)
    if r2.returncode != 0:
        return False, f"link failed:\n{r2.stderr}"
    r3 = _run(exe)
    if "half:3.5" not in r3.stdout.replace(" ", "").replace("half:3.500000", "half:3.5"):
        return False, f"expected the real value 3.5 (not truncated to 3), got: {r3.stdout!r}"

    proj_dir, result = build_and_grep({
        "main.dict": (
            'import from C the action Halve takes fractional number produces '
            'fractional number as Halve\n\n'
            'program Main\n'
            '    call Halve with 7.0 giving result\n'
            '    print the text "half:" and result\n'
            'end program\n'
        ),
    }, "cpp", "cpp_case")
    main_cpp = os.path.join(proj_dir, "build", "main.cpp")
    if not os.path.exists(main_cpp):
        return False, f"expected main.cpp to be written; result={result}"
    src = open(main_cpp).read()
    # Accept an explicit cast on the argument: FFI call sites now coerce
    # arguments to the DECLARED parameter type so one `import from C` line
    # works on every backend. `Halve((double)(7.0))` is the same call.
    if not re.search(r"double result = Halve\((\(double\))?\(?7\.0\)?\);", src):
        return False, (f"expected the C++ backend to also infer 'double' for 'result' "
                        f"(this backend had NO action_return_types registry at all before "
                        f"this fix), got:\n{src}")

    return True, "ok"


@regression("R49 two more real bugs found and fixed after R48: (1) fixed-size list "
            "`_count` variables are declared `size_t` but Dictum's %d-based printing "
            "expects `int` -- same size_t/%d mismatch already fixed for glist/gset/map, "
            "previously left open specifically for fixed lists (flagged, not fixed, during "
            "the gap #9 growable-list work); (2) the C++ backend's `import from C` extern "
            "declaration had no `extern \"C\"` linkage, so g++ mangled the declaration "
            "under C++ rules while the real external C symbol is unmangled -- confirmed "
            "with a real g++ link error, `undefined reference to Halve(double)`, even "
            "though `Halve` genuinely existed in the linked object")
def test_r49_count_format_and_extern_c_linkage(tmp):
    os.makedirs(tmp, exist_ok=True)
    cli_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Fixed-list _count format fix.
    dict_path = os.path.join(tmp, "count_test.dict")
    open(dict_path, "w").write(
        'program Main\n'
        '    keep nums as list of whole number with values 1, 2, 3, 4, 5\n'
        '    print the text "count:" and the count of nums\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "count_bin")
    r = subprocess.run(
        [sys.executable, "dictumc_cli.py", "--compile", dict_path,
         "--backend", "c", "--out", out_bin],
        capture_output=True, text=True, timeout=30, cwd=cli_dir,
    )
    if r.returncode != 0:
        return False, f"count-test compile failed:\n{r.stdout}\n{r.stderr}"
    src = open(out_bin + ".c").read()
    if "(int)nums_count" not in src:
        return False, f"expected an (int) cast on nums_count, got:\n{src}"
    r2 = _run(out_bin)
    if "count:5" not in r2.stdout:
        return False, f"expected real output count:5, got: {r2.stdout!r}"

    # 2. C++ extern "C" linkage fix.
    proj_dir = os.path.join(tmp, "cpp_extern_c")
    os.makedirs(proj_dir, exist_ok=True)
    open(os.path.join(proj_dir, "main.dict"), "w").write(
        'import from C the action Halve takes fractional number produces '
        'fractional number as Halve\n\n'
        'program Main\n'
        '    call Halve with 7.0 giving result\n'
        '    print the text "half:" and result\n'
        'end program\n'
    )
    import project_builder
    result = project_builder.build_project(proj_dir, backend="cpp", cpp_standard=17, verbose=False)
    build_dir = os.path.join(proj_dir, "build")
    main_cpp = os.path.join(build_dir, "main.cpp")
    if not os.path.exists(main_cpp):
        return False, f"expected main.cpp to be written; result={result}"
    src = open(main_cpp).read()
    # `noexcept` was added to every emitted C++ FFI declaration (C functions
    # never throw, and glibc's C++ headers declare libc symbols noexcept --
    # without it, binding e.g. abs is a hard "different exception specifier"
    # error). Accept either form: the linkage claim this test exists to check
    # is `extern "C"`, not the exception specifier.
    if not re.search(r'extern "C" double Halve\(double\)( noexcept)?;', src):
        return False, (f"expected a real extern \"C\" linkage declaration for Halve, "
                        f"got:\n{src}")

    # Real end-to-end link+run against a genuinely extern-"C"-compiled
    # implementation -- proves the linkage actually resolves, not just
    # that the declaration text looks right.
    impl_path = os.path.join(build_dir, "halve_impl.cpp")
    open(impl_path, "w").write('extern "C" double Halve(double x) { return x / 2.0; }\n')
    impl_obj = os.path.join(build_dir, "halve_impl.o")
    r3 = subprocess.run(["g++", "-std=c++17", "-c", impl_path, "-o", impl_obj],
                         capture_output=True, text=True, timeout=20)
    if r3.returncode != 0:
        return False, f"compiling the extern-C Halve implementation failed:\n{r3.stderr}"
    main_obj = os.path.join(build_dir, "main.o")
    r4 = subprocess.run(["g++", "-std=c++17", "-I", build_dir, "-c", main_cpp, "-o", main_obj],
                         capture_output=True, text=True, timeout=20)
    if r4.returncode != 0:
        return False, f"compiling main.cpp failed:\n{r4.stderr}"
    exe = os.path.join(build_dir, "cpp_extern_c_test")
    r5 = subprocess.run(["g++", main_obj, impl_obj, "-o", exe],
                         capture_output=True, text=True, timeout=20)
    if r5.returncode != 0:
        return False, (f"link failed -- this is exactly the bug this fix closes "
                        f"(a name-mangling mismatch against a real extern \"C\" symbol): "
                        f"{r5.stderr}")
    r6 = _run(exe)
    if "half:3.5" not in r6.stdout.replace(" ", "").replace("half:3.500000", "half:3.5"):
        return False, f"expected the real value 3.5, got: {r6.stdout!r}"

    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────
# R50-R57 — Nim backend (`--backend nim`): real, previously-unverified
# bugs. Before this pass, nothing in this suite ever actually ran
# generated Nim through a real `nim c` -- every one of these failed to
# compile with a real Nim compiler, including plain "hello world". See
# emit_nim.py and dictumc/nim_bootstrap.py.
# ─────────────────────────────────────────────────────────────────────────

def _nim_available():
    sys.path.insert(0, HERE)
    from dictumc.nim_bootstrap import get_nim_executable, NimBootstrapError
    try:
        return get_nim_executable(auto_install=False, quiet=True)
    except NimBootstrapError:
        return None


def _dictumc_nim_run(tmp, src_name, dict_source, timeout=30):
    """Compile+run a .dict program through the real CLI on --backend nim.
    Returns (returncode, stdout, stderr) of the produced binary, or
    raises with the compiler's own stderr if the compile step failed."""
    nim_exe = _nim_available()
    if nim_exe is None:
        return None
    src = os.path.join(tmp, src_name)
    open(src, "w").write(dict_source)
    out_bin = os.path.join(tmp, os.path.splitext(src_name)[0] + "_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "nim", "--compile", "--output", out_bin],
        capture_output=True, text=True, timeout=timeout, cwd=HERE,
    )
    if r.returncode != 0:
        raise AssertionError(f"nim compile failed:\n{r.stdout}\n{r.stderr}")
    run = _run(out_bin, timeout=timeout)
    return run


@regression("R50 emit_nim.py string literals are real Nim double-quoted syntax, not Python repr()")
def test_r50_nim_string_literal(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "hello.dict",
            'program hello:\n'
            '    print the text "Hello, Dictum!"\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "Hello, Dictum!" not in run.stdout:
        return False, f"expected the real string, got: {run.stdout!r}"
    return True, "ok"


@regression("R51 emit_nim.py `print` stringifies mixed text+number parts with $ before & concatenation")
def test_r51_nim_print_mixed_types(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "fib.dict",
            'action fib takes n as whole number produces whole number\n'
            '    if n is less than 2 then\n'
            '        return n\n'
            '    end if\n'
            '    keep a as whole number with value 0\n'
            '    keep b as whole number with value 0\n'
            '    call fib with n minus 1 giving a\n'
            '    call fib with n minus 2 giving b\n'
            '    return a plus b\n'
            'end action\n\n'
            'program fibonacci:\n'
            '    keep result as whole number with value 0\n'
            '    call fib with 10 giving result\n'
            '    print the text "fib(10):" and result\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "fib(10):55" not in run.stdout:
        return False, f"expected fib(10):55, got: {run.stdout!r}"
    return True, "ok"


@regression("R52 emit_nim.py `repeat N times using i` anchors the range to int32")
def test_r52_nim_repeat_loop_typing(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "factorial.dict",
            'program factorial:\n'
            '    keep result as whole number with value 1\n'
            '    keep i as whole number with value 0\n'
            '    keep k as whole number with value 0\n'
            '    repeat 5 times using i\n'
            '        put i plus 1 into k\n'
            '        put result times k into result\n'
            '    end repeat\n'
            '    print the text "factorial:" and result\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "factorial:120" not in run.stdout:
        return False, f"expected factorial:120, got: {run.stdout!r}"
    return True, "ok"


@regression("R53 emit_nim.py maps the `%` operator (modulo) to Nim's `mod`")
def test_r53_nim_modulo_operator(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "mod.dict",
            'program mod_test:\n'
            '    keep r as whole number with value 0\n'
            '    put 17 modulo 5 into r\n'
            '    print the text "mod:" and r\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "mod:2" not in run.stdout:
        return False, f"expected mod:2, got: {run.stdout!r}"
    return True, "ok"


@regression("R54 emit_nim.py `the count of X` is a UnaryOp, not a FuncCall")
def test_r54_nim_count_of(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "count.dict",
            'program count_test:\n'
            '    keep nums as growable list of whole number with no value\n'
            '    add 10 to nums\n'
            '    add 20 to nums\n'
            '    add 30 to nums\n'
            '    print the text "count:" and the count of nums\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "count:3" not in run.stdout:
        return False, f"expected count:3, got: {run.stdout!r}"
    return True, "ok"


@regression("R55 emit_nim.py Table[K, V]/HashSet[T] default-value construction doesn't double-close brackets")
def test_r55_nim_table_hashset_default(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "table.dict",
            'program table_test:\n'
            '    keep ages as map of text to whole number with no value\n'
            '    put 30 at "alice" in ages\n'
            '    print the text "age:" and the value at "alice" in ages\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "age:30" not in run.stdout:
        return False, f"expected age:30, got: {run.stdout!r}"
    return True, "ok"


@regression("R56 emit_nim.py `add to X` calls .incl() for HashSet targets, .add() for seq targets")
def test_r56_nim_set_incl_vs_add(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    try:
        run = _dictumc_nim_run(tmp, "set.dict",
            'program set_test:\n'
            '    keep tags as set of whole number with no value\n'
            '    add 1 to tags\n'
            '    add 2 to tags\n'
            '    add 1 to tags\n'
            '    print the text "tag-count:" and the count of tags\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    # A set: adding 1 twice must not double-count -- this also confirms
    # .incl() (set semantics) rather than .add() (which HashSet doesn't
    # even have -- this program wouldn't compile at all pre-fix).
    if "tag-count:2" not in run.stdout:
        return False, f"expected tag-count:2 (set dedupes), got: {run.stdout!r}"
    return True, "ok"


@regression("R57 emit_nim.py auto-imports std/tables and std/sets as a final pass over emitted source")
def test_r57_nim_auto_imports(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    # No `use` statement anywhere -- the only way Table[]/HashSet[] can
    # get their imports is the final-pass scan in get_output(), since
    # the up-front import pass only ever looks at `use` statements.
    try:
        run = _dictumc_nim_run(tmp, "imports.dict",
            'program imports_test:\n'
            '    keep ages as map of text to whole number with no value\n'
            '    keep tags as set of whole number with no value\n'
            '    put 1 at "x" in ages\n'
            '    add 5 to tags\n'
            '    print the text "ok"\n'
            'end program\n')
    except AssertionError as e:
        return False, str(e)
    if run.returncode != 0:
        return False, f"runtime failure: {run.stderr}"
    if "ok" not in run.stdout:
        return False, f"expected ok, got: {run.stdout!r}"
    return True, "ok"


@regression("R58 emit_nim.py real FFI call against a real system library (-lsqlite3): no fake header, cstring not string, --link actually links")
def test_r58_nim_real_ffi_sqlite3(tmp):
    if _nim_available() is None:
        return None, "SKIP: no Nim compiler available (checked vendored copy and PATH)"
    if not os.path.exists("/usr/include/sqlite3.h") or shutil.which("gcc") is None:
        return None, "SKIP: libsqlite3-dev not available in this environment"
    # Real end-to-end FFI: declares the real sqlite3 symbols (same
    # shape as compiler/blessed/sqlite3.dict), links against the real
    # system libsqlite3 via --link, and checks the REAL version string
    # sqlite3 itself reports -- not a canned/mocked value. Covers
    # R-NIM-9 (no fabricated header name), R-NIM-10 (`text` FFI params/
    # returns are `cstring`, not GC `string` -- the untreated case
    # segfaults on the first call), and R-NIM-11 (cstring->string at a
    # `call ... giving x` assignment site needs an explicit `$`).
    src = os.path.join(tmp, "sqlite_info.dict")
    open(src, "w").write(
        'import from C the action sqlite3_libversion takes nothing produces text as sqlite3_libversion\n'
        'import from C the action sqlite3_threadsafe takes nothing produces whole number as sqlite3_threadsafe\n\n'
        'program sqlite_info:\n'
        '    keep ver as text with value ""\n'
        '    call sqlite3_libversion giving ver\n'
        '    print the text "sqlite3 version:" and ver\n\n'
        '    keep ts as whole number with value 0\n'
        '    call sqlite3_threadsafe giving ts\n'
        '    print the text "threadsafe:" and ts\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "sqlite_info_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "nim", "--compile",
         "--output", out_bin, "--link", "sqlite3"],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"nim compile/link failed:\n{r.stdout}\n{r.stderr}"
    run = _run(out_bin, timeout=15)
    if run.returncode != 0:
        return False, f"runtime failure (likely the cstring/string GC bug if this regresses): {run.stderr}"
    real_ver_str = None
    if shutil.which("sqlite3"):
        real_ver = subprocess.run(["sqlite3", "-version"], capture_output=True, text=True)
        if real_ver.returncode == 0 and real_ver.stdout:
            real_ver_str = real_ver.stdout.split()[0]
    if "sqlite3 version:" not in run.stdout or "threadsafe:" not in run.stdout:
        return False, f"missing expected output lines: {run.stdout!r}"
    if real_ver_str and real_ver_str not in run.stdout:
        return False, f"expected the REAL installed sqlite3 version ({real_ver_str}) in output, got: {run.stdout!r}"
    if not real_ver_str and not re.search(r"sqlite3 version:\d+\.\d+\.\d+", run.stdout):
        return False, f"expected a real-looking X.Y.Z version string, got: {run.stdout!r}"
    return True, "ok"


@regression("R59 emit_c.py/emit_cpp.py: a bare single-file `program` block "
            "no longer emits a trailing dictum_main() call with no matching "
            "definition -- the body is already fully inlined into main() "
            "above it, so the call was always dead code that broke linking "
            "for literally any basic program on EITHER backend, including "
            "this suite's own R58-style sqlite3 example run through --backend c/cpp")
def test_r59_no_stray_dictum_main(tmp):
    src = os.path.join(tmp, "bare.dict")
    open(src, "w").write(
        'program bare_prog\n'
        '    keep x as whole number with value 41\n'
        '    put x plus 1 into x\n'
        '    print the text "result:" and x\n'
        'end program\n'
    )
    for backend in ("c", "cpp"):
        out_bin = os.path.join(tmp, f"bare_{backend}_bin")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=20, cwd=HERE,
        )
        if r.returncode != 0:
            return False, (f"[{backend}] compile/link failed (regressed -- likely the "
                            f"dictum_main stray-call bug is back):\n{r.stdout}\n{r.stderr}")
        run = _run(out_bin, timeout=10)
        if "result:42" not in run.stdout:
            return False, f"[{backend}] unexpected output: {run.stdout!r}"
    return True, "ok"


@regression("R60 dictumc_cli.py --compile: the real gcc/g++ invocation "
            "includes -I <runtime headers dir>, so a program using a "
            "runtime-header-dependent stdlib feature (growable list, map, "
            "set, JSON, file, text, ...) compiles through the actual "
            "documented --compile entry point regardless of caller cwd, "
            "not only when invoked from one specific directory a relative "
            "include happened to resolve from")
def test_r60_compile_includes_runtime_dir(tmp):
    src = os.path.join(tmp, "uses_glist.dict")
    open(src, "w").write(
        'program uses_glist\n'
        '    keep xs as growable list of whole number with no value\n'
        '    add 10 to xs\n'
        '    add 20 to xs\n'
        '    add 30 to xs\n'
        '    print the text "count:" and the count of xs\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "glist_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--compile", "--output", out_bin],
        capture_output=True, text=True, timeout=20, cwd=HERE,
    )
    if r.returncode != 0:
        return False, (f"compile failed (regressed -- the runtime -I include path is "
                        f"likely missing from _compile_c/_compile_cpp again):\n"
                        f"{r.stdout}\n{r.stderr}")
    run = _run(out_bin, timeout=10)
    if "count:3" not in run.stdout:
        return False, f"unexpected output: {run.stdout!r}"
    return True, "ok"


@regression("R61 dictumc_cli.py --compile: the intermediate C/C++ source is "
            "persisted at <binary>.<ext> instead of an ephemeral tempfile "
            "deleted immediately after compiling -- a compiled binary with "
            "no retrievable source defeats ASan re-compilation, inspection, "
            "and any downstream tooling (this suite's own R44/R49 among "
            "them) that reasonably expects to find it at a predictable path")
def test_r61_compile_persists_source(tmp):
    src = os.path.join(tmp, "persist.dict")
    open(src, "w").write(
        'program persist_prog\n'
        '    print the text "hi"\n'
        'end program\n'
    )
    for backend, ext in (("c", ".c"), ("cpp", ".cpp")):
        out_bin = os.path.join(tmp, f"persist_{backend}_bin")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=20, cwd=HERE,
        )
        if r.returncode != 0:
            return False, f"[{backend}] compile failed: {r.stdout}\n{r.stderr}"
        expected_src = out_bin + ext
        if not os.path.exists(expected_src):
            return False, (f"[{backend}] expected persisted source at "
                            f"{expected_src!r} but it doesn't exist (regressed -- "
                            "back to an ephemeral tempfile that gets deleted)")
        if os.path.getsize(expected_src) == 0:
            return False, f"[{backend}] persisted source at {expected_src!r} is empty"
    return True, "ok"


@regression("R62 verify/guide_c_verify.py: a gui_check's verify_script that "
            "can never fail (e.g. a no-op `return True`) is caught by "
            "validate_gui_self_tests() when a mutation_fixture is declared "
            "-- a PASS from an unproven verify_script should never be "
            "silently trusted")
def test_r62_gui_verify_script_self_test(tmp):
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import importlib
    gcv = importlib.import_module("guide_c_verify")
    importlib.reload(gcv)

    toothless = os.path.join(tmp, "toothless.py")
    open(toothless, "w").write(
        'import json\nprint(json.dumps({"ok": True, "detail": "always passes"}))\n'
    )
    fixture = os.path.join(tmp, "bad.png")
    open(fixture, "wb").write(b"not a real image, content is irrelevant here")

    manifest = {
        "project": "r62", "target": "linux", "gui": True, "binary": "nope",
        "roadmap_ids": {"R1": "x"}, "console_checks": [],
        "gui_checks": [{
            "name": "toothless_check", "class": "visual", "covers": ["R1"],
            "verify_script": "toothless.py", "mutation_fixture": "bad.png",
        }],
        "project_specific_scripts": [],
    }
    warnings = gcv.validate_gui_self_tests(tmp, manifest)
    if not any("cannot fail" in w or "PASSED against its own known-bad" in w for w in warnings):
        return False, (f"expected a warning flagging the toothless verify_script "
                        f"as unable to fail, got: {warnings!r}")
    return True, "ok"


@regression("R63 verify/guide_c_verify.py: a failing console_check causes "
            "gui_checks in the same manifest to be SKIPped, never launching "
            "Xvfb/the binary -- frontend responsiveness can't be "
            "meaningfully checked on a backend already proven broken, and "
            "shouldn't pay the cost of trying")
def test_r63_gui_fail_fast_on_console_failure(tmp):
    import json
    sys.path.insert(0, os.path.join(HERE, "verify"))
    import importlib
    gcv = importlib.import_module("guide_c_verify")
    importlib.reload(gcv)

    src = os.path.join(tmp, "fails.dict")
    open(src, "w").write(
        'program fails_prog\n'
        '    print the text "actual output"\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "fails_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--compile", "--output", out_bin],
        capture_output=True, text=True, timeout=20, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"setup compile failed: {r.stdout}\n{r.stderr}"

    expected = os.path.join(tmp, "expected.txt")
    open(expected, "w").write("this will never match\n")
    toothless = os.path.join(tmp, "toothless.py")
    open(toothless, "w").write(
        'import json\nprint(json.dumps({"ok": True, "detail": "n/a"}))\n'
    )
    manifest_path = os.path.join(tmp, "guide_c_manifest.json")
    manifest = {
        "project": "r63", "target": "linux", "gui": True, "binary": "fails_bin",
        "roadmap_ids": {"R1": "x"},
        "console_checks": [{
            "name": "will_fail", "class": "deterministic", "covers": ["R1"],
            "args": [], "expected_stdout_file": "expected.txt", "expect_exit_code": 0,
        }],
        "gui_checks": [{
            "name": "should_be_skipped", "class": "visual", "covers": ["R1"],
            "verify_script": "toothless.py",
        }],
        "project_specific_scripts": [],
    }
    open(manifest_path, "w").write(json.dumps(manifest))
    result = gcv.verify(manifest_path)
    console_result = next(r for r in result["results"] if r["name"] == "will_fail")
    gui_result = next(r for r in result["results"] if r["name"] == "should_be_skipped")
    if console_result["ok"] is not False:
        return False, f"expected console check to genuinely FAIL, got ok={console_result['ok']!r}"
    if gui_result["tier"] != "SKIP":
        return False, (f"expected gui_check to be SKIPped after the console failure "
                        f"(regressed -- fail-fast may be gone), got tier={gui_result['tier']!r}")
    if "console check already failed" not in (gui_result.get("detail") or ""):
        return False, f"SKIP reason doesn't explain why: {gui_result.get('detail')!r}"
    return True, "ok"


@regression("R64 emit_cpp.py _format_spec: a `text`-typed variable populated "
            "via `call FUNC giving VAR` on an imported C function prints "
            "with %s, not the numeric %d default -- declared_vars can hold "
            "either the raw Dictum type name ('text') or a converted C++ "
            "type string ('const char*') depending on which code path "
            "wrote it, and the old check only recognized the C++ form, so "
            "a real text value (confirmed: sqlite3's own version string) "
            "printed as garbage on the C++ backend while the C backend, "
            "printing the exact same call's result, was correct")
def test_r64_cpp_print_text_from_ffi_giving(tmp):
    if not os.path.exists("/usr/include/sqlite3.h") or shutil.which("g++") is None:
        return None, "SKIP: libsqlite3-dev / g++ not available in this environment"
    src = os.path.join(tmp, "ver.dict")
    open(src, "w").write(
        'import from C the action sqlite3_libversion takes nothing produces text as sqlite3_libversion\n\n'
        'program ver_prog\n'
        '    keep version as text with value "unknown"\n'
        '    call sqlite3_libversion giving version\n'
        '    print the text "sqlite3 version:" and version\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "ver_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "cpp", "--compile",
         "--output", out_bin, "--link", "sqlite3"],
        capture_output=True, text=True, timeout=20, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"compile/link failed: {r.stdout}\n{r.stderr}"
    run = _run(out_bin, timeout=10)
    if not re.search(r"sqlite3 version:\d+\.\d+\.\d+", run.stdout):
        return False, (f"expected a real X.Y.Z version string (regressed -- likely "
                        f"printing with %d again), got: {run.stdout!r}")
    return True, "ok"


@regression("R65 tools/bughunter.dict: the native mutation-fuzzer (itself "
            "written in and compiled by Dictum, per the request that this "
            "be fast/native rather than a Python harness) builds cleanly "
            "and completes a real, time-based (not iteration-count-based, "
            "so it can run unattended for hours on e.g. Kaggle) campaign "
            "against all three real backends (c/cpp/nim) per mutation, "
            "writing well-formed, internally-consistent counters to "
            "summary.txt")
def test_r65_bughunter_builds_and_runs(tmp):
    tools_dir = os.path.join(HERE, "tools")
    src = os.path.join(tools_dir, "bughunter.dict")
    if not os.path.exists(src):
        return False, f"expected {src} to exist"
    out_bin = os.path.join(tools_dir, "bughunter")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--compile", "--output", out_bin],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"bughunter.dict failed to compile: {r.stdout}\n{r.stderr}"

    duration_file = "/tmp/bughunt_duration_seconds.txt"
    open(duration_file, "w").write("12")
    findings_dir = os.path.join(tools_dir, "findings")
    summary_path = os.path.join(tools_dir, "summary.txt")
    shutil.rmtree(findings_dir, ignore_errors=True)
    if os.path.exists(summary_path):
        os.remove(summary_path)
    os.makedirs(findings_dir, exist_ok=True)

    run = _run(out_bin, timeout=90, cwd=tools_dir)
    if not os.path.exists(summary_path):
        return False, f"summary.txt was never written; stdout: {run.stdout!r}"
    summary = open(summary_path).read()

    m = re.search(r"total_runs:(\d+)", summary)
    if not m:
        return False, f"missing 'total_runs:' in summary.txt: {summary!r}"
    total_runs = int(m.group(1))
    if total_runs < 1:
        return False, (f"expected at least 1 completed mutation round in a 12-second "
                        f"time-based run, got {total_runs} -- summary: {summary!r}")

    for backend in ("c", "cpp", "nim"):
        line_m = re.search(rf"{backend}: crashes=(\d+) internal=(\d+) rejects=(\d+) ok=(\d+)", summary)
        if not line_m:
            return False, f"missing well-formed '{backend}: crashes=...' line in summary.txt: {summary!r}"
        crashes, internal, rejects, ok = (int(x) for x in line_m.groups())
        summed = crashes + internal + rejects + ok
        if summed != total_runs:
            return False, (f"[{backend}] counters don't sum to total_runs "
                            f"({summed} != {total_runs}): {summary!r}")
    return True, f"ok -- {total_runs} time-based mutation rounds across 3 backends in ~12s"


@regression("R66 tools/bughunter.dict: the crash-detection signal it "
            "watches for (the literal string 'Traceback' in captured "
            "compiler output) genuinely fires against a REAL, planted, "
            "unhandled exception -- not merely assumed to work because "
            "the tool runs clean against an already-healthy compiler. "
            "This is the same 'prove the check can fail' discipline as "
            "the GUI verify_script mutation_fixture (R62), applied to "
            "the bughunter's own core assumption")
def test_r66_bughunter_crash_signal_fires_on_real_crash(tmp):
    broken_cli = os.path.join(tmp, "broken_dictumc_cli.py")
    original = open(CLI).read()
    # Plant a real, unhandled exception at the very top of main() -- this
    # is not a simulated string, it's an actual Python exception that will
    # actually propagate to a real, uncaught traceback when this broken
    # copy is invoked, exactly like a genuine bughunter target would hit.
    marker = "def main() -> int:"
    if marker not in original:
        return False, "couldn't find main() to plant the test exception into"
    broken = original.replace(
        marker,
        marker + "\n    raise RuntimeError('R66 planted crash -- proves the signal fires')",
        1,
    )
    open(broken_cli, "w").write(broken)

    dummy_dict = os.path.join(tmp, "dummy.dict")
    open(dummy_dict, "w").write('program p\n    print the text "hi"\nend program\n')

    r = subprocess.run(
        [sys.executable, broken_cli, dummy_dict, "--backend", "c", "--compile",
         "--output", os.path.join(tmp, "out")],
        capture_output=True, text=True, timeout=15,
    )
    combined = r.stdout + r.stderr
    if "Traceback" not in combined:
        return False, (f"planted a real unhandled exception but 'Traceback' never "
                        f"appeared in output -- bughunter's core detection signal is "
                        f"unreliable (Python's default exception reporting may have "
                        f"changed, or dictumc_cli.py now catches broadly). Got: "
                        f"{combined[:300]!r}")
    if "R66 planted crash" not in combined:
        return False, f"got a traceback but not for the planted exception: {combined[:300]!r}"
    return True, "ok -- confirmed a real unhandled exception produces the exact " \
                 "'Traceback' signal bughunter.dict's has_traceback check looks for"


@regression("R67 emit_c.py _MODULE_CALL_MAP: Text.concat was hardcoded to "
            "raw libc strcat() (an unsafe in-place append requiring the "
            "destination to already have enough allocated capacity) "
            "instead of the real, safe dictum_text_concat() which "
            "allocates a correctly-sized buffer. Confirmed to segfault a "
            "real program (bughunter.dict itself, discovered while "
            "building it) the moment a short string was concatenated with "
            "a longer one. Every other Text.* entry in this map was "
            "already correct -- this was an isolated, severe mistake, not "
            "a systemic pattern")
def test_r67_text_concat_is_memory_safe(tmp):
    src = os.path.join(tmp, "concat.dict")
    open(src, "w").write(
        'use Text\n'
        'program concat_prog\n'
        '    keep a as text with value "short"\n'
        '    keep b as text with value ""\n'
        '    call Text.concat with a and " this is a much longer string that would '
        'overflow a small fixed buffer if strcat were used in place, exactly the bug '
        'this test guards against regressing" giving b\n'
        '    print the text "result:" and b\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "concat_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "c", "--compile", "--output", out_bin],
        capture_output=True, text=True, timeout=20, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"compile failed: {r.stdout}\n{r.stderr}"
    run = _run(out_bin, timeout=10)
    if run.returncode != 0:
        return False, (f"binary crashed (exit {run.returncode}) -- regressed back to "
                        f"the unsafe strcat() mapping. stdout: {run.stdout!r}")
    if "result:short this is a much longer string" not in run.stdout:
        return False, f"unexpected output: {run.stdout!r}"
    return True, "ok -- confirmed no crash and correct output on a real overflow case"


@regression("R68 Text.to_number (emit_c.py _MODULE_CALL_MAP missing entry) "
            "and two C++ header-portability bugs (realloc's void* return "
            "needs an explicit cast in C++, which C silently allows but "
            "C++ does not) in dictum_text.h and dictum_json.h -- together "
            "these blocked ANY use of Text.to_number on any backend, and "
            "blocked dictum_text.h from compiling under C++ at all, "
            "regardless of which specific function was actually called")
def test_r68_text_to_number_and_cpp_headers(tmp):
    src = os.path.join(tmp, "tonum.dict")
    open(src, "w").write(
        'use Text\n'
        'program tonum_prog\n'
        '    keep s as text with value "42"\n'
        '    keep n as whole number with value 0\n'
        '    call Text.to_number with s giving n\n'
        '    print the text "n:" and n\n'
        'end program\n'
    )
    for backend in ("c", "cpp"):
        out_bin = os.path.join(tmp, f"tonum_{backend}_bin")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile", "--output", out_bin],
            capture_output=True, text=True, timeout=20, cwd=HERE,
        )
        if r.returncode != 0:
            return False, (f"[{backend}] compile failed (regressed -- either the "
                            f"Text.to_number mapping or the C++ realloc cast fix is "
                            f"back to broken): {r.stdout}\n{r.stderr}")
        run = _run(out_bin, timeout=10)
        if "n:42" not in run.stdout:
            return False, f"[{backend}] unexpected output: {run.stdout!r}"
    return True, "ok -- Text.to_number works correctly on both C and C++"


@regression("R69 runtime/dictum_core.h must be self-sufficient (include its "
            "own stdint.h) rather than assume int32_t is already defined by "
            "whatever includes it. Adding dictum_flush_stdout() (needed for "
            "bughunter.dict's periodic progress output to actually be "
            "visible when redirected, not sit buffered) used int32_t "
            "without this, and broke every hand-written test harness in "
            "this file that includes the runtime headers directly without "
            "pre-including stdint.h itself -- Dictum-generated code always "
            "includes stdint.h first so this was invisible through the "
            "normal compile pipeline, only surfacing here")
def test_r69_dictum_core_self_sufficient(tmp):
    src = os.path.join(tmp, "t.c")
    open(src, "w").write(
        '#include "dictum_core.h"\n'
        'int main(void) { return dictum_flush_stdout(); }\n'
    )
    runtime_dir = os.path.join(HERE, "runtime")
    out_bin = os.path.join(tmp, "t_bin")
    r = subprocess.run(
        ["gcc", "-std=c11", "-I", runtime_dir, src, "-o", out_bin],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        return False, (f"dictum_core.h failed to compile standalone (without "
                        f"stdint.h pre-included by the caller) -- regressed: "
                        f"{r.stdout}\n{r.stderr}")
    return True, "ok -- dictum_core.h compiles standalone, no caller pre-include needed"


def _write_multifile_ffi_project(tmp: str) -> None:
    """A real 2-file project: a module wrapping its own `import from C`
    (getpid), used by a program in a SEPARATE file -- the exact shape
    that surfaced all four bugs below. Shared by R70-R73."""
    open(os.path.join(tmp, "sysinfo.dict"), "w").write(
        'module sysinfo\n\n'
        '    import from C the action getpid takes nothing produces whole number as raw_getpid\n\n'
        '    action get_process_id takes nothing produces whole number\n'
        '        keep p as whole number with value 0\n'
        '        call raw_getpid giving p\n'
        '        return p\n'
        '    end action\n\n'
        'end module\n'
    )
    open(os.path.join(tmp, "main.dict"), "w").write(
        'program main\n\n'
        '    use sysinfo\n\n'
        '    keep pid as whole number with value 0\n'
        '    call sysinfo.get_process_id giving pid\n\n'
        '    print the text "pid:" and pid\n\n'
        'end program\n'
    )


@regression("R70 project_builder.py: the per-file preamble insertion used "
            "to blindly prepend dictum_types.h/dictum_externs.h before ALL "
            "of a file's own generated code, pushing '#define "
            "_DEFAULT_SOURCE' (which must be the file's very first line, "
            "before any #include, to preempt glibc's own default) to "
            "AFTER an #include -- confirmed with a real gcc "
            "'_DEFAULT_SOURCE redefined' error the moment a module file "
            "got dictum_externs.h")
def test_r70_project_builder_default_source_ordering(tmp):
    _write_multifile_ffi_project(tmp)
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    sysinfo_c = os.path.join(out_dir, "sysinfo.c")
    if not os.path.exists(sysinfo_c):
        return False, f"expected {sysinfo_c} to exist"
    first_line = open(sysinfo_c).readline().strip()
    if first_line != "#define _DEFAULT_SOURCE":
        return False, (f"expected '#define _DEFAULT_SOURCE' as the first line "
                        f"(regressed -- an #include got prepended ahead of it "
                        f"again), got: {first_line!r}")
    r2 = subprocess.run(["make"], capture_output=True, text=True, timeout=30, cwd=out_dir)
    if r2.returncode != 0:
        return False, f"make failed: {r2.stdout}\n{r2.stderr}"
    return True, "ok"


@regression("R71 project_builder.py: an explicit --backend CLI flag was "
            "silently overridden by a stale on-disk dictum.project.json "
            "manifest from a PREVIOUS run -- confirmed with a real repro: "
            "building once with --backend c, then again with --backend "
            "cpp on the same workspace, silently produced C output again "
            "(gcc, .c files) with no error or warning. Precedence must be "
            "explicit CLI choice > manifest > hardcoded default")
def test_r71_project_builder_backend_flag_precedence(tmp):
    _write_multifile_ffi_project(tmp)
    out_c = os.path.join(tmp, "build_c")
    r1 = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_c],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r1.returncode != 0:
        return False, f"first (c) build failed: {r1.stdout}\n{r1.stderr}"
    if not os.path.exists(os.path.join(tmp, "dictum.project.json")):
        return False, "expected a manifest to be written after the first build"

    out_cpp = os.path.join(tmp, "build_cpp")
    r2 = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "cpp", "--out", out_cpp],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r2.returncode != 0:
        return False, f"second (cpp) build failed: {r2.stdout}\n{r2.stderr}"
    if not os.path.exists(os.path.join(out_cpp, "main.cpp")):
        return False, (f"expected main.cpp in the second build's output dir "
                        f"(regressed -- the stale manifest's 'backend: c' is "
                        f"silently winning over the explicit --backend cpp flag "
                        f"again). Files present: {os.listdir(out_cpp)}")
    return True, "ok -- explicit --backend cpp correctly won over the stale c manifest"


@regression("R72 emit_cpp.py: a `use <module>` for a module defined in a "
            "SEPARATE file (not this file's own) had its #include emitted "
            "inline at the use-statement's position inside main()'s body "
            "instead of hoisted to file scope -- C tolerates a nested "
            "function prototype so this was invisible there, but C++ "
            "rejected it outright for a zero-argument case (\"most vexing "
            "parse\": 'empty parentheses were disambiguated as a function "
            "declaration'). emit_c.py already had the fix (a dedicated "
            "pre-pass plus an indent>0 guard on the later redundant "
            "visit); emit_cpp.py never got it -- confirmed with a real "
            "2-file project building successfully on C but failing this "
            "exact way on C++ before the fix")
def test_r72_cpp_cross_file_use_hoisting(tmp):
    _write_multifile_ffi_project(tmp)
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "cpp", "--out", out_dir],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    main_cpp = os.path.join(out_dir, "main.cpp")
    content = open(main_cpp).read()
    if '#include "dictum_sysinfo.h"' not in content:
        return False, "expected the cross-file module's include somewhere in main.cpp"
    include_pos = content.index('#include "dictum_sysinfo.h"')
    main_pos = content.index("int main()")
    if include_pos > main_pos:
        return False, (f"the include landed AFTER 'int main()' (regressed -- "
                        f"back to being emitted inline inside the function body)")
    r2 = subprocess.run(["make"], capture_output=True, text=True, timeout=30, cwd=out_dir)
    if r2.returncode != 0:
        return False, f"make failed: {r2.stdout}\n{r2.stderr}"
    run = _run(os.path.join(out_dir, "main"), timeout=10)
    if "pid:" not in run.stdout:
        return False, f"unexpected runtime output: {run.stdout!r}"
    return True, "ok -- include correctly hoisted to file scope, build and run succeed"


@regression("R73 project_builder.py: a file that both declares its own "
            "`import from C` AND also gets the shared cross-project "
            "externs header (needed when it ALSO calls into a sibling "
            "file's declarations) could define the same FFI symbol "
            "twice in one translation unit -- confirmed with a real "
            "'redefinition of raw_getpid' gcc error. Fixed by guarding "
            "the file's own raw extern/wrapper lines with the same "
            "per-symbol #ifndef convention used for the aggregated "
            "headers, scoped entirely to project_builder.py's own text "
            "post-processing (NOT the shared emitters -- that was tried "
            "first and caused severe, unrelated breakage of single-file "
            "compilation)")
def test_r73_no_duplicate_ffi_symbol_definition(tmp):
    _write_multifile_ffi_project(tmp)
    out_dir = os.path.join(tmp, "build")
    r = subprocess.run(
        [sys.executable, PROJECT_BUILDER, tmp, "--backend", "c", "--out", out_dir],
        capture_output=True, text=True, timeout=30, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"project_builder.py failed: {r.stdout}\n{r.stderr}"
    r2 = subprocess.run(["make"], capture_output=True, text=True, timeout=30, cwd=out_dir)
    if r2.returncode != 0:
        return False, (f"make failed (regressed -- likely a duplicate FFI symbol "
                        f"definition is back): {r2.stdout}\n{r2.stderr}")
    run = _run(os.path.join(out_dir, "main"), timeout=10)
    if not re.search(r"pid:\d+", run.stdout):
        return False, f"unexpected output: {run.stdout!r}"
    return True, "ok"


@regression("R74 parser.py: `end program` / `end module` / `end if` are "
            "REQUIRED, not optional. They used to be checked with a bare "
            "`if cur == 'end'` that silently proceeded when absent, so a "
            "truncated or malformed .dict file parsed as though complete "
            "and emitted a REAL, RUNNING BINARY on the C and C++ backends "
            "-- malformed source producing a silently-wrong deliverable is "
            "the worst possible failure mode for this project. Found by "
            "cross-backend differential fuzzing: Nim's indentation-"
            "sensitive output rejected the exact same inputs C and C++ "
            "silently accepted (4 divergences in 120 mutants; 0 after the "
            "fix)")
def test_r74_block_terminators_required(tmp):
    cases = [
        ("missing end if",
         'program p\n    keep a as whole number with value 9\n'
         '    if a is greater than 2 then\n        print the text "y"\n'),
        ("missing end program",
         'program p\n    keep a as whole number with value 9\n'),
    ]
    for label, src in cases:
        path = os.path.join(tmp, "bad.dict")
        open(path, "w").write(src)
        out_bin = os.path.join(tmp, "bad_bin")
        r = subprocess.run(
            [sys.executable, CLI, path, "--backend", "c", "--compile", "--output", out_bin],
            capture_output=True, text=True, timeout=20, cwd=HERE,
        )
        if r.returncode == 0:
            return False, (f"[{label}] malformed source was ACCEPTED and compiled "
                            f"(regressed -- block terminators optional again). "
                            f"This silently produces a wrong binary from broken source.")
        combined = r.stdout + r.stderr
        if "terminator" not in combined:
            return False, f"[{label}] rejected, but not with a clear terminator error: {combined[-300:]!r}"

    good = os.path.join(tmp, "good.dict")
    open(good, "w").write(
        'program p\n    keep a as whole number with value 9\n'
        '    if a is greater than 2 then\n        print the text "yes"\n'
        '    end if\nend program\n'
    )
    good_bin = os.path.join(tmp, "good_bin")
    r2 = subprocess.run(
        [sys.executable, CLI, good, "--backend", "c", "--compile", "--output", good_bin],
        capture_output=True, text=True, timeout=20, cwd=HERE,
    )
    if r2.returncode != 0:
        return False, f"well-formed source was WRONGLY rejected: {r2.stdout}\n{r2.stderr}"
    run = _run(good_bin, timeout=10)
    if "yes" not in run.stdout:
        return False, f"well-formed program ran but output wrong: {run.stdout!r}"
    return True, "ok -- malformed rejected with a clear error, well-formed still works"


@regression("R75 emit_nim.py ImportC params: `import from C the action f "
            "takes whole number and text ...` lists TYPES only, never "
            "parameter names. The old rsplit(' ', 1) assumed a "
            "'<type> <name>' shape and got BOTH cases wrong: a two-word "
            "type like `whole number` became type 'whole' + name 'number' "
            "(invalid Nim), and a single-word type like `text` was "
            "SILENTLY DROPPED (len(parts) != 2), giving the Nim proc the "
            "wrong arity versus the real C symbol -- a silent ABI "
            "mismatch, not a compile error. Found by libmanifest.py "
            "verifying sdl2/raylib across all three targets: both passed "
            "on c and cpp, both failed only on nim")
def test_r75_nim_ffi_param_types(tmp):
    if shutil.which("nim") is None:
        return None, "SKIP: nim not available"
    src = os.path.join(tmp, "ffi.dict")
    open(src, "w").write(
        'import from C the action sqlite3_compileoption_used takes text '
        'produces whole number as opt_used\n'
        'import from C the action sqlite3_libversion_number takes nothing '
        'produces whole number as ver_num\n\n'
        'program ffi_prog\n'
        '    keep r as whole number with value 0\n'
        '    call opt_used with "ENABLE_FTS3" giving r\n'
        '    keep v as whole number with value 0\n'
        '    call ver_num giving v\n'
        '    print the text "v:" and v\n'
        'end program\n'
    )
    out_bin = os.path.join(tmp, "ffi_bin")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "nim", "--compile",
         "--output", out_bin, "--link", "sqlite3"],
        capture_output=True, text=True, timeout=120, cwd=HERE,
    )
    if r.returncode != 0:
        return False, f"nim compile failed (regressed): {(r.stdout + r.stderr)[-500:]}"
    nim_src = out_bin + ".nim"
    if os.path.exists(nim_src):
        text = open(nim_src).read()
        if "a0: cstring" not in text:
            return False, (f"single-word `text` param missing or misnamed in "
                            f"generated Nim (regressed -- it used to be dropped "
                            f"entirely): {text[:300]!r}")
    run = _run(out_bin, timeout=10)
    if not re.search(r"v:\d+", run.stdout):
        return False, f"ran but output wrong: {run.stdout!r}"
    return True, "ok -- multi-word and single-word FFI param types both correct on nim"


@regression("R76 multi-file projects build and run on ALL THREE backends. "
            "project_builder.py was hardcoded to choices=['c','cpp'], and "
            "three separate gaps kept nim out: emit_nim.py silently dropped "
            "every `use` statement (so a module could never reference a "
            "sibling), StdlibTranspiler had no 'nim' branch and fell "
            "through to CEmitter (silently emitting C source into .nim "
            "files), and stdlib_registry.extend_emitter unconditionally "
            "touched emitter.types which NimEmitter deliberately lacks")
def test_r76_multifile_all_three_backends(tmp):
    _write_multifile_ffi_project(tmp)
    results = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        out_dir = os.path.join(tmp, f"build_{backend}")
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, tmp, "--backend", backend, "--out", out_dir],
            capture_output=True, text=True, timeout=120, cwd=HERE,
        )
        if r.returncode != 0:
            return False, f"[{backend}] project_builder failed: {r.stdout}\n{r.stderr}"
        if backend == "nim":
            script = os.path.join(out_dir, "build.sh")
            if not os.path.exists(script):
                return False, "[nim] expected build.sh (nim needs no Makefile)"
            src = os.path.join(out_dir, "main.nim")
            if not os.path.exists(src):
                return False, f"[nim] no main.nim emitted: {os.listdir(out_dir)}"
            text = open(src).read()
            if "#include" in text:
                return False, ("[nim] emitted C source into a .nim file "
                                "(regressed -- StdlibTranspiler nim branch gone)")
            if "import sysinfo" not in text:
                return False, ("[nim] missing `import sysinfo` -- emit_nim is "
                                "dropping `use` again")
            rb = subprocess.run(["sh", script], capture_output=True, text=True,
                                 timeout=300, cwd=out_dir)
            if rb.returncode != 0:
                return False, f"[nim] build.sh failed: {rb.stdout[-400:]}\n{rb.stderr[-400:]}"
        else:
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                 timeout=120, cwd=out_dir)
            if rb.returncode != 0:
                return False, f"[{backend}] make failed: {rb.stdout}\n{rb.stderr}"
        run = _run(os.path.join(out_dir, "main"), timeout=15)
        if not re.search(r"pid:\d+", run.stdout):
            return False, f"[{backend}] unexpected output: {run.stdout!r}"
        results[backend] = True
    return True, f"ok -- multi-file cross-file FFI works on {sorted(results)}"


@regression("R77 A REAL multi-module program (3 modules: pure logic, a "
            "blessed-library FFI wrapper, and a program using both) builds "
            "and produces IDENTICAL output on all three backends. Found two "
            "real bugs no toy fixture reached: (1) project_builder's "
            "generate_header return-type whitelist omitted dictum_text, so "
            "a module action returning `text` was SILENTLY DROPPED from its "
            "own module header -- callers saw no declaration, which C "
            "treats as implicit int; (2) emit_nim.py never sanitized "
            "identifiers against Nim's reserved words, so a variable "
            "legitimately named `out` (fine in C/C++) crashed the Nim "
            "compiler outright")
def test_r77_real_multimodule_program(tmp):
    src_dir = os.path.join(HERE, "tests", "realprog")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/realprog fixtures not present"
    if not os.path.exists("/usr/include/sqlite3.h"):
        return None, "SKIP: libsqlite3-dev not available"
    work = os.path.join(tmp, "realprog")
    shutil.copytree(src_dir, work)

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        mani = os.path.join(work, "dictum.project.json")
        if os.path.exists(mani):
            os.remove(mani)
        out_dir = os.path.join(work, f"build_{backend}")
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, work, "--backend", backend, "--out", out_dir],
            capture_output=True, text=True, timeout=180, cwd=HERE,
        )
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {r.stdout}\n{r.stderr}"
        if backend == "nim":
            sh = os.path.join(out_dir, "build.sh")
            txt = open(sh).read().replace("nim c --opt:speed",
                                           "nim c --opt:speed --passL:-lsqlite3")
            open(sh, "w").write(txt)
            rb = subprocess.run(["sh", sh], capture_output=True, text=True,
                                 timeout=420, cwd=out_dir)
        else:
            mf = os.path.join(out_dir, "Makefile")
            txt = re.sub(r"^LDFLAGS  = .*$", "LDFLAGS  = -lm -lsqlite3",
                          open(mf).read(), flags=re.MULTILINE)
            open(mf, "w").write(txt)
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                 timeout=180, cwd=out_dir)
        if rb.returncode != 0:
            return False, f"[{backend}] compile failed: {rb.stdout[-500:]}\n{rb.stderr[-500:]}"
        run = _run(os.path.join(out_dir, "main"), timeout=20)
        if run.returncode != 0:
            return False, f"[{backend}] binary exited {run.returncode}"
        outputs[backend] = "".join(run.stdout.split())

    for expect in ("square(7)=49", "clamp(150,0,100)=100", "clamp(-5,0,100)=0",
                   "sqlite_present=1"):
        for b, o in outputs.items():
            if expect not in o:
                return False, f"[{b}] missing {expect!r} in {o!r}"
    if len(set(outputs.values())) > 1:
        return False, f"backends DISAGREE on a real program: {outputs}"
    return True, f"ok -- identical output across {sorted(outputs)}"


@regression("R78 multi-file + MULTI-LIBRARY: a project of 3 modules each "
            "binding a DIFFERENT C library (sqlite3, libcrypto, libc) plus "
            "a program using all three, built and run on all 3 backends. "
            "Every earlier multi-file test used exactly ONE library, which "
            "hid two real gaps: (1) project_builder.py had NO --link option "
            "at all, so a multi-file project could not link ANY C library "
            "-- it generated fine then died with 'undefined reference'; "
            "(2) the C++ backend emitted `extern \"C\" int abs(int);` "
            "without noexcept, but glibc's C++ headers declare libc symbols "
            "noexcept and in C++17 that is part of the function TYPE, so "
            "binding any libc function was a hard error -- and because the "
            "aggregated externs header leaks every declaration into every "
            "translation unit, ONE such binding broke the whole project")
def test_r78_multifile_multilibrary(tmp):
    src_dir = os.path.join(HERE, "tests", "multilib")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/multilib fixtures not present"
    if not os.path.exists("/usr/include/sqlite3.h"):
        return None, "SKIP: libsqlite3-dev not available"
    work = os.path.join(tmp, "multilib")
    shutil.copytree(src_dir, work)

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        mani = os.path.join(work, "dictum.project.json")
        if os.path.exists(mani):
            os.remove(mani)
        out_dir = os.path.join(work, f"build_{backend}")
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, work, "--backend", backend,
             "--out", out_dir, "--link", "sqlite3", "crypto"],
            capture_output=True, text=True, timeout=180, cwd=HERE,
        )
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {r.stdout}\n{r.stderr}"
        if backend == "nim":
            rb = subprocess.run(["sh", os.path.join(out_dir, "build.sh")],
                                 capture_output=True, text=True, timeout=420, cwd=out_dir)
        else:
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                 timeout=180, cwd=out_dir)
        if rb.returncode != 0:
            return False, (f"[{backend}] compile/link failed -- likely --link "
                            f"plumbing or the C++ noexcept FFI fix regressed: "
                            f"{rb.stdout[-400:]}\n{rb.stderr[-400:]}")
        run = _run(os.path.join(out_dir, "main"), timeout=20)
        if run.returncode != 0:
            return False, f"[{backend}] binary exited {run.returncode}"
        outputs[backend] = "".join(run.stdout.split())

    for expect in ("db_ok=1", "rng=1", "abs=42"):
        for b, o in outputs.items():
            if expect not in o:
                return False, f"[{b}] missing {expect!r} in {o!r}"
    if len(set(outputs.values())) > 1:
        return False, f"backends DISAGREE: {outputs}"
    return True, f"ok -- 3 modules / 3 libraries identical across {sorted(outputs)}"


@regression("R79 tools/libmanifest.py: the one-manifest-per-library system. "
            "`emit` renders a manifest to .dict binding source, and `verify` "
            "REALLY compiles+links+runs the manifest's own verify snippet on "
            "each target before recording a verdict -- it must never record a "
            "pass it did not observe. Guards the property that made it "
            "valuable: on its first real use it found sdl2 and raylib were "
            "silently broken on nim while passing on c/cpp")
def test_r79_libmanifest_emit_and_verify(tmp):
    lm = os.path.join(HERE, "tools", "libmanifest.py")
    if not os.path.exists(lm):
        return False, "tools/libmanifest.py missing"
    if not os.path.exists("/usr/include/sqlite3.h"):
        return None, "SKIP: libsqlite3-dev not available"

    # emit: manifest -> .dict binding source
    out_dict = os.path.join(tmp, "sqlite3_emitted.dict")
    r = subprocess.run([sys.executable, lm, "emit", "sqlite3", "--out", out_dict],
                       capture_output=True, text=True, timeout=60, cwd=HERE)
    if r.returncode != 0:
        return False, f"emit failed: {r.stdout}\n{r.stderr}"
    text = open(out_dict).read()
    if "import from C the action sqlite3_libversion" not in text:
        return False, f"emitted binding missing its import line: {text[:300]!r}"

    # verify: must genuinely build+run on each requested target
    targets = "c,cpp" + (",nim" if shutil.which("nim") else "")
    r2 = subprocess.run([sys.executable, lm, "verify", "sqlite3", "--targets", targets],
                        capture_output=True, text=True, timeout=600, cwd=HERE)
    if r2.returncode != 0:
        return False, f"verify reported failure: {r2.stdout[-500:]}"
    for t in targets.split(","):
        if f"{t}: PASS" not in r2.stdout:
            return False, f"target {t} did not PASS: {r2.stdout[-400:]}"

    # A manifest whose verify snippet CANNOT pass must be reported as FAIL.
    # Without this the whole tool is decorative -- see R62/R66 for the same
    # "prove the check can fail" discipline applied elsewhere.
    man_dir = os.path.join(HERE, "blessed", "manifests")
    bogus = os.path.join(man_dir, "_selftest_bogus.json")
    try:
        m = json.load(open(os.path.join(man_dir, "sqlite3.json")))
        m["library"] = "_selftest_bogus"
        m["verify"]["expect_regex"] = "THIS_CAN_NEVER_MATCH_XYZZY"
        json.dump(m, open(bogus, "w"), indent=2)
        r3 = subprocess.run([sys.executable, lm, "verify", "_selftest_bogus",
                             "--targets", "c"],
                            capture_output=True, text=True, timeout=180, cwd=HERE)
        if "c: PASS" in r3.stdout:
            return False, ("a manifest whose expect_regex can never match was "
                            "reported as PASS -- verify is not actually checking output")
    finally:
        if os.path.exists(bogus):
            os.remove(bogus)
    # `add` (draft a manifest from a REAL header via libclang) and registry
    # PERSISTENCE were both untested by the original R79, and both were
    # silently broken: `add` invoked generate_import_c.py without its
    # required --module-name/--output and expected stdout it never writes;
    # record_blessing probed GUESSED function names, found none, and printed
    # "registry has no recognized record function" -- so verify reported
    # PASS while the registry stayed empty.
    try:
        import clang.cindex  # noqa: F401
        have_clang = True
    except Exception:
        have_clang = False
    if have_clang and os.path.exists("/usr/include/zlib.h"):
        man_dir = os.path.join(HERE, "blessed", "manifests")
        probe = os.path.join(man_dir, "_selftest_add.json")
        try:
            ra = subprocess.run(
                [sys.executable, lm, "add", "_selftest_add",
                 "--header", "/usr/include/zlib.h", "--link", "z",
                 "--functions", "zlibVersion"],
                capture_output=True, text=True, timeout=300, cwd=HERE)
            if ra.returncode != 0:
                return False, f"`add` failed against a real header: {ra.stdout}\n{ra.stderr}"
            if not os.path.exists(probe):
                return False, "`add` reported success but wrote no manifest"
            drafted = json.load(open(probe))
            names = [i["c_name"] for i in drafted.get("imports", [])]
            if "zlibVersion" not in names:
                return False, f"`add` drafted no zlibVersion binding: {names!r}"
        finally:
            if os.path.exists(probe):
                os.remove(probe)

    # Registry persistence: after verify, the verdict must be readable back.
    try:
        sys.path.insert(0, HERE)
        from dictumc import import_c_registry as _reg
        if _reg.is_blessed("sqlite3", "c") is not True:
            return False, ("verify reported PASS but the registry does not "
                            "record sqlite3/c as blessed -- verdicts are not "
                            "being persisted")
    except Exception as e:
        return False, f"could not read back the blessing verdict: {e}"

    return True, f"ok -- add + emit + verify + registry persistence on {targets}"


@regression("R80 tools/dictation.py: the gated procedure for adding new "
            "grammar. proposed -> check (COMPATIBILITY) -> compatible -> "
            "test (FUNCTIONALITY) -> working. The two gates must be "
            "INDEPENDENT: `check` passing must NOT make a dictation usable, "
            "since compatibility is not function. Verifies (a) a keyword "
            "that already exists is rejected by check, (b) a genuinely new "
            "keyword passes check, and (c) that same unimplemented keyword "
            "still FAILS the functionality gate on all three backends")
def test_r80_dictation_gated_procedure(tmp):
    dc = os.path.join(HERE, "tools", "dictation.py")
    if not os.path.exists(dc):
        return False, "tools/dictation.py missing"
    d_dir = os.path.join(HERE, "dictations")
    created = []

    def run_d(*argv, timeout=300):
        return subprocess.run([sys.executable, dc, *argv],
                              capture_output=True, text=True, timeout=timeout, cwd=HERE)

    try:
        # (a) collision with an existing keyword must FAIL the check gate
        ex = os.path.join(tmp, "ex.dict")
        open(ex, "w").write('program p\n    print the text "x"\nend program\n')
        name_a = "_selftest_collide"
        created.append(name_a)
        r = run_d("propose", name_a, "--syntax", "while X repeat ... end while",
                  "--description", "collides on purpose", "--keywords", "while",
                  "--example", ex, "--expect", "x")
        if r.returncode != 0:
            return False, f"propose(collide) failed: {r.stdout}\n{r.stderr}"
        r = run_d("check", name_a, "--skip-suite")
        if "already exists" not in r.stdout:
            return False, (f"check did not reject a keyword that already exists "
                            f"in grammar.py KEYWORDS: {r.stdout[-300:]!r}")

        # (b) a genuinely new keyword should PASS the compatibility gate,
        # and (c) still FAIL the functionality gate because nothing
        # implements it. That gap is the whole point of two gates.
        name_b = "_selftest_newkw"
        created.append(name_b)
        ex2 = os.path.join(tmp, "ex2.dict")
        open(ex2, "w").write(
            'program p\n    zzblorp x is 1 then\n        print the text "y"\n'
            '    end zzblorp\nend program\n')
        r = run_d("propose", name_b, "--syntax", "zzblorp ... end zzblorp",
                  "--description", "deliberately unimplemented",
                  "--keywords", "zzblorp", "--example", ex2, "--expect", "y")
        if r.returncode != 0:
            return False, f"propose(new) failed: {r.stdout}\n{r.stderr}"
        r = run_d("check", name_b, "--skip-suite")
        if "state -> compatible" not in r.stdout:
            return False, f"new keyword failed the check gate: {r.stdout[-300:]!r}"
        r = run_d("test", name_b, timeout=600)
        if "state -> failed" not in r.stdout or "NOT usable" not in r.stdout:
            return False, ("an UNIMPLEMENTED dictation passed the functionality "
                            f"gate -- the gates are not independent: {r.stdout[-400:]!r}")
    finally:
        for n in created:
            f = os.path.join(d_dir, f"{n}.json")
            if os.path.exists(f):
                os.remove(f)
    return True, "ok -- collision rejected; check and test gates genuinely independent"


@regression("R81 DOGFOOD: a real SQLite-backed notes application written in "
            "Dictum -- a module wrapping a C shim, a program using it, real "
            "INSERT/COUNT/SUM against a real database file -- built and run "
            "on all three backends with identical output, and the resulting "
            "database independently verified. Writing it found two real bugs "
            "no synthetic test had: (1) an action returning `opaque pointer` "
            "emits `void* f(...)`, and generate_header's return-type "
            "whitelist matched bare `void` followed by whitespace, so EVERY "
            "pointer-returning action was silently dropped from its module "
            "header (implicit-int at the call site) -- same failure family "
            "as the earlier missing dictum_text entry; (2) `divided by` on "
            "whole numbers is INTEGER division in C/C++ but Nim's `/` is "
            "always FLOAT, so the same program failed to compile on Nim "
            "(the parser rewrites `divided by` to `/` before the emitter, "
            "so _BIN_OP_MAP's div entry never fired)")
def test_r81_real_sqlite_app(tmp):
    src_dir = os.path.join(HERE, "tests", "notesapp")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/notesapp fixtures not present"
    if not os.path.exists("/usr/include/sqlite3.h"):
        return None, "SKIP: libsqlite3-dev not available"
    work = os.path.join(tmp, "notesapp")
    shutil.copytree(src_dir, work)

    shim_o = os.path.join(work, "sqlite_shim.o")
    rc = subprocess.run(["gcc", "-c", os.path.join(work, "sqlite_shim.c"), "-o", shim_o],
                        capture_output=True, text=True, timeout=60)
    if rc.returncode != 0:
        return False, f"shim failed to compile: {rc.stderr[-300:]}"

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        for stale in ("dictum.project.json", "notes.db"):
            f = os.path.join(work, stale)
            if os.path.exists(f):
                os.remove(f)
        out_dir = os.path.join(work, f"build_{backend}")
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, work, "--backend", backend,
             "--out", out_dir, "--link", "sqlite3"],
            capture_output=True, text=True, timeout=180, cwd=HERE)
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {r.stdout}\n{r.stderr}"

        if backend == "nim":
            sh = os.path.join(out_dir, "build.sh")
            # object file must precede -lsqlite3 for the linker to resolve it
            txt = open(sh).read().replace(
                "--passL:-lsqlite3", f"--passL:{shim_o} --passL:-lsqlite3")
            open(sh, "w").write(txt)
            rb = subprocess.run(["sh", sh], capture_output=True, text=True,
                                 timeout=420, cwd=out_dir)
        else:
            mf = os.path.join(out_dir, "Makefile")
            txt = re.sub(r"^OBJS     = ", f"OBJS     = {shim_o} ",
                          open(mf).read(), flags=re.MULTILINE)
            open(mf, "w").write(txt)
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                 timeout=180, cwd=out_dir)
        if rb.returncode != 0:
            return False, (f"[{backend}] compile/link failed: "
                            f"{rb.stdout[-400:]}\n{rb.stderr[-400:]}")
        # cwd matters: the program opens "notes.db" relative to it.
        run = _run(os.path.join(out_dir, "main"), timeout=30, cwd=out_dir)
        if run.returncode != 0:
            return False, f"[{backend}] binary exited {run.returncode}"
        outputs[backend] = "".join(run.stdout.split())

    for expect in ("notes=3", "weight=16", "avg=5", "closed=0"):
        for b, o in outputs.items():
            if expect not in o:
                return False, f"[{b}] missing {expect!r} in {o!r}"
    if len(set(outputs.values())) > 1:
        return False, f"backends DISAGREE on a real app: {outputs}"

    # The program writes notes.db relative to its cwd, i.e. into whichever
    # build dir it ran from. Verify the LAST backend's database.
    last_backend = sorted(outputs)[-1]
    db = os.path.join(work, f"build_{last_backend}", "notes.db")
    if not os.path.exists(db):
        return False, ("the program reported success but wrote no database "
                        f"file at {db}")
    import sqlite3 as _s
    rows = list(_s.connect(db).execute("SELECT body, weight FROM notes"))
    if len(rows) != 3 or sum(r[1] for r in rows) != 16:
        return False, f"database contents wrong: {rows!r}"
    return True, f"ok -- real app identical on {sorted(outputs)}, db verified"


@regression("R82 header-completeness INVARIANT (a whole bug CLASS, not one "
            "bug): every action DEFINED in a module's generated source must "
            "be DECLARED in that module's generated header. generate_header "
            "matches return types against a hardcoded whitelist, so any type "
            "not on it vanishes silently -- callers get an implicit-int "
            "declaration. Three separate instances of this were found one at "
            "a time (text, opaque pointer, byte); tools/header_completeness.py "
            "checks every type in the vocabulary at once, including types "
            "added later")
def test_r82_header_completeness(tmp):
    tool = os.path.join(HERE, "tools", "header_completeness.py")
    if not os.path.exists(tool):
        return False, "tools/header_completeness.py missing"
    r = subprocess.run([sys.executable, tool], capture_output=True,
                       text=True, timeout=600, cwd=HERE)
    if r.returncode != 0:
        missing = [l.strip() for l in r.stdout.splitlines() if "MISSING" in l]
        return False, ("header-completeness invariant violated -- a return "
                        f"type is missing from generate_header's whitelist: {missing}")
    if "invariant holds" not in r.stdout:
        return False, f"unexpected output: {r.stdout[-300:]}"
    return True, "ok -- every type in the vocabulary survives header generation"


@regression("R83 `the address of X` -- the address-of operator, closing the "
            "FFI gap that made C out-parameter APIs uncallable. sqlite3_open "
            "takes `sqlite3 **ppDb`, so it was BLESSED YET UNCALLABLE from "
            ".dict source: a real app had to bind a hand-written C shim "
            "instead. This test calls sqlite3_open DIRECTLY with no shim on "
            "all three backends and checks it returns SQLITE_OK and really "
            "creates the database file. Also covers the validator rule that "
            "makes it usable at all: taking the ADDRESS of an uninitialized "
            "variable is not a READ of it -- that is precisely what an "
            "out-parameter is for -- so it must not raise 'Use of "
            "uninitialized variable'")
def test_r83_address_of_operator(tmp):
    src_dir = os.path.join(HERE, "tests", "addressof")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/addressof fixtures not present"
    if not os.path.exists("/usr/include/sqlite3.h"):
        return None, "SKIP: libsqlite3-dev not available"
    src_tpl = open(os.path.join(src_dir, "noshim.dict")).read()

    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        db = os.path.join(tmp, f"t_{backend}.db")
        src = os.path.join(tmp, f"noshim_{backend}.dict")
        open(src, "w").write(src_tpl.replace("/tmp/gaps/noshim.db", db))
        out_bin = os.path.join(tmp, f"noshim_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin, "--link", "sqlite3"],
            capture_output=True, text=True, timeout=180, cwd=HERE)
        if r.returncode != 0:
            return False, (f"[{backend}] address-of build failed -- the operator "
                            f"or its validator exemption regressed: "
                            f"{(r.stdout + r.stderr)[-400:]}")
        run = _run(out_bin, timeout=20)
        if "open_rc=0" not in run.stdout:
            return False, (f"[{backend}] sqlite3_open did not return SQLITE_OK "
                            f"through the address-of out-parameter: {run.stdout!r}")
        if not os.path.exists(db):
            return False, f"[{backend}] reported success but created no database"
    return True, "ok -- sqlite3_open called directly, no C shim, on all backends"


@regression("R84 Nim stdlib bridge + auto-enabled stdlib. Two gaps: (1) all "
            "92 registered stdlib functions were mapped ONLY to C "
            "implementations, so ANY `use Text`/`File`/`Math` program failed "
            "on nim with \"undeclared identifier\" -- not a missing feature "
            "here and there but the entire standard library, which is what "
            "made nim a second-class backend; (2) on c/cpp, 33 of the 92 "
            "resolve only via stdlib_registry.extend_emitter(), which only "
            "StdlibTranspiler calls -- so without an undiscoverable --stdlib "
            "flag `use Math` parsed fine, transpiled fine, and died at LINK "
            "time with 'undefined reference to Math_sqrt'. Now auto-enabled "
            "when the source uses a stdlib module")
def test_r84_stdlib_all_backends(tmp):
    src_dir = os.path.join(HERE, "tests", "nimstdlib")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/nimstdlib fixtures not present"
    src_tpl = open(os.path.join(src_dir, "stdlib_all.dict")).read()

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        d = os.path.join(tmp, backend)
        os.makedirs(d, exist_ok=True)
        src = os.path.join(d, "s.dict")
        open(src, "w").write(src_tpl)
        out_bin = os.path.join(d, "s")
        # NOTE: deliberately NO --stdlib flag -- auto-detection is the fix.
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=300, cwd=HERE)
        if r.returncode != 0:
            return False, (f"[{backend}] failed WITHOUT --stdlib -- either the "
                            f"nim bridge or stdlib auto-detection regressed: "
                            f"{(r.stdout + r.stderr)[-400:]}")
        run = _run(out_bin, timeout=20, cwd=d)
        if run.returncode != 0:
            return False, f"[{backend}] exited {run.returncode}"
        outputs[backend] = "".join(run.stdout.split())

    for expect in ("file=payload", "sqrt=4.000000", "n2s=99"):
        for b, o in outputs.items():
            if expect not in o:
                return False, f"[{b}] missing {expect!r} in {o!r}"
    if len(set(outputs.values())) > 1:
        return False, f"backends DISAGREE on stdlib results: {outputs}"
    return True, f"ok -- Text/File/Math identical across {sorted(outputs)}, no flags"


@regression("R85 higher-order actions: passing an action as a value. The "
            "function-TYPE annotation (`action taking A as T1 produces T2`) "
            "was already documented AND parsed, but an action name in value "
            "position resolved only against variables -- so the type existed "
            "with no way to produce a value of it. Three backend bugs behind "
            "it: emit_c rendered the type as a mangled identifier (not a C "
            "type); emit_cpp returned a HARDCODED std::function<bool(int32_t)> "
            "for every signature, which compiled cleanly and silently "
            "returned WRONG ANSWERS (42 became 1); emit_nim had no case at "
            "all and emitted the raw Dictum text as a Nim type")
def test_r85_higher_order_actions(tmp):
    src_dir = os.path.join(HERE, "tests", "hof")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/hof fixtures not present"
    src_tpl = open(os.path.join(src_dir, "hof.dict")).read()

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        src = os.path.join(tmp, f"hof_{backend}.dict")
        open(src, "w").write(src_tpl)
        out_bin = os.path.join(tmp, f"hof_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=180, cwd=HERE)
        if r.returncode != 0:
            return False, (f"[{backend}] higher-order build failed: "
                            f"{(r.stdout + r.stderr)[-400:]}")
        run = _run(out_bin, timeout=20)
        got = "".join(run.stdout.split())
        # 21 doubled = 42. A wrong RESULT here (notably 1) means a backend
        # is mistyping the callback rather than failing outright.
        if got != "r=42":
            return False, (f"[{backend}] expected 'r=42', got {got!r} -- the "
                            f"callback's signature is being mistyped")
        outputs[backend] = got
    return True, f"ok -- callbacks work and agree across {sorted(outputs)}"


@regression("R86 an UNBLESSED library via raw `import from C`: libuuid, with "
            "no manifest and no blessing, writing into a caller-allocated "
            "buffer via `the address of` and printing it through libc puts. "
            "Guards three real bugs found writing it: (1) `the address of` on "
            "a container yielded the address of the std::vector/seq OBJECT "
            "rather than its data -- a real segfault, since C gets a true "
            "array and the other two do not; (2) FFI call sites did not "
            "coerce arguments to the DECLARED parameter type, so one "
            "`import from C` line could not satisfy all three backends; "
            "(3) the nim coercion used cast[cstring] on a Nim string, which "
            "reinterprets the string OBJECT's pointer instead of its data -- "
            "that silently corrupted every SQL string in the real sqlite3 app "
            "while it still reported success")
def test_r86_unblessed_library_ffi(tmp):
    src_dir = os.path.join(HERE, "tests", "unblessed")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/unblessed fixtures not present"
    if not os.path.exists("/usr/include/uuid/uuid.h"):
        return None, "SKIP: uuid-dev not available"
    src_tpl = open(os.path.join(src_dir, "uuidgen.dict")).read()

    seen = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        src = os.path.join(tmp, f"u_{backend}.dict")
        open(src, "w").write(src_tpl)
        out_bin = os.path.join(tmp, f"u_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin, "--link", "uuid"],
            capture_output=True, text=True, timeout=180, cwd=HERE)
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {(r.stdout + r.stderr)[-400:]}"
        run = _run(out_bin, timeout=20)
        if run.returncode != 0:
            return False, (f"[{backend}] crashed (exit {run.returncode}) -- likely "
                            f"`the address of` is yielding the container object "
                            f"rather than its data buffer")
        # A real UUID, not garbage: 8-4-4-4-12 hex.
        m = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                      r"[0-9a-f]{4}-[0-9a-f]{12}\b", run.stdout)
        if not m:
            return False, (f"[{backend}] no valid UUID in output {run.stdout!r} -- "
                            f"the buffer was not filled correctly")
        seen[backend] = m.group(0)
    if len(set(seen.values())) != len(seen):
        return False, f"UUIDs should differ per run/backend, got {seen}"
    return True, f"ok -- unblessed libuuid works on {sorted(seen)}"


@regression("R87 BACKEND PARITY: the three emitters consume the same AST, so "
            "a node type or operator handled by one and not another is a gap "
            "by construction. This is the single most recurring bug shape in "
            "this project -- works on 1-2 backends, silently wrong on the "
            "third (emit_nim dropped every `use`; emit_cpp lacked emit_c's "
            "cross-file hoisting fix; emit_cpp hardcoded "
            "std::function<bool(int32_t)> and returned WRONG ANSWERS). "
            "tools/backend_parity.py diffs the handler sets; every remaining "
            "asymmetry must be listed in ALLOWED_ABSENCE with a stated "
            "reason, so divergence is a documented decision rather than an "
            "accident. On its first run it found nim missing sqrt/sin/cos/"
            "neg/deref -- `the square root of x` emitted `(sqrtx)`, a single "
            "undefined identifier")
def test_r87_backend_parity(tmp):
    tool = os.path.join(HERE, "tools", "backend_parity.py")
    if not os.path.exists(tool):
        return False, "tools/backend_parity.py missing"
    r = subprocess.run([sys.executable, tool], capture_output=True,
                       text=True, timeout=120, cwd=HERE)
    if r.returncode != 0:
        gaps = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("[")]
        return False, ("unexplained backend parity gap(s) -- either fix the "
                        f"backend or document the asymmetry with a reason: {gaps}")
    if "no unexplained parity gaps" not in r.stdout:
        return False, f"unexpected output: {r.stdout[-300:]}"
    return True, "ok -- no unexplained divergence between the three emitters"


@regression("R88 printf format spec must follow the DECLARED TYPE, never a "
            "guess from the variable NAME. Both emit_c and emit_cpp fell "
            "through to a name heuristic ('frac'/'dist'/'price'/'rate' -> "
            "%f) whenever the declared type was not in their short "
            "recognised list -- and int32_t was not in it. So `keep price "
            "as whole number with value 100` printed 'price=0.000000': "
            "undefined behaviour from passing an int to %f. `price`, "
            "`rate`, `distance` are about as ordinary as variable names "
            "get. Found by tools/explorer.py pairing its reserved-identifier "
            "fragment with a loop -- the trigger was a generated variable "
            "called `distinct_2` matching the 'dist' substring")
def test_r88_format_spec_follows_declared_type(tmp):
    src = os.path.join(tmp, "names.dict")
    open(src, "w").write(
        'program p\n'
        '    keep price as whole number with value 100\n'
        '    keep rate as whole number with value 7\n'
        '    keep distance as whole number with value 42\n'
        '    keep fraction as whole number with value 3\n'
        '    print the text "price=" and price and ",rate=" and rate and '
        '",distance=" and distance and ",fraction=" and fraction\n'
        'end program\n'
    )
    want = "price=100,rate=7,distance=42,fraction=3"
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        out_bin = os.path.join(tmp, f"n_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=180, cwd=HERE)
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {(r.stdout + r.stderr)[-300:]}"
        run = _run(out_bin, timeout=20)
        got = "".join(run.stdout.split())
        if got != want:
            return False, (f"[{backend}] got {got!r} want {want!r} -- an integer "
                            f"is being printed with a format guessed from its NAME "
                            f"instead of its declared type")
    return True, "ok -- declared type wins over the name heuristic on all backends"


@regression("R89 `attempt` with a PRE-DECLARED result variable on nim. "
            "`keep v ...` followed by `call f giving v` inside an attempt "
            "block emitted `var v` a SECOND time -- 'redefinition of v' -- "
            "so every attempt/on-success block using an already-declared "
            "result variable failed to compile on nim while working on c "
            "and cpp. `call ... giving` must DECLARE only when the name is "
            "new, and ASSIGN otherwise")
def test_r89_attempt_predeclared_result(tmp):
    src = os.path.join(tmp, "att.dict")
    open(src, "w").write(
        'action risky takes nothing produces whole number\n'
        '    return 5\n'
        'end action\n'
        'program p\n'
        '    keep v as whole number with value 0\n'
        '    attempt\n'
        '        call risky giving v\n'
        '    on success\n'
        '        print the text "ok=" and v\n'
        '    on failure\n'
        '        print the text "fail"\n'
        '    end attempt\n'
        'end program\n'
    )
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        out_bin = os.path.join(tmp, f"a_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=180, cwd=HERE)
        if r.returncode != 0:
            return False, (f"[{backend}] build failed -- `call giving` is likely "
                            f"redeclaring an existing variable: "
                            f"{(r.stdout + r.stderr)[-300:]}")
        run = _run(out_bin, timeout=20)
        if "ok=5" not in run.stdout:
            return False, f"[{backend}] unexpected output: {run.stdout!r}"
    return True, "ok -- attempt with a pre-declared result works on all backends"


@regression("R90 runtime headers must tolerate inclusion by MULTIPLE "
            "translation units. dictum_flush_stdout was a plain "
            "(non-static) DEFINITION in dictum_core.h, so every .c that "
            "included it emitted its own copy: 'multiple definition of "
            "dictum_flush_stdout' at link time. Invisible in a single-file "
            "build, broke EVERY multi-file project -- found by writing a "
            "real 2-module text-analysis tool. It cannot be `static inline` "
            "either, because `import from C` binds it by name and needs "
            "external linkage; `weak` gives both")
def test_r90_runtime_header_multi_tu(tmp):
    src_dir = os.path.join(HERE, "tests", "wordstat")
    if not os.path.isdir(src_dir):
        return None, "SKIP: tests/wordstat fixtures not present"
    work = os.path.join(tmp, "wordstat")
    shutil.copytree(src_dir, work)

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        mani = os.path.join(work, "dictum.project.json")
        if os.path.exists(mani):
            os.remove(mani)
        out_dir = os.path.join(work, f"build_{backend}")
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, work, "--backend", backend, "--out", out_dir],
            capture_output=True, text=True, timeout=200, cwd=HERE)
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {r.stdout}\n{r.stderr}"
        shutil.copyfile(os.path.join(work, "sample.txt"),
                        os.path.join(out_dir, "sample.txt"))
        if backend == "nim":
            rb = subprocess.run(["sh", os.path.join(out_dir, "build.sh")],
                                 capture_output=True, text=True, timeout=420, cwd=out_dir)
        else:
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                 timeout=200, cwd=out_dir)
        if rb.returncode != 0:
            combined = rb.stdout + rb.stderr
            hint = (" -- a runtime header is defining a symbol per translation "
                    "unit again" if "multiple definition" in combined else "")
            return False, f"[{backend}] link/compile failed{hint}: {combined[-400:]}"
        run = _run(os.path.join(out_dir, "main"), timeout=25, cwd=out_dir)
        outputs[backend] = "".join(run.stdout.split())

    # Counts independently verifiable against `wc` on sample.txt.
    for expect in ("chars=50", "words=10", "lines=1"):
        for b, o in outputs.items():
            if expect not in o:
                return False, f"[{b}] missing {expect!r} in {o!r}"
    if len(set(outputs.values())) > 1:
        return False, f"backends DISAGREE: {outputs}"
    return True, f"ok -- multi-module tool identical across {sorted(outputs)}"


@regression("R91 runtime-header includes must be gated on the WHOLE FILE, "
            "not just the Program node. A top-level Action is a SIBLING of "
            "Program, not inside it, so a `growable list` (or map/set) "
            "declared inside an ACTION never triggered its #include: "
            "\"unknown type name 'dictum_glist_t'\". Lists worked in "
            "`program main` and NOT in a helper action -- about as ordinary "
            "a thing to write as exists. StdlibTranspiler pre-scanned the "
            "file for attempt/produce-failure; the BASE Transpiler (used by "
            "any program with no `use` line) did no pre-scan at all. Also "
            "covers nim's int32(len(...)) cast, since Nim will not "
            "implicitly narrow int to int32 the way C does")
def test_r91_runtime_include_gated_on_whole_file(tmp):
    src = os.path.join(tmp, "inact.dict")
    open(src, "w").write(
        'action build_list takes nothing produces whole number\n'
        '    keep g as growable list of whole number with no value\n'
        '    add 4 to g\n'
        '    add 5 to g\n'
        '    keep a as whole number with value 0\n'
        '    put the count of g into a\n'
        '    return a\n'
        'end action\n\n'
        'program main\n'
        '    keep out_v as whole number with value 0\n'
        '    call build_list giving out_v\n'
        '    print the text "r=" and out_v\n'
        'end program\n'
    )
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        out_bin = os.path.join(tmp, f"il_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin],
            capture_output=True, text=True, timeout=200, cwd=HERE)
        if r.returncode != 0:
            combined = r.stdout + r.stderr
            hint = (" -- the glist runtime header is not being included for a "
                    "list declared inside an ACTION"
                    if "dictum_glist_t" in combined else "")
            return False, f"[{backend}] build failed{hint}: {combined[-300:]}"
        run = _run(out_bin, timeout=20)
        if "r=2" not in run.stdout:
            return False, f"[{backend}] unexpected output: {run.stdout!r}"
    return True, "ok -- collections work inside actions on all backends"


@regression("R92 a MODULE-ONLY file must get the same runtime #includes as "
            "a program file. A module-only translation unit has NO Program "
            "node, so the Program branch's include logic never ran for it; "
            "the Module branch checked only _has_produce_failure. A module "
            "using `attempt` therefore emitted dictum_error_clear() with no "
            "header: \"implicit declaration of function "
            "'dictum_error_clear'\". Found by tools/edges.py placing an "
            "ordinary feature (attempt) in the in_module CONTEXT -- the "
            "feature works fine in a program, and only the context differs")
def test_r92_module_only_runtime_includes(tmp):
    work = os.path.join(tmp, "modatt")
    os.makedirs(work)
    open(os.path.join(work, "helper.dict"), "w").write(
        'module helper\n'
        '    action risky takes nothing produces whole number\n'
        '        keep a as whole number with value 0\n'
        '        attempt\n'
        '            put 42 into a\n'
        '        on success\n'
        '            put a into a\n'
        '        on failure\n'
        '            put 0 into a\n'
        '        end attempt\n'
        '        return a\n'
        '    end action\n'
        'end module\n')
    open(os.path.join(work, "main.dict"), "w").write(
        'program main\n'
        '    use helper\n'
        '    keep v as whole number with value 0\n'
        '    call helper.risky giving v\n'
        '    print the text "r=" and v\n'
        'end program\n')

    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        mani = os.path.join(work, "dictum.project.json")
        if os.path.exists(mani):
            os.remove(mani)
        out_dir = os.path.join(work, f"b_{backend}")
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, work, "--backend", backend, "--out", out_dir],
            capture_output=True, text=True, timeout=200, cwd=HERE)
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {r.stdout}\n{r.stderr}"
        if backend == "nim":
            rb = subprocess.run(["sh", os.path.join(out_dir, "build.sh")],
                                 capture_output=True, text=True, timeout=420, cwd=out_dir)
        else:
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                 timeout=200, cwd=out_dir)
        if rb.returncode != 0:
            combined = rb.stdout + rb.stderr
            hint = (" -- a module-only file is missing its runtime #includes"
                    if "implicit declaration" in combined else "")
            return False, f"[{backend}] compile failed{hint}: {combined[-300:]}"
        run = _run(os.path.join(out_dir, "main"), timeout=20)
        if "r=42" not in run.stdout:
            return False, f"[{backend}] unexpected output: {run.stdout!r}"
    return True, "ok -- attempt inside a module works on all backends"


@regression("R93 `attempt` must ASSIGN to a pre-declared result variable, "
            "not shadow it. C++ emitted `auto v = ...` INSIDE THE TRY "
            "SCOPE, declaring a new local that shadowed the outer v -- so "
            "every read after the attempt saw the stale value. The program "
            "COMPILED CLEANLY and silently produced a wrong answer. Nim had "
            "the same bug but reported it loudly as 'redefinition of v' "
            "(R93's sibling, R89); C++ shadowing is strictly worse because "
            "nothing complains. This test asserts the VALUE and that all "
            "backends AGREE, which is the only way to catch it")
def test_r93_attempt_result_not_shadowed(tmp):
    if not os.path.exists("/usr/include/sqlite3.h"):
        return None, "SKIP: libsqlite3-dev not available"
    src = os.path.join(tmp, "att2.dict")
    open(src, "w").write(
        'import from C the action sqlite3_libversion_number takes nothing '
        'produces whole number as sqlite_ver\n\n'
        'program main\n'
        '    keep v as whole number with value 0\n'
        '    attempt\n'
        '        call sqlite_ver giving v\n'
        '    on success\n'
        '        print the text "ok=1"\n'
        '    on failure\n'
        '        print the text "ok=0"\n'
        '    end attempt\n'
        '    keep modern as whole number with value 0\n'
        '    if v is greater than 3000000 then\n'
        '        put 1 into modern\n'
        '    end if\n'
        '    print the text "modern=" and modern\n'
        'end program\n')

    outputs = {}
    for backend in ("c", "cpp", "nim"):
        if backend == "nim" and shutil.which("nim") is None:
            continue
        out_bin = os.path.join(tmp, f"at2_{backend}")
        r = subprocess.run(
            [sys.executable, CLI, src, "--backend", backend, "--compile",
             "--output", out_bin, "--link", "sqlite3"],
            capture_output=True, text=True, timeout=200, cwd=HERE)
        if r.returncode != 0:
            return False, f"[{backend}] build failed: {(r.stdout+r.stderr)[-300:]}"
        run = _run(out_bin, timeout=20)
        outputs[backend] = "".join(run.stdout.split())

    for b, got in outputs.items():
        if "modern=1" not in got:
            return False, (f"[{b}] got {got!r} -- the attempt's result variable "
                            f"is being SHADOWED rather than assigned, so the "
                            f"outer variable kept its stale value")
    if len(set(outputs.values())) > 1:
        return False, f"backends DISAGREE: {outputs}"
    return True, "ok -- attempt result assigns to the outer variable on all backends"


@regression("R94 backend-independent type semantics live in ONE shared "
            "table (dictumc/type_semantics.py), not duplicated per emitter. "
            "emit_c and emit_cpp each had their own printf-format decision "
            "-- only ~35%% textually similar, yet BOTH contained the same "
            "bug: a known integer fell through to a heuristic that guessed "
            "from the VARIABLE NAME, so `keep price as whole number` "
            "printed 'price=0.000000'. Textual similarity does not predict "
            "drift; SEMANTIC duplication does. This test asserts the shared "
            "table is authoritative, so a fix lands on every backend at "
            "once rather than needing to be remembered three times")
def test_r94_shared_type_semantics(tmp):
    sys.path.insert(0, HERE)
    from dictumc import type_semantics as ts

    # Documented synonyms must compare equal -- comparing them as raw
    # strings was a real bug (it rejected `add 1.5 to <list of decimal
    # number>` because the literal inferred as 'fractional number').
    if not ts.same_type("decimal number", "fractional number"):
        return False, "documented synonyms do not compare equal"
    if ts.same_type("whole number", "decimal number"):
        return False, "distinct types compare equal"

    # A KNOWN type must yield a definite spec; an UNKNOWN one must return
    # None rather than guessing -- returning a guess here is what let the
    # name heuristic override a declared type.
    for t, want in (("whole number", "%d"), ("decimal number", "%f"),
                    ("text", "%s"), ("truth value", "%d"),
                    ("int32_t", "%d"), ("double", "%f"), ("dictum_text", "%s")):
        got = ts.printf_spec(t)
        if got != want:
            return False, f"printf_spec({t!r}) = {got!r}, expected {want!r}"
    if ts.printf_spec("some_unknown_struct_t") is not None:
        return False, ("an UNKNOWN type must return None rather than a guess -- "
                        "guessing here is what allowed a name heuristic to "
                        "override a declared type")

    # And the emitters must actually CONSULT it.
    for mod in ("emit_c.py", "emit_cpp.py"):
        src = open(os.path.join(HERE, "dictumc", mod)).read()
        if "type_semantics" not in src:
            return False, (f"{mod} does not consult the shared type table -- "
                            f"it has drifted back to its own copy")
    return True, "ok -- one shared table, consulted by both C-family emitters"


@regression("R95 the C and C++ emitters must AGREE on the inferred kind of "
            "the same expression. Both implemented _infer_type_from_expr "
            "separately while performing identical inference -- only the "
            "SPELLING differed (dictum_text vs const char*). Inference is "
            "not cosmetic: the inferred type drives the printf conversion, "
            "the declaration and any cast, so a divergence shows up as a "
            "WRONG ANSWER rather than a compile error. This compares the "
            "two emitters directly on the same AST, which is the only way "
            "to catch divergence that both sides compile happily")
def test_r95_emitters_agree_on_inference(tmp):
    sys.path.insert(0, HERE)
    from dictumc.emit_c import CEmitter
    from dictumc.emit_cpp import CppEmitter
    from dictumc import type_semantics as ts
    from dictumc.ast_nodes import BinaryOp, Literal, UnaryOp

    ec, ecpp = CEmitter(), CppEmitter()
    # Spelling differs by design; compare the KIND each spelling denotes.
    cases = [
        ("int literal",      Literal(value=7)),
        ("float literal",    Literal(value=1.5)),
        ("bool literal",     Literal(value=True)),
        ("text literal",     Literal(value="s")),
        ("comparison >",     BinaryOp(op=">", left=Literal(value=3),
                                      right=Literal(value=1))),
        ("comparison <=",    BinaryOp(op="<=", left=Literal(value=3),
                                      right=Literal(value=1))),
        ("comparison !=",    BinaryOp(op="!=", left=Literal(value=3),
                                      right=Literal(value=1))),
        ("arithmetic +",     BinaryOp(op="+", left=Literal(value=3),
                                      right=Literal(value=1))),
        ("float arithmetic", BinaryOp(op="+", left=Literal(value=1.5),
                                      right=Literal(value=2.5))),
    ]
    for label, node in cases:
        kc = ts.kind_of(ec._infer_type_from_expr(node))
        kp = ts.kind_of(ecpp._infer_type_from_expr(node))
        if kc != kp:
            return False, (f"[{label}] emitters DISAGREE on inferred kind: "
                            f"c={kc!r} cpp={kp!r} -- the shared inference in "
                            f"type_semantics.py has been bypassed by one of them")
        if kc == ts.UNKNOWN:
            return False, f"[{label}] inferred UNKNOWN on both -- inference regressed"

    # A comparison must yield boolean, not the operand kind. Getting this
    # wrong would type a condition as an integer.
    cmp_node = BinaryOp(op=">", left=Literal(value=3), right=Literal(value=1))
    if ts.kind_of(ec._infer_type_from_expr(cmp_node)) != ts.BOOLEAN:
        return False, "a comparison did not infer as boolean"
    return True, f"ok -- both emitters agree on all {len(cases)} expression kinds"


if __name__ == "__main__":
    sys.exit(main())

