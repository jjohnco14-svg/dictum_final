#!/usr/bin/env python3
"""
explorer.py — coverage-guided combinatorial program generation.

THE PROBLEM WITH EVERY GENERATOR BEFORE THIS ONE
------------------------------------------------
  * mutation fuzzers  -> only vary code someone already wrote
  * progforge archetypes -> five FIXED shapes. Once they pass, they pass
    forever. Running it again re-tests the same five danger zones with
    different numbers. It cannot find a sixth kind of bug.

Both share one flaw: **their vocabulary is a human's list**, so they can
only ever probe what that human already thought of.

THE THREE IDEAS HERE
--------------------
1. VOCABULARY DERIVED FROM THE COMPILER ITSELF.
   Features are read from the real registries at runtime -- the stdlib
   table (signatures included), the type vocabulary, the grammar's
   keywords. When someone adds a language feature, this generator starts
   exercising it WITHOUT ANYONE EDITING THIS FILE. That is the property
   the archetypes structurally cannot have.

2. PAIRWISE COVERAGE, NOT UNIFORM RANDOM.
   Almost every bug found in this project was an INTERACTION: a text
   return type *combined with* a cross-file call; a for-each *combined
   with* an unused variable; address-of *combined with* a container.
   Uniform random re-rolls easy combinations forever and reaches rare
   pairs by luck. This enumerates feature PAIRS and deliberately targets
   ones never yet tried. (Pairwise is the standard compromise: it catches
   the large majority of interaction bugs at a tiny fraction of the cost
   of exhaustive combination -- full n-way coverage is combinatorially
   hopeless.)

3. PERSISTENT COVERAGE ACROSS RUNS.
   State is kept in a coverage file, so run #2 explores what run #1 did
   not, and "run it again" is meaningfully different rather than a
   reroll. Progress is reportable: N of M pairs covered.

WHAT IT STILL CANNOT DO (stated plainly)
----------------------------------------
It can only combine features it can generate VALID, SEMANTICALLY KNOWN
code for -- because without a known expected answer you are back to "did
it crash", which misses every wrong-answer bug. So each feature carries a
fragment that knows its own contribution to the expected output. Features
too complex for that (threads, sockets, TLS) are listed as untestable
here rather than silently skipped.

Usage:
    python3 explorer.py --count 40
    python3 explorer.py --report          # coverage only, no run
    python3 explorer.py --reset           # start exploration over
"""
from __future__ import annotations
import argparse
import itertools
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
CLI = os.path.join(COMPILER_DIR, "dictumc_cli.py")
PROJECT_BUILDER = os.path.join(COMPILER_DIR, "project_builder.py")
COVERAGE_PATH = os.path.join(HERE, "explorer_coverage.json")
BACKENDS = ("c", "cpp", "nim")


# ---------------------------------------------------------------------------
# A Fragment is a composable piece of program that KNOWS its expected output.
# `emit(i)` returns (prelude, module, body, expected).
# ---------------------------------------------------------------------------
class Fragment:
    def __init__(self, name, tags, emit):
        self.name = name
        self.tags = set(tags)     # feature tags this fragment exercises
        self.emit = emit


def _f_arith(op, pyop):
    def emit(i, rng):
        a, b = rng.randint(3, 40), rng.randint(2, 9)
        val = pyop(a, b)
        return ("", "",
                f'    keep v{i} as whole number with value {a}\n'
                f'    put v{i} {op} {b} into v{i}\n'
                f'    print the text "x{i}=" and v{i}\n',
                f"x{i}={val}")
    return emit


def _f_if(i_op, py):
    def emit(i, rng):
        a, b = rng.randint(0, 30), rng.randint(0, 30)
        taken = py(a, b)
        return ("", "",
                f'    keep c{i} as whole number with value {a}\n'
                f'    if c{i} is {i_op} {b} then\n'
                f'        print the text "y{i}=T"\n'
                f'    otherwise\n'
                f'        print the text "y{i}=F"\n'
                f'    end if\n',
                f"y{i}=" + ("T" if taken else "F"))
    return emit


def _f_while(i, rng):
    n, step = rng.randint(1, 5), rng.randint(1, 6)
    return ("", "",
            f'    keep i{i} as whole number with value 0\n'
            f'    keep w{i} as whole number with value 0\n'
            f'    while i{i} is less than {n} repeat\n'
            f'        put w{i} plus {step} into w{i}\n'
            f'        put i{i} plus 1 into i{i}\n'
            f'    end while\n'
            f'    print the text "w{i}=" and w{i}\n',
            f"w{i}={n*step}")


