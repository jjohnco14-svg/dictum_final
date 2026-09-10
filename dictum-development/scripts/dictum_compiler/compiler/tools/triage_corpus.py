#!/usr/bin/env python3
"""
triage_corpus.py — run a broad corpus of REAL Dictum programs across all
three backends, collect every failure, and group them by likely root cause.

WHY THIS EXISTS (the methodology change)
----------------------------------------
Up to now the loop has been: find one bug -> patch it -> repeat. That fixes
symptoms in isolation and hides shared causes. Three separate "fails only on
Nim" bugs found one at a time look like three problems; seen together on one
page they're obviously ONE problem (Nim is strictly typed and the other two
backends are not), which is a different and much better fix.

So this tool deliberately DOES NOT FIX ANYTHING. It gathers evidence first:
every program, every backend, every failure, grouped. The output is a bug
inventory to reason about, not a patch queue to grind through.

Each program is a genuine, complete, self-contained thing a person might
actually write -- not a mutation of a fixture, and not (importantly) a
construct chosen because I already know it works.

Usage:
    python3 triage_corpus.py [--compiler DIR] [--json OUT.json]
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
DEFAULT_COMPILER = os.path.dirname(HERE)
BACKENDS = ("c", "cpp", "nim")

# ---------------------------------------------------------------------------
# The corpus. `expect` is the correct output with all whitespace removed, so
# the known printf-vs-echo newline difference isn't reported as a failure.
# Programs are grouped by the feature area they exercise.
# ---------------------------------------------------------------------------
CORPUS = [
    # ---- shapes ----
    ("shape_basic", "shape", '''shape Point holds:
    x as whole number
    y as whole number
end shape

program p
    keep pt as Point with no value
    set x of pt to 3
    set y of pt to 4
    print the text "x=" and x of pt and ",y=" and y of pt
end program
''', "x=3,y=4"),

    ("shape_in_action", "shape", '''shape Box holds:
    w as whole number
    h as whole number
end shape

action area takes b as Box produces whole number
    keep r as whole number with value 0
    put w of b times h of b into r
    return r
end action

program p
    keep bx as Box with no value
    set w of bx to 5
    set h of bx to 6
    keep a as whole number with value 0
    call area with bx giving a
    print the text "a=" and a
end program
''', "a=30"),

    # ---- text operations ----
    ("text_concat", "text", '''use Text

program p
    keep a as text with value "foo"
    keep b as text with value ""
    call Text.concat with a and "bar" giving b
    print the text "s=" and b
end program
''', "s=foobar"),

    ("text_length", "text", '''use Text

program p
    keep a as text with value "hello"
    keep n as whole number with value 0
    call Text.length with a giving n
    print the text "n=" and n
end program
''', "n=5"),

    ("text_contains", "text", '''use Text

program p
    keep a as text with value "hello world"
    keep f as truth value with value 0
    call Text.contains with a and "world" giving f
    if f is equal to 1 then
        print the text "found"
    otherwise
        print the text "missing"
    end if
end program
''', "found"),

    # ---- loops ----
    ("for_each_list", "loops", '''program p
    keep xs as growable list of whole number with no value
    add 10 to xs
    add 20 to xs
    keep total as whole number with value 0
    for each n in xs repeat
        put total plus n into total
    end for
    print the text "t=" and total
end program
''', "t=30"),

    ("repeat_times", "loops", '''program p
    keep n as whole number with value 0
    repeat 4 times using i
        put n plus 3 into n
    end repeat
    print the text "n=" and n
end program
''', "n=12"),

    ("nested_while", "loops", '''program p
    keep i as whole number with value 0
    keep total as whole number with value 0
    while i is less than 3 repeat
        keep j as whole number with value 0
        while j is less than 2 repeat
            put total plus 1 into total
            put j plus 1 into j
        end while
        put i plus 1 into i
    end while
    print the text "t=" and total
end program
''', "t=6"),

    # ---- actions ----
    ("action_recursive", "actions", '''action fact takes n as whole number produces whole number
    if n is less than 2 then
        return 1
    end if
    keep sub as whole number with value 0
    keep less as whole number with value 0
    put n minus 1 into less
    call fact with less giving sub
    keep r as whole number with value 0
    put n times sub into r
    return r
end action

program p
    keep v as whole number with value 0
    call fact with 5 giving v
    print the text "f=" and v
end program
''', "f=120"),

    ("action_multi_return_types", "actions", '''action geti takes nothing produces whole number
    return 7
end action

action gett takes nothing produces text
    return "seven"
end action

program p
    keep a as whole number with value 0
    call geti giving a
    keep b as text with value ""
    call gett giving b
    print the text "a=" and a and ",b=" and b
end program
''', "a=7,b=seven"),

    # ---- decimals / mixed arithmetic ----
    ("decimal_arith", "decimal", '''program p
    keep d as decimal number with value 1.5
    put d plus 2.25 into d
    print the text "d=" and d
end program
''', "d=3.750000"),

    ("decimal_compare", "decimal", '''program p
    keep d as decimal number with value 2.5
    if d is greater than 1.0 then
        print the text "big"
    otherwise
        print the text "small"
    end if
end program
''', "big"),

    # ---- truth values ----
    ("bool_literal_true", "bool", '''program p
    keep f as truth value with value 1
    if f is equal to 1 then
        print the text "on"
    otherwise
        print the text "off"
    end if
end program
''', "on"),

    # ---- error handling ----
    ("attempt_success", "errors", '''action risky takes nothing produces whole number
    return 5
end action

program p
    keep v as whole number with value 0
    attempt
        call risky giving v
    on success
        print the text "ok=" and v
    on failure
        print the text "fail"
    end attempt
end program
''', "ok=5"),

    # ---- collections ----
    ("list_of_text", "collections", '''program p
    keep xs as growable list of text with no value
    add "a" to xs
    add "b" to xs
    print the text "n=" and the count of xs
end program
''', "n=2"),

    ("map_basic", "collections", '''use Map

program p
    keep m as map of text to whole number with no value
    put 5 at "five" in m
    print the text "v=" and the value at "five" in m
end program
''', "v=5"),
]


def run_one(name, src, expect, compiler_dir, backend, workdir):
    """Returns (status, detail). status in {ok, wrong, build_fail, run_fail}."""
    d = os.path.join(workdir, f"{name}_{backend}")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    p = os.path.join(d, "m.dict")
    open(p, "w").write(src)
    out_bin = os.path.join(d, "m")
    cli = os.path.join(compiler_dir, "dictumc_cli.py")
    try:
        r = subprocess.run(
            [sys.executable, cli, p, "--backend", backend, "--compile", "--output", out_bin],
            capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "build_fail", "compile timed out"
    if r.returncode != 0:
        err = ((r.stderr or "") + (r.stdout or "")).strip()
        line = ""
        for l in err.splitlines():
            if re.search(r"error", l, re.I):
                line = l.strip()
                break
        return "build_fail", (line or err[-200:])
    try:
        run = subprocess.run([out_bin], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return "run_fail", "binary timed out"
    if run.returncode != 0:
        return "run_fail", f"exit {run.returncode}"
    got = "".join(run.stdout.split())
    if got != expect:
        return "wrong", f"got {got!r} want {expect!r}"
    return "ok", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", default=DEFAULT_COMPILER)
    ap.add_argument("--json")
    args = ap.parse_args()

    workdir = tempfile.mkdtemp(prefix="triage_")
    inventory = []

    print(f"triage_corpus: {len(CORPUS)} real programs x {len(BACKENDS)} backends "
          f"= {len(CORPUS)*len(BACKENDS)} builds")
    print("collecting failures WITHOUT fixing, so root causes can be seen together\n")

    try:
        for name, area, src, expect in CORPUS:
            row = {"program": name, "area": area, "results": {}}
            marks = []
            for b in BACKENDS:
                status, detail = run_one(name, src, expect, args.compiler, b, workdir)
                row["results"][b] = {"status": status, "detail": detail}
                marks.append({"ok": ".", "wrong": "W", "build_fail": "B",
                              "run_fail": "R"}[status])
            inventory.append(row)
            flag = "" if all(m == "." for m in marks) else "   <-- FAILURE"
            print(f"  {name:<28} {area:<12} c:{marks[0]} cpp:{marks[1]} nim:{marks[2]}{flag}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # ---- inventory ----
    print("\n" + "=" * 72)
    print("BUG INVENTORY (grouped, not yet fixed)")
    print("=" * 72)

    failures = [r for r in inventory
                if any(v["status"] != "ok" for v in r["results"].values())]
    if not failures:
        print("no failures in this corpus")
    else:
        # Group by the shape of the failure: which backends failed together.
        groups = {}
        for r in failures:
            failed_on = tuple(b for b in BACKENDS if r["results"][b]["status"] != "ok")
            groups.setdefault(failed_on, []).append(r)

        for failed_on, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"\n--- fails on {'+'.join(failed_on)} "
                  f"({len(rows)} program{'s' if len(rows) != 1 else ''}) ---")
            for r in rows:
                b0 = failed_on[0]
                res = r["results"][b0]
                print(f"  [{r['area']:<11}] {r['program']:<28} {res['status']}")
                print(f"                {res['detail'][:150]}")

        print(f"\n{len(failures)} of {len(CORPUS)} programs failed on at least one backend.")
        print("Group by the 'fails on' headers above: a group that fails on exactly")
        print("one backend usually shares ONE root cause, not N separate bugs.")

    if args.json:
        json.dump(inventory, open(args.json, "w"), indent=2)
        print(f"\nfull inventory -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
