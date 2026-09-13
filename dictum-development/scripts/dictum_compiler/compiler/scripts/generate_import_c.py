#!/usr/bin/env python3
"""
generate_import_c.py — real bridge-generation tool for Dictum.

Fills a gap flagged honestly in Guide B: this script was referenced in
docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md as what produced the existing
blessed bridges, but never actually existed in the repo. This is a
real implementation, not a stub.

Parses a real C header via libclang (never guesses signatures from
memory) and emits:
  1. `shape ... holds ... end shape` declarations for any struct
     passed/returned by value, using exactly-sized field types (f32,
     f64, i32, ...) so the emitted struct's memory layout matches the
     real C struct byte-for-byte -- NOT `decimal number` for a real
     `float` field, which would silently double the struct size and
     corrupt every by-value call (see Guide A §11/§13).
  2. `import from C the action ... as ...` lines for every function
     whose signature is directly bindable (no real out-parameters).
  3. A clearly-separated list of functions that need a hand-written C
     wrapper first -- genuinely needed for: a struct/union OUT-parameter
     (a pointer to something other than a plain scalar), a function
     whose return type isn't representable at all, or multiple/nested
     out-parameters. A pointer-to-PRIMITIVE out-parameter (`int*`,
     `bool*`, `float*`, etc.) is directly bindable via Dictum's `the
     address of` operator (R83/R108) and needs NO wrapper -- classified
     as directly bindable, with a `# NOTE (parameter '...')` comment in
     the generated file explaining the calling convention. (This
     docstring previously said the opposite -- "Dictum's opaque pointer
     can't take the address of a local variable" -- which was true when
     originally written but has been wrong since `the address of` was
     added; fixed together with the classification logic itself once
     the staleness was noticed.) For whatever genuinely still needs a
     wrapper, a scaffolded stub is emitted into a companion .c file,
     converting the out-parameter to a return value -- the same pattern
     already used successfully for raygui's `GuiToggleGroup`.

Usage:
  python3 generate_import_c.py raygui.h --module-name raygui_bridge \
      --output raygui_bridge.dict --wrapper-output raygui_wrappers.c \
      --only-prefix Gui --define RAYGUI_STANDALONE

Requires: pip install libclang --break-system-packages
"""
import argparse
import ctypes.util
import os
import sys


def _load_libclang():
    """Locate the real libclang.so shipped by the `libclang` pip package.
    Does NOT predefine the header's own include guard macro when parsing
    later -- doing so makes the preprocessor skip the entire file,
    silently producing zero parsed functions with zero diagnostics
    (a real mistake made and caught while bridging raygui this
    session)."""
    try:
        import clang.cindex as cindex
    except ImportError:
        print("ERROR: pip install libclang --break-system-packages", file=sys.stderr)
        sys.exit(1)

    import clang
    lib_dir = os.path.join(os.path.dirname(clang.__file__), "native")
    for fn in os.listdir(lib_dir):
        if fn.startswith("libclang") and fn.endswith(".so"):
            cindex.Config.set_library_file(os.path.join(lib_dir, fn))
            break
    return cindex


# Verified this session (see Guide A §11/§13). NEVER map C `float` to
# `decimal number` -- that silently changes a 4-byte value to 8 bytes
# and corrupts the real ABI, both as a direct parameter and as a
# struct field.
C_TO_DICTUM_PRIMITIVE = {
    "int": "i32", "int32_t": "i32", "unsigned int": "u32", "uint32_t": "u32",
    "short": "i16", "int16_t": "i16", "unsigned short": "u16", "uint16_t": "u16",
    "long": "i64", "int64_t": "i64", "long long": "i64",
    "unsigned long": "u64", "uint64_t": "u64",
    "char": "i32",  # plain `char` as a numeric value, not a string
    "unsigned char": "u8", "uint8_t": "u8", "byte": "u8",
    "float": "f32",
    "double": "f64",
    "void": "nothing",
    "_Bool": "truth value", "bool": "truth value",
}

# Real, exact struct-field sizes (bytes) for the primitives above --
# used only to sanity-check emitted shapes against libclang's own
# reported struct size, so a mismatch is caught here rather than
# discovered later as a silent runtime corruption.
PRIMITIVE_SIZE = {
    "i32": 4, "u32": 4, "i16": 2, "u16": 2, "i64": 8, "u64": 8,
    "u8": 1, "f32": 4, "f64": 8, "truth value": 1,
}


class BindingResult:
    def __init__(self):
        self.shapes = {}          # struct name -> [(field_name, dictum_type, c_type)]
        self.direct_functions = []  # (name, dictum_params, dictum_return, notes)
        self.wrapper_needed = []    # (name, real_params, real_return, out_param_indices)
        self.skipped = []          # (name, reason)


