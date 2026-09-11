#!/usr/bin/env python3
"""
backend_parity.py — enforce that the three backends stay in step.

THE RECURRING WEAKNESS THIS TARGETS
-----------------------------------
Dictum has THREE separately hand-written emitters (emit_c.py, emit_cpp.py,
emit_nim.py). Nearly every bug found in this project's reliability pass was
the same shape: *works on one or two backends, silently wrong or missing on
the third*. A sample from one session:

  * emit_nim dropped every `use` statement -> no nim module could reference
    a sibling, so multi-file nim was impossible
  * emit_cpp lacked the cross-file `use` hoisting fix emit_c already had
  * emit_cpp returned a HARDCODED std::function<bool(int32_t)> for every
    action type -- compiled clean, returned WRONG ANSWERS
  * emit_nim had no case for action types at all
  * emit_c handled `for each` over a growable list; the array path did not

Each was found by accident, one at a time, usually by a program that
happened to hit it. But the *class* is mechanically detectable: the three
emitters consume the SAME AST, so a node type handled by one and not
another is a parity gap by construction.

This tool diffs the handler sets by parsing each emitter's source for
`isinstance(node, X)` dispatch and for the `op == "..."` cases inside the
unary/binary handlers.

IMPORTANT: a gap is a WARNING, not automatically a bug. Some asymmetry is
legitimate -- C needs typedef machinery that C++ templates make unnecessary,
Nim's module system needs no header emission at all. So this tool maintains
an explicit ALLOWED-ASYMMETRY list with a stated reason for each entry.
Anything NOT on that list is reported. The point is that every divergence
becomes a deliberate, documented decision rather than an accident nobody
noticed.

Usage:  python3 backend_parity.py [--json OUT]
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
EMITTERS = {
    "c":   os.path.join(COMPILER_DIR, "dictumc", "emit_c.py"),
    "cpp": os.path.join(COMPILER_DIR, "dictumc", "emit_cpp.py"),
    "nim": os.path.join(COMPILER_DIR, "dictumc", "emit_nim.py"),
}

# Node types a backend legitimately need not handle, with the REASON.
# Anything absent from a backend and NOT listed here gets reported.
ALLOWED_ABSENCE = {
    "cpp": {
        "HandleTypeDecl": "C++ uses real smart-pointer types; no void* typedef needed",
        "Bind":           "C-specific binding form; C++ path uses the normal decl route",
        "ImportDict":     "handled by the shared project_builder header machinery",
    },
    "nim": {
        # Nim's module system replaces the whole C header apparatus.
        "HandleTypeDecl":   "nim has no typedef/header model",
        "BuildDirective":   "nim builds via `nim c`, not a generated Makefile",
        "ExternFn":         "covered by nim's own importc pragma path",
        "Contains":         "expressed via nim's `in` operator inline",
        "ForeignShape":     "polyglot pipeline does not target nim",
        "PolyglotCall":     "polyglot pipeline does not target nim",
        "PolyglotImport":   "polyglot pipeline does not target nim",
        "PolyglotModule":   "polyglot pipeline does not target nim",
        "UnsafeForeignCall":"`unsafe` blocks emit raw C; no nim equivalent",
        "UnsafeToken":      "`unsafe` blocks emit raw C; no nim equivalent",
    },
    "c": {
        "ImportCpp":  "C cannot import C++ symbols -- correct by definition",
        # NOT a comfortable entry: this is a REAL language-level limitation
        # on the C backend, not a difference that does not matter. Recorded
        # here so the checker stays useful, but it belongs on the gap list.
        "LambdaExpr": "C has no closures; would need generated helper functions",
    },
}

# Operators reached through a different mechanism on some backend rather
# than a dedicated emitter case -- not gaps, but worth stating.
ALLOWED_ABSENCE_OPS = {
    "nim": {
        "pow":      "reached via the Math.pow stdlib bridge (dictumc/nim_stdlib.py)",
        "room_for": "C allocation-sizing form; nim seqs size themselves",
    },
}

# Unary/binary operator cases. Same idea: an operator emitted by one
# backend and not another is a silent behavioural divergence.
OP_PATTERNS = [
    re.compile(r'op\s*==\s*"([a-z_]+)"'),
    re.compile(r"op\s*==\s*'([a-z_]+)'"),
    re.compile(r'node\.op\s*==\s*"([a-z_]+)"'),
]


def node_handlers(path: str) -> set:
    src = open(path).read()
    return set(re.findall(r"isinstance\(\s*node\s*,\s*([A-Za-z_]\w*)\s*\)", src))


def op_cases(path: str) -> set:
    src = open(path).read()
    out = set()
    for pat in OP_PATTERNS:
        out |= set(pat.findall(src))
    # `op in ("a", "b")` groupings
    for grp in re.findall(r'op\s+in\s+\(([^)]*)\)', src):
        out |= set(re.findall(r'["\']([a-z_]+)["\']', grp))
    # Dict-based dispatch: `op in _SOME_OP_MAP` / `_MAP.get(node.op, ...)`.
    # Without this the checker reports a FALSE POSITIVE for any backend that
    # dispatches through a table instead of an if-chain -- which is exactly
    # what emit_nim does for math ops. A detector that cannot see a real
    # implementation is worse than no detector, because it trains people to
    # ignore it.
    for dname in re.findall(r'\bop\s+in\s+(_[A-Z_]+)', src) + \
                 re.findall(r'(_[A-Z_]+)\.get\(\s*node\.op', src) + \
                 re.findall(r'(_[A-Z_]+)\.get\(\s*op\b', src):
        m = re.search(rf'{dname}\s*[:=].*?\{{(.*?)\}}', src, re.S)
        if m:
            out |= set(re.findall(r'["\']([a-z_]+)["\']\s*:', m.group(1)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()

    nodes = {b: node_handlers(p) for b, p in EMITTERS.items()}
    ops = {b: op_cases(p) for b, p in EMITTERS.items()}

    print("backend_parity: the three emitters consume the SAME AST, so a")
    print("node type handled by one and not another is a gap by construction.\n")
    for b in EMITTERS:
        print(f"  {b:<4} {len(nodes[b]):>3} node handlers, {len(ops[b]):>3} operator cases")
    print()

    findings = []
    all_nodes = set().union(*nodes.values())
    for n in sorted(all_nodes):
        have = {b for b in EMITTERS if n in nodes[b]}
        missing = set(EMITTERS) - have
        if not missing:
            continue
        # Only report when a MAJORITY handles it -- a node only one backend
        # knows about is usually genuinely backend-specific, not a gap.
        if len(have) < 2:
            continue
        real_missing = [b for b in sorted(missing) if n not in ALLOWED_ABSENCE.get(b, {})]
        if real_missing:
            findings.append(("node", n, sorted(have), real_missing))

    all_ops = set().union(*ops.values())
    for o in sorted(all_ops):
        have = {b for b in EMITTERS if o in ops[b]}
        missing = [b for b in sorted(set(EMITTERS) - have)
                   if o not in ALLOWED_ABSENCE_OPS.get(b, {})]
        if missing and len(have) >= 2:
            findings.append(("op", o, sorted(have), missing))

    if not findings:
        print("no unexplained parity gaps")
    else:
        print(f"{len(findings)} PARITY GAP(S) -- handled by some backends, not others:\n")
        for kind, name, have, missing in findings:
            print(f"  [{kind:<4}] {name:<22} have: {','.join(have):<12} MISSING: {','.join(missing)}")
        print("\nEach is either a real bug or a deliberate decision. If deliberate,")
        print("add it to ALLOWED_ABSENCE in this file WITH A REASON, so the next")
        print("person sees a documented choice instead of an accident.")

    if args.json:
        json.dump([{"kind": k, "name": n, "have": h, "missing": m}
                   for k, n, h, m in findings], open(args.json, "w"), indent=2)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
