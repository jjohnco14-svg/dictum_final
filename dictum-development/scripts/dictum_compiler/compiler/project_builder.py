#!/usr/bin/env python3
"""
Dictum Project Builder — builds an entire multi-file .dict project to C/C++.

Given a workspace directory (or a dictum.project.json manifest), it:
  1. Discovers all .dict files
  2. Topologically sorts them (modules before programs that use them)
  3. Transpiles each file
  4. Generates .h stub headers for every module so cross-file #includes resolve
  5. Writes all .c/.cpp files, headers, and a unified Makefile
  6. Reports any errors with file + line context

Usage:
  python3 project_builder.py <workspace_dir> [--backend c|cpp] [--out <build_dir>]
"""

from __future__ import annotations
import os, sys, re, json, argparse, shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

# Same proven pattern as dictumc_cli.py (which works correctly standalone):
# insert the extension root — the parent of compiler/ — onto sys.path, then
# import dictumc.transpiler as a genuine absolute package import. dictumc/ has
# an __init__.py, so its own internal relative imports (e.g. transpiler.py's
# `from .lexer import ...`) resolve correctly once dictumc is imported as a
# package this way.
#
# The previous attempt added compiler/ itself to sys.path and fell back to
# the root-level compiler/transpiler.py on ImportError — but that file has
# the identical internal `from .lexer import ...` relative import, which
# fails the same way when transpiler.py is loaded as a bare top-level module
# rather than as part of a package. The fallback target was broken in the
# same way as the thing it was falling back from.
_EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _EXT_ROOT not in sys.path:
    sys.path.insert(0, _EXT_ROOT)

try:
    # Preferred: relative import, works when project_builder.py is itself
    # imported as part of the dictumc package (e.g. `from dictumc import
    # project_builder`, which is how compiler/dictumc/project_builder.py
    # would be reached if/when it's added there).
    from .transpiler import Transpiler, StdlibTranspiler
    from .validator import ValidationError, Validator
except ImportError:
    # Standalone script execution (`python3 project_builder.py ...`, which is
    # how the VS Code extension's buildProject command actually invokes this
    # file). dictumc has an __init__.py, so this resolves correctly.
    from dictumc.transpiler import Transpiler, StdlibTranspiler
    from dictumc.validator import ValidationError, Validator


# ── Type mapping: Dictum → C ───────────────────────────────────────────────────
DICTUM_TYPE_TO_C = {
    'whole number':    'int32_t',
    'decimal number':  'double',
    'text':            'const char*',
    'truth value':     'bool',
    'count':           'size_t',
    'bytes':           'uint8_t*',
    'nothing':         'void',
}

def dictum_type_to_c(dt: str) -> str:
    return DICTUM_TYPE_TO_C.get(dt.strip(), 'int32_t')


# ── Parse a .dict file for dependency info (fast, no full parse) ───────────────
def parse_deps(source: str, filepath: str) -> Dict:
    """
    Lightweight parser: extracts module/program names and their `use` dependencies.
    Returns { 'modules': [...], 'programs': [...], 'uses': [...], 'shapes': [...], 'actions': [...] }
    """
    modules, programs, uses, shapes, actions = [], [], [], [], []
    for line in source.splitlines():
        m = re.match(r'^\s*module\s+(\w+)\b', line)
        if m: modules.append(m.group(1))
        m = re.match(r'^\s*program\s+(\w+)\b', line)
        if m: programs.append(m.group(1))
        m = re.match(r'^\s*use\s+(\w+)', line)
        if m: uses.append(m.group(1))
        m = re.match(r'^\s*shape\s+(\w+)\s+holds\b', line)
        if m: shapes.append(m.group(1))
        m = re.match(r'^\s*action\s+(\w+)\s+(?:takes|produces)', line)
        if m: actions.append(m.group(1))
    return {'modules': modules, 'programs': programs, 'uses': uses,
            'shapes': shapes, 'actions': actions, 'file': filepath}


# ── Generate a .h header from transpiled C source ─────────────────────────────
def extract_extern_declarations(c_source: str) -> List[str]:
    """Pull real `extern <ret> <name>(<params>);` declarations and their
    `static inline` alias wrappers out of a file's generated C source.
    Shared by generate_header() (per-module headers) and the project-wide
    dictum_types.h aggregation below -- same real regex logic, one place,
    used for both a `module`-declared file and a plain top-level file
    (see the GAP-EXTERN-SHARE fix in build_project for why the latter
    needed this too)."""
    lines: List[str] = []
    seen_symbols: set = set()

    def _symbol_name(line: str) -> Optional[str]:
        m = re.search(r'(\w+)\s*\(', line)
        return m.group(1) if m else None

    def _guarded(line: str) -> str:
        sym = _symbol_name(line)
        if not sym or sym in seen_symbols:
            return line if sym is None else ''
        seen_symbols.add(sym)
        guard = f'DICTUM_FFI_SYM_{sym.upper()}_DEFINED'
        return f'#ifndef {guard}\n#define {guard}\n{line}\n#endif'

    extern_pattern = re.compile(r'^extern\s+[^\n{]+;\s*$', re.MULTILINE)
    for m in extern_pattern.finditer(c_source):
        line = m.group(0).strip()
        if line not in lines:
            g = _guarded(line)
            if g:
                lines.append(g)
    wrapper_pattern = re.compile(r'^static inline\s+[^\n]+\{[^\n]*\}\s*$', re.MULTILINE)
    for m in wrapper_pattern.finditer(c_source):
        line = m.group(0).strip()
        if line not in lines:
            g = _guarded(line)
            if g:
                lines.append(g)
    return lines


