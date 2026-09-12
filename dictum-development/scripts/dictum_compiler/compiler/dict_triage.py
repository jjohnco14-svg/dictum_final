#!/usr/bin/env python3
"""
dict_triage.py — automated Guide B triage for a single .dict submission.

This is the mechanical half of GUIDE_B_triage_protocol.md's §1/§1a/§2:
"run it for real" + "classify the failure". It exists so an AI running
Guide B doesn't have to hand-drive `dictumc_cli.py --compile`, hand-parse
raw gcc/g++ stderr, and manually map a `file.c:LINE:COL:` error back to
the right `.dict` line by eye every single time — one call to
`triage_file()` (or one `python3 dict_triage.py file.dict` invocation)
returns a single structured verdict with everything Guide B needs to
write its §5 report, cutting the round-trips (and therefore the context
a driving AI burns) for the common cases down to one.

It does NOT replace Guide B's judgment. It replaces the *mechanics*:
    - actually lex/parse/validate the file             (Case A detection)
    - actually compile with real gcc/g++                (Case C detection)
    - map gcc's C-line errors back to real .dict lines   (the missing half
      of Gap #2 — the marker-scanning logic already emitted by
      emit_c.py/emit_cpp.py's `/* @dictum-line:N */` comments existed only
      in the VS Code extension's out/transpiler.js, which isn't reachable
      from this CLI/batch pipeline; this is that same logic, in Python,
      usable here)
    - actually link + run the binary and diff against an expected value
      if one is known                                    (§0 step 4)
    - check declared LIBRARIES against what's actually blessed          (Case D)

What it deliberately does NOT do (left to Guide B / the AI, on purpose):
    - decide Case A vs Case B vs Case C for a *runtime* mismatch (that
      requires knowing the *intended* behavior — the README, per Guide A
      §20 — which this tool doesn't invent)
    - write the actual fix
    - update Guide A / SOURCE_OF_TRUTH.md / CHANGELOG.md
    - decide root cause of a Case C bug (it hands you the exact .dict
      line, the exact gcc message, and the generated C around it — that's
      the fast-start point for root-causing, not the root cause itself)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "dictumc_cli.py")
RUNTIME_DIR = os.path.join(HERE, "runtime")
BLESSED_DIR = os.path.join(HERE, "blessed")
REGISTRY_PATH = os.path.join(HERE, "dictumc", "import_c_registry.py")

sys.path.insert(0, HERE)


# ─────────────────────────────────────────────────────────────────────────
# Build Manifest (Guide A §19) — comment-block parsing for a single file
# ─────────────────────────────────────────────────────────────────────────

_MANIFEST_KEYS = ("TARGET", "BACKEND", "CPP_STANDARD", "LIBRARIES", "GUI")
_MANIFEST_DEFAULT = {
    "TARGET": "linux",
    "BACKEND": "c",
    "CPP_STANDARD": None,
    "LIBRARIES": [],
    "GUI": "no",
}


@dataclass
class Manifest:
    target: str = "linux"
    backend: str = "c"
    cpp_standard: Optional[int] = None
    libraries: List[str] = field(default_factory=list)
    gui: bool = False
    present: bool = False  # False => no manifest was found, defaults used


def parse_manifest(source: str) -> Manifest:
    """Guide A §19: a `# KEY: value` comment block at the top of the file.
    Absence of a manifest is itself meaningful — Guide B treats that as
    `TARGET: linux, BACKEND: c, LIBRARIES: none, GUI: no` (the narrowest
    default), never as license to assume Windows/GUI readiness."""
    found: Dict[str, str] = {}
    for line in source.splitlines()[:40]:  # manifest is always near the top
        stripped = line.strip()
        if not stripped.startswith("#"):
            if stripped and not stripped.startswith("#"):
                # stop scanning once real code starts, but only after we've
                # seen at least one manifest-shaped comment line, otherwise
                # keep looking a little further down (blank lines/other
                # header comments are fine before it)
                if found:
                    break
            continue
        body = stripped.lstrip("#").strip()
        if ":" not in body:
            continue
        key, _, val = body.partition(":")
        key = key.strip().upper()
        if key in _MANIFEST_KEYS:
            found[key] = val.strip()

    if not found:
        return Manifest(present=False, **{
            "target": _MANIFEST_DEFAULT["TARGET"],
            "backend": _MANIFEST_DEFAULT["BACKEND"],
            "cpp_standard": _MANIFEST_DEFAULT["CPP_STANDARD"],
            "libraries": [],
            "gui": False,
        })

    libs_raw = found.get("LIBRARIES", "none")
    libs = [] if libs_raw.strip().lower() == "none" else [
        s.strip() for s in libs_raw.split(",") if s.strip()
    ]
    cpp_std = found.get("CPP_STANDARD")
    return Manifest(
        present=True,
        target=found.get("TARGET", "linux").strip().lower(),
        backend=found.get("BACKEND", "c").strip().lower(),
        cpp_standard=int(cpp_std) if cpp_std and cpp_std.isdigit() else None,
        libraries=libs,
        gui=found.get("GUI", "no").strip().lower() == "yes",
    )


# ─────────────────────────────────────────────────────────────────────────
# Gap #2, Python side: C-line -> Dictum-line mapping + gcc output rewrite
#
# Mirrors out/transpiler.js's buildDictumLineMap()/translateCompilerOutput()
# (see emit_c.py's _emit_marked docstring for the original design), ported
# here so it's usable from a plain CLI/batch pipeline that never touches
# the VS Code extension.
# ─────────────────────────────────────────────────────────────────────────

_MARKER_RE = re.compile(r'/\*\s*@dictum-line:(\d+)\s*\*/')
_GCC_DIAG_RE = re.compile(
    r'^(?P<path>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|note):\s*(?P<msg>.*)$'
)


def build_dictum_line_map(generated_code: str) -> Dict[int, int]:
    """Forward-fill map: generated C/C++ line number -> Dictum source line.
    Every line from one `/* @dictum-line:N */` marker up to (but not
    including) the next marker inherits N. Lines before the first marker
    (preamble, #includes, struct defs, forward decls) have no entry —
    those are emitted by passes _emit_marked is deliberately not called
    from (see its docstring), so there is genuinely no single Dictum line
    responsible for them."""
    mapping: Dict[int, int] = {}
    current: Optional[int] = None
    for i, line in enumerate(generated_code.split("\n"), start=1):
        m = _MARKER_RE.search(line)
        if m:
            current = int(m.group(1))
        if current is not None:
            mapping[i] = current
    return mapping


def translate_compiler_output(
    gcc_stderr: str,
    src_path: str,
    line_map: Dict[int, int],
    dict_path: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Rewrite gcc/g++ stderr so every `<src_path>:LINE:COL:` reference
    that falls inside a mapped region now reads `<dict_path>:DICT_LINE:`
    instead — without touching the diagnostic message text itself, so
    nothing about *what* gcc is complaining about is lost, only *where*
    it's pointing gets corrected. Also returns a structured list of
    parsed diagnostics for programmatic use."""
    diagnostics: List[Dict[str, Any]] = []
    out_lines: List[str] = []
    base = os.path.basename(src_path)

    for raw_line in gcc_stderr.split("\n"):
        m = _GCC_DIAG_RE.match(raw_line)
        if m and (m.group("path") == src_path or os.path.basename(m.group("path")) == base):
            c_line = int(m.group("line"))
            dict_line = line_map.get(c_line)
            severity = m.group("severity")
            msg = m.group("msg")
            diagnostics.append({
                "severity": severity,
                "c_line": c_line,
                "c_col": int(m.group("col")),
                "dict_line": dict_line,
                "message": msg,
                "mapped": dict_line is not None,
            })
            if dict_line is not None:
                out_lines.append(f"{dict_path}:{dict_line}: {severity}: {msg}")
            else:
                out_lines.append(
                    f"{dict_path}:?: {severity}: {msg}  "
                    f"[unmapped — generated-C line {c_line} has no preceding "
                    f"@dictum-line marker; likely a preamble/global/forward-decl "
                    f"line rather than inside a statement body]"
                )
        else:
            out_lines.append(raw_line)

    return "\n".join(out_lines), diagnostics


# ─────────────────────────────────────────────────────────────────────────
# Case A detection — parse/validate, in-process (no subprocess needed,
# and this is where the *original*, already-precise line numbers live —
# see parser.py's `at line N` / validator.py's `[Line N]` conventions)
# ─────────────────────────────────────────────────────────────────────────

_SYNTAX_LINE_RE = re.compile(r'at line (\d+)')
_VALIDATION_LINE_RE = re.compile(r'^\[Line (\d+)\]\s*(.*)$')


def try_parse_and_validate(source: str, backend: str, stdlib: bool = True,
                            source_path: str = "") -> Dict[str, Any]:
    """Returns {"ok": True, "code": ..., "result": ...} on success, or
    {"ok": False, "stage": "syntax"|"validation", "errors": [...]} with
    each error already carrying its .dict line number, straight from the
    real lexer/parser/validator — this is Case A's evidence, gathered
    without ever touching gcc.

    `source_path`, when given, is threaded to the Transpiler so the real
    .dict filename (not a placeholder) ends up in the emitted code's real
    `#line` directives (line_directives.py / debug_mapper.py) — this is
    what lets debug_mapper's tier-1 fast path recognize gcc's own output
    as already pointing at the right file, with no line-map needed."""
    from dictumc.transpiler import Transpiler, StdlibTranspiler
    from dictumc.validator import ValidationError

    TranspilerClass = StdlibTranspiler if stdlib else Transpiler
    try:
        t = TranspilerClass(source=source, backend=backend, source_path=source_path)
        result = t.run(validate=True)
        return {"ok": True, "code": result["code"], "result": result}
    except SyntaxError as e:
        msg = str(e)
        m = _SYNTAX_LINE_RE.search(msg)
        errs = [{"line": int(m.group(1)) if m else None, "message": msg}]
        from dictumc.structured_errors import enrich_errors
        errs = enrich_errors(errs, source)
        return {
            "ok": False,
            "stage": "syntax",
            "errors": errs,
        }
    except ValidationError as e:
        errs = []
        for part in str(e).split("\n"):
            part = part.strip()
            if not part:
                continue
            vm = _VALIDATION_LINE_RE.match(part)
            if vm:
                errs.append({"line": int(vm.group(1)), "message": vm.group(2)})
            else:
                errs.append({"line": None, "message": part})
        from dictumc.structured_errors import enrich_errors
        errs = enrich_errors(errs, source)
        return {"ok": False, "stage": "validation", "errors": errs}


# ─────────────────────────────────────────────────────────────────────────
# Case D detection — declared LIBRARIES vs. what's actually blessed
# ─────────────────────────────────────────────────────────────────────────

def check_library_blessing(libraries: List[str], target: str) -> List[Dict[str, Any]]:
    """Best-effort Case D check. Guide B §2a describes a target-tagged
    `import_c_registry.py` keyed `<library>/<target>-<toolchain>`; if that
    registry exists in this checkout, use it for a real per-target
    answer. If it doesn't exist yet, fall back to the coarser signal of
    "is there a blessed/<lib>.dict at all" and say so explicitly, rather
    than silently pretending a per-target check happened."""
    results = []
    registry = None
    if os.path.exists(REGISTRY_PATH):
        try:
            sys.path.insert(0, os.path.join(HERE, "dictumc"))
            import import_c_registry  # type: ignore
            registry = import_c_registry
        except Exception:
            registry = None

    blessed_files = set()
    if os.path.isdir(BLESSED_DIR):
        blessed_files = {
            os.path.splitext(f)[0] for f in os.listdir(BLESSED_DIR) if f.endswith(".dict")
        }

    for lib in libraries:
        lib_norm = lib.strip().lower()
        if registry is not None and hasattr(registry, "is_blessed"):
            blessed = registry.is_blessed(lib_norm, target)
            results.append({
                "library": lib,
                "target": target,
                "blessed": blessed,
                "source": "import_c_registry.py (target-tagged)",
            })
        else:
            # No target-tagged registry exists yet. Per Guide B §2a/§3: a
            # same-named bridge is NEVER safe to assume valid for another
            # target just because the name matches, so the coarse presence
            # check can only ever answer "unverifiable", never "blessed" —
            # setting True here would silently reintroduce exactly the
            # cross-target reuse mistake the guide calls out by name.
            any_bridge_exists = lib_norm in blessed_files
            results.append({
                "library": lib,
                "target": target,
                "blessed": None,
                "source": (
                    f"no target-tagged import_c_registry.py found at {REGISTRY_PATH} — "
                    f"{'a blessed/' + lib_norm + '.dict exists but its target is not recorded here' if any_bridge_exists else 'no blessed/' + lib_norm + '.dict found at all'}; "
                    "cannot confirm blessing for this specific target without "
                    "a manual check per Guide B §2a"
                ),
            })

    return results


# ─────────────────────────────────────────────────────────────────────────
# End-to-end triage
# ─────────────────────────────────────────────────────────────────────────

def _gcc_compile(code: str, backend: str, cpp_standard: Optional[int], ldflags: List[str],
                  extra_include_dirs: Optional[List[str]] = None) -> Tuple[subprocess.CompletedProcess, str, str]:
    ext = ".cpp" if backend == "cpp" else ".c"
    compiler = "g++" if backend == "cpp" else "gcc"
    flags = [f"-std=c++{cpp_standard or 17}"] if backend == "cpp" else ["-std=c11"]
    flags += ["-Wall", "-Wextra", "-Werror", "-O2", "-I", RUNTIME_DIR]
    for d in (extra_include_dirs or []):
        flags += ["-I", d]

    with tempfile.NamedTemporaryFile(suffix=ext, mode="w", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        src_path = tf.name
    bin_path = src_path[:-len(ext)] + "_bin"

    proc = subprocess.run(
        [compiler, *flags, src_path, "-o", bin_path, *ldflags],
        capture_output=True, text=True, timeout=60,
    )
    return proc, src_path, bin_path


def triage_file(
    path: str,
    backend: Optional[str] = None,
    expected_output: Optional[str] = None,
    run_timeout: int = 8,
    keep_artifacts: bool = False,
) -> Dict[str, Any]:
    """The full Guide B §1/§1a/§2 mechanical pass for one .dict file.
    Returns a single structured verdict — see the `case` field:
      "A"        — .dict file mistake, exact line(s)/message(s) attached
      "C"        — compiler bug, mapped to exact .dict line(s) where possible
      "D"        — declared library not blessed (or blessing unverifiable)
                    for the declared target
      "clean"    — compiled, linked, ran; matched expected_output if given
      "ambiguous"— compiled/ran but output didn't match expected_output
                    (or none was given) — ONLY a human/AI with Guide A +
                    the README can resolve this into A vs C, see Guide B §2
                    Case B/§0 step 4. All evidence is attached so that
                    decision needs no further tool calls.
    """
    source = open(path, encoding="utf-8").read()
    manifest = parse_manifest(source)
    backend = backend or manifest.backend or "c"
    dict_path = os.path.abspath(path)

    report: Dict[str, Any] = {
        "file": dict_path,
        "manifest": {
            "present": manifest.present,
            "target": manifest.target,
            "backend": backend,
            "cpp_standard": manifest.cpp_standard,
            "libraries": manifest.libraries,
            "gui": manifest.gui,
        },
    }

    # ---- Case D pre-check: don't even attempt a normal compile if a
    # declared library isn't known-blessed for the declared target
    # (Guide B §1a / Case D) ----
    if manifest.libraries:
        blessing = check_library_blessing(manifest.libraries, manifest.target)
        report["library_blessing"] = blessing
        unblessed = [b for b in blessing if b["blessed"] is False]
        unverifiable = [b for b in blessing if b["blessed"] is None]
        if unblessed:
            report["case"] = "D"
            report["summary"] = (
                f"{len(unblessed)} declared librar{'y is' if len(unblessed)==1 else 'ies are'} "
                f"not blessed for TARGET: {manifest.target} — "
                f"{', '.join(b['library'] for b in unblessed)}. "
                "Do not attempt a normal compile; follow Guide B §2a bridge "
                "generation protocol before proceeding."
            )
            return report
        if unverifiable:
            report["note"] = (
                "Some declared libraries could not be checked against a "
                "target-tagged registry (none found at "
                f"{REGISTRY_PATH}); proceeding with compile, but a linker "
                "failure below may actually be Case D, not Case C — check "
                "manually per Guide B §2a."
            )

    # ---- Step 1: parse + validate in-process (Case A's fast path) ----
    pv = try_parse_and_validate(source, backend, source_path=dict_path)
    if not pv["ok"]:
        report["case"] = "A"
        report["stage"] = pv["stage"]
        report["errors"] = pv["errors"]
        report["summary"] = (
            f"{pv['stage']} error(s) in the .dict file itself, "
            f"{len(pv['errors'])} total — see `errors` for exact line(s). "
            "Cross-check each against GUIDE_A_dict_language_reference.md "
            "before editing (Guide B §2 Case A)."
        )
        return report

    code = pv["code"]
    result = pv["result"]
    ldflags = result.get("ldflags") or ["-lm"]

    # ---- Step 2: real gcc/g++ compile ----
    try:
        proc, src_path, bin_path = _gcc_compile(code, backend, manifest.cpp_standard, ldflags)
    except FileNotFoundError as e:
        report["case"] = "environment"
        report["summary"] = f"compiler not found: {e}"
        return report

    if proc.returncode != 0:
        from dictumc import debug_mapper
        line_map = build_dictum_line_map(code)
        translated, diags = debug_mapper.map_gcc_output(proc.stderr, src_path, dict_path,
                                                          marker_line_map=line_map)
        mapped = [d for d in diags if d["mapped"] and d["severity"] == "error"]
        unmapped = [d for d in diags if not d["mapped"] and d["severity"] == "error"]

        report["case"] = "C"
        report["gcc_returncode"] = proc.returncode
        report["gcc_stderr_raw"] = proc.stderr
        report["gcc_stderr_translated"] = translated
        report["diagnostics"] = diags
        report["generated_code"] = code
        if not keep_artifacts:
            os.unlink(src_path)
        if mapped:
            lines_str = ", ".join(str(d["dict_line"]) for d in mapped)
            snippet_lines = source.splitlines()
            snippets = {
                d["dict_line"]: snippet_lines[d["dict_line"] - 1]
                if 0 < d["dict_line"] <= len(snippet_lines) else None
                for d in mapped
            }
            report["dict_line_snippets"] = snippets
            report["summary"] = (
                f"gcc/g++ rejected the generated {('C++' if backend=='cpp' else 'C')}; "
                f"mapped to real .dict line(s) {lines_str}. The .dict source at "
                f"{'that line' if len(mapped)==1 else 'those lines'} is syntactically "
                "valid per the parser (it got past validation) — read the mapped "
                "line(s) + the generated C around the marker before deciding this "
                "is a real compiler bug (Case C) vs. a Case A logic mistake the "
                "validator can't catch. If it's Case C, follow Guide B §2 Case C "
                "steps 1-8 (root-cause in emit_c.py/emit_cpp.py, fix, regression "
                "test, Guide A sync)."
            )
        else:
            report["summary"] = (
                "gcc/g++ rejected the generated code but no error line mapped "
                "back to a real .dict statement line (see `gcc_stderr_translated` "
                "— these are marked [unmapped]). This usually means the failure "
                "is in preamble/global/forward-decl code the marker pass doesn't "
                "cover — read the raw generated C directly (`generated_code`)."
            )
        return report

    # ---- Step 3: link succeeded — run it, diff if we have an expected value ----
    try:
        run = subprocess.run([bin_path], capture_output=True, text=True, timeout=run_timeout)
    except subprocess.TimeoutExpired:
        report["case"] = "ambiguous"
        report["summary"] = (
            f"binary compiled and linked cleanly but did not exit within "
            f"{run_timeout}s — could be an intentional long-running/GUI "
            "program (check manifest GUI field / hand off to Guide C) or a "
            "real hang bug. Not auto-classifiable."
        )
        if not keep_artifacts:
            os.unlink(src_path)
        return report

    if not keep_artifacts:
        os.unlink(src_path)
        if os.path.exists(bin_path):
            os.unlink(bin_path)

    report["run_returncode"] = run.returncode
    report["stdout"] = run.stdout
    report["stderr"] = run.stderr

    if expected_output is not None:
        if run.returncode == 0 and run.stdout == expected_output:
            report["case"] = "clean"
            report["summary"] = "compiled, linked, ran, output matched expected_output exactly."
        else:
            report["case"] = "ambiguous"
            report["expected_output"] = expected_output
            report["summary"] = (
                "compiled and ran, but output didn't match expected_output. "
                "This is Guide B §0 step 4 territory — could be Case A (the "
                ".dict logic itself is wrong) or Case C (compiler silently "
                "miscompiled correct .dict logic). Needs the README's stated "
                "intent (Guide A §20) to resolve; both `stdout` and "
                "`expected_output` are attached so no further tool call is "
                "needed to make that call."
            )
    else:
        report["case"] = "ambiguous"
        report["summary"] = (
            "compiled, linked, and ran with no crash (exit "
            f"{run.returncode}), but no expected_output was supplied so "
            "correctness can't be checked — this is NOT the same as "
            "'clean'. Per Guide B §0 step 4, an independently known-correct "
            "expected value (hand-computed, from the README, or a stated "
            "arithmetic identity) is required before this can be called done."
        )
    return report


# ─────────────────────────────────────────────────────────────────────────
# Multi-file project triage — Guide B §1's other documented input shape
# ("a directory of .dict files"), via the real project_builder.py
# ─────────────────────────────────────────────────────────────────────────

def parse_project_manifest(workspace: str) -> Manifest:
    """Guide A §19: for a project directory, the Build Manifest is a plain
    `MANIFEST.txt` at the project root — a different file from
    project_builder.py's own `dictum.project.json` (that one is the
    compiler's internal build config: backend/cpp_standard/exclude list;
    this one is Guide B/C's target/library/GUI declaration). Absence
    defaults exactly as it does for a single file."""
    path = os.path.join(workspace, "MANIFEST.txt")
    if not os.path.exists(path):
        return Manifest(present=False)
    text = open(path, encoding="utf-8").read()
    # Reuse the same KEY: value line parser as the single-file path, just
    # without requiring a leading '#' (MANIFEST.txt is plain text, not a
    # comment block inside a .dict file).
    found: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip().upper()
        if key in _MANIFEST_KEYS:
            found[key] = val.strip()
    if not found:
        return Manifest(present=False)
    libs_raw = found.get("LIBRARIES", "none")
    libs = [] if libs_raw.strip().lower() == "none" else [
        s.strip() for s in libs_raw.split(",") if s.strip()
    ]
    cpp_std = found.get("CPP_STANDARD")
    return Manifest(
        present=True,
        target=found.get("TARGET", "linux").strip().lower(),
        backend=found.get("BACKEND", "c").strip().lower(),
        cpp_standard=int(cpp_std) if cpp_std and cpp_std.isdigit() else None,
        libraries=libs,
        gui=found.get("GUI", "no").strip().lower() == "yes",
    )


def triage_project(
    workspace: str,
    backend: Optional[str] = None,
    expected_output: Optional[str] = None,
    run_timeout: int = 8,
    keep_artifacts: bool = False,
    static: bool = False,
) -> Dict[str, Any]:
    """Project-directory counterpart of triage_file(). Runs the real
    `project_builder.py` build_project() in-process (Case A across every
    file), then a real `make` in the generated build dir (Case C, with
    each gcc/g++ error mapped back to its own originating .dict file by
    the same basename convention project_builder.py itself uses), then
    runs the resulting binary if one expected_output is given."""
    import project_builder

    workspace = os.path.abspath(workspace)
    manifest = parse_project_manifest(workspace)
    backend = backend or manifest.backend or "c"

    report: Dict[str, Any] = {
        "workspace": workspace,
        "manifest": {
            "present": manifest.present,
            "target": manifest.target,
            "backend": backend,
            "cpp_standard": manifest.cpp_standard,
            "libraries": manifest.libraries,
            "gui": manifest.gui,
        },
    }

    if manifest.libraries:
        blessing = check_library_blessing(manifest.libraries, manifest.target)
        report["library_blessing"] = blessing
        unblessed = [b for b in blessing if b["blessed"] is False]
        if unblessed:
            report["case"] = "D"
            report["summary"] = (
                f"{len(unblessed)} declared librar{'y is' if len(unblessed)==1 else 'ies are'} "
                f"not blessed for TARGET: {manifest.target} — "
                f"{', '.join(b['library'] for b in unblessed)}. "
                "Follow Guide B §2a before attempting a build."
            )
            return report

    build_dir = os.path.join(tempfile.mkdtemp(prefix="dict_triage_project_"), "build")
    result = project_builder.build_project(
        workspace=workspace,
        backend=backend,
        cpp_standard=manifest.cpp_standard or 17,
        out_dir=build_dir,
        static=static,
    )

    if not result["success"]:
        errors = []
        for e in result["errors"]:
            msg = e["message"]
            sm = _SYNTAX_LINE_RE.search(msg)
            vm = _VALIDATION_LINE_RE.match(msg.split("\n")[0].strip())
            line = int(sm.group(1)) if sm else (int(vm.group(1)) if vm else None)
            errors.append({"file": e["file"], "line": line, "message": msg})
        report["case"] = "A"
        report["errors"] = errors
        report["summary"] = (
            f"{len(errors)} error(s) across the project — see `errors` for "
            "file + line. Cross-check each against GUIDE_A_dict_language_"
            "reference.md before editing (Guide B §2 Case A)."
        )
        return report

    # Real `make` — same discipline as Guide B §1's `cd build && make`.
    make_proc = subprocess.run(
        ["make"], cwd=build_dir, capture_output=True, text=True, timeout=90,
    )
    if make_proc.returncode != 0:
        # Build per-file line maps for every generated .c/.cpp so each
        # error can be traced back to the right *.dict* file, not just
        # "somewhere in the project".
        ext = ".c" if backend == "c" else ".cpp"
        line_maps: Dict[str, Dict[int, int]] = {}
        for fname in os.listdir(build_dir):
            if fname.endswith(ext):
                code = open(os.path.join(build_dir, fname), encoding="utf-8").read()
                line_maps[fname] = build_dictum_line_map(code)

        diags = []
        translated_lines = []
        for raw_line in make_proc.stderr.split("\n"):
            m = re.match(r'^(?P<path>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|note):\s*(?P<msg>.*)$', raw_line)
            if m:
                src_base = os.path.basename(m.group("path"))
                dict_base = os.path.splitext(src_base)[0] + ".dict"
                c_line = int(m.group("line"))
                dict_line = line_maps.get(src_base, {}).get(c_line)
                diags.append({
                    "dict_file": dict_base,
                    "dict_line": dict_line,
                    "c_file": src_base,
                    "c_line": c_line,
                    "severity": m.group("severity"),
                    "message": m.group("msg"),
                    "mapped": dict_line is not None,
                })
                if dict_line is not None:
                    translated_lines.append(f"{dict_base}:{dict_line}: {m.group('severity')}: {m.group('msg')}")
                else:
                    translated_lines.append(f"{dict_base}:?: {m.group('severity')}: {m.group('msg')} [unmapped]")
            else:
                translated_lines.append(raw_line)

        report["case"] = "C"
        report["make_returncode"] = make_proc.returncode
        report["make_stderr_raw"] = make_proc.stderr
        report["make_stderr_translated"] = "\n".join(translated_lines)
        report["diagnostics"] = diags
        mapped = [d for d in diags if d["mapped"] and d["severity"] == "error"]
        report["summary"] = (
            f"`make` failed in the generated build dir; "
            f"{len(mapped)} error(s) mapped back to real .dict file+line "
            "(see `diagnostics`). Same Case A-vs-Case C judgment call as "
            "the single-file path applies per line."
        )
        if not keep_artifacts:
            import shutil as _shutil
            _shutil.rmtree(os.path.dirname(build_dir), ignore_errors=True)
        return report

    # Find the built binary — project_builder names it after the first
    # program found (see generate_makefile's prog_name); just take the
    # Makefile's own TARGET line to avoid re-deriving that logic here.
    target_name = None
    mf = os.path.join(build_dir, "Makefile")
    if os.path.exists(mf):
        for line in open(mf, encoding="utf-8"):
            if line.startswith("TARGET"):
                target_name = line.split("=", 1)[1].strip()
                break
    bin_path = os.path.join(build_dir, target_name) if target_name else None
    if keep_artifacts:
        report["bin_path"] = bin_path  # only meaningful when the build dir actually persists

    if not bin_path or not os.path.exists(bin_path):
        report["case"] = "ambiguous"
        report["summary"] = "make succeeded but the expected binary wasn't found — check Makefile TARGET manually."
        return report

    if static:
        sys.path.insert(0, os.path.join(HERE, "verify"))
        import verify_static_link
        report["static_link_check"] = verify_static_link.check(bin_path)

    try:
        run = subprocess.run([bin_path], capture_output=True, text=True, timeout=run_timeout)
    except subprocess.TimeoutExpired:
        report["case"] = "ambiguous"
        report["summary"] = f"binary built cleanly but didn't exit within {run_timeout}s — check manifest GUI field / hand off to Guide C."
        if not keep_artifacts:
            import shutil as _shutil
            _shutil.rmtree(os.path.dirname(build_dir), ignore_errors=True)
        return report

    report["run_returncode"] = run.returncode
    report["stdout"] = run.stdout
    report["stderr"] = run.stderr

    if not keep_artifacts:
        import shutil as _shutil
        _shutil.rmtree(os.path.dirname(build_dir), ignore_errors=True)
    else:
        report["build_dir"] = build_dir

    if expected_output is not None:
        if run.returncode == 0 and run.stdout == expected_output:
            report["case"] = "clean"
            report["summary"] = "project built, linked, ran; output matched expected_output exactly."
        else:
            report["case"] = "ambiguous"
            report["expected_output"] = expected_output
            report["summary"] = "project ran but output didn't match expected_output — needs the README's stated intent to resolve (Guide B §0 step 4)."
    else:
        report["case"] = "ambiguous"
        report["summary"] = "project built and ran with no crash, but no expected_output was supplied so correctness can't be confirmed (Guide B §0 step 4)."

    # Static linking was explicitly requested (a freelance-deliverable
    # requirement, not a nice-to-have) but real ldd shows it isn't --
    # this overrides an otherwise-clean logic result. Correct program
    # logic in a binary that still needs the client's exact glibc/shared
    # libs isn't the deliverable that was promised.
    slc = report.get("static_link_check")
    if slc and slc.get("ok") is False:
        report["case"] = "ambiguous"
        report["summary"] = ("program logic may be correct, but --static was requested and the "
                              f"binary is NOT actually static: {slc['detail']}")
    return report




_R_HEADER_RE = re.compile(r'@regression\("R(\d+)\b')


def next_regression_number(selftest_path: str) -> int:
    text = open(selftest_path, encoding="utf-8").read()
    nums = [int(m.group(1)) for m in _R_HEADER_RE.finditer(text)]
    return (max(nums) + 1) if nums else 1


def emit_regression_stub(selftest_path: str, dict_path: str, backend: str, bug_summary: str) -> str:
    """Appends a templated `Rn` regression-test stub to run_selftest.py,
    following the exact shape of the existing R1-R23 tests, with the
    failing .dict source embedded so it becomes a real, standalone
    regression case. The AI still has to fill in the TODOs (expected
    output, and the fix itself) — this only removes the boilerplate."""
    n = next_regression_number(selftest_path)
    src = open(dict_path, encoding="utf-8").read()
    # Embed the source as a Python triple-quoted literal, escaping only
    # what's needed to keep it a valid Python string.
    escaped = src.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    func_name = f"test_r{n}_{os.path.splitext(os.path.basename(dict_path))[0]}"
    func_name = re.sub(r"\W", "_", func_name)

    stub = f'''

@regression("R{n} {bug_summary}  [TODO: fill in real summary once root-caused per Guide B §2 Case C]")
def {func_name}(tmp):
    os.makedirs(tmp, exist_ok=True)
    src = os.path.join(tmp, "main.dict")
    open(src, "w", encoding="utf-8").write("""\\
{escaped}""")
    r = subprocess.run(
        [sys.executable, CLI, src, "--backend", "{backend}", "--compile",
         "--output", os.path.join(tmp, "out")],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return False, f"compile failed (TODO: confirm this is the fixed-and-should-pass case, not still failing): {{r.stdout}}\\n{{r.stderr}}"
    run = _run(os.path.join(tmp, "out"))
    if run.returncode != 0:
        return False, f"runtime failure: rc={{run.returncode}} stdout={{run.stdout!r}} stderr={{run.stderr!r}}"
    # TODO: replace with the real, independently-known-correct expected
    # value (Guide B §0 step 4) before this stub counts as a real test.
    if run.stdout != "TODO_EXPECTED_OUTPUT":
        return False, f"TODO: fill in real expected output; got: {{run.stdout!r}}"
    return True, "ok"
'''
    with open(selftest_path, "a", encoding="utf-8") as fh:
        fh.write(stub)
    return func_name


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        prog="dict_triage.py",
        description="Automated Guide B triage: run a .dict file for real, "
                     "classify any failure (Case A/C/D), map gcc errors "
                     "back to .dict lines, and optionally scaffold a "
                     "regression test stub.",
    )
    p.add_argument("file", help="Path to the .dict file, or a project directory, to triage")
    p.add_argument("--backend", choices=["c", "cpp"], default=None,
                    help="Override the manifest's declared backend")
    p.add_argument("--expected-output", default=None,
                    help="Known-correct expected stdout, for Guide B §0 step 4")
    p.add_argument("--expected-output-file", default=None,
                    help="Read expected stdout from a file instead")
    p.add_argument("--json", action="store_true", help="Print raw JSON report")
    p.add_argument("--emit-regression-stub", action="store_true",
                    help="On Case C, append an Rn stub to run_selftest.py")
    p.add_argument("--selftest-path", default=os.path.join(HERE, "run_selftest.py"))
    p.add_argument("--keep-artifacts", action="store_true",
                    help="Don't delete the temp .c/.cpp/binary (for manual inspection)")
    p.add_argument("--cache", action="store_true",
                    help="Serve a cached verdict when the file, args, and compiler "
                         "internals are all unchanged since the last --cache run "
                         "(see verify/cache_lib.py). Off by default.")
    p.add_argument("--cache-path", default=None,
                    help="Cache file location (default: .dict_triage_cache.json next "
                         "to the target file)")
    p.add_argument("--static", action="store_true",
                    help="Static-link the build (project mode only) and verify with real "
                         "ldd, not just trust the flag. See verify/verify_static_link.py.")
    args = p.parse_args()

    expected = args.expected_output
    if args.expected_output_file:
        expected = open(args.expected_output_file, encoding="utf-8").read()

    cache = None
    cache_key = None
    if args.cache:
        sys.path.insert(0, os.path.join(HERE, "verify"))
        import cache_lib
        target = os.path.abspath(args.file)
        cache_path = args.cache_path or os.path.join(
            os.path.dirname(target) if not os.path.isdir(target) else target,
            ".dict_triage_cache.json",
        )
        cache = cache_lib.Cache(cache_path)
        source_fingerprint = (
            cache_lib._file_fingerprint(target) if os.path.isdir(target)
            else cache_lib.hash_inputs(open(target, encoding="utf-8").read())
        )
        cache_key = cache_lib.hash_inputs(
            source_fingerprint,
            cache_lib.compiler_fingerprint(os.path.join(HERE, "dictumc")),
            str(args.backend), str(expected),
        )
        cached = cache.get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached["from_cache"] = True
            if args.json:
                print(json.dumps(cached, indent=2, default=str))
            else:
                _print_human(cached)
                print("\n(served from cache -- file, args, and compiler internals all "
                      "unchanged since the last --cache run; re-run without --cache, or "
                      "touch the file, to force a fresh check)")
            return 0 if cached.get("case") == "clean" else 1

    report = triage_project(args.file, backend=args.backend, expected_output=expected,
                             keep_artifacts=args.keep_artifacts, static=args.static) if os.path.isdir(args.file) else triage_file(
        args.file,
        backend=args.backend,
        expected_output=expected,
        keep_artifacts=args.keep_artifacts,
    )

    if cache is not None:
        report["from_cache"] = False
        cache.set(cache_key, report)

    if args.emit_regression_stub and report.get("case") == "C" and not os.path.isdir(args.file):
        func_name = emit_regression_stub(
            args.selftest_path, args.file,
            report["manifest"]["backend"],
            report["summary"].split("\n")[0][:100],
        )
        report["regression_stub_added"] = func_name

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)

    return 0 if report.get("case") == "clean" else 1


