#!/usr/bin/env python3
"""
emit_binding.py — `dictum emit-binding`: generates a Python ctypes binding
straight from the SAME type registry the C/C++ emitters use, so a Python
orchestrator calling a compiled Dictum kernel can never hand-type argtypes
that silently drift from the real signature.

WHY THIS EXISTS (the Python-orchestrates-Dictum-kernel direction)
---------------------------------------------------------------------
The split: Python for orchestration/I/O/AI glue (its ecosystem wins there),
Dictum for the logic that must be verified and byte-reproducible (native,
auditable, checked across 3 backends), C/C++ via `import from C`/`C++` for
device/library access. Dictum doesn't have to win a whole application --
only the part where a wrong answer is expensive. That reframing only works
if the BOUNDARY between the two languages can't silently drift -- two
individually-correct sides can still disagree at the ABI.

That risk is not hypothetical -- reproduced directly before writing this
tool: a real Dictum kernel (`calculate_tariff(weight_kg, distance_km,
rate_class)`, all real numbers) called via ctypes with a HAND-WRITTEN
argtypes list. Getting the C TYPES wrong (float where int expected) is
caught loudly by ctypes. Getting the SEMANTIC ORDER wrong -- swapping
weight_kg and distance_km, both `c_double`, both individually valid to
ctypes -- is not caught at all: `calculate_tariff(distance_km, weight_kg,
rate_class)` ran, returned a real number (112.8), and was simply wrong
(the correct answer is 14.25). No crash, no warning -- ctypes has no way
to know two doubles were swapped. That is the exact "silent wrong answer"
failure class this whole project treats as its top risk (see
run_selftest.py's own regression history), now demonstrated at the
Python/Dictum boundary specifically.

WHAT THIS GENERATES
----------------------
For each qualifying action, two things, never hand-typed:
  1. `argtypes`/`restype` on the raw ctypes function, derived from
     dictumc/type_registry.py's own c_type_map() -- the SAME table
     emit_c.py's type_to_c() uses, so this can never disagree with the
     compiled kernel's actual signature.
  2. A Python wrapper function with KEYWORD-ONLY parameters using the
     ACTION'S REAL PARAMETER NAMES (`def calculate_tariff(*, weight_kg,
     distance_km, rate_class): ...`). This is the actual fix for the
     demonstrated bug: swapping two same-typed positional arguments is
     silent, but passing `distance_km=` where `weight_kg=` was meant is
     either self-evidently correct or a clear TypeError (missing/unknown
     keyword) -- there is no third, silently-wrong outcome once the
     caller is forced to name each argument.

WHAT THIS REFUSES, AND WHY (clear negative space, not a silent guess)
------------------------------------------------------------------------
Only actions whose entire signature is built from plain scalar types
(whole/fractional number, truth value, byte, the fixed-width int/float
families) plus `text` AS A PARAMETER are bound. Specifically refused,
loudly, per-action (one unsupported action does not block binding the
rest of the file):
  - `text` as a RETURN type -- checked directly against real generated C
    before deciding this: a `text`-returning action can return a pointer
    to a string literal (safe to read) OR a pointer built at runtime by
    a stdlib call whose ownership/lifetime this tool has not verified
    end-to-end. Binding it as `c_char_p` might work by accident or might
    hand Python a dangling/leaked pointer -- getting an ABI tool's OWN
    output subtly wrong is worse than refusing, so v1 refuses.
  - `opaque pointer`, `result`, shapes, and container types (list/map/
    set) -- no ctypes-safe representation attempted without knowing the
    real runtime struct layout of each.
Every refusal names the action and the specific type that blocked it, so
a human decides whether to widen this tool or restructure the kernel's
signature, rather than silently getting nothing or a wrong binding.

Usage:
    python3 emit_binding.py KERNEL.dict --out kernel_binding.py --lib ./libkernel.so
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from typing import List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
sys.path.insert(0, COMPILER_DIR)

from dictumc.lexer import Lexer
from dictumc.parser import Parser
from dictumc.ast_nodes import Action, Module
from dictumc.type_registry import c_type_map

# Dictum raw type -> (ctypes name, Python type hint). Built directly from
# c_type_map() -- the same table emit_c.py's type_to_c() consults -- so
# this can never invent a mapping the C emitter doesn't also use.
_C_TO_CTYPES = {
    "bool": "c_bool", "uint8_t": "c_uint8", "int16_t": "c_int16",
    "uint16_t": "c_uint16", "int32_t": "c_int32", "uint32_t": "c_uint32",
    "int64_t": "c_int64", "uint64_t": "c_uint64", "float": "c_float",
    "double": "c_double", "size_t": "c_size_t",
}
_PY_HINT = {
    "c_bool": "bool", "c_uint8": "int", "c_int16": "int", "c_uint16": "int",
    "c_int32": "int", "c_uint32": "int", "c_int64": "int", "c_uint64": "int",
    "c_float": "float", "c_double": "float", "c_size_t": "int",
    "c_char_p": "bytes",
}


def _resolve_param_ctype(dictum_type: str) -> Optional[str]:
    """A Dictum type this tool will bind as a plain scalar ctypes
    argument, or None if it's outside the safe, verified scope above."""
    if dictum_type == "text":
        return "c_char_p"  # safe as an INPUT only -- caller's bytes outlive the call
    c_name = c_type_map().get(dictum_type)
    return _C_TO_CTYPES.get(c_name)


