#!/usr/bin/env python3
"""
differential_fuzzer.py — feeds the SAME mutated .dict source to all three
backends (c / cpp / nim) and flags any DISAGREEMENT: one backend accepting
what another rejects, or two accepting but producing different runtime
output.

WHY THIS IS THE MOST VALUABLE OF THE FUZZERS: the other three
(bughunter.dict, multifile_fuzzer.py, blessed_library_fuzzer.py) all ask
"did anything crash?" — a bar that a compiler can clear while still being
badly wrong. This one asks "do the backends agree?", which catches
*semantic* bugs no crash-hunter can see.

It has already earned its place: on its first real run it found that
`end program` / `end module` / `end if` were OPTIONAL in the parser, so a
truncated .dict file silently compiled to a real, running binary on C and
C++ (Nim's indentation-sensitive output was the only thing rejecting it).
4 divergences in 120 mutants before the fix; 0 after.

Two disagreement classes are reported separately, because they mean very
different things:
  * accept_divergence — backends disagree on whether the source is VALID.
    Usually a frontend (parser/validator) bug, since the frontend is
    shared: if it accepted the source, every backend should get it.
  * output_divergence — all backends accepted and built, but the compiled
    programs printed DIFFERENT things. This is the more serious class:
    same source, same semantics expected, different behavior.
"""
from __future__ import annotations
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
CLI = os.path.join(COMPILER_DIR, "dictumc_cli.py")

BACKENDS = ("c", "cpp", "nim")

SEEDS = [
    'program s0\n    keep x as whole number with value 3\n    put x plus 4 into x\n'
    '    print the text "x:" and x\nend program\n',

    'program s1\n    keep xs as growable list of whole number with no value\n'
    '    add 1 to xs\n    add 2 to xs\n    print the text "count:" and the count of xs\nend program\n',

    'program s2\n    keep a as whole number with value 9\n    keep b as whole number with value 2\n'
    '    if a is greater than b then\n        print the text "yes"\n    otherwise\n'
    '        print the text "no"\n    end if\nend program\n',

    'program s3\n    keep i as whole number with value 0\n    while i is less than 3 repeat\n'
    '        print the text "i:" and i\n        put i plus 1 into i\n    end while\nend program\n',

    'program s4\n    keep t as text with value "hello"\n    print the text "t:" and t\nend program\n',
]

MUTATIONS = [
    ("op_swap",    lambda s, r: s.replace("plus", "modulo", 1)),
    ("cmp_swap",   lambda s, r: s.replace("greater than", "less than", 1)),
    ("num_change", lambda s, r: s.replace("3", str(r.randrange(0, 99)), 1)),
    ("truncate",   lambda s, r: s[:r.randrange(1, len(s))]),
    ("drop_line",  lambda s, r: "\n".join(
        l for i, l in enumerate(s.splitlines()) if i != r.randrange(len(s.splitlines()))) + "\n"),
    ("dup_line",   lambda s, r: (lambda ls, i: "\n".join(ls[:i] + [ls[i]] + ls[i:]) + "\n")(
        s.splitlines(), r.randrange(len(s.splitlines())))),
]


def build(src: str, backend: str, tmpd: str) -> "tuple[bool, str]":
    p = os.path.join(tmpd, "t.dict")
    open(p, "w").write(src)
    out = os.path.join(tmpd, f"t_{backend}")
    try:
        r = subprocess.run(
            [sys.executable, CLI, p, "--backend", backend, "--compile", "--output", out],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    return r.returncode == 0, (r.stdout + r.stderr)[-500:]


def run_bin(path: str) -> "tuple[bool, str]":
    try:
        r = subprocess.run([path], capture_output=True, text=True, timeout=10)
        return r.returncode == 0, r.stdout
    except Exception as e:
        return False, f"RUNFAIL: {e}"


def smoke() -> "tuple[dict, dict]":
    """Every backend must build + run the KNOWN-good seed correctly before
    it's trusted -- otherwise a missing toolchain looks like a divergence."""
    enabled, reasons = {}, {}
    for b in BACKENDS:
        tmpd = tempfile.mkdtemp()
        try:
            ok, log = build(SEEDS[0], b, tmpd)
            if not ok:
                enabled[b], reasons[b] = False, f"build failed: {log[-300:]}"
                continue
            ran, out = run_bin(os.path.join(tmpd, f"t_{b}"))
            if not ran or "x:7" not in out:
                enabled[b], reasons[b] = False, f"ran but wrong output: {out[-200:]!r}"
                continue
            enabled[b] = True
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)
    return enabled, reasons