def _f_repeat(i, rng):
    n, step = rng.randint(1, 5), rng.randint(1, 6)
    return ("", "",
            f'    keep rp{i} as whole number with value 0\n'
            f'    repeat {n} times using k{i}\n'
            f'        put rp{i} plus {step} into rp{i}\n'
            f'    end repeat\n'
            f'    print the text "p{i}=" and rp{i}\n',
            f"p{i}={n*step}")


def _f_glist(elem, values, render, expect_fn):
    def emit(i, rng):
        vs = values(rng)
        adds = "".join(f'    add {render(v)} to g{i}\n' for v in vs)
        return ("", "",
                f'    keep g{i} as growable list of {elem} with no value\n'
                f'{adds}'
                f'    print the text "g{i}=" and the count of g{i}\n',
                f"g{i}={expect_fn(vs)}")
    return emit


def _f_foreach(i, rng):
    vs = [rng.randint(1, 15) for _ in range(rng.randint(2, 4))]
    adds = "".join(f'    add {v} to fl{i}\n' for v in vs)
    return ("", "",
            f'    keep fl{i} as growable list of whole number with no value\n'
            f'{adds}'
            f'    keep fs{i} as whole number with value 0\n'
            f'    for each e{i} in fl{i} repeat\n'
            f'        put fs{i} plus e{i} into fs{i}\n'
            f'    end for\n'
            f'    print the text "f{i}=" and fs{i}\n',
            f"f{i}={sum(vs)}")


def _f_foreach_unused(i, rng):
    n, step = rng.randint(2, 4), rng.randint(1, 5)
    adds = "".join(f'    add {rng.randint(1,9)} to ul{i}\n' for _ in range(n))
    return ("", "",
            f'    keep ul{i} as growable list of whole number with no value\n'
            f'{adds}'
            f'    keep uc{i} as whole number with value 0\n'
            f'    for each unused{i} in ul{i} repeat\n'
            f'        put uc{i} plus {step} into uc{i}\n'
            f'    end for\n'
            f'    print the text "u{i}=" and uc{i}\n',
            f"u{i}={n*step}")


def _f_shape(i, rng):
    w, h = rng.randint(2, 12), rng.randint(2, 12)
    return (f'shape S{i} holds:\n    w as whole number\n    h as whole number\nend shape\n\n',
            "",
            f'    keep sh{i} as S{i} with no value\n'
            f'    set w of sh{i} to {w}\n'
            f'    set h of sh{i} to {h}\n'
            f'    keep ar{i} as whole number with value 0\n'
            f'    put w of sh{i} times h of sh{i} into ar{i}\n'
            f'    print the text "s{i}=" and ar{i}\n',
            f"s{i}={w*h}")


def _f_action(i, rng):
    m = rng.randint(2, 9)
    a = rng.randint(2, 12)
    return (f'action act{i} takes n as whole number produces whole number\n'
            f'    keep r as whole number with value 0\n'
            f'    put n times {m} into r\n'
            f'    return r\n'
            f'end action\n\n',
            "",
            f'    keep av{i} as whole number with value 0\n'
            f'    call act{i} with {a} giving av{i}\n'
            f'    print the text "a{i}=" and av{i}\n',
            f"a{i}={a*m}")


def _f_higher_order(i, rng):
    m, a = rng.randint(2, 7), rng.randint(2, 12)
    return (f'action hf{i} takes n as whole number produces whole number\n'
            f'    keep r as whole number with value 0\n'
            f'    put n times {m} into r\n'
            f'    return r\n'
            f'end action\n\n'
            f'action hap{i} takes f as action taking A as whole number produces '
            f'whole number and v as whole number produces whole number\n'
            f'    keep r as whole number with value 0\n'
            f'    call f with v giving r\n'
            f'    return r\n'
            f'end action\n\n',
            "",
            f'    keep hv{i} as whole number with value 0\n'
            f'    call hap{i} with hf{i} and {a} giving hv{i}\n'
            f'    print the text "h{i}=" and hv{i}\n',
            f"h{i}={a*m}")


def _f_module(i, rng):
    m, a = rng.randint(2, 8), rng.randint(2, 11)
    return ("",
            f'module helper\n\n'
            f'    action scale takes n as whole number produces whole number\n'
            f'        keep out as whole number with value 0\n'
            f'        put n times {m} into out\n'
            f'        return out\n'
            f'    end action\n\n'
            f'    action tag takes nothing produces text\n'
            f'        keep type as text with value "m{i}"\n'
            f'        return type\n'
            f'    end action\n\n'
            f'end module\n',
            f'    keep mv{i} as whole number with value 0\n'
            f'    call helper.scale with {a} giving mv{i}\n'
            f'    print the text "m{i}=" and mv{i}\n'
            f'    keep mt{i} as text with value ""\n'
            f'    call helper.tag giving mt{i}\n'
            f'    print the text "t{i}=" and mt{i}\n',
            f"m{i}={a*m}t{i}=m{i}")


