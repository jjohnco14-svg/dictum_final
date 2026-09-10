#!/usr/bin/env python3
"""
header_completeness.py — mechanically detect a whole BUG CLASS rather than
individual bugs.

THE PATTERN
-----------
Two bugs found separately turned out to be one invariant violation:

  * a module action returning `text` was silently dropped from its
    generated header (whitelist lacked `dictum_text`)
  * a module action returning `opaque pointer` was silently dropped
    (whitelist matched bare `void`, not `void*`)

Both hide identically and nastily: the header generator matches return
types against a HARDCODED WHITELIST, so any type not on it vanishes. The
int-returning actions in the same module are declared correctly, so the
module looks fine. Callers in other files then see no declaration at all,
which C treats as an implicit int-returning function -- a wrong-type call
that either fails under -Werror or silently misbehaves without it.

Fuzzing cannot find this efficiently: it only appears when a module exports
an action of an unlisted return type AND another file calls it. But it is
trivially checkable as an INVARIANT:

    every action DEFINED in a module's generated source
    must be DECLARED in that module's generated header

So this tool generates one module exporting an action for EVERY type in the
Dictum type vocabulary, builds it, and diffs defined-vs-declared. One run
covers the entire class, including types nobody has thought to test, and any
type added to the language later.

Usage:  python3 header_completeness.py [--compiler DIR]
"""
from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COMPILER = os.path.dirname(HERE)

# (dictum type, a literal/value for it, whether it needs `with no value`)
# (dictum type, initializer, can it be used at a call site?)
# `opaque pointer` has no literal form -- it can only come from an FFI call
# -- so the validator (correctly) rejects passing an uninitialized one. It
# is still checked in the HEADER, which is what this invariant is about; it
# just gets no corroborating call site.
TYPES = [
    ("whole number",    "with value 0",    True),
    ("decimal number",  "with value 0.0",  True),
    ("truth value",     "with value 1",    True),
    ("text",            'with value ""',   True),
    ("opaque pointer",  "with no value",   False),
    ("byte",            "with value 0",    True),
]


def build_probe(compiler_dir: str, workdir: str, backend: str):
    """One module exporting an action per type, plus a program calling each
    (the call site is what turns a missing declaration into a real error)."""
    mod = ["module probe", ""]
    main = ["program main", "", "    use probe", ""]
    tested = []
    for i, (ty, init, callable_) in enumerate(TYPES):
        name = f"get{i}"
        # Parameter pass-through rather than constructing a value: some
        # types (opaque pointer) cannot be declared `with no value` and
        # then returned -- the validator correctly rejects returning an
        # uninitialized variable. Pass-through exercises the return type
        # in the generated header, which is all this invariant needs, and
        # is valid for every type in the vocabulary.
        mod += [
            f"    action {name} takes p as {ty} produces {ty}",
            f"        return p",
            f"    end action",
            "",
        ]
        if callable_:
            main += [
                f"    keep r{i} as {ty} {init}",
                f"    call probe.{name} with r{i} giving r{i}",
            ]
        tested.append((name, ty))
    mod.append("end module")
    main += ['    print the text "done"', "", "end program"]

    open(os.path.join(workdir, "probe.dict"), "w").write("\n".join(mod) + "\n")
    open(os.path.join(workdir, "main.dict"), "w").write("\n".join(main) + "\n")

    out = os.path.join(workdir, f"build_{backend}")
    pb = os.path.join(compiler_dir, "project_builder.py")
    r = subprocess.run(
        [sys.executable, pb, workdir, "--backend", backend, "--out", out],
        capture_output=True, text=True, timeout=180)
    return out, r, tested


def check(compiler_dir: str) -> int:
    print("header_completeness: checking the invariant")
    print("  'every action DEFINED in a module's generated source")
    print("   must be DECLARED in that module's generated header'\n")

    problems = []
    for backend in ("c", "cpp"):
        # nim has no separate header model -- it exports via `proc*`, so this
        # particular invariant does not apply there.
        workdir = tempfile.mkdtemp(prefix="hdrcheck_")
        try:
            out, r, tested = build_probe(compiler_dir, workdir, backend)
            if r.returncode != 0:
                print(f"[{backend}] project_builder failed:\n{r.stdout[-500:]}")
                problems.append((backend, "build", r.stdout[-200:]))
                continue

            ext = ".c" if backend == "c" else ".cpp"
            src_path = os.path.join(out, "probe" + ext)
            hdr_path = os.path.join(out, "dictum_probe.h")
            if not (os.path.exists(src_path) and os.path.exists(hdr_path)):
                problems.append((backend, "missing artifacts", str(os.listdir(out))))
                continue

            src = open(src_path).read()
            hdr = open(hdr_path).read()

            for name, ty in tested:
                sym = f"probe_{name}"
                defined = re.search(rf"^\s*[\w \*]+\b{sym}\s*\(", src, re.M) is not None
                declared = sym in hdr
                mark = "ok " if (not defined or declared) else "MISSING"
                print(f"  [{backend}] {ty:<16} {sym:<12} "
                      f"defined={int(defined)} declared={int(declared)}  {mark}")
                if defined and not declared:
                    problems.append((backend, ty, sym))

            # The call sites make a missing declaration a hard error, so a
            # successful compile is independent corroboration.
            mk = os.path.join(out, "Makefile")
            if os.path.exists(mk):
                rb = subprocess.run(["make"], capture_output=True, text=True,
                                     timeout=180, cwd=out)
                if rb.returncode != 0:
                    err = (rb.stdout + rb.stderr)
                    first = next((l for l in err.splitlines()
                                  if re.search(r"error", l, re.I)), "")
                    print(f"  [{backend}] COMPILE FAILED: {first[:130]}")
                    problems.append((backend, "compile", first[:200]))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        print()

    print("=" * 68)
    if problems:
        print(f"{len(problems)} PROBLEM(S) -- the invariant is violated:")
        for b, ty, detail in problems:
            print(f"  [{b}] {ty}: {detail}")
        print("\nA return type missing from generate_header's whitelist means every")
        print("action using it vanishes from its module header. Add the type there.")
        return 1
    print("invariant holds for every type in the vocabulary")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=DEFAULT_COMPILER)
    args = ap.parse_args()
    return check(args.compiler)


if __name__ == "__main__":
    sys.exit(main())