def _resolve_return_ctype(dictum_type: str) -> Optional[str]:
    if dictum_type == "text":
        return None  # refused -- see module docstring
    c_name = c_type_map().get(dictum_type)
    return _C_TO_CTYPES.get(c_name)


def _collect_actions(source: str) -> List[Tuple[str, Action]]:
    """(qualified_c_symbol_name, Action) for every action in the file,
    top-level or module-scoped -- qualified using the SAME `Module_action`
    mangling emit_c.py/emit_cpp.py use, so the generated binding's symbol
    name always matches the real compiled one."""
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens, grammar=None).parse()
    out: List[Tuple[str, Action]] = []

    def walk(nodes, module_name: Optional[str]):
        for node in nodes:
            if isinstance(node, Action):
                symbol = f"{module_name}_{node.name}" if module_name else node.name
                out.append((symbol, node))
            elif isinstance(node, Module):
                walk(node.body, node.name)

    walk(ast, None)
    return out


def generate_binding(source: str, lib_path: str) -> Tuple[str, List[str]]:
    """Returns (generated_python_source, warnings). Warnings list every
    action that was skipped and exactly why -- never silent."""
    actions = _collect_actions(source)
    warnings: List[str] = []
    bound = []

    for symbol, action in actions:
        if action.template_params:
            warnings.append(f"'{symbol}': skipped -- generic (template) actions "
                             f"have no single fixed ABI signature to bind.")
            continue
        arg_ctypes = []
        ok = True
        for pname, ptype in action.params:
            ct = _resolve_param_ctype(ptype)
            if ct is None:
                warnings.append(f"'{symbol}': skipped -- parameter '{pname}' has "
                                 f"type '{ptype}', which is outside emit_binding's "
                                 f"verified-safe scope (see module docstring).")
                ok = False
                break
            arg_ctypes.append((pname, ptype, ct))
        if not ok:
            continue
        ret_ct = _resolve_return_ctype(action.ret_type)
        if action.ret_type != "nothing" and ret_ct is None:
            warnings.append(f"'{symbol}': skipped -- return type '{action.ret_type}' "
                             f"is outside emit_binding's verified-safe scope "
                             f"(text returns are refused -- see module docstring).")
            continue
        bound.append((symbol, action, arg_ctypes, ret_ct))

    lines = [
        '"""',
        f"AUTO-GENERATED by dictum emit-binding on "
        f"{datetime.datetime.now(datetime.timezone.utc).isoformat()}.",
        "DO NOT HAND-EDIT -- regenerate from the .dict source instead. Every",
        "argtypes/restype below comes directly from dictumc/type_registry.py's",
        "c_type_map(), the same table the C/C++ emitters use, so this file",
        "cannot silently disagree with the compiled kernel's real ABI.",
        '"""',
        "from __future__ import annotations",
        "import ctypes",
        "",
        f'_lib = ctypes.CDLL({lib_path!r})',
        "",
    ]
    for symbol, action, arg_ctypes, ret_ct in bound:
        lines.append(f"_lib.{symbol}.argtypes = "
                     f"[{', '.join('ctypes.' + ct for _, _, ct in arg_ctypes)}]")
        lines.append(f"_lib.{symbol}.restype = "
                     f"{'ctypes.' + ret_ct if ret_ct else 'None'}")
        lines.append("")
        py_params = ", ".join(
            f"{pname}: {_PY_HINT.get(ct, 'object')}" for pname, _, ct in arg_ctypes
        )
        ret_hint = f" -> {_PY_HINT.get(ret_ct, 'object')}" if ret_ct else ""
        lines.append(f"def {action.name}(*, {py_params}){ret_hint}:")
        lines.append(f'    """Binds the Dictum action `{action.name}` '
                     f'(compiled symbol `{symbol}`).')
        lines.append(f"    Keyword-only on purpose -- see module docstring: this is "
                     f"what turns a")
        lines.append(f"    same-typed-argument swap into a clear TypeError instead "
                     f"of a silent")
        lines.append(f'    wrong answer."""')
        call_args = ", ".join(pname for pname, _, _ in arg_ctypes)
        lines.append(f"    return _lib.{symbol}({call_args})")
        lines.append("")

    return "\n".join(lines), warnings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="path to the .dict kernel source")
    ap.add_argument("--lib", required=True, help="path to the compiled .so, "
                                                    "as the generated binding will load it")
    ap.add_argument("--out", required=True, help="output .py file")
    args = ap.parse_args(argv)

    source = open(args.source, encoding="utf-8").read()
    code, warnings = generate_binding(source, args.lib)
    open(args.out, "w").write(code)

    for w in warnings:
        print(f"emit-binding: {w}", file=sys.stderr)
    print(f"emit-binding: wrote '{args.out}'"
          + (f" ({len(warnings)} action(s) skipped, see above)" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
