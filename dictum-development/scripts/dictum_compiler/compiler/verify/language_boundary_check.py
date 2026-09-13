#!/usr/bin/env python3
"""
language_boundary_check.py — validates a SOURCE_OF_TRUTH_<project>.md's
`## Language Boundary` section (Guide A §0 Phase 1b) against reality, the
same way guide_a_coverage_check.py validates the roadmap against the test
manifest and guide_a_traceability_check.py validates it against real code.

WHAT THIS CLOSES
------------------
The Python-orchestrates/Dictum-verifies split (Guide A §0 Phase 1b) turns
"which language for this block" into a written, reviewable decision via a
`### block: NAME` / `exposes: fn1, fn2` / `verified_by: ...` format. A
written decision that nobody re-checks against the real code is just a
nicer-looking guess. This script makes the `exposes:` line a checkable
claim instead of prose:

  - `file:` must actually exist in the project.
  - For a `language: dictum` block with an `exposes:` list, every named
    action must actually exist in that .dict file AND actually be
    bindable by `dictum emit-binding` (tools/emit_binding.py) -- reusing
    emit_binding.py's OWN action-collection and scope-checking logic, so
    this can never disagree with what emit-binding would really do.
    Claiming an action is exposed when it has a `text` return, a
    container type, or is a template is caught here -- at review time,
    not discovered later when a Python orchestrator imports a binding
    that silently doesn't have the function it expected.

WHAT THIS DOES NOT DO
------------------------
It does not check that `rationale:` is a GOOD rationale, or that
`verified_by:` names a check that actually exists and passes -- that's
requirement-to-test territory guide_a_coverage_check.py already owns for
roadmap IDs, and duplicating it here for boundary blocks would be a
second, driftable copy of the same idea. This script's job is narrower
and mechanical: does the language boundary, as WRITTEN, match the
language boundary as it REALLY IS in the code.

Usage:
    python3 language_boundary_check.py --source-of-truth SOURCE_OF_TRUTH_x.md --project .
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)
TOOLS_DIR = os.path.join(COMPILER_DIR, "tools")
sys.path.insert(0, TOOLS_DIR)
sys.path.insert(0, COMPILER_DIR)

KNOWN_LANGUAGES = {"dictum", "python", "c", "cpp", "c++", "javascript", "rust", "go"}

_BLOCK_HEADER_RE = re.compile(r'^###\s+block:\s*(\S+)\s*$', re.MULTILINE)
_FIELD_RE = re.compile(r'^-\s*([a-zA-Z_]+):\s*(.+)$', re.MULTILINE)


def _extract_section(markdown: str) -> Optional[str]:
    m = re.search(r'^##\s+Language Boundary\s*$', markdown, re.MULTILINE)
    if not m:
        return None
    rest = markdown[m.end():]
    # stop at the next top-level (##) heading, if any
    nxt = re.search(r'^##\s+\S', rest, re.MULTILINE)
    return rest[:nxt.start()] if nxt else rest


def parse_language_boundary(markdown_path: str) -> List[Dict[str, Any]]:
    """[] if the project has no `## Language Boundary` section at all --
    that's a normal, valid state for a pure-Dictum project, not an error."""
    text = open(markdown_path, encoding="utf-8").read()
    section = _extract_section(text)
    if section is None:
        return []

    headers = list(_BLOCK_HEADER_RE.finditer(section))
    blocks = []
    for i, h in enumerate(headers):
        name = h.group(1)
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(section)
        body = section[start:end]
        fields: Dict[str, str] = {}
        for fm in _FIELD_RE.finditer(body):
            key, val = fm.group(1).strip().lower(), fm.group(2).strip()
            fields[key] = val
        blocks.append({"name": name, **fields})
    return blocks


