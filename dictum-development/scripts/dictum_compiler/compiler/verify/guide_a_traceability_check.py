#!/usr/bin/env python3
"""
guide_a_traceability_check.py — closes the OTHER half of the traceability
gap HANDOFF.md §9.5 names as the crux of the "reading loop":

    "An auditor's real question is 'show me the code implementing
    requirement 3.' Nothing answers that today."

`guide_a_coverage_check.py` (already real, already wired into
run_pipeline.py) answers "which TEST covers roadmap ID Rn" -- it maps
[Rn] in SOURCE_OF_TRUTH_<project>.md to a `covers` entry in the Guide C
manifest. It does NOT answer "which CODE implements Rn" -- a roadmap
claim can be covered by a test and still have no traceable implementation,
or a `.dict` action can exist with no roadmap claim behind it (an orphan
nothing flags today).

This script closes that: it scans a project's real `.dict` source for a
lightweight, already-legal comment convention --

    # implements: R3, R4
    action compute_tariff takes ...

-- (Dictum's lexer already treats a bare `#` as a line comment; this adds
no grammar) and builds the missing half of the bidirectional map:

    roadmap ID  <->  code (this script, NEW)  <->  test (guide_a_coverage_check.py, EXISTING)

so a reader can ask "show me the code for R3" as a real, non-drifting
lookup instead of grep-and-hope, and so an orphan on EITHER side --
a roadmap claim with no implementing code, or a `.dict` construct tagged
with a roadmap ID that doesn't exist in the markdown (a rename/typo) --
becomes visible instead of silent.

WHAT THIS DOES NOT DO
----------------------
It does not require every `.dict` construct to carry a tag -- helper
actions, internal plumbing, and FFI bindings often have no 1:1 roadmap
claim, and forcing one would just produce noise. Untagged constructs are
reported informationally (`untagged`), never as a failure. The failure
signal is specifically: a roadmap claim with ZERO implementing code and
no declared gap, or a tag referencing a roadmap ID that does not exist.

Usage:
    python3 guide_a_traceability_check.py --project path/to/project_dir \\
        --source-of-truth SOURCE_OF_TRUTH_x.md [--manifest guide_c_manifest.json] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guide_a_coverage_check as coverage_check  # reuse the SAME roadmap-id /
                                                   # covered-id extraction so
                                                   # this can never disagree
                                                   # with the coverage check
                                                   # about what an [Rn] tag is

DECL_RE = re.compile(r'^\s*(program|action|module|method)\s+(\w+)')
IMPLEMENTS_RE = re.compile(r'implements\s*:\s*([A-Za-z0-9_,\s]+)', re.IGNORECASE)


def scan_dict_file(path: str, project_root: str) -> List[dict]:
    """Every top-level program/action/module/method declaration in one
    .dict file, with any roadmap IDs tagged on it via a `# implements:
    Rn, Rm` comment on one of the (blank-line-tolerant) lines immediately
    above the declaration."""
    text = open(path, encoding="utf-8", errors="replace").read()
    lines = text.splitlines()
    rel = os.path.relpath(path, project_root)
    out = []
    for i, line in enumerate(lines):
        m = DECL_RE.match(line)
        if not m:
            continue
        kind, name = m.group(1), m.group(2)
        ids: List[str] = []
        j = i - 1
        while j >= 0:
            stripped = lines[j].strip()
            if stripped == "":
                j -= 1
                continue
            if stripped.startswith("#"):
                im = IMPLEMENTS_RE.search(stripped)
                if im:
                    ids.extend(x.strip() for x in im.group(1).split(",") if x.strip())
                j -= 1
                continue
            break
        out.append({
            "kind": kind, "name": name, "file": rel, "line": i + 1,
            "implements": sorted(set(ids)),
        })
    return out


def scan_project(project_dir: str) -> List[dict]:
    constructs = []
    for root, _dirs, files in os.walk(project_dir):
        if os.sep + "build" + os.sep in root + os.sep:
            continue  # generated output, not source
        for fname in sorted(files):
            if fname.endswith(".dict"):
                constructs.extend(scan_dict_file(os.path.join(root, fname), project_dir))
    return constructs


def check(project_dir: str, source_of_truth: str, manifest_path: Optional[str] = None) -> dict:
    constructs = scan_project(project_dir)
    roadmap_ids = coverage_check.extract_roadmap_ids(source_of_truth)

    implemented_by: Dict[str, List[dict]] = {}
    orphan_tags: List[dict] = []  # tagged with an ID that isn't in the roadmap markdown
    untagged: List[dict] = []

    for c in constructs:
        if not c["implements"]:
            untagged.append(c)
            continue
        for rid in c["implements"]:
            entry = {"kind": c["kind"], "name": c["name"], "file": c["file"], "line": c["line"]}
            if rid in roadmap_ids:
                implemented_by.setdefault(rid, []).append(entry)
            else:
                orphan_tags.append({**entry, "tagged_id": rid})

    tested_by: Dict[str, List[str]] = {}
    gap_ids: Dict[str, str] = {}
    if manifest_path and os.path.exists(manifest_path):
        manifest = json.load(open(manifest_path))
        tested_by = coverage_check.extract_covered_ids(manifest)
        gap_ids = {g["roadmap_id"]: g.get("reason", "") for g in manifest.get("known_gaps", [])}

    unimplemented = sorted(
        rid for rid in roadmap_ids
        if rid not in implemented_by and rid not in gap_ids
    )

    trace_table = {}
    for rid in sorted(roadmap_ids):
        trace_table[rid] = {
            "implemented_by": implemented_by.get(rid, []),
            "tested_by": tested_by.get(rid, []),
            "declared_gap": gap_ids.get(rid),
        }

    ok = not unimplemented and not orphan_tags

    return {
        "project_dir": project_dir,
        "roadmap_ids": sorted(roadmap_ids),
        "trace_table": trace_table,
        "unimplemented": unimplemented,
        "orphan_tags": orphan_tags,
        "untagged_constructs": [
            {"kind": c["kind"], "name": c["name"], "file": c["file"], "line": c["line"]}
            for c in untagged
        ],
        "ok": ok,
    }


def print_human(report: dict) -> None:
    print(f"project: {report['project_dir']}")
    print(f"roadmap IDs: {len(report['roadmap_ids'])}")
    print()
    for rid, row in report["trace_table"].items():
        impl = row["implemented_by"]
        test = row["tested_by"]
        if impl:
            where = ", ".join(f"{e['file']}:{e['line']} ({e['kind']} {e['name']})" for e in impl)
            tag = "[IMPLEMENTED]"
        elif row["declared_gap"] is not None:
            where = f"declared gap: {row['declared_gap']}"
            tag = "[GAP]"
        else:
            where = "-- no implementing code found --"
            tag = "[UNIMPLEMENTED]"
        test_note = f", tested by: {', '.join(test)}" if test else ", NOT TESTED" if impl else ""
        print(f"  {tag} {rid} -- {where}{test_note}")

    if report["orphan_tags"]:
        print("\nWARNING -- code tagged with a roadmap ID that does not exist in "
              "the markdown (likely a rename/typo):")
        for o in report["orphan_tags"]:
            print(f"  {o['file']}:{o['line']} ({o['kind']} {o['name']}) -> tagged '{o['tagged_id']}'")

    if report["untagged_constructs"]:
        print(f"\n{len(report['untagged_constructs'])} untagged construct(s) "
              f"(informational -- not every construct needs a roadmap tag):")
        for u in report["untagged_constructs"]:
            print(f"  {u['file']}:{u['line']} ({u['kind']} {u['name']})")

    print()
    print("OVERALL: " + ("OK -- every roadmap claim has traceable implementing code, "
                          "no orphan tags"
                          if report["ok"] else
                          "NEEDS ATTENTION -- see UNIMPLEMENTED / WARNING lines above"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project directory containing .dict source")
    ap.add_argument("--source-of-truth", required=True)
    ap.add_argument("--manifest", default=None, help="optional: also merges in test coverage")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = check(args.project, args.source_of_truth, args.manifest)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
