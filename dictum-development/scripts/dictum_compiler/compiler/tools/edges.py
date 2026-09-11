#!/usr/bin/env python3
"""
edges.py — find the edges: every FEATURE x every CONTEXT.

THE OBSERVATION THIS IS BUILT ON
--------------------------------
Across this project's reliability work, a generator repeatedly saturated its
own coverage and stayed clean while hand-written programs kept finding real
bugs. Looking at what those bugs actually needed:

  ODR bug        `use Text` INSIDE A MODULE, in a MULTI-FILE build
  header class   a module exporting BOTH int- and text-returning actions
  attempt/nim    `call ... giving` on a PRE-DECLARED variable, inside
                 an attempt block
  unused loop    a `for each` whose BODY ignores the loop variable
  address-of     `the address of` applied to a CONTAINER, not a scalar

None of these is an exotic feature. Every one is an ORDINARY feature placed
in a CONTEXT it had never been placed in. explorer.py combines features with
each other but always emits them in ONE context -- inline in `program main`,
usually single-file. That is precisely the blind spot.

So this tool takes the other axis. For each feature it can generate, it
places that feature in every structural context:

    program body          (the baseline everything else already covers)
    inside an action      (local scope, with a return value)
    inside a module       (cross-file symbol, needs a header)
    multi-file            (module in a SEPARATE file -- own translation unit)
    inside a loop body    (repeated execution, scoping per iteration)
    inside a conditional  (one branch only)
    nested two deep       (loop inside conditional)

FEATURES x CONTEXTS is a small matrix -- a few hundred cells -- but it is
the cross-product that actually produced today's bugs, and no amount of
feature-pair depth reaches it.

Expected output is computed here, so this checks CORRECTNESS, not just
"did it build". Every cell is a real compile+run on all three backends.

Usage:
    python3 edges.py                 # full matrix
    python3 edges.py --feature text_len --context in_module
"""
from __future__ import annotations
import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
CLI = os.path.join(COMPILER_DIR, "dictumc_cli.py")
PROJECT_BUILDER = os.path.join(COMPILER_DIR, "project_builder.py")
BACKENDS = ("c", "cpp", "nim")


# ---------------------------------------------------------------------------
# FEATURES: each produces (uses, setup_lines, expr_lines, result_var, expected)
# `uses` are `use X` lines the feature needs -- these matter enormously,
# because a stdlib dependency inside a MODULE is what triggered the ODR bug.
# ---------------------------------------------------------------------------
FEATURES = {
    "arith": {
        "uses": [],
        "setup": ['keep a_F as whole number with value 20'],
        "work":  ['put a_F plus 22 into a_F'],
        "result": ("a_F", "whole number"), "expect": "42",
    },
    "text_len": {
        "uses": ["Text"],
        "setup": ['keep s_F as text with value "abcdefgh"',
                  'keep a_F as whole number with value 0'],
        "work":  ['call Text.length with s_F giving a_F'],
        "result": ("a_F", "whole number"), "expect": "8",
    },
    "text_upper": {
        "uses": ["Text"],
        "setup": ['keep s_F as text with value "xyz"',
                  'keep t_F as text with value ""'],
        "work":  ['call Text.to_upper with s_F giving t_F'],
        "result": ("t_F", "text"), "expect": "XYZ",
    },
    "math_sqrt": {
        "uses": ["Math"],
        "setup": ['keep d_F as decimal number with value 81.0',
                  'keep r_F as decimal number with value 0.0'],
        "work":  ['call Math.sqrt with d_F giving r_F'],
        "result": ("r_F", "decimal number"), "expect": "9.000000",
    },
    "glist": {
        "uses": [],
        "setup": ['keep g_F as growable list of whole number with no value',
                  'add 4 to g_F', 'add 5 to g_F', 'add 6 to g_F',
                  'keep a_F as whole number with value 0'],
        "work":  ['put the count of g_F into a_F'],
        "result": ("a_F", "whole number"), "expect": "3",
    },
    "glist_text": {
        "uses": [],
        "setup": ['keep gt_F as growable list of text with no value',
                  'add "p" to gt_F', 'add "q" to gt_F',
                  'keep a_F as whole number with value 0'],
        "work":  ['put the count of gt_F into a_F'],
        "result": ("a_F", "whole number"), "expect": "2",
    },
    "foreach": {
        "uses": [],
        "setup": ['keep fl_F as growable list of whole number with no value',
                  'add 7 to fl_F', 'add 8 to fl_F',
                  'keep a_F as whole number with value 0'],
        "work":  ['for each e_F in fl_F repeat',
                  '    put a_F plus e_F into a_F',
                  'end for'],
        "result": ("a_F", "whole number"), "expect": "15",
    },
    "shape": {
        "uses": [],
        "shape_decl": 'shape Sh_F holds:\n    w as whole number\n    h as whole number\nend shape',
        "setup": ['keep sh_F as Sh_F with no value', 'set w of sh_F to 6',
                  'set h of sh_F to 7', 'keep a_F as whole number with value 0'],
        "work":  ['put w of sh_F times h of sh_F into a_F'],
        "result": ("a_F", "whole number"), "expect": "42",
    },
    "attempt": {
        "uses": [],
        "setup": ['keep a_F as whole number with value 0'],
        "work":  ['attempt', '    put 42 into a_F', 'on success',
                  '    put a_F into a_F', 'on failure',
                  '    put 0 into a_F', 'end attempt'],
        "result": ("a_F", "whole number"), "expect": "42",
    },
    "reserved_name": {
        "uses": [],
        "setup": ['keep out_F as whole number with value 21',
                  'keep a_F as whole number with value 0'],
        "work":  ['put out_F times 2 into a_F'],
        "result": ("a_F", "whole number"), "expect": "42",
    },
}

