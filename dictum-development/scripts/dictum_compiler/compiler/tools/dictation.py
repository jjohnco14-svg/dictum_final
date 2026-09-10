#!/usr/bin/env python3
"""
dictation.py — add a new dictation (a new piece of Dictum grammar) through
a gated procedure, instead of editing six files and hoping.

WHY A PROCEDURE AND NOT JUST AN EDIT
------------------------------------
A new dictation is not one change. It touches, at minimum:
    dictumc/lexer.py        tokens
    dictumc/parser.py       parse rule
    dictumc/grammar.py      KEYWORDS  (HAND-SYNCED -- a known drift risk)
    dictumc/validator.py    type checking
    dictumc/emit_c.py       C backend
    dictumc/emit_cpp.py     C++ backend    <- hand-written twin of emit_c
    dictumc/emit_nim.py     Nim backend    <- a third, separate implementation
Miss any one and you get silent divergence, which this project has produced
repeatedly and painfully: a fix landing in emit_c.py but not emit_cpp.py, a
KEYWORDS set drifting from the parser, `--backend nim` silently emitting C.

So a dictation moves through three states, and cannot skip one:

    proposed  -> `check`  -> compatible -> `test` -> working

  check  (COMPATIBILITY)  Can this dictation exist here at all?
                          - keyword collisions with the existing KEYWORDS set
                          - collisions with the Dictum type vocabulary
                          - whether the word is already parseable as an
                            identifier today (adding it would change the
                            meaning of existing valid programs)
                          - the full existing regression suite still passes
                          Answers: "does adding this break what already works?"

  test   (FUNCTIONALITY)  Does it actually do the thing?
                          - compiles a REAL example program using it
                          - on ALL THREE backends
                          - runs each binary and checks real output
                          - requires all three to AGREE
                          Answers: "does it work, everywhere, identically?"

Only a dictation in `working` state is reported as usable. `check` passing
does NOT make it usable -- compatibility is not function.

COMMANDS
    list                       every dictation and its state
    propose <name> --syntax S --description D --example FILE --expect TEXT
                               register a new dictation as `proposed`
    check   <name>             run the COMPATIBILITY gate
    test    <name>             run the FUNCTIONALITY gate (all 3 backends)
    show    <name>             full detail, including why a gate failed
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
CLI = os.path.join(COMPILER_DIR, "dictumc_cli.py")
SELFTEST = os.path.join(COMPILER_DIR, "run_selftest.py")
DICTATION_DIR = os.path.join(COMPILER_DIR, "dictations")

BACKENDS = ("c", "cpp", "nim")
STATES = ("proposed", "compatible", "working", "failed")


def spec_path(name: str) -> str:
    return os.path.join(DICTATION_DIR, f"{name}.json")


def load(name: str) -> dict:
    p = spec_path(name)
    if not os.path.exists(p):
        raise SystemExit(f"no dictation '{name}'. Known: "
                         f"{', '.join(sorted(list_names())) or '(none)'}")
    return json.load(open(p))


def save(spec: dict) -> None:
    os.makedirs(DICTATION_DIR, exist_ok=True)
    json.dump(spec, open(spec_path(spec["name"]), "w"), indent=2)


def list_names() -> list:
    if not os.path.isdir(DICTATION_DIR):
        return []
    return [f[:-5] for f in os.listdir(DICTATION_DIR) if f.endswith(".json")]


def existing_keywords() -> set:
    sys.path.insert(0, COMPILER_DIR)
    try:
        from dictumc.grammar import DictumGrammar
        return set(DictumGrammar.KEYWORDS)
    except Exception:
        # Fall back to reading the literal set out of the source, so this
        # tool still works if grammar.py can't be imported standalone.
        src = open(os.path.join(COMPILER_DIR, "dictumc", "grammar.py")).read()
        m = re.search(r"KEYWORDS\s*=\s*\{(.*?)\}", src, re.S)
        return set(re.findall(r"'([^']+)'", m.group(1))) if m else set()


def type_vocabulary() -> set:
    sys.path.insert(0, COMPILER_DIR)
    try:
        from dictumc import type_registry as tr
        for attr in ("ALL_TYPES", "TYPE_WORDS", "DICTUM_TYPES"):
            v = getattr(tr, attr, None)
            if v:
                return set(v)
    except Exception:
        pass
    return set()


# ---------------------------------------------------------------------------
# Gate 1 -- COMPATIBILITY
# ---------------------------------------------------------------------------

def gate_check(spec: dict) -> "tuple[bool, list]":
    findings = []
    kws = existing_keywords()
    types = type_vocabulary()

    for w in spec["keywords"]:
        if w in kws:
            findings.append(("FAIL", f"keyword '{w}' already exists in "
                                      f"grammar.py KEYWORDS -- adding it would "
                                      f"redefine existing grammar"))
        if w in types:
            findings.append(("FAIL", f"keyword '{w}' is part of the Dictum type "
                                      f"vocabulary -- it cannot also be a "
                                      f"statement keyword"))
        if not re.fullmatch(r"[a-z][a-z_]*", w):
            findings.append(("FAIL", f"keyword '{w}' is not a plain lowercase "
                                      f"word; Dictum keywords are bare words"))

    # Would this word currently parse as an ordinary identifier? If so,
    # promoting it to a keyword silently changes the meaning of any existing
    # program that used it as a variable name.
    for w in spec["keywords"]:
        probe = (f"program probe_{w}\n"
                 f"    keep {w} as whole number with value 1\n"
                 f'    print the text "v:" and {w}\n'
                 f"end program\n")
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "probe.dict")
            open(p, "w").write(probe)
            r = subprocess.run(
                [sys.executable, CLI, p, "--backend", "c", "--output",
                 os.path.join(tmp, "probe.c")],
                capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                findings.append(("WARN", f"'{w}' is currently valid as an "
                                          f"identifier -- existing programs using "
                                          f"it as a variable name would break"))
        except Exception:
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # The existing suite must still pass. A dictation that breaks what
    # already works is not compatible, whatever else is true about it.
    try:
        r = subprocess.run([sys.executable, SELFTEST], capture_output=True,
                           text=True, timeout=1800, cwd=COMPILER_DIR)
        tail = r.stdout[-1500:]
        m = re.search(r"Regression:\s*(\d+)/(\d+)", tail)
        if not m:
            findings.append(("FAIL", "could not read regression results"))
        elif m.group(1) != m.group(2):
            findings.append(("FAIL", f"regression suite is NOT clean "
                                      f"({m.group(1)}/{m.group(2)}) -- fix that "
                                      f"before adding grammar"))
        else:
            findings.append(("OK", f"regression suite clean ({m.group(0)})"))
    except subprocess.TimeoutExpired:
        findings.append(("FAIL", "regression suite timed out"))

    failed = any(k == "FAIL" for k, _ in findings)
    return (not failed), findings


# ---------------------------------------------------------------------------
# Gate 2 -- FUNCTIONALITY
# ---------------------------------------------------------------------------

def gate_test(spec: dict) -> "tuple[bool, list]":
    findings = []
    example = spec.get("example", "")
    expect = spec.get("expect_output", "")
    if not example.strip():
        return False, [("FAIL", "no example program -- cannot test function")]
    if not expect:
        return False, [("FAIL", "no expect_output -- a test that can't fail "
                                 "proves nothing")]

    outputs = {}
    for b in BACKENDS:
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "ex.dict")
            open(p, "w").write(example)
            out_bin = os.path.join(tmp, "ex")
            cmd = [sys.executable, CLI, p, "--backend", b, "--compile",
                   "--output", out_bin]
            for lib in spec.get("link", []):
                cmd += ["--link", lib]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                findings.append(("FAIL", f"[{b}] did not compile: "
                                          f"{((r.stderr or '') + (r.stdout or ''))[-300:]}"))
                continue
            run = subprocess.run([out_bin], capture_output=True, text=True, timeout=30)
            if run.returncode != 0:
                findings.append(("FAIL", f"[{b}] built but exited {run.returncode}"))
                continue
            outputs[b] = run.stdout
            if expect not in run.stdout:
                findings.append(("FAIL", f"[{b}] output {run.stdout[:120]!r} "
                                          f"does not contain {expect!r}"))
            else:
                findings.append(("OK", f"[{b}] compiled, ran, output correct"))
        except subprocess.TimeoutExpired:
            findings.append(("FAIL", f"[{b}] timed out"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if len(outputs) == len(BACKENDS):
        # All three built AND ran -- now they must AGREE. Trailing-newline
        # differences are the one known, documented cross-backend
        # divergence (printf vs echo) and are normalized out here rather
        # than reported as a dictation failure.
        norm = {b: "\n".join(o.splitlines()) for b, o in outputs.items()}
        if len(set(norm.values())) > 1:
            findings.append(("FAIL", f"backends DISAGREE on output: {outputs}"))
        else:
            findings.append(("OK", "all three backends agree on output"))

    failed = any(k == "FAIL" for k, _ in findings)
    return (not failed), findings


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def report(findings) -> None:
    for kind, msg in findings:
        mark = {"OK": "  ok  ", "WARN": " warn ", "FAIL": " FAIL "}[kind]
        print(f"[{mark}] {msg}")


def cmd_list(args) -> int:
    names = sorted(list_names())
    if not names:
        print(f"no dictations yet in {DICTATION_DIR}")
        return 0
    print(f"{'name':<16} {'state':<12} keywords")
    for n in names:
        s = load(n)
        print(f"{n:<16} {s.get('state','?'):<12} {','.join(s.get('keywords',[]))}")
    print("\nOnly dictations in state 'working' are usable.")
    return 0


def cmd_propose(args) -> int:
    if os.path.exists(spec_path(args.name)):
        raise SystemExit(f"dictation '{args.name}' already exists; "
                         f"use `show` or delete it first")
    example = ""
    if args.example:
        example = open(args.example).read()
    spec = {
        "name": args.name,
        "description": args.description,
        "syntax": args.syntax,
        "keywords": args.keywords or [args.name],
        "example": example,
        "expect_output": args.expect or "",
        "link": args.link or [],
        "state": "proposed",
        "check_findings": [],
        "test_findings": [],
    }
    save(spec)
    print(f"proposed '{args.name}' (state: proposed)")
    print(f"  syntax:   {args.syntax}")
    print(f"  keywords: {spec['keywords']}")
    print(f"\nNext: implement it in lexer/parser/grammar KEYWORDS/validator")
    print(f"      AND all three emitters (emit_c.py, emit_cpp.py, emit_nim.py),")
    print(f"      then run:  python3 tools/dictation.py check {args.name}")
    return 0


def cmd_check(args) -> int:
    spec = load(args.name)
    print(f"COMPATIBILITY gate for '{args.name}' -- can this dictation exist here?\n")
    ok, findings = gate_check(spec)
    report(findings)
    spec["check_findings"] = findings
    spec["state"] = "compatible" if ok else "failed"
    save(spec)
    print(f"\nstate -> {spec['state']}")
    if ok:
        print(f"Compatible. This does NOT mean it works yet.")
        print(f"Next: python3 tools/dictation.py test {args.name}")
    return 0 if ok else 1


def cmd_test(args) -> int:
    spec = load(args.name)
    if spec.get("state") not in ("compatible", "working"):
        raise SystemExit(
            f"'{args.name}' is in state '{spec.get('state')}'. Run `check` "
            f"first -- functionality is not tested until compatibility passes.")
    print(f"FUNCTIONALITY gate for '{args.name}' -- does it work on all 3 backends?\n")
    ok, findings = gate_test(spec)
    report(findings)
    spec["test_findings"] = findings
    spec["state"] = "working" if ok else "failed"
    save(spec)
    print(f"\nstate -> {spec['state']}")
    print("USABLE." if ok else "NOT usable.")
    return 0 if ok else 1


def cmd_show(args) -> int:
    print(json.dumps(load(args.name), indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    pp = sub.add_parser("propose")
    pp.add_argument("name")
    pp.add_argument("--syntax", required=True, help="the surface form, e.g. 'unless X then ... end unless'")
    pp.add_argument("--description", required=True, help="what it does")
    pp.add_argument("--keywords", nargs="*", help="new keywords it introduces (default: the name)")
    pp.add_argument("--example", help="path to a .dict file exercising it")
    pp.add_argument("--expect", help="substring the example must print")
    pp.add_argument("--link", nargs="*")
    pp.set_defaults(func=cmd_propose)

    pc = sub.add_parser("check"); pc.add_argument("name"); pc.set_defaults(func=cmd_check)
    pt = sub.add_parser("test");  pt.add_argument("name"); pt.set_defaults(func=cmd_test)
    ps = sub.add_parser("show");  ps.add_argument("name"); ps.set_defaults(func=cmd_show)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