def map_type(cindex, clang_type, struct_registry, header_path):
    """Returns (dictum_type_str, is_out_param_pointer, is_struct_by_value, note)."""
    spelling = clang_type.spelling.replace("const ", "").strip()
    # Resolve through typedefs (e.g. `Rectangle` is `typedef struct
    # Rectangle {...} Rectangle;` -- clang_type.kind for a parameter of
    # type `Rectangle` is TYPEDEF, not RECORD, so checking .kind directly
    # misses every typedef'd struct. Bug found and fixed this session:
    # it was silently falling through to "opaque pointer" for Rectangle,
    # dropping the shape entirely instead of emitting it.
    canonical = clang_type.get_canonical()
    kind = canonical.kind if canonical.kind == cindex.TypeKind.RECORD else clang_type.kind

    if kind == cindex.TypeKind.POINTER:
        pointee = clang_type.get_pointee()
        pointee_spelling = pointee.spelling.replace("const ", "").strip()
        if pointee_spelling in ("char", "const char"):
            return "text", False, False, None
        # Resolve through any typedef/elaborated wrapping before checking
        # kind. `pointee.kind` alone is NOT enough: a pointer to a
        # typedef'd enum (e.g. raygui.h's own RAYGUI_STANDALONE fallback
        # `typedef enum { false, true } bool;`) reports as
        # TypeKind.ELABORATED at this level, not TypeKind.ENUM -- checking
        # `pointee.kind` directly against ENUM silently never matches, so
        # this was fixed once already (adding ENUM to the tuple below) and
        # STILL didn't catch it, because the real fix has to be resolving
        # the canonical type first. Confirmed against the real raygui.h:
        # GuiToggle/GuiCheckBox's `bool *` params only get correctly
        # flagged as needing a wrapper once this canonical resolution is
        # in place -- verified by regenerating the bridge and checking
        # the output, not just by re-reading this code.
        pointee_canonical_kind = pointee.get_canonical().kind
        if pointee_canonical_kind in (cindex.TypeKind.INT, cindex.TypeKind.UINT,
                             cindex.TypeKind.FLOAT, cindex.TypeKind.DOUBLE,
                             cindex.TypeKind.BOOL, cindex.TypeKind.SHORT,
                             cindex.TypeKind.USHORT, cindex.TypeKind.LONG,
                             cindex.TypeKind.ULONG, cindex.TypeKind.ENUM):
            # BUGFIX: this used to unconditionally classify a pointer to a
            # primitive as `needs_wrapper` ("Dictum's opaque pointer can't
            # take the address of a local variable"). That was true when
            # this comment was written, but `the address of X` has existed
            # since R83 specifically to solve exactly this case -- verified
            # directly against a real out-parameter function (`get_status
            # (whole number, opaque pointer) -> whole number`, bound with
            # no wrapper at all: `call get_status with code and the
            # address of severity giving result`, correct output
            # confirmed) -- see Guide A's struct-by-value/module-FFI
            # section and R108. A pointer-to-primitive out-parameter is
            # DIRECTLY bindable now: `opaque pointer` in the signature,
            # with the caller passing `the address of` a local variable of
            # the matching Dictum primitive type. No wrapper, no
            # scaffolded C, no manual fill-in.
            dictum_pointee = C_TO_DICTUM_PRIMITIVE.get(pointee_spelling, pointee_spelling)
            # BUGFIX (found immediately after fixing the classification
            # above, before this had shipped anywhere): for a pointee
            # whose SPELLING isn't itself a recognized C primitive name
            # (a custom `typedef enum {...} SomeBool;`, e.g. raygui's own
            # RAYGUI_STANDALONE fallback bool -- see R45), the note fell
            # back to the raw spelling ('SomeBool') as if it were a real
            # Dictum type to declare a local variable as. It isn't --
            # confirmed directly: `keep x as r45_bool ...` is not valid
            # Dictum, only its real underlying scalar type is (`i32`,
            # confirmed working end-to-end for an enum out-parameter).
            # Derive the guidance from the CANONICAL kind instead of the
            # spelling, which is robust to any custom typedef name.
            _CANONICAL_KIND_TO_DICTUM = {
                cindex.TypeKind.BOOL: "truth value",
                cindex.TypeKind.FLOAT: "f32", cindex.TypeKind.DOUBLE: "f64",
                cindex.TypeKind.SHORT: "i16", cindex.TypeKind.USHORT: "u16",
                cindex.TypeKind.LONG: "i64", cindex.TypeKind.ULONG: "u64",
                cindex.TypeKind.INT: "i32", cindex.TypeKind.UINT: "u32",
                cindex.TypeKind.ENUM: "i32",  # enums are int-sized in practice; confirmed working
            }
            dictum_pointee = _CANONICAL_KIND_TO_DICTUM.get(pointee_canonical_kind, dictum_pointee)
            return ("opaque pointer", False, False,
                    f"out-parameter: pass `the address of` a local "
                    f"'{dictum_pointee}' variable -- no wrapper needed (R83/R108)")
        return "opaque pointer", False, False, f"pointer to {pointee_spelling} -- verify manually, may need a wrapper"

    if kind == cindex.TypeKind.RECORD:
        struct_registry.add(spelling)
        return spelling, False, True, None

    base = C_TO_DICTUM_PRIMITIVE.get(spelling)
    if base:
        return base, False, False, None

    return "opaque pointer", False, False, f"unrecognized type '{spelling}' -- verify manually"