def _bindable_action_names(dict_path: str) -> Dict[str, Optional[str]]:
    """action_name -> None if bindable, or a reason string if
    emit_binding.py would skip it. Reuses emit_binding.py's OWN
    collection/scope logic directly rather than re-implementing it, so
    this check can never quietly diverge from what `dictum emit-binding`
    would really do."""
    import emit_binding
    source = open(dict_path, encoding="utf-8").read()
    actions = emit_binding._collect_actions(source)
    result: Dict[str, Optional[str]] = {}
    for symbol, action in actions:
        name = action.name
        if action.template_params:
            result[name] = "generic (template) action -- no single fixed ABI to bind"
            continue
        bad = None
        for pname, ptype in action.params:
            if emit_binding._resolve_param_ctype(ptype) is None:
                bad = f"parameter '{pname}' has unsupported type '{ptype}'"
                break
        if bad:
            result[name] = bad
            continue
        if action.ret_type != "nothing" and emit_binding._resolve_return_ctype(action.ret_type) is None:
            result[name] = f"return type '{action.ret_type}' is not bindable (see emit_binding.py scope)"
            continue
        result[name] = None
    return result


def check(source_of_truth: str, project_dir: str) -> Dict[str, Any]:
    blocks = parse_language_boundary(source_of_truth)
    results = []
    ok = True

    for block in blocks:
        name = block["name"]
        entry: Dict[str, Any] = {"block": name, "problems": []}
        language = block.get("language")
        if not language:
            entry["problems"].append("no 'language:' field")
        elif language.lower() not in KNOWN_LANGUAGES:
            entry["problems"].append(f"unrecognized language '{language}' "
                                      f"(known: {sorted(KNOWN_LANGUAGES)})")

        file_rel = block.get("file")
        file_abs = None
        if not file_rel:
            entry["problems"].append("no 'file:' field")
        else:
            file_abs = os.path.join(project_dir, file_rel)
            if not os.path.exists(file_abs):
                entry["problems"].append(f"file '{file_rel}' does not exist under {project_dir}")

        exposes = block.get("exposes")
        if exposes:
            exposed_names = [n.strip() for n in exposes.split(",") if n.strip()]
            if not language or language.lower() != "dictum":
                entry["problems"].append("'exposes:' is only meaningful on a "
                                          "'language: dictum' block")
            elif file_abs and os.path.exists(file_abs):
                try:
                    bindable = _bindable_action_names(file_abs)
                except Exception as e:
                    entry["problems"].append(f"could not check exposed actions: {e}")
                    bindable = {}
                for n in exposed_names:
                    if n not in bindable:
                        entry["problems"].append(
                            f"exposes '{n}', but no such action exists in {file_rel}")
                    elif bindable[n] is not None:
                        entry["problems"].append(
                            f"exposes '{n}', but it is not bindable by "
                            f"`dictum emit-binding`: {bindable[n]}")
            entry["exposed"] = exposed_names

        entry["ok"] = not entry["problems"]
        if not entry["ok"]:
            ok = False
        results.append(entry)

    return {
        "source_of_truth": source_of_truth,
        "project_dir": project_dir,
        "blocks": results,
        "has_language_boundary_section": bool(blocks) or _extract_section(
            open(source_of_truth, encoding="utf-8").read()) is not None,
        "ok": ok,
    }


def print_human(report: Dict[str, Any]) -> None:
    if not report["has_language_boundary_section"]:
        print("No '## Language Boundary' section -- pure-Dictum project, nothing to check.")
        return
    for entry in report["blocks"]:
        tag = "OK" if entry["ok"] else "PROBLEMS"
        print(f"[{tag}] block: {entry['block']}")
        if entry.get("exposed"):
            print(f"       exposes: {', '.join(entry['exposed'])}")
        for p in entry["problems"]:
            print(f"       - {p}")
    print()
    print("OVERALL: " + ("OK" if report["ok"] else "NEEDS ATTENTION -- see PROBLEMS above"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-of-truth", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = check(args.source_of_truth, args.project)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