def generate_header(module_name: str, c_source: str, dict_source: str) -> str:
    """
    Extract function declarations from transpiled C, generate a proper header.
    Includes dictum_types.h so cross-module shape references resolve.
    """
    guard = f"DICTUM_{module_name.upper()}_H"
    lines = [
        f"/* Auto-generated by dictumc project builder */",
        f"/* Module: {module_name} */",
        f"#ifndef {guard}",
        f"#define {guard}",
        f"",
        f"#include <stdint.h>",
        f"#include <stdbool.h>",
        f"#include <stdlib.h>",
        f'#include "dictum_types.h"',   # brings in all cross-project shapes
        f"",
    ]

    # Extract struct definitions (shapes)
    struct_blocks = re.findall(r'(typedef\s+struct\s+\w+\s*\{[^}]+\}\s*\w+\s*;)', c_source, re.DOTALL)
    for sb in struct_blocks:
        lines.append(sb.strip())
        lines.append("")

    # Extract function declarations (strip body, add semicolon)
    # Pattern: returntype funcname(params) {
    #
    # The return-type alternation must include Dictum's own typedefs, not
    # just raw C ones. `dictum_text` was missing, so any module action
    # returning `text` was silently dropped from this header -- callers in
    # other files saw no declaration at all, which C treats as an implicit
    # int-returning function: a real compile failure under -Werror, and a
    # silent pointer/int type confusion without it. Confirmed with a real
    # 3-module program where `version_number` (int32_t) was declared
    # correctly while `version_text` (dictum_text) beside it vanished.
    # `dictum_\w+` covers the other runtime typedefs (dictum_glist_t and
    # friends) for the same reason.
    fn_pattern = re.compile(
        r'^((?:int32_t|double|bool|void|const char\*|size_t|uint8_t\*|uint64_t'
        r'|int64_t|dictum_text|dictum_\w+\*?)\s+'
        r'\w+\s*\([^)]*\))\s*\{',
        re.MULTILINE
    )
    for m in fn_pattern.finditer(c_source):
        lines.append(f"{m.group(1)};")

    # FFI-IMPORT FIX: `import from C the action X ... as Y` (ImportC) emits
    # its own already-correct declarations directly into the .c file --
    # `extern <ret> <real_c_name>(<params>);`, plus, when the Dictum-side
    # alias differs from the real C symbol, a `static inline` wrapper under
    # the alias -- but neither form was ever picked up here, since both are
    # a single already-terminated statement (ending in `;`), not a function
    # *definition* with a `{ ... }` body the way `fn_pattern` above expects.
    # A file that only `use`s a module consisting purely of FFI imports
    # (e.g. io_file.dict, which has no genuine `action` blocks at all) got a
    # completely EMPTY header for it, so every caller in another file had no
    # prototype in scope at all -- gcc's implicit-int fallback then
    # (silently, with only a warning) truncated any non-int return value,
    # e.g. gcode_fopen's `void*` FILE* handle to 32 bits.
    for line in extract_extern_declarations(c_source):
        if line not in lines:
            lines.append(line)

    lines += ["", f"#endif /* {guard} */", ""]
    return "\n".join(lines)


# ── Topological sort ──────────────────────────────────────────────────────────
def topo_sort(file_info: List[Dict]) -> List[Dict]:
    """Sort files so modules come before programs that use them."""
    # Build module-name → file index
    mod_to_idx: Dict[str, int] = {}
    for i, fi in enumerate(file_info):
        for m in fi['modules']:
            mod_to_idx[m] = i

    # Build adjacency (file uses file)
    n = len(file_info)
    adj: List[Set[int]] = [set() for _ in range(n)]
    for i, fi in enumerate(file_info):
        for used in fi['uses']:
            if used in mod_to_idx:
                adj[i].add(mod_to_idx[used])  # i depends on mod_to_idx[used]

    # Kahn's algorithm
    in_degree = [0] * n
    for i in range(n):
        for j in adj[i]:
            in_degree[j] += 0  # adj[i] = dependencies of i, not reverse
    # Build reverse: who depends on me
    rev: List[Set[int]] = [set() for _ in range(n)]
    for i in range(n):
        for dep in adj[i]:
            rev[dep].add(i)

    in_deg = [len(adj[i]) for i in range(n)]
    queue = [i for i in range(n) if in_deg[i] == 0]
    order = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for dependent in rev[node]:
            in_deg[dependent] -= 1
            if in_deg[dependent] == 0:
                queue.append(dependent)

    if len(order) != n:
        # Cycle detected — just return original order
        return file_info
    return [file_info[i] for i in order]


# ── Generate unified Makefile ─────────────────────────────────────────────────

def _guard_shape_typedefs(src: str) -> str:
    """Wrap each `typedef struct {...} Name;` in a per-shape #ifndef guard.

    A shape declared in one .dict file is emitted BOTH into that file's own
    generated C AND into the project-wide dictum_types.h aggregate. The
    defining file doesn't include dictum_types.h directly, but it arrives
    transitively through any module header it uses -- so the typedef lands
    twice in one translation unit and gcc rejects it with "conflicting
    types for 'S3'". Same problem, and same solution, as the per-symbol FFI
    guards already used here: guard by name so however many paths deliver
    the definition, only the first one takes effect.
    """
    def _wrap(m):
        block = m.group(0)
        nm = re.search(r'\}\s*(\w+)\s*;', block)
        if not nm:
            return block
        g = f'DICTUM_SHAPE_{nm.group(1).upper()}_DEFINED'
        return f'#ifndef {g}\n#define {g}\n{block}\n#endif'
    return re.sub(r'typedef\s+struct\s*\w*\s*\{[^}]+\}\s*\w+\s*;',
                  _wrap, src, flags=re.DOTALL)


_RUNTIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runtime')


def generate_makefile(
    file_info: List[Dict],
    c_files: List[str],
    build_dir: str,
    backend: str,
    cpp_standard: int,
    ldflags: Optional[Set[str]] = None,
    static: bool = False,
) -> str:
    programs = []
    for fi in file_info:
        programs.extend(fi['programs'])

    ext = '.c' if backend == 'c' else '.cpp'
    compiler = 'gcc' if backend == 'c' else 'g++'
    std_flag = '' if backend == 'c' else f'-std=c++{cpp_standard} '
    asan_flag = '-fsanitize=address -fno-omit-frame-pointer '

    obj_list = ' '.join(
        os.path.splitext(os.path.basename(f))[0] + '.o'
        for f in c_files
    )
    prog_name = programs[0].lower() if programs else 'dictum_out'

    # FIX (link-flag plumbing bug): this used to hardcode "-lm" no matter
    # what any file in the project used, so any project touching
    # Mutex/Thread/Semaphore (-lpthread), Tls (-lssl -lcrypto), Shm/Timer
    # (-lrt), or a blessed library's #[link "x"] directive would compile
    # every file successfully and then fail at the final link step with
    # undefined references. `ldflags` is aggregated across every file's
    # real get_ldflags() result by the caller.
    ldflags_sorted = sorted(ldflags) if ldflags else ['-lm']
    # Keep -lm first for readability/stability, rest alphabetical.
    if '-lm' in ldflags_sorted:
        ldflags_sorted.remove('-lm')
        ldflags_sorted.insert(0, '-lm')
    ldflags_str = ' '.join(ldflags_sorted)
    if static:
        static_flags = ['-static', '-static-libgcc']
        if backend != 'c':
            static_flags.append('-static-libstdc++')
        # Prepended, not appended: -static must come before the libraries
        # it's meant to affect on some linkers/ld versions -- putting it
        # first is the safe order regardless of toolchain.
        ldflags_str = ' '.join(static_flags) + ' ' + ldflags_str

    lines = [
        f"# Auto-generated by dictumc project builder",
        f"# Rebuild with: make",
        f"",
        f"CC       = {compiler}",
        # -I <runtime dir> is REQUIRED, not optional: any program using a
        # runtime-header stdlib feature (growable list, map, set, JSON,
        # text, ...) #includes e.g. dictum_glist.h, which lives in the
        # compiler's runtime/ directory and is NOT copied into the build
        # dir. Without it a multi-file build dies with "dictum_glist.h: No
        # such file or directory". The single-file CLI path was given this
        # same fix earlier (see R60); the multi-file Makefile never got it,
        # so the gap survived until a generated multi-module program that
        # used a growable list finally exercised it.
        f"CFLAGS   = {std_flag}-Wall -Wextra -Werror -O2 -I. -I{_RUNTIME_DIR}",
        f"CFLAGS_D = {std_flag}{asan_flag}-Wall -Wextra -O1 -g -I. -I{_RUNTIME_DIR}  # debug+asan (warnings-only, not -Werror, so a debugging session isn't blocked by a style warning while chasing a real ASan finding)",
        f"LDFLAGS  = {ldflags_str}",
        f"SRCS     = {' '.join(os.path.basename(f) for f in c_files)}",
        f"OBJS     = {obj_list}",
        f"TARGET   = {prog_name}",
        f"",
        f"all: $(TARGET)",
        f"",
        f"$(TARGET): $(OBJS)",
        f"\t$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)",
        f"",
        f"%.o: %{ext}",
        f"\t$(CC) $(CFLAGS) -c -o $@ $<",
        f"",
        f"debug: $(SRCS)",
        f"\t$(CC) $(CFLAGS_D) -o $(TARGET)_debug $^ $(LDFLAGS)",
        f"",
        f"clean:",
        f"\trm -f $(OBJS) $(TARGET) $(TARGET)_debug",
        f"",
        f".PHONY: all debug clean",
    ]
    return "\n".join(lines)


# ── Project manifest ──────────────────────────────────────────────────────────
def load_or_create_manifest(workspace: str) -> Dict:
    manifest_path = os.path.join(workspace, 'dictum.project.json')
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            return json.load(f)
    # Auto-discover. BUGFIX (silent --backend/--cpp-standard override):
    # this used to hardcode 'backend': 'c' and 'cpp_standard': 17 here, so
    # build_project()'s `manifest.get('backend', backend)` always found a
    # value from THIS dict and never fell through to the backend/
    # cpp_standard arguments build_project() was actually called with —
    # meaning `project_builder.py <dir> --backend cpp` silently built as C
    # anyway, with no error or warning, on any workspace that didn't
    # already have a saved dictum.project.json. Deliberately omitting
    # these two keys here lets manifest.get(key, <caller's real argument>)
    # work as its call site clearly intends: an explicit on-disk
    # dictum.project.json still wins (unchanged), but a fresh workspace
    # now genuinely respects the caller's backend/cpp_standard instead of
    # always reverting to the auto-discover default.
    return {
        'name': os.path.basename(workspace),
        'version': '0.1.0',
        'entry': None,  # None = auto-detect program files
        'exclude': ['build/', '.git/', 'node_modules/'],
    }


def write_manifest(workspace: str, manifest: Dict):
    path = os.path.join(workspace, 'dictum.project.json')
    with open(path, 'w') as f:
        json.dump(manifest, f, indent=2)
    return path