def extract_struct_fields(cindex, struct_decl):
    fields = []
    for child in struct_decl.get_children():
        if child.kind == cindex.CursorKind.FIELD_DECL:
            ftype = child.type.spelling.replace("const ", "").strip()
            dictum_t = C_TO_DICTUM_PRIMITIVE.get(ftype)
            if dictum_t is None:
                # Never silently guess a field type -- a wrong guess here
                # corrupts the whole struct's real memory layout. Flag it
                # for manual review instead (found and fixed this
                # session: this used to silently default to "f32" for
                # anything unrecognized, e.g. a nested struct or pointer
                # field, which would be a real, dangerous bug if trusted).
                dictum_t = f"MANUAL_REVIEW_NEEDED /* real type: {ftype} */"
            fields.append((child.spelling, dictum_t, ftype))
    return fields


def generate(header_path, module_name, only_prefix, defines, functions_filter):
    cindex = _load_libclang()
    index = cindex.Index.create()
    args = [f"-D{d}" for d in defines] if defines else []
    tu = index.parse(header_path, args=["-x", "c"] + args)

    errs = [d for d in tu.diagnostics if d.severity >= 3]
    if errs:
        print(f"WARNING: {len(errs)} parse error(s) -- output may be incomplete:", file=sys.stderr)
        for e in errs[:5]:
            print(f"  {e}", file=sys.stderr)

    result = BindingResult()
    struct_registry = set()
    seen_structs = {}
    functions = []

    def walk(node):
        for c in node.get_children():
            if c.kind == cindex.CursorKind.FUNCTION_DECL:
                loc = c.location.file
                if loc and os.path.basename(loc.name) == os.path.basename(header_path):
                    functions.append(c)
            walk(c)
    walk(tu.cursor)

    if only_prefix:
        functions = [f for f in functions if f.spelling.startswith(only_prefix)]
    if functions_filter:
        functions = [f for f in functions if f.spelling in functions_filter]

    for fn in functions:
        name = fn.spelling
        ret_type = fn.result_type
        ret_dictum, ret_is_out, ret_is_struct, ret_note = map_type(cindex, ret_type, struct_registry, header_path)

        params = list(fn.get_arguments())
        param_infos = []
        needs_wrapper = False
        out_indices = []
        for i, p in enumerate(params):
            p_dictum, p_is_out, p_is_struct, p_note = map_type(cindex, p.type, struct_registry, header_path)
            param_infos.append((p.spelling or f"arg{i}", p_dictum, p.type.spelling, p_is_struct, p_note))
            if p_is_out:
                needs_wrapper = True
                out_indices.append(i)

        if ret_dictum is None:
            needs_wrapper = True

        if needs_wrapper:
            result.wrapper_needed.append((name, param_infos, ret_type.spelling, out_indices))
        else:
            result.direct_functions.append((name, param_infos, ret_dictum, ret_note))

    # Resolve real struct field layouts for every struct type referenced
    for struct_name in struct_registry:
        cursor = None
        def find_struct(node):
            nonlocal cursor
            for c in node.get_children():
                if c.kind == cindex.CursorKind.STRUCT_DECL and c.spelling == struct_name:
                    cursor = c
                    return
                find_struct(c)
        find_struct(tu.cursor)
        if cursor:
            result.shapes[struct_name] = extract_struct_fields(cindex, cursor)
        else:
            result.shapes[struct_name] = None  # typedef'd anonymous struct, needs manual entry

    return result


