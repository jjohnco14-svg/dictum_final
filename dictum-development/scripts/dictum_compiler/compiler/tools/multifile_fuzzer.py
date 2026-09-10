#!/usr/bin/env python3
"""
multifile_fuzzer.py — mutation-tests Dictum's multi-file project builder
(project_builder.py) + cross-file `import from C` mechanism, on C and C++
(Nim has no multi-file support at all — a real, separate, known limitation,
not something this tool tests).

This exists because tools/bughunter.dict (the native single-file fuzzer)
structurally cannot reach this surface: it drives dictumc_cli.py directly,
one file at a time. Four real bugs (preamble ordering, a silently-wrong
--backend flag override, C++-only cross-file `use` hoisting, duplicate FFI
symbol definitions) were found by hand-testing this exact surface and were
invisible to a 4+ hour, 5600-round single-file campaign that found zero
crashes — proof the two are genuinely different attack surfaces, not that
one subsumes the other.

Design mirrors bughunter.dict: time-based (reads its duration from a
config file, not a hardcoded iteration count), smoke-tests each backend
before trusting it, archives only interesting findings, writes a live,
periodically-overwritten summary.
"""
from __future__ import annotations
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
PROJECT_BUILDER = os.path.join(COMPILER_DIR, "project_builder.py")

SYSINFO_DICT = '''module sysinfo

    import from C the action getpid takes nothing produces whole number as raw_getpid

    action get_process_id takes nothing produces whole number
        keep p as whole number with value 0
        call raw_getpid giving p
        return p
    end action

end module
'''

MAIN_DICT = '''program main

    use sysinfo

    keep pid as whole number with value 0
    call sysinfo.get_process_id giving pid

    print the text "pid:" and pid

end program
'''


def smoke_test(backend: str) -> bool:
    """Build + run the KNOWN-good project once. Only a backend that passes
    this gets used for the real campaign -- same discipline as bughunter.dict,
    so a missing/broken toolchain shows up as a clean skip, never a false
    'crash'."""
    tmp = os.path.join("/tmp", f"mf_smoke_{backend}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    open(os.path.join(tmp, "sysinfo.dict"), "w").write(SYSINFO_DICT)
    open(os.path.join(tmp, "main.dict"), "w").write(MAIN_DICT)
    out = os.path.join(tmp, "build")
    try:
        r = subprocess.run(
            [sys.executable, PROJECT_BUILDER, tmp, "--backend", backend, "--out", out],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return False
        r2 = subprocess.run(["make"], capture_output=True, text=True, timeout=60, cwd=out)
        if r2.returncode != 0:
            return False
        r3 = subprocess.run([os.path.join(out, "main")], capture_output=True, text=True, timeout=10)
        return "pid:" in r3.stdout
    except Exception:
        return False


def mutate(seed: str, rng: random.Random) -> str:
    """Two strategies, same spirit as bughunter.dict: a safe operator swap
    (plus/other likely-valid), or aggressive truncation (likely-invalid,
    stresses the parser/builder's error handling)."""
    if rng.random() < 0.5:
        return seed.replace("whole number", "decimal number", 1) if "whole number" in seed else seed
    n = len(seed)
    if n < 2:
        return seed
    cut = rng.randint(1, n - 1)
    return seed[:cut]


def classify(build_result: subprocess.CompletedProcess, make_result: "subprocess.CompletedProcess | None") -> str:
    combined = (build_result.stdout or "") + (build_result.stderr or "")
    if make_result is not None:
        combined += (make_result.stdout or "") + (make_result.stderr or "")
    if "Traceback" in combined:
        return "crash"
    if "internal error" in combined:
        return "internal"
    if re.search(r"error|Error", combined):
        return "reject"
    if build_result.returncode == 0 and (make_result is None or make_result.returncode == 0):
        return "ok"
    return "reject"


def main() -> int:
    duration_file = "/tmp/multifile_duration_seconds.txt"
    duration = 60
    if os.path.exists(duration_file):
        try:
            duration = int(open(duration_file).read().strip())
        except ValueError:
            pass

    print(f"multifile_fuzzer.py starting, duration={duration}s", flush=True)
    enabled = {}
    for backend in ("c", "cpp"):
        ok = smoke_test(backend)
        enabled[backend] = ok
        print(f"SMOKE TEST -- {backend}: {int(ok)}", flush=True)

    findings_dir = os.path.join(HERE, "multifile_findings")
    os.makedirs(findings_dir, exist_ok=True)
    summary_path = os.path.join(HERE, "multifile_summary.txt")

    rng = random.Random(os.getpid() ^ int(time.time()))
    counts = {b: {"ok": 0, "reject": 0, "internal": 0, "crash": 0} for b in ("c", "cpp")}
    total = 0
    findings = 0
    start = time.time()
    last_heartbeat = 0

    while True:
        elapsed = time.time() - start
        if elapsed > duration or total > 50000:
            break

        mutant_main = mutate(MAIN_DICT, rng)
        for backend in ("c", "cpp"):
            if not enabled[backend]:
                continue
            tmp = f"/tmp/mf_case_{backend}_{total}"
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            open(os.path.join(tmp, "sysinfo.dict"), "w").write(SYSINFO_DICT)
            open(os.path.join(tmp, "main.dict"), "w").write(mutant_main)
            out = os.path.join(tmp, "build")
            try:
                r = subprocess.run(
                    [sys.executable, PROJECT_BUILDER, tmp, "--backend", backend, "--out", out],
                    capture_output=True, text=True, timeout=30,
                )
                r2 = None
                if r.returncode == 0:
                    r2 = subprocess.run(["make"], capture_output=True, text=True, timeout=30, cwd=out)
                verdict = classify(r, r2)
            except subprocess.TimeoutExpired:
                verdict = "crash"
                r = r2 = None
            counts[backend][verdict] += 1
            if verdict in ("crash", "internal"):
                findings += 1
                fname = os.path.join(findings_dir, f"case_{backend}_{findings}_main.dict")
                open(fname, "w").write(mutant_main)
            shutil.rmtree(tmp, ignore_errors=True)
        total += 1

        elapsed = time.time() - start
        if elapsed - last_heartbeat > 30:
            last_heartbeat = elapsed
            summary = {
                "elapsed_seconds": int(elapsed), "total_runs": total,
                "findings_count": findings, "counts": counts,
            }
            open(summary_path, "w").write(json.dumps(summary, indent=2))
            print(f"--- progress --- {json.dumps(summary)}", flush=True)

    summary = {"elapsed_seconds": int(time.time() - start), "total_runs": total,
               "findings_count": findings, "counts": counts}
    open(summary_path, "w").write(json.dumps(summary, indent=2))
    print(f"DONE {json.dumps(summary)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
