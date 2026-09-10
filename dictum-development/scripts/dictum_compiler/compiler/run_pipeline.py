#!/usr/bin/env python3
"""
run_pipeline.py — the "final boss" one-call entry point spanning Guide B,
Guide C, and the Guide A coverage check, in that order, for one project.

Why the order matters and is fixed, not configurable: verifying *target*
behavior (Guide C) on a project that doesn't even compile/link cleanly
(Guide B) is meaningless -- there's nothing correct to check yet. So this
always runs Guide B's project-mode triage first and stops there on a real
failure, never wasting an Xvfb/screenshot pass on a build that's already
known broken. Guide C only runs once Guide B is clean. The coverage check
(Guide A's roadmap <-> Guide C manifest traceability) runs last and
independently of whether Guide C's checks passed -- coverage is about
whether the *right things are being checked at all*, which is worth
knowing even when what's being checked is currently failing.

Usage:
    python3 run_pipeline.py --project path/to/project_dir \\
        --manifest path/to/guide_c_manifest.json \\
        [--source-of-truth path/to/SOURCE_OF_TRUTH_project.md] \\
        [--backend c|cpp] [--expected-output "..."] [--cache] [--json]

What this does NOT do (same division of labor as every script in this
pipeline): it doesn't decide whether a Guide C failure is a compiler bug
(Case C, Guide B's territory) or an application bug (Guide C's own to
fix) -- that judgment call stays with whoever reads this report. It
doesn't fix anything itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "verify"))


def run(project_dir: str, manifest_path: Optional[str], source_of_truth: Optional[str],
        backend: Optional[str] = None, expected_output: Optional[str] = None,
        use_cache: bool = False, static: bool = False) -> Dict[str, Any]:
    import dict_triage

    report: Dict[str, Any] = {"project_dir": os.path.abspath(project_dir)}

    # ---- Stage 1: Guide B (always runs) ----
    # If Guide C is going to run, Guide B's build must persist (triage_file/
    # triage_project normally clean up their ephemeral build dir immediately
    # after the run check -- fine for Guide B alone, but Guide C needs a
    # real, still-existing binary to launch).
    guide_b = dict_triage.triage_project(project_dir, backend=backend, expected_output=expected_output,
                                          keep_artifacts=bool(manifest_path), static=static)
    report["guide_b"] = guide_b
    guide_b_ok = guide_b.get("case") in ("clean",) or (
        guide_b.get("case") == "ambiguous"  # ran cleanly, just nothing to diff against -- not a failure
    )
    report["guide_b_ok"] = guide_b_ok

    if not guide_b_ok:
        report["guide_c"] = None
        report["coverage"] = None
        report["overall_ok"] = False
        report["stopped_at"] = "guide_b"
        report["stop_reason"] = ("Guide B found a real problem (a genuine .dict mistake, a "
                                  "compiler/emitter bug, or an unresolvable library) -- Guide C "
                                  "was not run, since verifying target behavior on a build "
                                  "that doesn't compile/link cleanly isn't meaningful.")
        return report

    # ---- Stage 2: Guide C (only if Guide B is clean, and only if a manifest was given) ----
    if manifest_path:
        import guide_c_verify
        # Point the manifest at the real binary Guide B just built, rather
        # than whatever stale/aspirational path the manifest's "binary"
        # field says -- a temp copy alongside the original (so relative
        # paths for expected_stdout_file etc. still resolve against the
        # real project dir, only "binary" is overridden to an absolute path).
        effective_manifest_path = manifest_path
        bin_path = guide_b.get("bin_path")
        if bin_path:
            manifest_data = json.load(open(manifest_path))
            manifest_data["binary"] = bin_path  # absolute -- os.path.join ignores project_root for this
            effective_manifest_path = manifest_path + ".resolved.tmp.json"
            json.dump(manifest_data, open(effective_manifest_path, "w"))
        guide_c = guide_c_verify.verify(effective_manifest_path, use_cache=use_cache)
        report["guide_c"] = guide_c
        report["guide_c_ok"] = guide_c["overall_ok"]
    else:
        report["guide_c"] = None
        report["guide_c_ok"] = None  # not attempted, not a failure

    # ---- Stage 3: coverage check (independent of whether Guide C's checks passed) ----
    if manifest_path and source_of_truth:
        import guide_a_coverage_check
        coverage = guide_a_coverage_check.check(source_of_truth, manifest_path)
        report["coverage"] = coverage
        report["coverage_ok"] = coverage["ok"]
    else:
        report["coverage"] = None
        report["coverage_ok"] = None

    report["overall_ok"] = guide_b_ok and (report["guide_c_ok"] is not False) and (
        report["coverage_ok"] is not False)
    report["stopped_at"] = None
    return report


def print_human(report: Dict[str, Any]) -> None:
    print(f"project: {report['project_dir']}")
    print()
    print(f"[{'PASS' if report['guide_b_ok'] else 'FAIL'}] Guide B (compile/link/run triage) "
          f"-- case={report['guide_b'].get('case')}")
    slc = report["guide_b"].get("static_link_check")
    if slc:
        print(f"       static-link check: {'PASS' if slc['ok'] else 'FAIL'} -- {slc['detail']}")
    if not report["guide_b_ok"]:
        print(f"       {report['guide_b'].get('summary', '')}")
        print(f"\nSTOPPED at Guide B: {report['stop_reason']}")
        print("\nOVERALL: NEEDS ATTENTION")
        return

    if report["guide_c"] is not None:
        s = report["guide_c"]["summary"]
        tag = "PASS" if report["guide_c_ok"] else "FAIL"
        skip_note = f" ({s['skip']} skipped)" if s["skip"] else ""
        print(f"[{tag}] Guide C (target verification) -- {s['pass']}/{s['total'] - s['skip']} "
              f"passed{skip_note}")
        for r in report["guide_c"]["results"]:
            if r["ok"] is not True:
                print(f"       [{r['name']}] {r['detail']}")
        if report["guide_c"].get("class_warnings"):
            print("       advisory (manifest 'class' field): "
                  + "; ".join(report["guide_c"]["class_warnings"]))
    else:
        print("[SKIPPED] Guide C -- no --manifest given")

    if report["coverage"] is not None:
        tag = "PASS" if report["coverage_ok"] else "FAIL"
        print(f"[{tag}] Guide A coverage check -- "
              f"{len(report['coverage']['roadmap_ids_in_markdown']) - len(report['coverage']['uncovered'])}"
              f"/{len(report['coverage']['roadmap_ids_in_markdown'])} roadmap IDs covered or declared")
        for rid in report["coverage"]["uncovered"]:
            print(f"       UNCOVERED: {rid}")
    else:
        print("[SKIPPED] Guide A coverage check -- no --source-of-truth given, or no --manifest")

    print()
    print("OVERALL: " + ("OK" if report["overall_ok"] else "NEEDS ATTENTION -- see FAIL lines above"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, help="project directory (Guide B target)")
    ap.add_argument("--manifest", default=None, help="guide_c_manifest.json (Guide C + coverage)")
    ap.add_argument("--source-of-truth", default=None, help="SOURCE_OF_TRUTH_<project>.md (coverage)")
    ap.add_argument("--backend", default=None, choices=["c", "cpp"])
    ap.add_argument("--expected-output", default=None)
    ap.add_argument("--cache", action="store_true", help="see dict_triage.py/guide_c_verify.py --cache")
    ap.add_argument("--static", action="store_true",
                     help="Static-link the build and verify with real ldd -- see "
                          "verify/verify_static_link.py.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = run(args.project, args.manifest, args.source_of_truth,
                 backend=args.backend, expected_output=args.expected_output, use_cache=args.cache,
                 static=args.static)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_human(report)
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