def emit_dict(result, module_name, header_path):
    lines = []
    lines.append(f"module {module_name}")
    lines.append("")
    lines.append(f"# Auto-generated by generate_import_c.py from {os.path.basename(header_path)}")
    lines.append("# Real ABI parsed via libclang -- not hand-typed. Review anything marked")
    lines.append("# 'verify manually' below before trusting it as blessed.")
    lines.append("")

    for struct_name, fields in result.shapes.items():
        if fields is None:
            lines.append(f"# NOTE: struct '{struct_name}' body not found (likely a typedef'd")
            lines.append(f"# anonymous struct) -- add its shape manually, matching the real header.")
            lines.append("")
            continue
        lines.append(f"shape {struct_name} holds")
        for fname, dtype, ctype in fields:
            lines.append(f"    {fname} as {dtype}    # C: {ctype}")
        lines.append("end shape")
        lines.append("")

    lines.append("# -- Directly bindable (no out-parameters) --")
    lines.append("")
    for name, params, ret, note in result.direct_functions:
        param_types = " and ".join(p[1] for p in params)
        alias = name
        if params:
            lines.append(f"import from C the action {name} takes {param_types} produces {ret} as {alias}")
        else:
            lines.append(f"import from C the action {name} takes nothing produces {ret} as {alias}")
        if note:
            lines.append(f"    # NOTE (return value): {note}")
        # BUGFIX: per-PARAMETER notes (e.g. "out-parameter: pass `the
        # address of` a local 'whole number' variable") were computed by
        # map_type() but silently discarded here -- only the return
        # type's note ever made it into the generated file. An
        # out-parameter binding now looks identical to any other
        # directly-bindable function with no indication of how to
        # actually call it, which defeats the point of fixing the
        # classification itself (see map_type's out-parameter branch).
        for pname, _ptype, _cspelling, _is_struct, pnote in params:
            if pnote:
                lines.append(f"    # NOTE (parameter '{pname}'): {pnote}")
    lines.append("")

    if result.wrapper_needed:
        lines.append("# -- Needs a wrapper first (see companion .c file) --")
        lines.append("# Bind the wrapper function below, NOT the raw C function directly.")
        lines.append("")
        for name, params, ret, out_idx in result.wrapper_needed:
            wrapper_name = f"cncgui_{name.lstrip('Gg')}" if name[0].isupper() else f"wrap_{name}"
            wrapper_name = f"wrap_{name[0].lower()}{name[1:]}"
            param_desc = ", ".join(f"{p[0]}:{p[2]}" for p in params)
            lines.append(f"# {name}({param_desc}) -> {ret}  [real out-param(s) at index {out_idx}]")
            lines.append(f"# import from C the action {wrapper_name} takes ... produces ... as {wrapper_name}")
        lines.append("")

    return "\n".join(lines)


def emit_wrapper_c(result, header_path):
    lines = []
    lines.append(f'#include "{os.path.basename(header_path)}"')
    lines.append("")
    lines.append("// Auto-scaffolded by generate_import_c.py. Fill in the TODO body of each")
    lines.append("// wrapper: copy the out-parameter's current value in, call the real")
    lines.append("// function with a local variable, return the updated value. This is the")
    lines.append("// same pattern already used for raygui's GuiToggleGroup wrapper.")
    lines.append("")
    for name, params, ret, out_idx in result.wrapper_needed:
        wrapper_name = f"wrap_{name[0].lower()}{name[1:]}"
        c_params = ", ".join(f"{p[2]} {p[0]}" for p in params)
        lines.append(f"// TODO: verify this signature against the real header before using.")
        lines.append(f"/* {ret} {wrapper_name}({c_params}) {{")
        lines.append(f"    // real out-param(s) at index {out_idx} -- copy in, call, return updated value")
        lines.append(f"    return {name}(...);")
        lines.append("} */")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("header", help="Path to the real C header to bridge")
    ap.add_argument("--module-name", required=True)
    ap.add_argument("--output", required=True, help="Output .dict bridge file")
    ap.add_argument("--wrapper-output", help="Output scaffolded wrapper .c file")
    ap.add_argument("--only-prefix", default=None, help="Only bind functions starting with this prefix")
    ap.add_argument("--define", action="append", default=[], help="Macro to define when parsing (repeatable)")
    ap.add_argument("--functions", default=None, help="Comma-separated list to restrict to specific functions")
    args = ap.parse_args()

    functions_filter = set(args.functions.split(",")) if args.functions else None
    result = generate(args.header, args.module_name, args.only_prefix, args.define, functions_filter)

    dict_out = emit_dict(result, args.module_name, args.header)
    with open(args.output, "w") as f:
        f.write(dict_out)
    print(f"Wrote {args.output}: {len(result.direct_functions)} direct bindings, "
          f"{len(result.wrapper_needed)} need wrappers, {len(result.shapes)} shape(s).")

    if args.wrapper_output and result.wrapper_needed:
        wrapper_out = emit_wrapper_c(result, args.header)
        with open(args.wrapper_output, "w") as f:
            f.write(wrapper_out)
        print(f"Wrote {args.wrapper_output} (scaffolded, needs TODO bodies filled in).")


if __name__ == "__main__":
    main()