# ── Main build function ───────────────────────────────────────────────────────
def build_project(
    workspace: str,
    backend: Optional[str] = None,
    cpp_standard: int = 17,
    out_dir: Optional[str] = None,
    verbose: bool = False,
    static: bool = False,
) -> Dict:
    """
    Build all .dict files in workspace to C/C++.
    `backend`: explicit choice always wins over a stored manifest value;
    None falls back to the manifest's own 'backend' field, then to 'c'.
    Returns {'success': bool, 'files': [...], 'errors': [...], 'warnings': [...]}
    """
    workspace = os.path.abspath(workspace)
    manifest  = load_or_create_manifest(workspace)
    backend   = backend if backend is not None else manifest.get('backend', 'c')
    cpp_std   = manifest.get('cpp_standard', cpp_standard)
    build_dir = out_dir or os.path.join(workspace, 'build')
    os.makedirs(build_dir, exist_ok=True)

    exclude = manifest.get('exclude', [])
    ext_out = {'c': '.c', 'cpp': '.cpp', 'nim': '.nim'}[backend]

    # ── 1. Discover all .dict files ───────────────────────────────────────
    dict_files = []
    for root, dirs, files in os.walk(workspace):
        # Prune excluded dirs
        dirs[:] = [d for d in dirs if not any(
            os.path.join(root, d).startswith(os.path.join(workspace, ex.rstrip('/')))
            for ex in exclude
        )]
        for fname in files:
            if fname.endswith('.dict'):
                dict_files.append(os.path.join(root, fname))

    if not dict_files:
        return {'success': False, 'errors': [f'No .dict files found in {workspace}'], 'files': [], 'warnings': []}

    # ── 2. Parse dependencies ─────────────────────────────────────────────
    file_info = []
    for fp in dict_files:
        with open(fp, encoding='utf-8') as f:
            src = f.read()
        info = parse_deps(src, fp)
        info['source'] = src
        file_info.append(info)

    # ── 3. Topological sort ───────────────────────────────────────────────
    sorted_info = topo_sort(file_info)

    # ── 4. Pre-pass: collect all shape structs into a shared types header,
    #      AND build a project-wide shapes/actions registry.
    #
    #      CROSS-FILE `use` FIX: `use ModuleName` is the documented,
    #      sanctioned way (docs §15) to pull a sibling file's shapes/
    #      actions into scope, but each file used to be validated by its
    #      own brand-new Validator instance, which only ever learns about
    #      shapes/actions declared in the AST it's handed -- i.e. only ITS
    #      OWN top-level declarations. A file that did exactly what the
    #      docs say (`use core_types`, then `keep v as Vector3 with no
    #      value` for a Vector3 shape defined in core_types.dict) failed
    #      validation with "Unknown type 'Vector3'", followed by a cascade
    #      of "Assignment/Use of undeclared variable" errors for every
    #      later use of that variable -- even though the .dict source was
    #      correct per the language reference. Parsing every file once here
    #      (no validation yet) and collecting its shapes/actions into a
    #      project-wide registry lets step 4b below forward that registry
    #      into each file's own validation pass.
    import re as _re
    try:
        from .ast_nodes import Module as _Module, Action as _Action, ImportC as _ImportC, ImportCpp as _ImportCpp
    except ImportError:
        from dictumc.ast_nodes import Module as _Module, Action as _Action, ImportC as _ImportC, ImportCpp as _ImportCpp
    all_shapes_code: List[str] = []
    all_externs_code: List[str] = []
    shape_header_path = os.path.join(build_dir, 'dictum_types.h')
    project_shapes: Dict[str, object] = {}
    project_actions: Dict[str, object] = {}
    # BUGFIX (call...giving type inference, cross-file): a project-wide
    # registry of every callable's real declared Dictum return type --
    # native `action`s AND `import from C`/`import from C++` functions --
    # so a file that only CALLS a function declared in a SIBLING file
    # (e.g. main.dict calling into mathlib.dict's `import from C ...
    # Combine ... produces fractional number`) infers the auto-declared
    # `call ... giving VAR` target's type correctly instead of falling
    # back to int32_t. Each file's own StdlibTranspiler/CEmitter instance
    # only ever sees ITS OWN file's declarations (see the GAP-EXTERN-SHARE
    # fix above for the same cross-file-instance-isolation problem with
    # extern prototypes) -- this is threaded into each file's real
    # emission the same way project_shapes/project_actions already are.
    project_import_return_types: Dict[str, str] = {}
    # EMITTER CROSS-FILE FIX: `emitter.local_modules` and `emitter.
    # _module_actions` (used by `_resolve_call_name` in emit_c.py/emit_cpp.py
    # to decide whether an unqualified call like `emit_header(...)` must be
    # mangled to its defining module's prefixed C name, e.g.
    # `gcode_emitter_emit_header`) were ALSO only ever populated from the
    # current file's own AST (`{n.name for n in ast if isinstance(n, Module)}`
    # in transpiler.py). A file that only `use`s a module defined in a
    # SIBLING file (never defines that module itself) has no way to know the
    # module exists, so `use gcode_emitter` + a bare `call emit_header with
    # ...` resolved to the unmangled name at the call site -- while the
    # actual function DEFINITION in gcode_emitter.dict's own file got the
    # module-prefixed name. Result: it compiled clean (see the shape/action
    # validator fixes above) but failed to LINK -- "undefined reference to
    # `emit_header`" etc. -- because the two files' name-mangling decisions
    # disagreed. Same root cause as the two validator-level fixes above, one
    # layer further down the pipeline (found by actually invoking gcc/ld, not
    # by re-reading the transpiler).
    project_modules: set = set()
    project_module_actions: Dict[str, set] = {}

    for fi in sorted_info:
        try:
            t_pre = StdlibTranspiler(source=fi['source'], backend=backend, cpp_standard=cpp_std,
                                      source_path=fi.get('file', ''))
            r_pre = t_pre.run(validate=False)
        except Exception:
            # A file that can't even parse will fail loudly on its own in
            # step 4b below with a real, attributable error -- don't let a
            # broken sibling file silently poison the registry pre-pass.
            continue

        _collector = Validator(cpp_mode=(backend == 'cpp'))
        try:
            _collector.collect_globals(r_pre['ast'])
            project_shapes.update(_collector.shapes)
            project_actions.update(_collector.actions)
        except Exception:
            pass

        try:
            for _n in r_pre['ast']:
                if isinstance(_n, _Module):
                    project_modules.add(_n.name)
                    project_module_actions.setdefault(_n.name, set()).update(
                        s.name for s in _n.body if isinstance(s, _Action))
        except Exception:
            pass

        # BUGFIX (call...giving type inference, cross-file): collect
        # this file's own Action/ImportC/ImportCpp return types into the
        # project-wide registry. Top-level only (matches how ImportC/
        # ImportCpp are actually declared in every real .dict file this
        # project ships -- e.g. blessed/raylib.dict's bindings are all
        # top-level, not nested in a module).
        try:
            for _n in r_pre['ast']:
                if isinstance(_n, _Action):
                    project_import_return_types[_n.name] = _n.ret_type
                elif isinstance(_n, _ImportC):
                    project_import_return_types[_n.action_name] = _n.ret_type
                    if _n.alias:
                        project_import_return_types[_n.alias] = _n.ret_type
                elif isinstance(_n, _ImportCpp) and getattr(_n, 'item_type', None) == 'action':
                    project_import_return_types[_n.alias] = _n.ret_type
        except Exception:
            pass

        if fi['shapes']:
            # Match: typedef struct { ... } Name;
            structs = _re.findall(

                r'typedef struct\s*\{[^}]+\}\s*\w+\s*;',
                r_pre['code'], _re.DOTALL
            )
            all_shapes_code.extend(structs)

        # GAP-EXTERN-SHARE fix: `generate_header()` only ever ran for
        # files that declare `module X` -- a plain top-level file with
        # nothing but `import from C`/`import from C++` declarations
        # (e.g. a blessed-library bridge like raylib.dict, copied into a
        # project as-is, no `module` wrapper) got NO shared header at
        # all, so a sibling file calling its functions had no prototype
        # in scope. gcc's implicit-int fallback (silent, warning-only)
        # then mis-classified any float/struct-by-value argument into
        # the wrong register per the real x86-64 SysV ABI -- confirmed
        # by an actual test: `DrawCircle(x, y, 60.0, color)` called
        # across a file boundary rendered nothing at the expected
        # position at all (screenshot-verified: center pixel was plain
        # background, not the circle's color), while the SAME function
        # called from within its own declaring file worked. Fixed by
        # aggregating every file's real externs project-wide into
        # dictum_types.h (already included unconditionally by any file
        # that doesn't define its own shapes), not just module-declared
        # files' own per-module headers.
        all_externs_code.extend(extract_extern_declarations(r_pre['code']))

    # Always write dictum_types.h — module headers include it unconditionally.
    # If no shapes exist it is just an empty guard header.
    _seen_externs = set()
    _deduped_externs = []
    for _line in all_externs_code:
        if _line not in _seen_externs:
            _seen_externs.add(_line)
            _deduped_externs.append(_line)
    type_hdr_lines = [
        '/* dictum_types.h — auto-generated shared type definitions */',
        '#ifndef DICTUM_TYPES_H', '#define DICTUM_TYPES_H',
        '#include <stdint.h>', '#include <stdbool.h>', '#include <stdlib.h>', '',
        '#ifndef DICTUM_TEXT_DEFINED', '#define DICTUM_TEXT_DEFINED',
        'typedef const char *dictum_text;', '#endif', '',
    ] + ([_guard_shape_typedefs(s.strip()) for s in all_shapes_code] if all_shapes_code else []) + [
        '', '#endif /* DICTUM_TYPES_H */',
    ]
    with open(shape_header_path, 'w', encoding='utf-8') as _fh:
        _fh.write('\n'.join(type_hdr_lines))
    # written_files.append(shape_header_path) — added below after list init

    # GAP-EXTERN-SHARE fix: a SEPARATE header for aggregated externs,
    # included unconditionally by every file (not gated behind "does
    # this file define its own shapes" the way dictum_types.h's shape
    # section is). Splitting these out matters because the two have
    # different duplication rules in C: a shape's `typedef struct {...}
    # Name;` genuinely conflicts if a file both defines Name itself AND
    # includes dictum_types.h's copy of it (hence that header's existing
    # conditional include) -- but an `extern` function declaration is
    # always safe to see more than once as long as it's consistent, so
    # gating it the same way as shapes was unnecessarily hiding real
    # prototypes from files that also happen to declare their own
    # shapes. This is the fix for the bug an actual raylib GUI test
    # caught: `DrawCircle`'s float radius argument silently corrupted
    # when called from a file (main.dict) that has no shapes of its own
    # calling into a file (raylib.dict) that does -- main.dict *did*
    # get dictum_types.h before, but a file with zero shapes AND zero
    # externs of its own still needs to see externs from elsewhere,
    # which the old single-header, shape-gated design couldn't express.
    externs_header_path = os.path.join(build_dir, 'dictum_externs.h')
    externs_hdr_lines = [
        '/* dictum_externs.h — auto-generated, project-wide extern declarations',
        ' * for every `import from C`/`import from C++` binding in this project,',
        ' * regardless of which file declared them or whether that file uses a',
        ' * `module` wrapper. Included (after dictum_types.h) by every file that',
        ' * does not define its own shapes, so a function declared in one file',
        ' * has a real, correct prototype visible when called from another --',
        ' * closes a real bug where a plain (non-module) file\'s declarations',
        ' * were invisible project-wide, silently corrupting float/struct-by-',
        ' * value arguments passed to them from another file (gcc\'s implicit-',
        ' * int fallback misclassifies the argument\'s real register class',
        ' * under the x86-64 SysV ABI).',
        ' *',
        ' * SCOPE, honestly: deliberately does NOT #include dictum_types.h',
        ' * itself, to avoid re-triggering a duplicate shape-typedef error for',
        ' * a file that defines its own shapes (that file already sees its own',
        ' * typedefs directly). This means a shape-DEFINING file calling an',
        ' * extern from ANOTHER file, whose signature references a shape it',
        ' * doesn\'t itself define, is not yet covered -- a narrower, real',
        ' * remaining gap, not silently papered over. */',
        '#ifndef DICTUM_EXTERNS_H', '#define DICTUM_EXTERNS_H',
        '#include <stdint.h>', '#include <stdbool.h>', '#include <stddef.h>', '',
        '#ifndef DICTUM_TEXT_DEFINED', '#define DICTUM_TEXT_DEFINED',
        'typedef const char *dictum_text;', '#endif', '',
    ] + _deduped_externs + ['', '#endif /* DICTUM_EXTERNS_H */']
    with open(externs_header_path, 'w', encoding='utf-8') as _fh:
        _fh.write('\n'.join(externs_hdr_lines))

    # ── 4b. Transpile each file ───────────────────────────────────────────────
    errors, warnings, written_files = [], [], []
    written_files.append(shape_header_path)  # always present
    written_files.append(externs_header_path)  # always present
    generated_headers: Dict[str, str] = {}  # module_name → header path
    all_ldflags: Set[str] = {'-lm'}  # aggregated across every file for the unified Makefile

    for fi in sorted_info:
        fp = fi['file']
        rel = os.path.relpath(fp, workspace)
        if verbose:
            print(f"  compiling {rel}...", file=sys.stderr)

        try:
            # FIX (Problem 0 gap): this was plain Transpiler, so a
            # multi-file project never got STDLIB_ACTION_FAMILIES
            # registration (extend_validator/extend_emitter) at all —
            # File/Json/Http/Net/Mutex/Math/etc. calls in a project build
            # would fail validation outright, a stricter failure mode than
            # the single-file CLI path (which supports `--stdlib`).
            t = StdlibTranspiler(
                source=fi['source'],
                backend=backend,
                cpp_standard=cpp_std,
                source_path=fi.get('file', ''),
            )
            # CROSS-FILE `use` FIX: forward the project-wide registry built
            # in step 4 above, so a shape/action declared in another file
            # this file `use`s is recognized instead of erroring "Unknown
            # type". See validator.py Validator.validate() for the merge
            # semantics (this file's own declarations still win on any
            # name collision).
            result = t.run(validate=True, extra_shapes=project_shapes, extra_actions=project_actions,
                            extra_local_modules=project_modules, extra_module_actions=project_module_actions,
                            extra_import_return_types=project_import_return_types)
        except (SyntaxError, ValidationError) as e:
            errors.append({'file': rel, 'message': str(e), 'line': 0})
            continue
        except Exception as e:
            errors.append({'file': rel, 'message': f'Internal error: {e}', 'line': 0})
            continue

        if result.get('warnings'):
            for w in result['warnings']:
                warnings.append({'file': rel, 'message': str(w)})

        # FIX (link-flag plumbing bug): collect this file's real ldflags
        # (from `use X` modules + #[link ...] directives) so the unified
        # project Makefile generated at the end can actually link — it
        # used to hardcode "-lm" regardless of what any file needed.
        all_ldflags.update(result.get('ldflags') or ['-lm'])

        c_code = result['code']

        # Guard this file's own raw extern/wrapper lines so they safely
        # coexist with the same symbol also arriving via an aggregated
        # header (dictum_externs.h, a module's own public header) that
        # this file might also include below. Confirmed necessary: a
        # real module (wrapping getpid()) got 'redefinition of
        # raw_getpid' when both its own directly-emitted copy and the
        # shared aggregator's copy landed in the same translation unit.
        # Scoped to project_builder.py's own text post-processing only --
        # NOT the shared emitters, which caused severe, unrelated
        # breakage (confirmed: broke single-file compilation entirely)
        # when this same guard was tried there instead.
        def _guard_own_ffi_lines(src: str) -> str:
            def _sym(line: str) -> Optional[str]:
                m = re.search(r'(\w+)\s*\(', line)
                return m.group(1) if m else None

            def _wrap(m: 're.Match') -> str:
                line = m.group(0)
                sym = _sym(line)
                if not sym:
                    return line
                guard = f'DICTUM_FFI_SYM_{sym.upper()}_DEFINED'
                return f'#ifndef {guard}\n#define {guard}\n{line}\n#endif'

            src = re.sub(r'^extern\s+[^\n{]+;\s*$', _wrap, src, flags=re.MULTILINE)
            src = re.sub(r'^static inline\s+[^\n]+\{[^\n]*\}\s*$', _wrap, src, flags=re.MULTILINE)
            return src

        # The C/C++ shared-header machinery below (dictum_types.h,
        # dictum_externs.h, per-symbol FFI guards, _DEFAULT_SOURCE ordering)
        # is entirely a C-family concern. Nim has a real module system:
        # each module file exports its `proc*`s and a consumer just writes
        # `import <module>`, resolved from the sibling .nim file. So for the
        # nim backend, write the emitted source straight out and skip all of
        # it -- applying C preprocessor logic to Nim source would be
        # meaningless at best and corrupting at worst.
        if backend == 'nim':
            base = os.path.splitext(os.path.basename(fp))[0]
            out_path = os.path.join(build_dir, base.lower() + ext_out)
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(c_code)
            written_files.append(out_path)
            continue

        c_code = _guard_own_ffi_lines(c_code)
        c_code = _guard_shape_typedefs(c_code)

        # Determine output filename
        base = os.path.splitext(os.path.basename(fp))[0]
        out_path = os.path.join(build_dir, base + ext_out)

        # Strip per-file stdlib includes — Makefile handles linking
        # Keep the code as-is for now (fully self-contained)
        # Include dictum_types.h in files that DON'T define their own shapes
        file_defines_shapes = len(fi['shapes']) > 0
        _prelude_includes = []
        if all_shapes_code and not file_defines_shapes:
            _prelude_includes.append('#include "dictum_types.h"')
        if _deduped_externs and not file_defines_shapes:
            # GAP-EXTERN-SHARE fix: a file with no shapes of its own
            # (like main.dict calling into raylib.dict) needs to see
            # every project-wide extern, not just its own file's.
            # MUST come after dictum_types.h -- confirmed by a real
            # build failure (a raylib DrawCircle test): prepending each
            # include separately put dictum_externs.h BEFORE
            # dictum_types.h (each prepend puts its own line first,
            # so the second prepend ends up ahead of the first), and
            # dictum_externs.h's declarations reference shape types
            # (Color, Camera3D, ...) that only dictum_types.h defines --
            # "unknown type name 'Color'" on every such extern.
            #
            # A file that ALSO declares its own `import from C` still
            # gets this header (a file may need externs for OTHER
            # modules' symbols too, not just its own -- confirmed by
            # R47's real raylib case). The duplicate-definition risk
            # this used to guard against (confirmed real: a module
            # wrapping getpid() got 'redefinition of raw_getpid' when
            # both its own per-file wrapper AND this shared header
            # defined it) is now handled correctly and more precisely
            # by extract_extern_declarations' own per-symbol #ifndef
            # guard, which only skips the exact duplicated symbol
            # rather than excluding the whole shared header.
            _prelude_includes.append('#include "dictum_externs.h"')
        if _prelude_includes:
            # Fix (preamble-ordering bug): the file's own generated code
            # always starts with `#define _DEFAULT_SOURCE` as its very
            # first line, deliberately before any #include, to preempt
            # glibc's own default value of that macro. Blindly prepending
            # the prelude includes before ALL of c_code pushed that define
            # to AFTER an include, which pulls in glibc's own definition
            # first -- confirmed with a real build failure ("_DEFAULT_SOURCE
            # redefined") the moment a module file got dictum_externs.h.
            # Insert the prelude right after that first line instead.
            lines = c_code.split('\n', 1)
            if lines and lines[0].strip() == '#define _DEFAULT_SOURCE' and len(lines) > 1:
                c_code = lines[0] + '\n' + '\n'.join(_prelude_includes) + '\n' + lines[1]
            else:
                c_code = '\n'.join(_prelude_includes) + '\n' + c_code

        # ── Module prefix: rename `action_name` → `ModuleName_action_name` ─
        # The compiler emits unqualified names; the program calls prefixed names.
        # We patch the module .c to match what the program emits.
        for mod_name in fi['modules']:
            for action_name in fi['actions']:
                # Replace function definitions: `int32_t action_name(` → `int32_t ModuleName_action_name(`
                # Use word-boundary to avoid partial replacements
                c_code = _re.sub(
                    r'(?<![A-Za-z0-9_])' + _re.escape(action_name) + r'\s*\(',
                    f'{mod_name}_{action_name}(',
                    c_code
                )

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(c_code)
        written_files.append(out_path)

        # ── 4c. Gap #7: write the real, AST-based public export header ────
        # StdlibTranspiler.run() (see transpiler.py) already computes a
        # type-correct header for every top-level `export shape`/`export
        # action`/`export`ed global via emitter.get_header_output(ast) --
        # populated into result['h_code'] (C backend) / result['hpp_code']
        # (C++ backend) -- but this project-level build path never read
        # either key back out, so a real multi-file project's exports
        # never reached disk: an external C/C++ consumer had no header to
        # #include against the compiled object at all, even though
        # dictum_types.h already carried the struct (shapes are always
        # aggregated there) with no matching action prototypes anywhere.
        # This does NOT replace the existing per-`module` header below
        # (§5) -- that one is for cross-file .dict-to-.dict linking and is
        # unrelated to the `export` keyword.
        export_code = result.get('h_code') or result.get('hpp_code')
        if export_code:
            exp_ext = '.h' if 'h_code' in result else '.hpp'
            exp_name = f"{base}_export{exp_ext}"
            exp_path = os.path.join(build_dir, exp_name)
            with open(exp_path, 'w', encoding='utf-8') as f:
                f.write(export_code)
            written_files.append(exp_path)
            if verbose:
                print(f"    → {exp_name} (public export header)", file=sys.stderr)

        # ── 5. Generate .h header for every module ────────────────────────
        for mod_name in fi['modules']:
            header_content = generate_header(mod_name, c_code, fi['source'])
            h_name = f"dictum_{mod_name.lower()}.h"
            h_path = os.path.join(build_dir, h_name)
            with open(h_path, 'w', encoding='utf-8') as f:
                f.write(header_content)
            generated_headers[mod_name] = h_path
            written_files.append(h_path)
            if verbose:
                print(f"    → {h_name}", file=sys.stderr)

    # ── 6. Provide dictum_core.h / dictum_error.h in the build dir ────────
    # These used to be written as EMPTY STUBS (just the include guard and
    # three system includes). Because the Makefile puts `-I.` before the
    # runtime include path, those stubs SHADOWED the real runtime headers
    # of the same name -- so any file that genuinely needed a declaration
    # from them (dictum_error_set, which dictum_glist.h and every other
    # collection header calls) failed with "implicit declaration of
    # function 'dictum_error_set'" under -Werror. Copy the REAL headers;
    # only fall back to a stub if no real one exists.
    for stub_name in ['dictum_core', 'dictum_error']:
        h_path = os.path.join(build_dir, stub_name + '.h')
        if os.path.exists(h_path):
            continue
        real_h = os.path.join(_RUNTIME_DIR, stub_name + '.h')
        if os.path.exists(real_h):
            shutil.copyfile(real_h, h_path)
        else:
            with open(h_path, 'w', encoding='utf-8') as f:
                f.write(f"/* {stub_name}.h — auto-generated stub */\n")
                f.write(f"#ifndef {stub_name.upper()}_H\n")
                f.write(f"#define {stub_name.upper()}_H\n")
                f.write(f"#include <stdint.h>\n#include <stdbool.h>\n#include <stdlib.h>\n")
                f.write(f"#endif\n")
        written_files.append(h_path)

    # ── 7. Write Makefile (or, for nim, a build script) ───────────────────
    c_files = [f for f in written_files if f.endswith(ext_out)]
    if backend == 'nim':
        # Nim resolves `import <module>` from sibling .nim files itself and
        # compiles the whole dependency graph from the entry file, so there
        # are no per-object rules to write. Emit a build script that invokes
        # nim on the program's own file. Link flags go through --passL,
        # matching dictumc_cli.py's single-file nim path.
        entry = None
        for fi_ in sorted_info:
            if fi_['programs']:
                entry = os.path.splitext(os.path.basename(fi_['file']))[0].lower()
                break
        if entry is None and c_files:
            entry = os.path.splitext(os.path.basename(c_files[-1]))[0]
        passl = ' '.join(f'--passL:{fl}' for fl in sorted(all_ldflags) if fl != '-lm')
        script = (
            '#!/bin/sh\n'
            '# Auto-generated by dictumc project builder (nim backend).\n'
            '# Nim compiles the whole import graph from the entry module,\n'
            '# so there is no per-object linking step to script here.\n'
            'set -e\n'
            f'nim c --opt:speed {passl} -o:{entry} {entry}.nim\n'
        )
        mf_path = os.path.join(build_dir, 'build.sh')
        with open(mf_path, 'w', encoding='utf-8') as f:
            f.write(script)
        os.chmod(mf_path, 0o755)
        written_files.append(mf_path)
    else:
        makefile = generate_makefile(sorted_info, c_files, build_dir, backend, cpp_std, all_ldflags, static=static)
        mf_path  = os.path.join(build_dir, 'Makefile')
        with open(mf_path, 'w', encoding='utf-8') as f:
            f.write(makefile)
        written_files.append(mf_path)

    # ── 8. Write/update manifest ──────────────────────────────────────────
    if not os.path.exists(os.path.join(workspace, 'dictum.project.json')):
        write_manifest(workspace, {
            **manifest,
            'backend': backend,
            'cpp_standard': cpp_std,
        })
        written_files.append(os.path.join(workspace, 'dictum.project.json'))

    n_modules  = sum(len(fi['modules'])  for fi in sorted_info)
    n_programs = sum(len(fi['programs']) for fi in sorted_info)

    return {
        'success': len(errors) == 0,
        'files': written_files,
        'errors': errors,
        'warnings': warnings,
        'stats': {
            'dict_files': len(dict_files),
            'modules': n_modules,
            'programs': n_programs,
            'c_files': len(c_files),
            'headers': len(generated_headers),
        }
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        prog='project_builder',
        description='Build a multi-file Dictum project to C/C++',
    )
    p.add_argument('workspace', help='Project directory (contains .dict files)')
    p.add_argument('--backend', choices=['c', 'cpp', 'nim'], default=None,
                    help='Explicit CLI choice always wins over a stored project '
                         'manifest value. If omitted, falls back to the manifest, '
                         'then to "c".')
    p.add_argument('--cpp-standard', type=int, choices=[17, 20, 23], default=17)
    p.add_argument('--out', default='', help='Output directory (default: <workspace>/build)')
    p.add_argument('--verbose', '-v', action='store_true')
    p.add_argument('--static', action='store_true',
                    help='Static-link the binary (-static -static-libgcc[-libstdc++]) -- '
                         'for a client deliverable that runs on any Linux box without '
                         'the client needing matching shared libs installed.')
    args = p.parse_args()

    result = build_project(
        workspace=args.workspace,
        backend=args.backend,
        cpp_standard=args.cpp_standard,
        out_dir=args.out or None,
        verbose=args.verbose,
        static=args.static,
    )

    if result['errors']:
        for e in result['errors']:
            print(f"ERROR [{e['file']}]: {e['message']}", file=sys.stderr)

    if result['warnings']:
        for w in result['warnings']:
            print(f"WARNING [{w['file']}]: {w['message']}", file=sys.stderr)

    s = result['stats']
    print(f"{'✓' if result['success'] else '✗'} "
          f"{s['dict_files']} files → {s['c_files']} C files, "
          f"{s['headers']} headers, Makefile")
    for f in result['files']:
        print(f"  → {f}")

    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
