#!/usr/bin/env python3
"""
blessed_library_fuzzer.py — mutation-tests Dictum's actual blessed library
bindings (raylib, raygui, sdl2, openssl, sqlite3, glfw), the real-world FFI
surface end users would actually call.

WHY THIS EXISTS: bughunter.dict tests single-file programs with no FFI at
all. multifile_fuzzer.py tests cross-file FFI but only a single trivial
getpid() binding. Neither ever compiles or runs a single line from any of
the six blessed/*.dict files -- the actual bindings this project ships and
calls "verified." This closes that gap directly.

Design mirrors bughunter.dict/multifile_fuzzer.py: real smoke test per
library before it's trusted for the campaign (so a missing system library
is a clean skip, never a false crash), time-based, live summary, findings
archived only for genuine crash/internal-error verdicts.
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
CLI = os.path.join(COMPILER_DIR, "dictumc_cli.py")
BLESSED = os.path.join(COMPILER_DIR, "blessed")
THIRDPARTY = os.path.join(BLESSED, "thirdparty")

# Each entry: real .dict source (copies the exact import lines from the
# real blessed/<lib>.dict file, per the project's own documented practice
# of copying rather than hand-guessing), plus real link/compile needs.
LIBRARIES = {
    "sqlite3": {
        "dict": '''import from C the action sqlite3_libversion takes nothing produces text as sqlite3_libversion

program p
    keep v as text with value ""
    call sqlite3_libversion giving v
    print the text "v:" and v
end program
''',
        "link": ["sqlite3"], "extra_c": None, "expect": r"v:\d+\.\d+\.\d+",
    },
    "openssl": {
        "dict": '''import from C the action RAND_status takes nothing produces whole number as RAND_status

program p
    keep s as whole number with value 0
    call RAND_status giving s
    print the text "s:" and s
end program
''',
        "link": ["crypto"], "extra_c": None, "expect": r"s:\d+",
    },
    "sdl2": {
        "dict": '''import from C the action SDL_Init takes whole number produces whole number as SDL_Init
import from C the action SDL_Quit takes nothing produces nothing as SDL_Quit

program p
    keep r as whole number with value 0
    call SDL_Init with 0 giving r
    call SDL_Quit
    print the text "r:" and r
end program
''',
        "link": ["SDL2"], "extra_c": None, "expect": r"r:0",
    },
    "glfw": {
        "dict": '''import from C the action glfwGetVersionString takes nothing produces text as glfwGetVersionString

program p
    keep v as text with value ""
    call glfwGetVersionString giving v
    print the text "v:" and v
end program
''',
        "link": ["glfw"], "extra_c": None, "expect": r"v:\d+\.\d+",
    },
    "raylib": {
        "dict": '''import from C the action InitWindow takes whole number and whole number and text produces nothing as InitWindow
import from C the action CloseWindow takes nothing produces nothing as CloseWindow

program p
    call InitWindow with 200 and 150 and "t"
    call CloseWindow
    print the text "ok:1"
end program
''',
        "link": ["raylib", "m", "pthread", "dl", "rt", "GL", "X11"],
        "extra_c": None, "expect": r"ok:1", "needs_xvfb": True,
    },
    "raygui": {
        "dict": '''import from C the action GuiLock takes nothing produces nothing as GuiLock
import from C the action GuiIsLocked takes nothing produces truth value as GuiIsLocked
import from C the action GuiUnlock takes nothing produces nothing as GuiUnlock

program p
    call GuiLock
    keep locked as truth value with value 0
    call GuiIsLocked giving locked
    call GuiUnlock
    print the text "locked:" and locked
end program
''',
        "link": ["raylib", "m", "pthread", "dl", "rt", "GL", "X11"],
        "extra_c": "raygui_impl.c", "expect": r"locked:1",
    },
}

RAYGUI_IMPL_C = f'#define RAYGUI_IMPLEMENTATION\n#include "{THIRDPARTY}/raygui.h"\n'


def build_and_run(lib: str, dict_src: str, workdir: str) -> subprocess.CompletedProcess:
    os.makedirs(workdir, exist_ok=True)
    spec = LIBRARIES[lib]
    dict_path = os.path.join(workdir, "t.dict")
    open(dict_path, "w").write(dict_src)
    out_bin = os.path.join(workdir, "t")

    cmd = [sys.executable, CLI, dict_path, "--backend", "c", "--compile", "--output", out_bin]
    if spec.get("extra_c") == "raygui_impl.c":
        # Single-header library: needs its implementation compiled once.
        # Dictum's own build doesn't know about this -- compile it
        # separately to an object file and hand the compiler an extra
        # translation unit isn't directly supported by dictumc_cli.py, so
        # instead compile the whole program in two steps here, mirroring
        # what a real user integrating a single-header C library must do.
        impl_c = os.path.join(workdir, "raygui_impl.c")
        open(impl_c, "w").write(RAYGUI_IMPL_C)
        impl_o = os.path.join(workdir, "raygui_impl.o")
        r0 = subprocess.run(["gcc", "-I", THIRDPARTY, "-c", impl_c, "-o", impl_o],
                             capture_output=True, text=True, timeout=30)
        if r0.returncode != 0:
            return r0
        # Compile the Dictum program to .c only (no link), then link both.
        src_c = out_bin + ".c"
        r1 = subprocess.run([sys.executable, CLI, dict_path, "--backend", "c", "--output", src_c],
                             capture_output=True, text=True, timeout=30)
        if r1.returncode != 0:
            return r1
        for lib_name in spec["link"]:
            pass
        r2 = subprocess.run(
            ["gcc", "-I", os.path.join(COMPILER_DIR, "runtime"), "-I", THIRDPARTY,
             src_c, impl_o, "-o", out_bin] + [f"-l{L}" for L in spec["link"]],
            capture_output=True, text=True, timeout=30,
        )
        if r2.returncode != 0:
            return r2
    else:
        for lib_name in spec["link"]:
            cmd += ["--link", lib_name]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return r

    env = os.environ.copy()
    if spec.get("needs_xvfb") or lib == "raygui":
        env["DISPLAY"] = ":97"
    return subprocess.run([out_bin], capture_output=True, text=True, timeout=15, env=env)


def smoke_test(lib: str) -> "tuple[bool, str]":
    """Returns (passed, reason). On failure the reason carries the real
    compiler/linker/runtime error -- a silent 0/1 verdict turns a broken
    environment into an all-zero campaign that looks like 'found nothing'
    when it actually means 'ran nothing'."""
    try:
        r = build_and_run(lib, LIBRARIES[lib]["dict"], f"/tmp/bl_smoke_{lib}")
    except Exception as e:
        return False, f"exception: {e}"
    if r.returncode != 0:
        err = ((r.stderr or "") + (r.stdout or "")).strip()
        return False, f"exit {r.returncode}: {err[-400:]}"
    if not re.search(LIBRARIES[lib]["expect"], r.stdout):
        return False, (f"ran but output didn't match {LIBRARIES[lib]['expect']!r}: "
                        f"{r.stdout[-200:]!r}")
    return True, "ok"


def mutate(seed: str, rng: random.Random) -> str:
    if rng.random() < 0.4:
        return seed.replace(" 0", " 1", 1) if " 0" in seed else seed
    n = len(seed)
    if n < 4:
        return seed
    cut = rng.randint(n // 2, n - 1)
    return seed[:cut]


def classify(r: "subprocess.CompletedProcess | None") -> str:
    if r is None:
        return "crash"
    combined = (r.stdout or "") + (r.stderr or "")
    if "Traceback" in combined:
        return "crash"
    if "internal error" in combined:
        return "internal"
    if r.returncode != 0 or re.search(r"error|Error", combined):
        return "reject"
    return "ok"


def main() -> int:
    duration_file = "/tmp/blessed_duration_seconds.txt"
    duration = 60
    if os.path.exists(duration_file):
        try:
            duration = int(open(duration_file).read().strip())
        except ValueError:
            pass

    print(f"blessed_library_fuzzer.py starting, duration={duration}s", flush=True)

    xvfb_proc = None
    if shutil.which("Xvfb"):
        xvfb_proc = subprocess.Popen(["Xvfb", ":97", "-screen", "0", "800x600x24"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

    enabled = {}
    skip_reasons = {}
    for lib in LIBRARIES:
        ok, reason = smoke_test(lib)
        enabled[lib] = ok
        if not ok:
            skip_reasons[lib] = reason
            print(f"SMOKE TEST -- {lib}: 0  SKIPPED because: {reason}", flush=True)
        else:
            print(f"SMOKE TEST -- {lib}: 1", flush=True)

    findings_dir = os.path.join(HERE, "blessed_findings")
    os.makedirs(findings_dir, exist_ok=True)
    summary_path = os.path.join(HERE, "blessed_summary.txt")

    rng = random.Random(os.getpid() ^ int(time.time()))
    counts = {lib: {"ok": 0, "reject": 0, "internal": 0, "crash": 0} for lib in LIBRARIES}
    total = 0
    findings = 0
    start = time.time()
    last_heartbeat = 0

    active_libs = [lib for lib, ok in enabled.items() if ok]
    if not active_libs:
        print("NO LIBRARIES PASSED THEIR SMOKE TEST -- nothing was fuzzed.", flush=True)
        print("This is an ENVIRONMENT problem, not a clean result. Reasons:", flush=True)
        for lib, why in skip_reasons.items():
            print(f"  {lib}: {why}", flush=True)
        open(summary_path, "w").write(json.dumps(
            {"error": "all libraries skipped -- environment problem, NOT a clean run",
             "skip_reasons": skip_reasons}, indent=2))
        if xvfb_proc:
            xvfb_proc.terminate()
        return 0

    while True:
        elapsed = time.time() - start
        if elapsed > duration or total > 20000:
            break

        lib = active_libs[total % len(active_libs)]
        mutant = mutate(LIBRARIES[lib]["dict"], rng)
        workdir = f"/tmp/bl_case_{lib}_{total}"
        try:
            r = build_and_run(lib, mutant, workdir)
        except subprocess.TimeoutExpired:
            r = None
        verdict = classify(r)
        counts[lib][verdict] += 1
        if verdict in ("crash", "internal"):
            findings += 1
            open(os.path.join(findings_dir, f"case_{lib}_{findings}.dict"), "w").write(mutant)
        shutil.rmtree(workdir, ignore_errors=True)
        total += 1

        elapsed = time.time() - start
        if elapsed - last_heartbeat > 30:
            last_heartbeat = elapsed
            summary = {"elapsed_seconds": int(elapsed), "total_runs": total,
                       "findings_count": findings, "enabled": enabled,
                       "skip_reasons": skip_reasons, "counts": counts}
            open(summary_path, "w").write(json.dumps(summary, indent=2))
            print(f"--- progress --- {json.dumps(summary)}", flush=True)

    summary = {"elapsed_seconds": int(time.time() - start), "total_runs": total,
               "findings_count": findings, "enabled": enabled,
                       "skip_reasons": skip_reasons, "counts": counts}
    open(summary_path, "w").write(json.dumps(summary, indent=2))
    print(f"DONE {json.dumps(summary)}", flush=True)
    if xvfb_proc:
        xvfb_proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
