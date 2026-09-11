#!/usr/bin/env python3
"""
dictum — one command to build and check a Dictum program.

WHY THIS EXISTS
---------------
Shipping a program currently means knowing all of this:

  * dictumc_cli.py for a single file, project_builder.py for several
  * `make` for c/cpp, `build.sh` for nim
  * --link flags, which `import from C` does not carry and nothing
    auto-discovers
  * hand-editing OBJS in the generated Makefile to link a C shim
  * --passL ordering for nim (object files BEFORE -l libraries)

Every one of those is a real step that has to be gotten right, and the
information needed for most of them already exists somewhere in the tree --
the blessed manifests record each library's link flags, the registry
records which targets are verified. It was simply never wired to the build.

COMMANDS
    dictum build <path> [--backend c|cpp|nim] [--link LIB ...] [--shim F.c]
        Build a .dict file or a project DIRECTORY. Picks single-file vs
        project automatically, runs the right build step per backend,
        compiles and links any C shims, and resolves link flags from the
        manifests so `--link sqlite3` is usually unnecessary.

    dictum check <path>
        Build on ALL THREE backends and compare the output. Cross-backend
        VALUE disagreement is the single highest-yield bug signal in this
        project -- it caught a C++ shadowing bug that a 94-test suite, a
        saturated combinatorial explorer, and a full feature x context
        matrix all passed. It should not be an internal tool; it should be
        something anyone can run on their own program before shipping.

    dictum libs
        Show which libraries are blessed, on which targets, so you know
        what you can call before you write the call.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
CLI = os.path.join(COMPILER_DIR, "dictumc_cli.py")
PROJECT_BUILDER = os.path.join(COMPILER_DIR, "project_builder.py")
MANIFEST_DIR = os.path.join(COMPILER_DIR, "blessed", "manifests")
BACKENDS = ("c", "cpp", "nim")


def load_manifest_links() -> dict:
    """library name -> its link flags, straight from the blessed manifests.
    This is the data that makes `--link` usually unnecessary."""
    out = {}
    if os.path.isdir(MANIFEST_DIR):
        for f in os.listdir(MANIFEST_DIR):
            if f.endswith(".json"):
                try:
                    m = json.load(open(os.path.join(MANIFEST_DIR, f)))
                    out[m["library"]] = m.get("link", [])
                except Exception:
                    pass
    return out


def infer_links(sources: list, shim_sources: list = None) -> list:
    """Guess the needed -l flags from the C symbols a program imports.

    `import from C` names a SYMBOL, never the library it lives in, and
    nothing auto-discovers that -- which is why a project can generate
    cleanly and then die at link time with 'undefined reference'. The
    manifests know the mapping; this uses it. Symbol prefixes are matched
    conservatively, and anything unmatched is simply not guessed at.
    """
    text = ""
    for s in sources:
        try:
            text += open(s).read()
        except Exception:
            pass
    imported = set(re.findall(r"import from C(?:\+\+)? the action\s+(\w+)", text))
    # A C SHIM's own calls count too. A shim wraps an awkward C API (an
    # out-parameter, a callback) so Dictum can reach it -- the .dict then
    # names only the WRAPPER, so scanning .dict files alone misses the
    # library the shim actually depends on, and the build dies at link time
    # with the real symbols the user never wrote.
    for shim in (shim_sources or []):
        try:
            stext = open(shim).read()
            imported |= set(re.findall(r"\b(\w+)\s*\(", stext))
        except Exception:
            pass
    links, why = [], {}
    manifests = load_manifest_links()
    # symbol prefix -> manifest library
    PREFIX = {
        "sqlite3_": "sqlite3", "RAND_": "openssl", "EVP_": "openssl",
        "SHA": "openssl", "SDL_": "sdl2", "glfw": "glfw",
        "InitWindow": "raylib", "CloseWindow": "raylib", "Draw": "raylib",
        "Gui": "raygui", "zlib": "zlib", "compress": "zlib",
        "uncompress": "zlib",
    }
    for sym in imported:
        for pre, lib in PREFIX.items():
            if sym.startswith(pre):
                for fl in manifests.get(lib, [lib]):
                    if fl not in links:
                        links.append(fl)
                        why[fl] = f"{sym} -> {lib}"
                break
    return links, why


def is_project(path: str) -> bool:
    if os.path.isdir(path):
        return True
    d = os.path.dirname(os.path.abspath(path)) or "."
    return len([f for f in os.listdir(d) if f.endswith(".dict")]) > 1


def build_one(path, backend, links, shim_objs, outdir, quiet=False):
    """Returns (ok, binary_path, message)."""
    if os.path.isdir(path):
        proj, entry_dir = path, path
    else:
        proj, entry_dir = os.path.dirname(os.path.abspath(path)) or ".", None

    if is_project(path):
        out = outdir or os.path.join(proj, f"build_{backend}")
        mani = os.path.join(proj, "dictum.project.json")
        if os.path.exists(mani):
            os.remove(mani)   # stale manifest used to silently override --backend
        cmd = [sys.executable, PROJECT_BUILDER, proj, "--backend", backend, "--out", out]
        for l in links:
            cmd += ["--link", l.lstrip("-l")]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, None, (r.stdout + r.stderr)[-500:]

        if backend == "nim":
            sh = os.path.join(out, "build.sh")
            txt = open(sh).read()
            if shim_objs:
                # Object files must precede -l libraries or the linker will
                # not resolve them -- a real trap when hand-editing.
                ins = " ".join(f"--passL:{o}" for o in shim_objs)
                txt = txt.replace("nim c ", f"nim c {ins} ", 1)
                open(sh, "w").write(txt)
            rb = subprocess.run(["sh", sh], capture_output=True, text=True,
                                timeout=420, cwd=out)
        else:
            mf = os.path.join(out, "Makefile")
            if shim_objs:
                txt = re.sub(r"^OBJS     = ", "OBJS     = " + " ".join(shim_objs) + " ",
                             open(mf).read(), flags=re.MULTILINE)
                open(mf, "w").write(txt)
            rb = subprocess.run(["make"], capture_output=True, text=True,
                                timeout=300, cwd=out)
        if rb.returncode != 0:
            return False, None, explain(rb.stdout + rb.stderr)
        return True, os.path.join(out, "main"), ""

    # single file
    binp = outdir or os.path.splitext(path)[0] + f"_{backend}"
    cmd = [sys.executable, CLI, path, "--backend", backend, "--compile", "--output", binp]
    for l in links:
        cmd += ["--link", l.lstrip("-l")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return False, None, explain(r.stdout + r.stderr)
    return True, binp, ""


def explain(log: str) -> str:
    """Attach the FIX to the error where it is mechanically derivable.
    `undefined reference to sqlite3_open` -> the manifests know which
    library provides that symbol; saying so beats making the user work it
    out from a linker message."""
    tail = log[-600:]
    hints = []
    for sym in set(re.findall(r"undefined reference to [`']?(\w+)", log)):
        for pre, lib in (("sqlite3_", "sqlite3"), ("RAND_", "crypto"),
                         ("SDL_", "SDL2"), ("glfw", "glfw"),
                         ("InitWindow", "raylib"), ("Gui", "raylib")):
            if sym.startswith(pre):
                hints.append(f"  hint: '{sym}' comes from {lib} -- add --link {lib}")
                break
        else:
            hints.append(f"  hint: '{sym}' is not provided by any linked library. "
                         f"If it is your own C shim, pass --shim yourfile.c")
    if "multiple definition" in log:
        hints.append("  hint: a symbol is defined in more than one translation "
                     "unit -- a runtime header may be defining rather than "
                     "declaring it")
    return tail + ("\n" + "\n".join(sorted(set(hints))) if hints else "")


def compile_shims(shims: list) -> list:
    objs = []
    for c in shims:
        o = os.path.splitext(os.path.abspath(c))[0] + ".o"
        r = subprocess.run(["gcc", "-c", c, "-o", o], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"shim {c} failed to compile:\n{r.stderr[-400:]}")
            sys.exit(1)
        objs.append(o)
    return objs


def cmd_build(args) -> int:
    links, why = infer_links(collect_sources(args.path), args.shim)
    for l in (args.link or []):
        if l not in links:
            links.append(l)
    if why and not args.quiet:
        for fl, reason in why.items():
            print(f"  auto-link {fl}  ({reason})")
    shim_objs = compile_shims(args.shim or [])
    ok, binp, msg = build_one(args.path, args.backend, links, shim_objs, args.out)
    if not ok:
        print(f"build FAILED ({args.backend}):\n{msg}")
        return 1
    print(f"built: {binp}")
    return 0


def collect_sources(path: str) -> list:
    if os.path.isdir(path):
        return [os.path.join(path, f) for f in os.listdir(path) if f.endswith(".dict")]
    d = os.path.dirname(os.path.abspath(path)) or "."
    return [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".dict")]


def cmd_check(args) -> int:
    """Build on all three backends and COMPARE OUTPUT."""
    links, _ = infer_links(collect_sources(args.path), args.shim)
    for l in (args.link or []):
        if l not in links:
            links.append(l)
    shim_objs = compile_shims(args.shim or [])

    print("dictum check: building on all three backends and comparing output.")
    print("Cross-backend disagreement is the highest-yield bug signal there is --")
    print("a program can compile and run cleanly on every backend and still")
    print("produce a DIFFERENT ANSWER on one of them.\n")

    results, outputs = {}, {}
    for b in BACKENDS:
        if b == "nim" and shutil.which("nim") is None:
            print(f"  {b:<4} SKIP (nim not installed)")
            continue
        ok, binp, msg = build_one(args.path, b, links, shim_objs, None, quiet=True)
        if not ok:
            print(f"  {b:<4} BUILD FAILED")
            print("\n".join("       " + l for l in msg.splitlines()[-6:]))
            results[b] = None
            continue
        run = subprocess.run([binp], capture_output=True, text=True, timeout=60,
                             cwd=os.path.dirname(binp) or ".")
        outputs[b] = run.stdout
        results[b] = "".join(run.stdout.split())
        print(f"  {b:<4} ok   {results[b][:60]}")

    good = {b: v for b, v in results.items() if v is not None}
    print()
    if not good:
        print("no backend built -- see errors above")
        return 1
    if len(set(good.values())) > 1:
        print("BACKENDS DISAGREE -- this is a real bug in your program or the compiler:")
        for b, v in good.items():
            print(f"  {b:<4} {v}")
        print("\nWhitespace is normalised before comparing, so this is a genuine")
        print("difference in VALUES, not formatting.")
        return 1
    if len(good) < len(BACKENDS):
        print(f"all {len(good)} available backends agree "
              f"({', '.join(sorted(good))}) -- but not all three were tested")
        return 0
    print("all three backends agree")
    return 0


def cmd_libs(args) -> int:
    try:
        sys.path.insert(0, COMPILER_DIR)
        from dictumc import import_c_registry as reg
    except Exception:
        reg = None
    mans = load_manifest_links()
    if not mans:
        print("no blessed manifests")
        return 0
    print(f"{'library':<12} {'link':<28} verified on")
    for lib in sorted(mans):
        tgts = ""
        if reg:
            tgts = ",".join(t for t in BACKENDS if reg.is_blessed(lib, t) is True) or "-none-"
        print(f"{lib:<12} {' '.join(mans[lib]):<28} {tgts}")
    print("\nA target not listed is UNVERIFIED, which is different from broken.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("build")
    pb.add_argument("path")
    pb.add_argument("--backend", choices=BACKENDS, default="c")
    pb.add_argument("--link", nargs="*")
    pb.add_argument("--shim", nargs="*", help="C shim source files to compile and link")
    pb.add_argument("--out")
    pb.add_argument("--quiet", action="store_true")
    pb.set_defaults(func=cmd_build)

    pc = sub.add_parser("check")
    pc.add_argument("path")
    pc.add_argument("--link", nargs="*")
    pc.add_argument("--shim", nargs="*")
    pc.set_defaults(func=cmd_check)

    pl = sub.add_parser("libs")
    pl.set_defaults(func=cmd_libs)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