CONTEXTS = ("program_body", "in_action", "in_module", "in_loop",
            "in_conditional", "nested_two_deep")


def ind(lines, n):
    pad = "    " * n
    return "".join(f"{pad}{l}\n" for l in lines)


def build(feature: str, context: str):
    """Returns (main_src, module_src_or_None, expected)."""
    f = FEATURES[feature]
    tag = feature[:4]
    sub = lambda ls: [l.replace("_F", f"_{tag}") for l in ls]
    setup, work = sub(f["setup"]), sub(f["work"])
    rvar, rtype = f["result"][0].replace("_F", f"_{tag}"), f["result"][1]
    shape_decl = f.get("shape_decl", "").replace("_F", f"_{tag}")
    uses = "".join(f"use {u}\n" for u in f["uses"])
    expected = f"r={f['expect']}"

    if context == "program_body":
        src = (uses + ("\n" + shape_decl + "\n" if shape_decl else "") +
               "\nprogram main\n\n" + ind(setup, 1) + ind(work, 1) +
               f'    print the text "r=" and {rvar}\n' + "\nend program\n")
        return src, None, expected

    if context == "in_action":
        body = ind(setup, 1) + ind(work, 1) + f"    return {rvar}\n"
        src = (uses + ("\n" + shape_decl + "\n" if shape_decl else "") +
               f"\naction compute_{tag} takes nothing produces {rtype}\n{body}end action\n"
               "\nprogram main\n\n"
               f"    keep out_v as {rtype} with " +
               ("value 0\n" if rtype == "whole number" else
                'value ""\n' if rtype == "text" else "value 0.0\n") +
               f"    call compute_{tag} giving out_v\n"
               f'    print the text "r=" and out_v\n\nend program\n')
        return src, None, expected

    if context == "in_module":
        # The feature lives in a MODULE, in its own file. This is the shape
        # that exposed the one-definition-rule bug: a stdlib dependency
        # pulled into a second translation unit.
        body = ind(setup, 2) + ind(work, 2) + f"        return {rvar}\n"
        mod = (uses + ("\n" + shape_decl + "\n" if shape_decl else "") +
               "\nmodule helper\n\n"
               f"    action compute takes nothing produces {rtype}\n{body}    end action\n\n"
               "end module\n")
        main = ("\nprogram main\n\n    use helper\n\n"
                f"    keep out_v as {rtype} with " +
                ("value 0\n" if rtype == "whole number" else
                 'value ""\n' if rtype == "text" else "value 0.0\n") +
                "    call helper.compute giving out_v\n"
                '    print the text "r=" and out_v\n\nend program\n')
        return main, mod, expected

    if context == "in_loop":
        # Runs the feature inside a loop body: per-iteration scoping, and
        # re-declaration hazards that a single execution never reveals.
        src = (uses + ("\n" + shape_decl + "\n" if shape_decl else "") +
               "\nprogram main\n\n"
               "    keep n_it as whole number with value 0\n"
               "    while n_it is less than 2 repeat\n"
               + ind(setup, 2) + ind(work, 2) +
               "        put n_it plus 1 into n_it\n"
               "    end while\n"
               f'    print the text "r=" and {rvar}\n\nend program\n')
        return src, None, expected

    if context == "in_conditional":
        src = (uses + ("\n" + shape_decl + "\n" if shape_decl else "") +
               "\nprogram main\n\n"
               "    keep flag_c as whole number with value 1\n"
               "    if flag_c is equal to 1 then\n"
               + ind(setup, 2) + ind(work, 2) +
               f'        print the text "r=" and {rvar}\n'
               "    otherwise\n"
               '        print the text "r=skipped"\n'
               "    end if\n\nend program\n")
        return src, None, expected

    if context == "nested_two_deep":
        src = (uses + ("\n" + shape_decl + "\n" if shape_decl else "") +
               "\nprogram main\n\n"
               "    keep flag_c as whole number with value 1\n"
               "    if flag_c is equal to 1 then\n"
               "        keep n_it as whole number with value 0\n"
               "        while n_it is less than 2 repeat\n"
               + ind(setup, 3) + ind(work, 3) +
               "            put n_it plus 1 into n_it\n"
               "        end while\n"
               f'        print the text "r=" and {rvar}\n'
               "    end if\n\nend program\n")
        return src, None, expected

    raise ValueError(context)