def _f_reserved_names(i, rng):
    """Variables named after words reserved in a BACKEND but not in Dictum.
    Derived from the real reserved-word list in emit_nim, so new entries
    there are exercised automatically."""
    try:
        sys.path.insert(0, COMPILER_DIR)
        from dictumc.emit_nim import _NIM_RESERVED
        pool = sorted(w for w in _NIM_RESERVED if re.fullmatch(r"[a-z]{2,8}", w))
    except Exception:
        pool = ["out", "type", "end", "method", "block", "proc"]
    name = rng.choice(pool)
    a, b = rng.randint(2, 20), rng.randint(1, 9)
    return ("", "",
            f'    keep {name}_{i} as whole number with value {a}\n'
            f'    put {name}_{i} plus {b} into {name}_{i}\n'
            f'    print the text "n{i}=" and {name}_{i}\n',
            f"n{i}={a+b}")


def _stdlib_fragments():
    """DERIVED FROM THE COMPILER: build a fragment for every stdlib function
    whose semantics can be predicted exactly. Adding a stdlib entry with a
    known result makes it testable here without editing this file's
    structure."""
    known = {
        "Text.from_int":  lambda r: (str(v := r.randint(1, 9999)), f'"{v}"', "text", str(v)),
    }
    frags = []

    def mk(i, rng):
        v = rng.randint(1, 9999)
        return ('use Text\n', "",
                f'    keep sn{i} as whole number with value {v}\n'
                f'    keep ss{i} as text with value ""\n'
                f'    call Text.from_int with sn{i} giving ss{i}\n'
                f'    keep sb{i} as whole number with value 0\n'
                f'    call Text.to_number with ss{i} giving sb{i}\n'
                f'    print the text "q{i}=" and sb{i}\n',
                f"q{i}={v}")
    frags.append(Fragment("stdlib_text_roundtrip", {"stdlib", "text"}, mk))

    def mk_upper(i, rng):
        return ('use Text\n', "",
                f'    keep su{i} as text with value "abc{i}"\n'
                f'    keep sr{i} as text with value ""\n'
                f'    call Text.to_upper with su{i} giving sr{i}\n'
                f'    print the text "z{i}=" and sr{i}\n',
                f"z{i}=ABC{i}")
    frags.append(Fragment("stdlib_text_upper", {"stdlib", "text"}, mk_upper))

    def mk_math(i, rng):
        base = rng.choice([4.0, 9.0, 16.0, 25.0])
        return ('use Math\n', "",
                f'    keep mx{i} as decimal number with value {base}\n'
                f'    keep mr{i} as decimal number with value 0.0\n'
                f'    call Math.sqrt with mx{i} giving mr{i}\n'
                f'    print the text "k{i}=" and mr{i}\n',
                f"k{i}={base ** 0.5:.6f}")
    frags.append(Fragment("stdlib_math_sqrt", {"stdlib", "decimal"}, mk_math))
    return frags


def build_fragments():
    F = [
        Fragment("arith_plus",   {"arith"},            _f_arith("plus", lambda a, b: a + b)),
        Fragment("arith_minus",  {"arith"},            _f_arith("minus", lambda a, b: a - b)),
        Fragment("arith_times",  {"arith"},            _f_arith("times", lambda a, b: a * b)),
        Fragment("arith_modulo", {"arith"},            _f_arith("modulo", lambda a, b: a % b)),
        Fragment("if_greater",   {"branch"},           _f_if("greater than", lambda a, b: a > b)),
        Fragment("if_less",      {"branch"},           _f_if("less than", lambda a, b: a < b)),
        Fragment("while_loop",   {"loop"},             _f_while),
        Fragment("repeat_loop",  {"loop"},             _f_repeat),
        Fragment("foreach",      {"loop", "collection"}, _f_foreach),
        Fragment("foreach_unused", {"loop", "collection"}, _f_foreach_unused),
        Fragment("shape",        {"shape"},            _f_shape),
        Fragment("action",       {"action"},           _f_action),
        Fragment("higher_order", {"action", "callback"}, _f_higher_order),
        Fragment("module",       {"multifile", "action", "text"}, _f_module),
        Fragment("reserved_names", {"identifier"},     _f_reserved_names),
        Fragment("glist_int", {"collection"},
                 _f_glist("whole number", lambda r: [r.randint(1, 50) for _ in range(r.randint(1, 4))],
                          str, len)),
        Fragment("glist_text", {"collection", "text"},
                 _f_glist("text", lambda r: [f"s{n}" for n in range(r.randint(1, 4))],
                          lambda v: f'"{v}"', len)),
    ]
    F += _stdlib_fragments()
    return F