def main() -> int:
    duration = 60
    df = "/tmp/differential_duration_seconds.txt"
    if os.path.exists(df):
        try:
            duration = int(open(df).read().strip())
        except ValueError:
            pass

    print(f"differential_fuzzer.py starting, duration={duration}s", flush=True)
    enabled, reasons = smoke()
    for b in BACKENDS:
        if enabled.get(b):
            print(f"SMOKE TEST -- {b}: 1", flush=True)
        else:
            print(f"SMOKE TEST -- {b}: 0  SKIPPED because: {reasons.get(b)}", flush=True)

    active = [b for b in BACKENDS if enabled.get(b)]
    findings_dir = os.path.join(HERE, "differential_findings")
    os.makedirs(findings_dir, exist_ok=True)
    summary_path = os.path.join(HERE, "differential_summary.txt")

    if len(active) < 2:
        msg = ("fewer than 2 backends available -- a differential test is "
               "meaningless with one backend. This is an ENVIRONMENT problem, "
               "NOT a clean result.")
        print(msg, flush=True)
        open(summary_path, "w").write(json.dumps(
            {"error": msg, "skip_reasons": reasons}, indent=2))
        return 0

    rng = random.Random(os.getpid() ^ int(time.time()))
    total = 0
    accept_div = 0
    output_div = 0
    newline_div = 0
    by_mutation = {name: 0 for name, _ in MUTATIONS}
    start = time.time()
    last_hb = 0

    while time.time() - start < duration and total < 50000:
        seed = SEEDS[rng.randrange(len(SEEDS))]
        mname, mfn = MUTATIONS[rng.randrange(len(MUTATIONS))]
        try:
            mutant = mfn(seed, rng)
        except Exception:
            continue
        if not mutant.strip():
            continue

        tmpd = tempfile.mkdtemp()
        try:
            built, logs, outputs = {}, {}, {}
            for b in active:
                ok, log = build(mutant, b, tmpd)
                built[b], logs[b] = ok, log
                if ok:
                    ran, out = run_bin(os.path.join(tmpd, f"t_{b}"))
                    outputs[b] = out if ran else None

            if len(set(built.values())) > 1:
                accept_div += 1
                by_mutation[mname] += 1
                fn = os.path.join(findings_dir, f"accept_div_{accept_div}_{mname}.dict")
                open(fn, "w").write(mutant)
                open(fn + ".log", "w").write(json.dumps(
                    {"verdicts": built, "logs": logs}, indent=2))
                print(f"!! ACCEPT DIVERGENCE ({mname}): {built}", flush=True)
            else:
                real = {b: o for b, o in outputs.items() if o is not None}
                # KNOWN, DOCUMENTED divergence: Dictum's `print` maps to
                # printf() on C/C++ (no trailing newline) but `echo` on Nim
                # (always appends one). That is a real cross-backend
                # inconsistency and it is deliberately NOT auto-fixed here:
                # changing `print` semantics would alter the output of every
                # existing Dictum program and every Guide C manifest's
                # expected_stdout, which is a language-design decision, not
                # a bug fix. Counted separately so it can't drown out
                # substantive divergences in the results.
                normalized = {b: "\n".join(o.splitlines()) for b, o in real.items()}
                if len(real) > 1 and len(set(real.values())) > 1 \
                        and len(set(normalized.values())) == 1:
                    newline_div += 1
                elif len(real) > 1 and len(set(real.values())) > 1:
                    output_div += 1
                    by_mutation[mname] += 1
                    fn = os.path.join(findings_dir, f"output_div_{output_div}_{mname}.dict")
                    open(fn, "w").write(mutant)
                    open(fn + ".log", "w").write(json.dumps({"outputs": real}, indent=2))
                    print(f"!! OUTPUT DIVERGENCE ({mname}): {real}", flush=True)
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)
        total += 1

        elapsed = time.time() - start
        if elapsed - last_hb > 30:
            last_hb = elapsed
            s = {"elapsed_seconds": int(elapsed), "total_runs": total,
                 "accept_divergences": accept_div, "output_divergences": output_div,
                 "newline_only_divergences_KNOWN": newline_div,
                 "enabled": enabled, "by_mutation": by_mutation}
            open(summary_path, "w").write(json.dumps(s, indent=2))
            print(f"--- progress --- {json.dumps(s)}", flush=True)

    s = {"elapsed_seconds": int(time.time() - start), "total_runs": total,
         "accept_divergences": accept_div, "output_divergences": output_div,
         "newline_only_divergences_KNOWN": newline_div,
                 "newline_only_divergences_KNOWN": newline_div,
         "enabled": enabled, "skip_reasons": reasons, "by_mutation": by_mutation}
    open(summary_path, "w").write(json.dumps(s, indent=2))
    print(f"DONE {json.dumps(s)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
