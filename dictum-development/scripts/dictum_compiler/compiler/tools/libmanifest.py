#!/usr/bin/env python3
"""
libmanifest.py — one manifest per library, blessed across all backends
with one command.

THE PROBLEM THIS SOLVES
-----------------------
Adding a library used to mean hand-writing a blessed/<lib>.dict, then
separately convincing yourself it worked on each backend, with the
per-target verdict living only in someone's head. There was no single
artifact describing "what this library is", and nothing that would
mechanically prove a binding works on c AND cpp AND nim before calling it
blessed.

KEY FACT THIS BUILDS ON (verified, not assumed): Dictum's `import from C`
syntax is already backend-agnostic -- the exact same import lines compile
and run correctly on c, cpp, and nim. So a manifest does NOT need
per-backend binding variants. What genuinely differs per backend is only
whether the thing actually *builds and runs* there, which is precisely
what must be verified rather than guessed.

MANIFEST FORMAT (blessed/manifests/<lib>.json)
    {
      "library": "sqlite3",
      "link": ["sqlite3"],
      "headers": ["sqlite3.h"],
      "shapes": [ {"name": "...", "fields": [["r","byte"], ...]} ],
      "imports": [
        {"c_name": "sqlite3_libversion", "params": [], "returns": "text",
         "alias": "sqlite3_libversion"}
      ],
      "verify": {
        "body": "    keep v as text with value \\"\\"\\n    call ...",
        "expect_regex": "v:\\\\d+\\\\.\\\\d+"
      }
    }

COMMANDS
    list                       -- show every manifest and its per-target status
    emit   <lib> [--out F]     -- generate the .dict binding file
    verify <lib> [--targets c,cpp,nim]
                               -- REALLY compile + link + run the verify
                                  snippet on each target, then record the
                                  per-target verdict in import_c_registry.py.
                                  Never records a pass it didn't observe.
    add    <lib> --header H [--link L ...]
                               -- draft a manifest from a real C header via
                                  the existing libclang-based
                                  scripts/generate_import_c.py, then STOP.
                                  A drafted manifest is explicitly NOT
                                  blessed until `verify` says so.
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
BLESSED = os.path.join(COMPILER_DIR, "blessed")
MANIFEST_DIR = os.path.join(BLESSED, "manifests")
GENERATE_IMPORT_C = os.path.join(COMPILER_DIR, "scripts", "generate_import_c.py")

ALL_TARGETS = ("c", "cpp", "nim")


def manifest_path(lib: str) -> str:
    return os.path.join(MANIFEST_DIR, f"{lib}.json")


def load_manifest(lib: str) -> dict:
    p = manifest_path(lib)
    if not os.path.exists(p):
        raise SystemExit(f"no manifest for '{lib}' at {p}\n"
                         f"available: {', '.join(sorted(list_manifests())) or '(none)'}")
    return json.load(open(p))


def list_manifests() -> list:
    if not os.path.isdir(MANIFEST_DIR):
        return []
    return [f[:-5] for f in os.listdir(MANIFEST_DIR) if f.endswith(".json")]


def render_dict(m: dict) -> str:
    """Manifest -> .dict binding source. Backend-agnostic by design (see
    module docstring): the same text is what every backend consumes."""
    out = [f"# Auto-generated from blessed/manifests/{m['library']}.json",
           f"# Do not hand-edit -- edit the manifest and re-run:",
           f"#   python3 tools/libmanifest.py emit {m['library']}",
           ""]
    for shape in m.get("shapes", []):
        out.append(f"shape {shape['name']} holds:")
        for fname, ftype in shape["fields"]:
            out.append(f"    {fname} as {ftype}")
        out.append("end shape")
        out.append("")
    for imp in m.get("imports", []):
        params = imp.get("params") or []
        takes = " and ".join(params) if params else "nothing"
        alias = imp.get("alias") or imp["c_name"]
        out.append(f"import from C the action {imp['c_name']} takes {takes} "
                   f"produces {imp['returns']} as {alias}")
    return "\n".join(out) + "\n"


def build_verify_program(m: dict) -> str:
    """The verify snippet, wrapped into a real, complete program."""
    body = m["verify"]["body"]
    imports = []
    for imp in m.get("imports", []):
        params = imp.get("params") or []
        takes = " and ".join(params) if params else "nothing"
        alias = imp.get("alias") or imp["c_name"]
        imports.append(f"import from C the action {imp['c_name']} takes {takes} "
                       f"produces {imp['returns']} as {alias}")
    shapes = []
    for shape in m.get("shapes", []):
        shapes.append(f"shape {shape['name']} holds:")
        for fname, ftype in shape["fields"]:
            shapes.append(f"    {fname} as {ftype}")
        shapes.append("end shape")
    return ("\n".join(shapes + imports) + "\n\n"
            f"program verify_{m['library']}\n{body}\nend program\n")


def verify_target(m: dict, target: str, workdir: str) -> "tuple[bool, str]":
    """REALLY compile + link + run on this target. Returns (passed, detail).
    Nothing here infers a pass from a name match or a prior verdict."""
    src = os.path.join(workdir, f"verify_{m['library']}_{target}.dict")
    open(src, "w").write(build_verify_program(m))
    out_bin = os.path.join(workdir, f"verify_{m['library']}_{target}")
    cmd = [sys.executable, CLI, src, "--backend", target, "--compile", "--output", out_bin]
    for lib in m.get("link", []):
        cmd += ["--link", lib]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "compile timed out"
    if r.returncode != 0:
        return False, f"compile/link failed: {((r.stderr or '') + (r.stdout or ''))[-400:]}"

    env = os.environ.copy()
    if m.get("needs_display"):
        env["DISPLAY"] = env.get("DISPLAY", ":97")
    try:
        run = subprocess.run([out_bin], capture_output=True, text=True, timeout=30, env=env)
    except subprocess.TimeoutExpired:
        return False, "binary timed out"
    if run.returncode != 0:
        return False, f"ran but exited {run.returncode}: {run.stdout[-200:]!r}"
    expect = m["verify"]["expect_regex"]
    if not re.search(expect, run.stdout):
        return False, f"output {run.stdout[-200:]!r} did not match {expect!r}"
    return True, f"ok ({run.stdout.strip()[:80]!r})"


def record_blessing(lib: str, target: str, blessed: bool, note: str) -> None:
    """Persist the verdict in the project's real import_c_registry, which is
    the single source of truth for per-library/per-target blessing.

    This used to probe a list of GUESSED function names and silently print
    "registry has no recognized record function" when none matched -- so no
    verdict was ever actually persisted and the registry stayed empty while
    verify reported PASS. The real API is
    register(library, target, blessed, toolchain, note)."""
    sys.path.insert(0, COMPILER_DIR)
    try:
        from dictumc import import_c_registry as reg
    except Exception as e:
        print(f"  (could not import registry: {e})")
        return
    toolchain = {
        "c": _tool_version("gcc"),
        "cpp": _tool_version("g++"),
        "nim": _tool_version("nim"),
    }.get(target, target)
    try:
        reg.register(library=lib, target=target, blessed=blessed,
                     toolchain=toolchain, note=note[:300])
    except Exception as e:
        print(f"  (registry write failed: {e})")


def _tool_version(exe: str) -> str:
    try:
        r = subprocess.run([exe, "--version"], capture_output=True,
                           text=True, timeout=20)
        return (r.stdout or r.stderr).splitlines()[0][:80]
    except Exception:
        return exe


def cmd_list(args) -> int:
    names = sorted(list_manifests())
    if not names:
        print(f"no manifests yet in {MANIFEST_DIR}")
        return 0
    print(f"{'library':<12} {'link':<24} imports  verified-targets")
    for n in names:
        m = load_manifest(n)
        v = m.get("_verified", {})
        good = ",".join(t for t in ALL_TARGETS if v.get(t) is True) or "-none-"
        print(f"{n:<12} {','.join(m.get('link', [])):<24} "
              f"{len(m.get('imports', [])):>7}  {good}")
    return 0


def cmd_emit(args) -> int:
    m = load_manifest(args.library)
    text = render_dict(m)
    out = args.out or os.path.join(BLESSED, f"{args.library}.dict")
    open(out, "w").write(text)
    print(f"wrote {out} ({len(m.get('imports', []))} imports, "
          f"{len(m.get('shapes', []))} shapes)")
    return 0


def cmd_verify(args) -> int:
    m = load_manifest(args.library)
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    bad = [t for t in targets if t not in ALL_TARGETS]
    if bad:
        raise SystemExit(f"unknown target(s): {bad}; valid: {ALL_TARGETS}")

    workdir = tempfile.mkdtemp(prefix=f"libverify_{args.library}_")
    results = {}
    try:
        for t in targets:
            ok, detail = verify_target(m, t, workdir)
            results[t] = ok
            print(f"  {args.library} / {t}: {'PASS' if ok else 'FAIL'} -- {detail}")
            record_blessing(args.library, t, ok, detail)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    m.setdefault("_verified", {}).update(results)
    json.dump(m, open(manifest_path(args.library), "w"), indent=2)

    passed = [t for t, ok in results.items() if ok]
    failed = [t for t, ok in results.items() if not ok]
    print(f"\n{args.library}: verified on {passed or '-none-'}"
          + (f"; FAILED on {failed}" if failed else ""))
    return 0 if not failed else 1


def cmd_add(args) -> int:
    """Draft a manifest from a real header via libclang. Explicitly does
    NOT bless it -- a drafted binding is a hypothesis until `verify` runs."""
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    if not os.path.exists(GENERATE_IMPORT_C):
        raise SystemExit(f"missing {GENERATE_IMPORT_C}")
    # generate_import_c.py writes the bridge to a FILE and requires
    # --module-name/--output; it does not print to stdout. (This call was
    # wrong until a real `add` was attempted end-to-end -- R79 only
    # exercised `emit` and `verify`.)
    with tempfile.TemporaryDirectory() as _td:
        _out = os.path.join(_td, f"{args.library}_bridge.dict")
        cmd = [sys.executable, GENERATE_IMPORT_C, args.header,
               "--module-name", f"{args.library}_bridge", "--output", _out]
        if args.only_prefix:
            cmd += ["--only-prefix", args.only_prefix]
        if args.functions:
            cmd += ["--functions", ",".join(args.functions)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise SystemExit(f"generate_import_c.py failed:\n"
                             f"{(r.stderr or r.stdout)[-1200:]}")
        if not os.path.exists(_out):
            raise SystemExit(f"generate_import_c.py reported success but wrote "
                             f"no file at {_out}")
        generated = open(_out).read()
    class _R:  # keep the parsing loop below unchanged
        pass
    r = _R()
    r.stdout = generated

    imports, shapes = [], []
    cur_shape = None
    for line in r.stdout.splitlines():
        s = line.strip()
        ms = re.match(r'^shape\s+(\w+)\s+holds:', s)
        if ms:
            cur_shape = {"name": ms.group(1), "fields": []}
            continue
        if s == "end shape" and cur_shape:
            shapes.append(cur_shape)
            cur_shape = None
            continue
        if cur_shape:
            mf = re.match(r'^(\w+)\s+as\s+(.+)$', s)
            if mf:
                cur_shape["fields"].append([mf.group(1), mf.group(2).strip()])
            continue
        mi = re.match(r'^import from C the action\s+(\w+)\s+takes\s+(.+?)\s+'
                      r'produces\s+(.+?)\s+as\s+(\w+)', s)
        if mi:
            c_name, takes, returns, alias = mi.groups()
            params = [] if takes.strip() == "nothing" else \
                     [p.strip() for p in takes.split(" and ")]
            imports.append({"c_name": c_name, "params": params,
                            "returns": returns.split("#")[0].strip(), "alias": alias})

    m = {
        "library": args.library,
        "link": args.link or [],
        "headers": [os.path.basename(args.header)],
        "shapes": shapes,
        "imports": imports,
        "verify": {
            "body": "    # TODO: write a real call that proves this binding works,\n"
                    "    #       then set expect_regex to match its real output.\n"
                    "    print the text \"TODO\"",
            "expect_regex": "TODO",
        },
        "_verified": {},
        "_note": "DRAFTED, NOT BLESSED. Fill in `verify`, then run: "
                 f"python3 tools/libmanifest.py verify {args.library}",
    }
    json.dump(m, open(manifest_path(args.library), "w"), indent=2)
    print(f"drafted {manifest_path(args.library)}: "
          f"{len(imports)} imports, {len(shapes)} shapes")
    print("NOT blessed yet -- fill in the `verify` block, then run:")
    print(f"  python3 tools/libmanifest.py verify {args.library}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    pe = sub.add_parser("emit"); pe.add_argument("library"); pe.add_argument("--out")
    pe.set_defaults(func=cmd_emit)

    pv = sub.add_parser("verify"); pv.add_argument("library")
    pv.add_argument("--targets", default=",".join(ALL_TARGETS))
    pv.set_defaults(func=cmd_verify)

    pa = sub.add_parser("add"); pa.add_argument("library")
    pa.add_argument("--header", required=True); pa.add_argument("--link", nargs="*")
    pa.add_argument("--only-prefix", help="only bind functions with this prefix")
    pa.add_argument("--functions", nargs="*", help="only bind these named functions")
    pa.set_defaults(func=cmd_add)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
