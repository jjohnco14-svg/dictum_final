#!/usr/bin/env python3
"""
dictumc — Dictum Compiler CLI v5.1

NEW in v5.1:
  --backend nim        Emit Nim source (compiles to C via nim c)
  --defensive          Emit C with runtime safety checks
  --run                Compile and run the output automatically

Usage:
  dictumc <file.dict> [options]
  dictumc <file.dict> --backend nim --run
  dictumc <file.dict> --defensive --compile
"""

import sys
import os
import argparse
import re
import subprocess
import tempfile


def _run_repl(backend: str, cpp_standard: int, defensive: bool = False) -> int:
    """
    Minimal interactive read-transpile-print loop.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dictumc.transpiler import Transpiler
    from dictumc.validator import ValidationError

    print(f"Dictum REPL — backend: {backend}" +
          (f" (C++{cpp_standard})" if backend == "cpp" else "") +
          (" [DEFENSIVE]" if defensive else ""))
    print("Type a statement or full program. Blank line submits. Ctrl+D / Ctrl+C to exit.\n")

    TOP_LEVEL_KEYWORDS = ("program", "action", "shape", "use ", "import ")

    while True:
        try:
            lines = []
            prompt = ">>> "
            while True:
                line = input(prompt)
                if line.strip() == "" and lines:
                    break
                if line.strip() == "" and not lines:
                    continue
                lines.append(line)
                prompt = "... "
        except (EOFError, KeyboardInterrupt):
            print("\nExiting Dictum REPL.")
            return 0

        raw = "\n".join(lines)
        is_top_level = raw.strip().startswith(TOP_LEVEL_KEYWORDS)
        source = raw if is_top_level else (
            "program _repl:\n"
            + "\n".join("    " + l for l in lines)
            + "\nend program\n"
        )

        try:
            t = Transpiler(source=source, backend=backend,
                           cpp_standard=cpp_standard, namespace="",
                           defensive=defensive)
            result = t.run(validate=True, summary=False, grammar_guided=False)
            code = result.get("code") if isinstance(result, dict) else result
            print(code)
        except (SyntaxError, ValidationError) as e:
            print(f"error: {e}", file=sys.stderr)
        except Exception as e:
            print(f"internal error: {e}", file=sys.stderr)

    return 0


def _compile_c(source_path: str, output_path: str, defensive: bool = False, extra_libs=None) -> int:
    """Compile generated C with gcc."""
    cc = os.environ.get("CC", "gcc")
    runtime_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")
    cmd = [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-I", runtime_dir,
           source_path, "-o", output_path, "-lm"]
    for lib in (extra_libs or []):
        cmd.append(f"-l{lib}")
    if defensive:
        cmd.extend(["-g", "-O0"])
    print(f"dictumc: running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("dictumc: compile error:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1
    print(f"dictumc: compiled to '{output_path}'")
    return 0


def _compile_cpp(source_path: str, output_path: str, cpp_standard: int = 17, extra_libs=None) -> int:
    """Compile generated C++ with g++."""
    cxx = os.environ.get("CXX", "g++")
    runtime_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")
    cmd = [cxx, f"-std=c++{cpp_standard}", "-O2", "-Wall", "-Wextra", "-I", runtime_dir,
           source_path, "-o", output_path, "-lm"]
    for lib in (extra_libs or []):
        cmd.append(f"-l{lib}")
    print(f"dictumc: running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("dictumc: compile error:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1
    print(f"dictumc: compiled to '{output_path}'")
    return 0


def _compile_nim(source_path: str, output_path: str, quiet: bool = False, extra_libs=None) -> int:
    """Compile generated Nim with nim c.

    Uses nim_bootstrap to resolve a working `nim` executable -- vendored
    copy, PATH, or auto-downloaded on first use -- instead of assuming
    `nim` is already on PATH. See dictumc/nim_bootstrap.py.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dictumc.nim_bootstrap import get_nim_executable, NimBootstrapError
    try:
        nim_exe = get_nim_executable(auto_install=True, quiet=quiet)
    except NimBootstrapError as e:
        print(f"dictumc: error: {e}", file=sys.stderr)
        return 1
    cmd = [nim_exe, "c", "--opt:speed", "-o:" + output_path]
    for lib in (extra_libs or []):
        cmd.append(f"--passL:-l{lib}")
    cmd.append(source_path)
    print(f"dictumc: running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("dictumc: compile error:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1
    print(f"dictumc: compiled to '{output_path}'")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="dictumc", description="Dictum Compiler v5.1")
    p.add_argument("file", nargs="?", help="Input .dict source file")
    p.add_argument("--backend", choices=["c", "cpp", "nim"], default="c")
    p.add_argument("--defensive", action="store_true",
                   help="Emit C with runtime safety checks")
    p.add_argument("--run", action="store_true",
                   help="Compile and run the resulting binary")
    p.add_argument("--cpp-standard", type=int, choices=[17, 20, 23], default=17)
    p.add_argument("--namespace", default="")
    p.add_argument("--validate", action="store_true", help="Validate only")
    p.add_argument("--no-validate", action="store_true", help="Skip validation")
    p.add_argument("--compile", action="store_true", help="Compile emitted code")
    p.add_argument("--output", "-o", default="", help="Output path")
    p.add_argument("--makefile", action="store_true",
                   help="Write Makefile alongside output (C backend only)")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--grammar", action="store_true",
                   help="Grammar-constrained parsing")
    p.add_argument("--stdlib", action="store_true",
                   help="Stdlib-aware transpiler")
    p.add_argument("--emit-ast", action="store_true", help="Dump AST repr")
    p.add_argument("--print-ldflags", action="store_true",
                   help="Print linker flags and exit")
    p.add_argument("--repl", action="store_true",
                   help="Interactive read-transpile-print loop")
    p.add_argument("--link", action="append", default=[],
                   help="Extra native library to link, e.g. --link sqlite3 "
                        "adds -lsqlite3 (repeatable). Needed for any "
                        "`import from C` bridge to a real system library "
                        "(sqlite3, raylib, sdl2, openssl, ...) -- the "
                        "transpile step alone never auto-discovers link "
                        "flags for those.")
    p.add_argument("--install-nim", action="store_true",
                   help="Fetch/vendor the Nim compiler now and exit "
                        "(normally happens automatically on first "
                        "--backend nim --run/--compile)")
    args = p.parse_args()

    if args.install_nim:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from dictumc.nim_bootstrap import get_nim_executable, NimBootstrapError
        try:
            path = get_nim_executable(auto_install=True, quiet=False)
        except NimBootstrapError as e:
            print(f"dictumc: error: {e}", file=sys.stderr)
            return 1
        print(f"dictumc: Nim compiler ready: {path}")
        return 0

    if args.defensive and args.backend != "c":
        print("warning: --defensive only applies to C backend, ignoring", file=sys.stderr)
        args.defensive = False

    if args.repl:
        return _run_repl(args.backend, args.cpp_standard, args.defensive)

    # Read source
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                source = fh.read()
        except FileNotFoundError:
            print(f"dictumc: error: file '{args.file}' not found", file=sys.stderr)
            return 1
    else:
        if sys.stdin.isatty():
            p.print_help()
            return 0
        source = sys.stdin.read()

    # Import
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dictumc.transpiler import Transpiler, StdlibTranspiler
    from dictumc.validator import ValidationError

    TranspilerClass = StdlibTranspiler if args.stdlib else Transpiler

    try:
        t = TranspilerClass(
            source=source,
            backend=args.backend,
            cpp_standard=args.cpp_standard,
            namespace=args.namespace,
            defensive=args.defensive,
        )
        result = t.run(
            validate=not args.no_validate,
            summary=args.summary,
            grammar_guided=args.grammar,
        )
    except (SyntaxError, ValidationError) as e:
        print(f"dictumc: error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"dictumc: internal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    # Warnings
    for w in result.get("warnings", []):
        print(f"dictumc: warning: {w}", file=sys.stderr)

    if args.validate:
        print("dictumc: validation passed", file=sys.stderr)
        if args.summary and "summary" in result:
            print(result["summary"])
        return 0

    if args.print_ldflags:
        print(" ".join(result.get("ldflags") or ["-lm"]))
        return 0

    if args.emit_ast:
        import pprint
        pprint.pprint(result["ast"])
        return 0

    if args.summary and "summary" in result:
        print(result["summary"])

    code: str = result["code"]

    # Determine output extension
    ext = ".nim" if args.backend == "nim" else (".cpp" if args.backend == "cpp" else ".c")
    out_src = args.output if args.output and not args.compile else ""

    if args.compile or args.run:
        binary_out = args.output or (os.path.splitext(args.file)[0] if args.file else "a.out")

        if args.backend == "nim":
            # Persist the intermediate source at a DETERMINISTIC, Nim-valid
            # name next to the binary, rather than a random tempfile.
            #
            # Real bug this fixes (found by differential fuzzing): Nim takes
            # its module name from the source filename and rejects names
            # containing double underscores -- "Error: invalid module name:
            # tmpXXXX__Y". tempfile.NamedTemporaryFile generates random
            # names that sometimes contain "__", so the Nim backend failed
            # NONDETERMINISTICALLY: the exact same .dict input would compile
            # or fail depending only on which temp name it happened to draw.
            # Sanitize defensively too, in case the user's own output name
            # would itself be an invalid Nim module name.
            base_dir = os.path.dirname(os.path.abspath(binary_out)) or "."
            base_name = os.path.basename(binary_out) or "dictum_out"
            safe = re.sub(r'[^0-9A-Za-z_]', '_', base_name)
            safe = re.sub(r'_+', '_', safe).strip('_') or "dictum_out"
            if safe[0].isdigit():
                safe = "m" + safe
            src_path = os.path.join(base_dir, safe + ".nim")
            with open(src_path, "w", encoding="utf-8") as tf:
                tf.write(code)
            rc = _compile_nim(src_path, binary_out, extra_libs=args.link)
            if rc != 0:
                return rc
            if args.run:
                print(f"dictumc: running {binary_out}")
                return subprocess.run([binary_out]).returncode
            return 0

        # C or C++ -- persist the intermediate source next to the binary
        # (<binary>.c / <binary>.cpp) instead of an ephemeral tempfile that
        # gets deleted immediately after. A compiled binary with no
        # retrievable source defeats inspection, ASan re-compilation, and
        # any tooling (including this project's own regression suite) that
        # reasonably expects to find it at a predictable path.
        src_path = binary_out + ext
        with open(src_path, "w", encoding="utf-8") as tf:
            tf.write(code)

        if args.backend == "cpp":
            rc = _compile_cpp(src_path, binary_out, args.cpp_standard, extra_libs=args.link)
        else:
            rc = _compile_c(src_path, binary_out, args.defensive, extra_libs=args.link)

        if rc != 0:
            return rc

        if args.run:
            print(f"dictumc: running {binary_out}")
            return subprocess.run([binary_out]).returncode
        return 0

    # Write code
    if out_src:
        with open(out_src, "w", encoding="utf-8") as fh:
            fh.write(code)
        print(f"dictumc: wrote '{out_src}'", file=sys.stderr)
    else:
        sys.stdout.write(code)

    # Write header if generated
    if "h_code" in result:
        h_path = (os.path.splitext(out_src)[0] + ".h") if out_src else None
        if h_path:
            with open(h_path, "w", encoding="utf-8") as fh:
                fh.write(result["h_code"])
    elif "hpp_code" in result:
        hpp_path = (os.path.splitext(out_src)[0] + ".hpp") if out_src else None
        if hpp_path:
            with open(hpp_path, "w", encoding="utf-8") as fh:
                fh.write(result["hpp_code"])

    # Write Makefile if requested
    if args.makefile and args.backend == "c" and result.get("makefile"):
        mf_dir = os.path.dirname(out_src) if out_src else "."
        mf_path = os.path.join(mf_dir, "Makefile")
        prog_name = os.path.splitext(os.path.basename(out_src))[0] if out_src else "program"
        mf_text = result["makefile"].replace("program:", f"{prog_name}:") \
                                     .replace("program.c", f"{prog_name}.c") \
                                     .replace("-o program ", f"-o {prog_name} ")
        with open(mf_path, "w", encoding="utf-8") as fh:
            fh.write(mf_text)
        print(f"dictumc: wrote '{mf_path}'", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