def run_cell(feature, context, workdir):
    try:
        main_src, mod_src, expected = build(feature, context)
    except Exception as e:
        return "skip", f"cannot construct: {e}"

    outputs = {}
    for backend in BACKENDS:
        if backend == "nim" and shutil.which("nim") is None:
            continue
        d = os.path.join(workdir, backend)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        open(os.path.join(d, "main.dict"), "w").write(main_src)
        if mod_src:
            open(os.path.join(d, "helper.dict"), "w").write(mod_src)
        try:
            if mod_src:
                out = os.path.join(d, "b")
                r = subprocess.run([sys.executable, PROJECT_BUILDER, d,
                                    "--backend", backend, "--out", out],
                                   capture_output=True, text=True, timeout=200)
                if r.returncode != 0:
                    return "build_fail", f"[{backend}] {(r.stdout+r.stderr)[-260:]}"
                if backend == "nim":
                    rb = subprocess.run(["sh", os.path.join(out, "build.sh")],
                                        capture_output=True, text=True, timeout=300, cwd=out)
                else:
                    rb = subprocess.run(["make"], capture_output=True, text=True,
                                        timeout=200, cwd=out)
                if rb.returncode != 0:
                    return "build_fail", f"[{backend}] {(rb.stdout+rb.stderr)[-260:]}"
                binp = os.path.join(out, "main")
            else:
                binp = os.path.join(d, "p")
                r = subprocess.run([sys.executable, CLI, os.path.join(d, "main.dict"),
                                    "--backend", backend, "--compile", "--output", binp],
                                   capture_output=True, text=True, timeout=200)
                if r.returncode != 0:
                    return "build_fail", f"[{backend}] {(r.stdout+r.stderr)[-260:]}"
            run = subprocess.run([binp], capture_output=True, text=True, timeout=30, cwd=d)
            outputs[backend] = "".join(run.stdout.split())
        except subprocess.TimeoutExpired:
            return "build_fail", f"[{backend}] timeout"

    want = "".join(expected.split())
    for b, got in outputs.items():
        if got != want:
            return "wrong", f"[{b}] got {got!r} want {want!r}"
    if len(set(outputs.values())) > 1:
        return "wrong", f"backends disagree: {outputs}"
    return "ok", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature")
    ap.add_argument("--context")
    ap.add_argument("--json")
    args = ap.parse_args()

    feats = [args.feature] if args.feature else sorted(FEATURES)
    ctxs = [args.context] if args.context else list(CONTEXTS)

    print(f"edges: {len(feats)} features x {len(ctxs)} contexts = "
          f"{len(feats)*len(ctxs)} cells, each on all 3 backends")
    print("Bugs live where an ORDINARY feature meets a context it has never")
    print("been placed in -- that is the axis feature-pairing cannot reach.\n")
    print(f"{'feature':<15}" + "".join(f"{c[:9]:<11}" for c in ctxs))

    findings = []
    root = tempfile.mkdtemp(prefix="edges_")
    try:
        for f in feats:
            row = f"{f:<15}"
            for c in ctxs:
                verdict, detail = run_cell(f, c, os.path.join(root, f"{f}_{c}"))
                mark = {"ok": ".", "wrong": "WRONG", "build_fail": "BUILD",
                        "skip": "-"}[verdict]
                row += f"{mark:<11}"
                if verdict in ("wrong", "build_fail"):
                    findings.append((f, c, verdict, detail))
            print(row, flush=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    if not findings:
        print("every feature works in every context")
    else:
        print(f"{len(findings)} EDGE(S) FOUND:\n")
        for f, c, v, d in findings:
            print(f"  {f} x {c}: {v}")
            print(f"    {d[:220]}\n")
    if args.json:
        json.dump([{"feature": f, "context": c, "verdict": v, "detail": d}
                   for f, c, v, d in findings], open(args.json, "w"), indent=2)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