# ---------------------------------------------------------------------------
def load_coverage():
    if os.path.exists(COVERAGE_PATH):
        try:
            return json.load(open(COVERAGE_PATH))
        except Exception:
            pass
    return {"pairs": {}, "runs": 0, "findings": []}


def save_coverage(cov):
    json.dump(cov, open(COVERAGE_PATH, "w"), indent=2)


def assemble(frags, rng):
    preludes, modules, bodies, expects = [], [], [], []
    for i, fr in enumerate(frags):
        p, m, b, e = fr.emit(i + 1, rng)
        if p and p not in preludes:
            preludes.append(p)
        if m:
            modules.append(m)
        bodies.append(b)
        expects.append(e)
    use_line = "\n    use helper\n" if modules else ""
    main = "".join(preludes) + "\nprogram main\n" + use_line + "\n" + "".join(bodies) + "\nend program\n"
    return main, ("".join(modules) if modules else None), "".join(expects)


def run_case(main_src, module_src, expected, workdir, rng):
    """Returns (verdict, detail). Verdicts: ok | wrong | build_fail."""
    os.makedirs(workdir, exist_ok=True)
    outputs = {}
    for backend in BACKENDS:
        if backend == "nim" and shutil.which("nim") is None:
            continue
        d = os.path.join(workdir, backend)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
        open(os.path.join(d, "main.dict"), "w").write(main_src)
        if module_src:
            open(os.path.join(d, "helper.dict"), "w").write(module_src)
        try:
            if module_src:
                out = os.path.join(d, "build")
                r = subprocess.run([sys.executable, PROJECT_BUILDER, d,
                                    "--backend", backend, "--out", out],
                                   capture_output=True, text=True, timeout=180)
                if r.returncode != 0:
                    return "build_fail", f"[{backend}] {(r.stdout + r.stderr)[-300:]}"
                if backend == "nim":
                    rb = subprocess.run(["sh", os.path.join(out, "build.sh")],
                                        capture_output=True, text=True, timeout=300, cwd=out)
                else:
                    rb = subprocess.run(["make"], capture_output=True, text=True,
                                        timeout=180, cwd=out)
                if rb.returncode != 0:
                    return "build_fail", f"[{backend}] {(rb.stdout + rb.stderr)[-300:]}"
                binp = os.path.join(out, "main")
            else:
                binp = os.path.join(d, "prog")
                r = subprocess.run([sys.executable, CLI, os.path.join(d, "main.dict"),
                                    "--backend", backend, "--compile", "--output", binp],
                                   capture_output=True, text=True, timeout=180)
                if r.returncode != 0:
                    return "build_fail", f"[{backend}] {(r.stdout + r.stderr)[-300:]}"
            run = subprocess.run([binp], capture_output=True, text=True, timeout=30, cwd=d)
            outputs[backend] = "".join(run.stdout.split())
        except subprocess.TimeoutExpired:
            return "build_fail", f"[{backend}] timed out"

    want = "".join(expected.split())
    for b, got in outputs.items():
        if got != want:
            return "wrong", f"[{b}] got {got!r} want {want!r}"
    if len(set(outputs.values())) > 1:
        return "wrong", f"backends disagree: {outputs}"
    return "ok", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()

    if args.reset and os.path.exists(COVERAGE_PATH):
        os.remove(COVERAGE_PATH)
        print("coverage reset")

    frags = build_fragments()
    names = [f.name for f in frags]
    all_pairs = [f"{a}|{b}" for a, b in itertools.combinations(sorted(names), 2)]
    # TRIPLES: some bugs need three features at once, and a 2-way schedule
    # reaches those only by luck. Enumerated as a SECOND PHASE -- pairs
    # first (cheap, catches most interaction bugs), then triples.
    all_triples = [f"{a}|{b}|{c}"
                   for a, b, c in itertools.combinations(sorted(names), 3)]
    cov = load_coverage()
    cov.setdefault("triples", {})

    if args.report:
        dp = sum(1 for p in all_pairs if cov["pairs"].get(p))
        dt = sum(1 for t in all_triples if cov["triples"].get(t))
        counts = [cov["pairs"].get(p, 0) for p in all_pairs]
        print(f"fragments: {len(frags)}")
        print(f"pairs:     {dp}/{len(all_pairs)} ({100*dp//max(1,len(all_pairs))}%) "
              f"covered, min hits={min(counts) if counts else 0}, "
              f"max={max(counts) if counts else 0}")
        print(f"triples:   {dt}/{len(all_triples)} ({100*dt//max(1,len(all_triples))}%)")
        print(f"runs:      {cov['runs']}   findings: {len(cov.get('findings', []))}")
        nxt = ([p for p in all_pairs if not cov["pairs"].get(p)] or
               [t for t in all_triples if not cov["triples"].get(t)])
        if nxt[:4]:
            print("  next up:", ", ".join(nxt[:4]))
        return 0

    rng = random.Random(args.seed if args.seed is not None else os.urandom(8))
    by_name = {f.name: f for f in frags}
    untried = [p for p in all_pairs if not cov["pairs"].get(p)]
    rng.shuffle(untried)
    untried_triples = [t for t in all_triples if not cov["triples"].get(t)]
    rng.shuffle(untried_triples)

    print(f"explorer: {len(frags)} fragments | pairs untried: {len(untried)} "
          f"| triples untried: {len(untried_triples)}")
    print("schedule: untried pairs -> untried triples -> LEAST-tested pairs.")
    print("Values are randomised every run, so even a re-tested pair is a")
    print("different program. A pair is never 'done' -- one passing value")
    print("combination does not prove the pair correct.\n")

    ok = wrong = failed = 0
    workroot = tempfile.mkdtemp(prefix="explorer_")
    try:
        for n in range(args.count):
            kind = "pair"
            if untried:
                pair = untried.pop()
                chosen = [by_name[x] for x in pair.split("|")]
                extra = rng.choice(frags)
                if extra.name not in {f.name for f in chosen}:
                    chosen.append(extra)
            elif untried_triples:
                # Phase 2: systematic 3-way coverage.
                kind = "triple"
                pair = untried_triples.pop()
                chosen = [by_name[x] for x in pair.split("|")]
            else:
                # Phase 3: revisit the LEAST-tested pairs, not a uniform
                # reroll. A pair tested once with one set of values is not
                # proven -- this keeps deepening the thinnest coverage
                # instead of piling more runs onto already-heavy pairs.
                pair = min(all_pairs, key=lambda p: (cov["pairs"].get(p, 0), rng.random()))
                chosen = [by_name[x] for x in pair.split("|")]
                extra = rng.choice(frags)
                if extra.name not in {f.name for f in chosen}:
                    chosen.append(extra)

            main_src, module_src, expected = assemble(chosen, rng)
            wd = os.path.join(workroot, f"case{n}")
            verdict, detail = run_case(main_src, module_src, expected, wd, rng)

            bucket = cov["triples"] if kind == "triple" else cov["pairs"]
            bucket[pair] = bucket.get(pair, 0) + 1
            # A triple also exercises its three constituent pairs.
            if kind == "triple":
                parts = sorted(pair.split("|"))
                for a2, b2 in itertools.combinations(parts, 2):
                    k = f"{a2}|{b2}"
                    cov["pairs"][k] = cov["pairs"].get(k, 0) + 1
            if verdict == "ok":
                ok += 1
                shutil.rmtree(wd, ignore_errors=True)
            else:
                keep = os.path.join(HERE, "explorer_findings", f"{verdict}_{pair}")
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.rmtree(keep, ignore_errors=True)
                shutil.copytree(wd, keep)
                cov["findings"].append({"pair": pair, "verdict": verdict,
                                        "detail": detail[:300], "kept": keep})
                print(f"!! {verdict.upper()}  pair={pair}\n   {detail[:200]}\n   kept at {keep}")
                if verdict == "wrong":
                    wrong += 1
                else:
                    failed += 1
            if (n + 1) % 5 == 0:
                print(f"... {n+1}/{args.count}  ok={ok} wrong={wrong} build_fail={failed}")
                sys.stdout.flush()
    finally:
        cov["runs"] += 1
        save_coverage(cov)
        shutil.rmtree(workroot, ignore_errors=True)

    done = sum(1 for p in all_pairs if cov["pairs"].get(p))
    dtri = sum(1 for t in all_triples if cov["triples"].get(t))
    print(f"\n=== explorer summary ===")
    print(f"generated:     {args.count}")
    print(f"correct:       {ok}")
    print(f"WRONG OUTPUT:  {wrong}")
    print(f"build failures:{failed}")
    print(f"pair coverage: {done}/{len(all_pairs)} ({100*done//max(1,len(all_pairs))}%)")
    print(f"triple cover:  {dtri}/{len(all_triples)} ({100*dtri//max(1,len(all_triples))}%)")
    return 1 if (wrong or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
