"""
selftest_lib.py — the same @regression/PASS-FAIL-SKIP rigor
run_selftest.py uses for the compiler itself, packaged so any Dictum
PROJECT (cnc_vibecoder, or anything else) can build its own deterministic
regression suite without reinventing that boilerplate.

Why this exists: the split settled on earlier in this pipeline is that
deterministic parts of a project (G-code generation from a fixed DXF +
params, a speeds/feeds calculator, anything whose correct output is exact
and reproducible) belong in an exact-diff regression suite -- cheap, fast,
no Xvfb, no numeric thresholds -- the same mechanism the compiler itself
uses. Only the genuinely non-deterministic-to-verify part (what actually
renders on screen) belongs in Guide C's numeric-threshold checks
(guide_c_verify.py). This module is what a project's own deterministic
suite is built FROM.

A project wires this in like:

    from selftest_lib import deterministic_check, main

    @deterministic_check("G-code for a 40x30 rectangle at 5mm depth matches "
                          "an independently hand-computed toolpath exactly")
    def test_rect_toolpath(tmp):
        ...
        if actual != expected:
            return False, f"diff: {actual!r} != {expected!r}"
        return True, "ok"

    if __name__ == "__main__":
        import sys
        sys.exit(main())

Running that file directly (`python3 project_selftest.py`) prints a
human-readable PASS/FAIL/SKIP report, same style as the compiler's own
`run_selftest.py`. Running it with `--json` prints ONE aggregated verdict
in exactly the `{"ok": bool, "detail": str}` shape guide_c_verify.py's
project_specific_scripts entries expect -- so a project's deterministic
suite can be plugged straight into a Guide C manifest as one entry:

    {"name": "toolpath_determinism", "class": "deterministic",
     "covers": ["R7"], "script": "verify/project_selftest.py", "args": ["--json"]}

Same design rules as the compiler's own regression runner:
    - a check returns (True, detail) / (False, detail) / (None, detail) --
      True=PASS, False=FAIL (a real bug), None=SKIP (an environment gap,
      never conflated with a real failure -- see run_selftest.py's own
      R23 for why this distinction matters)
    - each check gets its own fresh tmp dir
    - an uncaught exception in a check counts as FAIL, not a crash of the
      whole suite
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from typing import Callable, List, Tuple

CheckFn = Callable[[str], Tuple[bool, str]]

_CHECKS: List[Tuple[str, CheckFn]] = []


def deterministic_check(description: str):
    def decorator(fn: CheckFn) -> CheckFn:
        _CHECKS.append((description, fn))
        return fn
    return decorator


def run_all() -> List[Tuple[str, object, str]]:
    """Returns a list of (description, ok, detail). ok is True/False/None."""
    results = []
    for desc, fn in _CHECKS:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                ok, detail = fn(tmp)
            except Exception as e:
                ok, detail = False, f"exception: {e}"
        results.append((desc, ok, detail))
    return results


def print_human(results) -> None:
    for desc, ok, detail in results:
        tag = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
        print(f"[{tag}] {desc}")
        if ok is not True:
            print(f"       {detail}")
    n_pass = sum(1 for _, ok, _ in results if ok is True)
    n_fail = sum(1 for _, ok, _ in results if ok is False)
    n_skip = sum(1 for _, ok, _ in results if ok is None)
    print(f"\n{n_pass}/{len(results) - n_skip} passed"
          f"{f' ({n_skip} skipped)' if n_skip else ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true",
                     help="print one aggregated {ok, detail} verdict, matching "
                          "guide_c_verify.py's project_specific_scripts contract")
    args = ap.parse_args()

    results = run_all()
    n_fail = sum(1 for _, ok, _ in results if ok is False)

    if args.json:
        failing = [f"{desc}: {detail}" for desc, ok, detail in results if ok is False]
        verdict = {
            "ok": n_fail == 0,
            "detail": ("all deterministic checks passed" if n_fail == 0 else
                       f"{n_fail} deterministic check(s) failed: " + "; ".join(failing)),
            "results": [{"description": d, "ok": ok, "detail": det} for d, ok, det in results],
        }
        print(json.dumps(verdict))
    else:
        print_human(results)

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