def _print_human(report: Dict[str, Any]) -> None:
    print(f"{'workspace' if 'workspace' in report else 'file':<9} {report.get('file') or report.get('workspace')}")
    m = report["manifest"]
    print(f"manifest: TARGET={m['target']} BACKEND={m['backend']} "
          f"LIBRARIES={','.join(m['libraries']) or 'none'} GUI={'yes' if m['gui'] else 'no'}"
          f"{' (defaulted — no manifest found)' if not m['present'] else ''}")
    print(f"case:     {report.get('case', '?')}")
    print()
    print(report.get("summary", ""))
    print()
    if report.get("note"):
        print(f"note: {report['note']}")
        print()

    if report.get("case") == "A":
        for e in report["errors"]:
            loc = f"line {e['line']}" if e.get("line") else "line unknown"
            prefix = f"{e['file']} " if "file" in e else ""
            stage = f"[{report['stage']}] " if "stage" in report else ""
            print(f"  {stage}{prefix}{loc}: {e['message']}")

    elif report.get("case") == "C" and "diagnostics" in report and report["diagnostics"] and "dict_file" in report["diagnostics"][0]:
        for d in report["diagnostics"]:
            if d["severity"] != "error":
                continue
            loc = f"{d['dict_file']}:{d['dict_line']}" if d["mapped"] else f"{d['dict_file']}:[unmapped]"
            print(f"  {loc}  (generated {d['c_file']} line {d['c_line']}): {d['message']}")

    elif report.get("case") == "C":
        for d in report.get("diagnostics", []):
            if d["severity"] != "error":
                continue
            loc = f".dict:{d['dict_line']}" if d["mapped"] else "[unmapped]"
            print(f"  {loc}  (generated C line {d['c_line']}): {d['message']}")
        snippets = report.get("dict_line_snippets") or {}
        if snippets:
            print()
            print("  .dict source at mapped line(s):")
            for line_no, text in snippets.items():
                print(f"    {line_no}: {text}")

    elif report.get("case") == "D":
        for b in report.get("library_blessing", []):
            print(f"  {b['library']} / {b['target']}: blessed={b['blessed']} ({b['source']})")

    elif report.get("case") == "ambiguous":
        print(f"  stdout: {report.get('stdout', '')!r}")
        if "expected_output" in report:
            print(f"  expected: {report['expected_output']!r}")

    if report.get("regression_stub_added"):
        print()
        print(f"regression stub added: {report['regression_stub_added']} "
              f"(fill in the TODOs, then re-run the full suite)")


if __name__ == "__main__":
    sys.exit(main())
