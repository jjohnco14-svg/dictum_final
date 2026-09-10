#!/usr/bin/env python3
"""
guide_a_coverage_check.py — closes the traceability gap between Guide A's
Phase 1 roadmap and Guide C's Phase 2 Test Manifest.

The gap this exists to close: a roadmap claim in SOURCE_OF_TRUTH_<project>.md
("imports a DXF stock profile", "camera stays correctly positioned for
DXF-based meshes", ...) can currently have ZERO checks behind it and nothing
notices -- Guide C only ever runs what the manifest tells it to, so a claim
that never made it into the manifest is invisible, not failing. This script
makes that gap loud instead of silent.

It does NOT decide whether a check is a *good* check -- it only confirms
every roadmap ID tagged in the markdown is either:
  (a) referenced in at least one check's "covers" array in the JSON manifest, or
  (b) explicitly listed in the manifest's "known_gaps" with a stated reason.
A roadmap ID that's neither is reported as UNCOVERED -- a claim Guide A
made that nothing in Guide C's manifest currently protects.

It also checks the reverse direction: a "covers" entry in the manifest that
references an ID not present in the markdown is almost always a typo (an ID
that got renamed in one file and not the other) -- reported as
UNKNOWN_ID_REFERENCED so that kind of drift doesn't silently make a real
check look like it's covering something it isn't.

Roadmap items are tagged in the markdown like this, anywhere in the Phase 1
roadmap section:
    - [R1] Imports a DXF stock profile and a separate DXF target profile.
    - [R2] Camera framing stays correct for both legacy and DXF-based meshes.

Usage:
    python3 guide_a_coverage_check.py --source-of-truth SOURCE_OF_TRUTH_x.md \\
                                       --manifest guide_c_manifest.json
    python3 guide_a_coverage_check.py ... --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Set


ROADMAP_TAG_RE = re.compile(r"\[([A-Z][A-Za-z0-9_]*\d+)\]")


def extract_roadmap_ids(markdown_path: str) -> Set[str]:
    text = open(markdown_path, encoding="utf-8", errors="replace").read()
    return set(ROADMAP_TAG_RE.findall(text))


def extract_covered_ids(manifest: dict) -> Dict[str, List[str]]:
    """Map roadmap_id -> list of check names that claim to cover it."""
    covered: Dict[str, List[str]] = {}
    for section in ("console_checks", "gui_checks", "project_specific_scripts"):
        for check in manifest.get(section, []):
            for rid in check.get("covers", []):
                covered.setdefault(rid, []).append(check.get("name", "?"))
    return covered


def check(source_of_truth: str, manifest_path: str) -> dict:
    manifest = json.load(open(manifest_path))
    markdown_ids = extract_roadmap_ids(source_of_truth)
    manifest_declared_ids = set(manifest.get("roadmap_ids", {}).keys())
    covered = extract_covered_ids(manifest)
    gap_ids = {g["roadmap_id"]: g.get("reason", "") for g in manifest.get("known_gaps", [])}

    uncovered = sorted(markdown_ids - set(covered.keys()) - set(gap_ids.keys()))
    unknown_refs = sorted(set(covered.keys()) - markdown_ids)
    unknown_gap_refs = sorted(set(gap_ids.keys()) - markdown_ids)
    stale_manifest_ids = sorted(manifest_declared_ids - markdown_ids)
    missing_manifest_ids = sorted(markdown_ids - manifest_declared_ids)

    ok = not (uncovered or unknown_refs or unknown_gap_refs)

    return {
        "roadmap_ids_in_markdown": sorted(markdown_ids),
        "covered": {rid: names for rid, names in covered.items()},
        "declared_gaps": gap_ids,
        "uncovered": uncovered,
        "unknown_ids_referenced_in_covers": unknown_refs,
        "unknown_ids_referenced_in_known_gaps": unknown_gap_refs,
        "stale_roadmap_ids_block_entries": stale_manifest_ids,
        "roadmap_ids_missing_from_roadmap_ids_block": missing_manifest_ids,
        "ok": ok,
    }


def print_human(report: dict) -> None:
    print(f"Roadmap IDs found in markdown: {len(report['roadmap_ids_in_markdown'])}")
    for rid in report["roadmap_ids_in_markdown"]:
        if rid in report["covered"]:
            names = ", ".join(report["covered"][rid])
            print(f"  [COVERED]  {rid} -- checked by: {names}")
        elif rid in report["declared_gaps"]:
            print(f"  [GAP]      {rid} -- declared gap: {report['declared_gaps'][rid]}")
        else:
            print(f"  [UNCOVERED] {rid} -- no check, no declared gap")
    if report["unknown_ids_referenced_in_covers"]:
        print("\nWARNING -- 'covers' references an ID not in the markdown "
              "(likely a typo/rename drift):")
        for rid in report["unknown_ids_referenced_in_covers"]:
            print(f"  {rid} (covered by {report['covered'][rid]})")
    if report["unknown_ids_referenced_in_known_gaps"]:
        print("\nWARNING -- 'known_gaps' references an ID not in the markdown:")
        for rid in report["unknown_ids_referenced_in_known_gaps"]:
            print(f"  {rid}")
    print()
    print("OVERALL: " + ("OK -- every roadmap claim is covered or an explicit declared gap"
                          if report["ok"] else
                          "NEEDS ATTENTION -- see UNCOVERED / WARNING lines above"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-of-truth", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = check(args.source_of_truth, args.manifest)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
