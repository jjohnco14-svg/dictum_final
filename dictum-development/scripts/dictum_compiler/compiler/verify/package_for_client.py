#!/usr/bin/env python3
"""
package_for_client.py — assembles exactly what a freelance client should
receive, from a verified run_pipeline.py report: the binary, a plain-
language README, an optional copy of the generated C/C++ source (never
the .dict source), and a client-facing test report scrubbed of internal
tooling jargon (no "Dictum", "Guide A/B/C", "triage", ".dict" anywhere in
what ships).

The one property this file exists to guarantee, not just aim for: **no
.dict file, ever, under any flag combination, makes it into the output
zip.** That's checked mechanically right before zipping, not just relied
on by construction -- see _assert_no_dict_files(). If that check fires,
packaging aborts loudly rather than silently shipping IP that was
supposed to stay in the private repo.

This does NOT run any checks itself -- it takes a run_pipeline.py report
(pass one in directly, or point --pipeline-report at a saved JSON file)
and refuses to package anything that report says failed. It doesn't
re-verify; it trusts the report the same way a human would, which means
the report needs to be current -- don't package from a stale report after
editing the project.

Usage:
    python3 run_pipeline.py --project . --manifest guide_c_manifest.json --json > report.json
    python3 package_for_client.py --pipeline-report report.json \\
        --project-name "cnc-quote-tool" \\
        --description "Calculates cutting time and cost estimates from a DXF profile." \\
        --usage "Run: ./cnc-quote-tool part.dxf --material aluminum" \\
        --output deliverable.zip \\
        --include-source   # optional -- ships the generated C, never the .dict
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from typing import Any, Dict, List, Optional


def _assert_no_dict_files(root: str) -> None:
    """The hard guard. Walks the staged deliverable directory right before
    zipping and refuses to proceed if a .dict file is anywhere in it --
    including nested inside a copied 'generated source' directory, in
    case a future project structure ever puts .dict and .c files side by
    side in the same folder."""
    offenders = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".dict"):
                offenders.append(os.path.join(dirpath, f))
    if offenders:
        raise RuntimeError(
            "REFUSING TO PACKAGE: .dict source file(s) found in the staged deliverable -- "
            "these are IP and must never ship to a client:\n  " + "\n  ".join(offenders)
        )


def _client_test_report_markdown(pipeline_report: Dict[str, Any], project_name: str) -> str:
    """Translates a run_pipeline.py report into a short, plain-language
    report with zero internal tooling vocabulary -- a client reads this,
    not a Dictum-aware developer."""
    lines = [f"# Test Report — {project_name}", ""]
    lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    guide_b = pipeline_report.get("guide_b", {})
    build_ok = pipeline_report.get("guide_b_ok", False)
    lines.append(f"- Build: {'✅ PASS' if build_ok else '❌ FAIL'}")

    slc = guide_b.get("static_link_check")
    if slc:
        lines.append(f"- Runs standalone, no installation required: "
                      f"{'✅ confirmed' if slc.get('ok') else '❌ not confirmed'}")

    guide_c = pipeline_report.get("guide_c")
    if guide_c:
        s = guide_c["summary"]
        gradable = s["total"] - s["skip"]
        lines.append(f"- Functional tests: {'✅' if pipeline_report.get('guide_c_ok') else '❌'} "
                      f"{s['pass']}/{gradable} passed")

    lines.append("")
    lines.append(f"**Overall: {'✅ READY' if pipeline_report.get('overall_ok') else '❌ NOT READY'}**")
    return "\n".join(lines)


def _default_readme(project_name: str, description: str, usage: str) -> str:
    return (
        f"# {project_name}\n\n"
        f"{description}\n\n"
        f"## How to run\n\n"
        f"```\n{usage}\n```\n\n"
        f"This is a single, self-contained binary — no installation or additional "
        f"software is required to run it.\n"
    )


def package(
    pipeline_report: Dict[str, Any],
    project_name: str,
    description: str,
    usage: str,
    output_zip: str,
    include_source: bool = False,
    source_dir: Optional[str] = None,
    readme_text: Optional[str] = None,
) -> Dict[str, Any]:
    if not pipeline_report.get("overall_ok"):
        raise RuntimeError(
            "REFUSING TO PACKAGE: the supplied pipeline report is not overall_ok -- "
            "package only what actually passed. Re-run run_pipeline.py, fix what's "
            "failing, and pass a fresh, passing report."
        )

    bin_path = pipeline_report.get("guide_b", {}).get("bin_path")
    if not bin_path or not os.path.exists(bin_path):
        raise RuntimeError(
            "REFUSING TO PACKAGE: no built binary found in the pipeline report "
            "(guide_b.bin_path) -- was the report generated with a manifest, so "
            "Guide B kept its build artifacts?"
        )

    with tempfile.TemporaryDirectory() as stage:
        # 1. the binary itself, renamed to the project name, executable
        dest_bin = os.path.join(stage, project_name)
        shutil.copy2(bin_path, dest_bin)
        st = os.stat(dest_bin)
        os.chmod(dest_bin, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        # 2. README
        open(os.path.join(stage, "README.md"), "w").write(
            readme_text or _default_readme(project_name, description, usage)
        )

        # 3. client-facing test report (never the raw JSON -- scrubbed of jargon)
        open(os.path.join(stage, "TEST_REPORT.md"), "w").write(
            _client_test_report_markdown(pipeline_report, project_name)
        )

        # 4. optional generated source -- .c/.h/.cpp files ONLY, explicitly
        #    never anything ending in .dict, checked file-by-file on the
        #    way in (belt-and-suspenders with the whole-tree guard below).
        if include_source and source_dir and os.path.isdir(source_dir):
            src_dest = os.path.join(stage, "generated_source")
            os.makedirs(src_dest, exist_ok=True)
            for dirpath, _dirs, files in os.walk(source_dir):
                for f in files:
                    if f.endswith((".c", ".h", ".cpp", ".hpp")):
                        shutil.copy2(os.path.join(dirpath, f), os.path.join(src_dest, f))
                    # anything else (including .dict) is silently NOT copied --
                    # the guard below still runs as a hard backstop regardless

        _assert_no_dict_files(stage)  # the hard guard, right before zipping

        if os.path.exists(output_zip):
            os.remove(output_zip)
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirs, files in os.walk(stage):
                for f in files:
                    full = os.path.join(dirpath, f)
                    zf.write(full, os.path.relpath(full, stage))

        return {"ok": True, "output": os.path.abspath(output_zip),
                "contents": sorted(os.path.relpath(os.path.join(dp, f), stage)
                                    for dp, _d, fs in os.walk(stage) for f in fs)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pipeline-report", required=True, help="path to a run_pipeline.py --json report")
    ap.add_argument("--project-name", required=True)
    ap.add_argument("--description", required=True)
    ap.add_argument("--usage", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--include-source", action="store_true")
    ap.add_argument("--source-dir", default=None, help="required if --include-source is set")
    args = ap.parse_args()

    report = json.load(open(args.pipeline_report))
    try:
        result = package(report, args.project_name, args.description, args.usage,
                          args.output, include_source=args.include_source, source_dir=args.source_dir)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
