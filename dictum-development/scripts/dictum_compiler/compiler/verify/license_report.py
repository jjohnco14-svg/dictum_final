#!/usr/bin/env python3
"""
license_report.py — surfaces the real license of every linked library in a
build, and flags copyleft obligations before a deliverable ships (HANDOFF.md
§8.7: "Shipping a static binary linked against GPL code has consequences.
Nothing tracks license obligations today. This is cheap to fix now and
expensive to discover after a delivery." Also closes half of §7.3's
"License / attribution handling — real legal exposure").

WHERE THE DATA COMES FROM
---------------------------
Each of the 10 blessed/manifests/*.json now carries real license metadata
(license: an SPDX identifier, license_copyleft: bool, license_note: a short
human explanation) verified via web search during this session, not
asserted from memory -- see the commit that added them for sources. This
module is the read side: given the list of libraries a build actually
declared (a project's Build Manifest LIBRARIES field, or an explicit list),
it looks each one up and reports what's really there.

THE SPECIFIC RISK THIS FLAGS
-------------------------------
Dynamic linking against an LGPL library (e.g. libm/glibc, `m` in the
blessed registry) carries essentially no practical obligation. STATIC
linking is a different legal question -- the LGPL requires the recipient
be able to relink against a modified version of the library, which a
plain static binary doesn't allow for. So the same library can be a
non-issue in one build and a real, undisclosed obligation in another,
purely based on --static. This module cross-references the two facts
(is anything copyleft-licensed among the linked libraries? was the build
static?) and raises the warning specifically when both are true, rather
than either warning on every copyleft library regardless of link mode
(noisy, trains people to ignore it) or never warning at all (the actual
gap this closes).

WHAT THIS IS NOT
------------------
Not legal advice, and it doesn't block a build or a package -- it
surfaces facts so a human can make an informed call, the same posture
this project takes everywhere else (Guide B classifies, it doesn't fix;
this reports, it doesn't refuse). An unlisted/unblessed library (bound
directly via `import from C` with no manifest) has no license entry
here and is reported as UNKNOWN -- not silently omitted -- since that's
the honest answer, not a false "clear."

Usage:
    python3 license_report.py --libraries sqlite3 m --static
    python3 license_report.py --pipeline-report report.json
    python3 license_report.py --libraries raylib sdl2 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_DIR = os.path.join(os.path.dirname(HERE), "blessed", "manifests")


def _load_license_info(library: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(MANIFEST_DIR, f"{library}.json")
    if not os.path.exists(path):
        return None
    try:
        m = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    return {
        "license": m.get("license"),
        "copyleft": m.get("license_copyleft", None),
        "note": m.get("license_note", ""),
    }


def report(libraries: List[str], static_link: bool = False) -> Dict[str, Any]:
    entries = []
    any_copyleft = False
    any_unknown = False
    for lib in sorted(set(libraries)):
        info = _load_license_info(lib)
        if info is None:
            entries.append({"library": lib, "license": None, "copyleft": None,
                             "note": "UNKNOWN -- not a blessed library with recorded "
                                     "license info (bound directly via `import from C` "
                                     "with no manifest, or a typo). Verify its license "
                                     "manually before shipping."})
            any_unknown = True
            continue
        entries.append({"library": lib, **info})
        if info.get("copyleft"):
            any_copyleft = True

    static_risk = bool(static_link and any_copyleft)
    warnings = []
    if static_risk:
        copyleft_libs = [e["library"] for e in entries if e.get("copyleft")]
        warnings.append(
            f"STATIC build links against copyleft-licensed librar"
            f"{'y' if len(copyleft_libs) == 1 else 'ies'}: {', '.join(copyleft_libs)}. "
            f"Static linking an LGPL library carries a real obligation (the "
            f"recipient must be able to relink against a modified version) "
            f"that dynamic linking does not. Review before shipping this build."
        )
    if any_unknown:
        warnings.append(
            "One or more linked libraries have no recorded license info -- "
            "see entries marked UNKNOWN above."
        )

    return {
        "libraries": entries,
        "static_link": static_link,
        "any_copyleft": any_copyleft,
        "any_unknown": any_unknown,
        "static_copyleft_risk": static_risk,
        "warnings": warnings,
    }


def report_from_pipeline(pipeline_report: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the linked-library list and static-link status straight from a
    real run_pipeline.py report, so this never needs the caller to
    re-supply information the pipeline already collected."""
    guide_b = pipeline_report.get("guide_b", {})
    libraries = guide_b.get("manifest", {}).get("libraries", []) or []
    static_link = bool(guide_b.get("static_link_check"))
    return report(libraries, static_link=static_link)


def to_markdown(rep: Dict[str, Any]) -> str:
    if not rep["libraries"]:
        return "No third-party libraries linked."
    lines = ["| Library | License | Copyleft |", "|---|---|---|"]
    for e in rep["libraries"]:
        lic = e["license"] or "UNKNOWN"
        cl = "⚠️ yes" if e.get("copyleft") else ("no" if e.get("copyleft") is False else "?")
        lines.append(f"| {e['library']} | {lic} | {cl} |")
    if rep["warnings"]:
        lines.append("")
        for w in rep["warnings"]:
            lines.append(f"⚠️ {w}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--libraries", nargs="*", default=None)
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--pipeline-report", default=None, help="path to a run_pipeline.py --json report")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.pipeline_report:
        pr = json.load(open(args.pipeline_report))
        rep = report_from_pipeline(pr)
    elif args.libraries is not None:
        rep = report(args.libraries, static_link=args.static)
    else:
        ap.error("supply either --libraries ... or --pipeline-report FILE")
        return 2

    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(to_markdown(rep))
    return 1 if rep["static_copyleft_risk"] else 0


if __name__ == "__main__":
    sys.exit(main())
