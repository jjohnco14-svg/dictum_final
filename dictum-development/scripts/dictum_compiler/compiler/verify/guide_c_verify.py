#!/usr/bin/env python3
"""
guide_c_verify.py — automated Guide C verification for one project.

This is the mechanical half of GUIDE_C_target_verification.md, the same
role dict_triage.py plays for Guide B: it exists so an AI running Guide C
doesn't have to hand-drive Xvfb/`import`/ffmpeg/kill sequences, re-derive
console diffs, and re-invoke each project-specific verify script one at a
time across a dozen separate tool calls every session. One call —

    python3 verify/guide_c_verify.py --manifest guide_c_manifest.json

— reads a project's Guide C Test Manifest (Guide A §0, Phase 2; schema in
guide_c_manifest.schema.json) and runs EVERYTHING it declares in one
process: console-class diffs, GUI-class Xvfb+screenshot capture (with
project-supplied verify scripts consuming the screenshot numerically —
Guide C §2b-1, never by having an AI eyeball the PNG), and every
project-specific script listed. Output is one structured verdict, same
shape as dict_triage.py's, that an AI reads and reports from — it does
not re-derive the check plumbing from prose each time.

What it deliberately does NOT do (left to the AI running Guide C, on
purpose, matching that document's own division of labor):
    - decide whether a mismatch is a compiler bug (Case C, -> Guide B) vs
      an application bug (Guide C's own to fix) -- this tool only reports
      what it observed and what was expected; the same-side-vs-other-side
      judgment stays a judgment call
    - fix anything it finds
    - write or maintain the manifest itself (that's Guide A §0 Phase 2)
    - decide what a project-specific verify script's numeric thresholds
      should be -- it just runs the script and reports its verdict
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────
# Result plumbing
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    kind: str                     # "console" | "gui" | "project_specific"
    tier: str                     # BUILT | RUN-VERIFIED | VISUAL-VERIFIED | SKIP | FAIL
    ok: Optional[bool]            # True / False / None (skip, e.g. no Xvfb)
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)


def _run(cmd: List[str], timeout: int = 30, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


def _normalize_crlf(text: str) -> str:
    return text.replace("\r\n", "\n")


# ─────────────────────────────────────────────────────────────────────────
# §2a — console-class checks
# ─────────────────────────────────────────────────────────────────────────

def run_console_check(project_root: str, binary: str, spec: Dict[str, Any],
                      cache=None, cache_key_prefix: str = "") -> CheckResult:
    """Thin caching wrapper around _run_console_check_uncached -- console
    checks are inherently deterministic (same binary + same args + same
    expected value -> same real answer), so they're always safe to cache
    when the binary and spec haven't changed."""
    bin_path = os.path.join(project_root, binary)
    if cache is not None and os.path.exists(bin_path):
        import cache_lib
        cache_key = cache_lib.hash_inputs(
            cache_key_prefix, cache_lib._file_fingerprint(bin_path), json.dumps(spec, sort_keys=True),
        )
        cached = cache.get(cache_key)
        if cached is not None:
            r = CheckResult(**cached)
            r.evidence = dict(r.evidence, from_cache=True)
            return r
        result = _run_console_check_uncached(project_root, binary, spec)
        cache.set(cache_key, result.__dict__)
        return result
    return _run_console_check_uncached(project_root, binary, spec)


def _run_console_check_uncached(project_root: str, binary: str, spec: Dict[str, Any]) -> CheckResult:
    name = spec["name"]
    args = spec.get("args", [])
    expect_rc = spec.get("expect_exit_code", 0)
    bin_path = os.path.join(project_root, binary)
    if not os.path.exists(bin_path):
        return CheckResult(name, "console", "SKIP", None,
                            f"binary not found: {bin_path} -- build it first, this isn't a "
                            "verification finding")

    try:
        r = _run([bin_path, *args], timeout=spec.get("timeout", 30), cwd=project_root)
    except Exception as e:
        return CheckResult(name, "console", "FAIL", False, f"failed to run binary: {e}")

    if r.returncode != expect_rc:
        return CheckResult(
            name, "console", "FAIL", False,
            f"exit code {r.returncode}, expected {expect_rc}. stderr: {r.stderr[:500]}",
            {"stdout": r.stdout[:2000], "stderr": r.stderr[:2000]},
        )

    diff_spec = spec.get("expected_file_diff")
    if diff_spec:
        produced_path = os.path.join(project_root, diff_spec["produced"])
        expected_path = os.path.join(project_root, diff_spec["expected"])
        if not os.path.exists(produced_path):
            return CheckResult(name, "console", "FAIL", False,
                                f"expected produced file not found: {produced_path}")
        produced = _normalize_crlf(open(produced_path, encoding="utf-8", errors="replace").read())
        expected = _normalize_crlf(open(expected_path, encoding="utf-8", errors="replace").read())
        if produced != expected:
            return CheckResult(
                name, "console", "FAIL", False,
                "produced file differs from expected (after CRLF normalization)",
                {"produced_head": produced[:500], "expected_head": expected[:500]},
            )
        return CheckResult(name, "console", "RUN-VERIFIED", True, "file diff clean")

    expected_stdout_file = spec.get("expected_stdout_file")
    if expected_stdout_file:
        expected_path = os.path.join(project_root, expected_stdout_file)
        expected = _normalize_crlf(open(expected_path, encoding="utf-8", errors="replace").read())
        actual = _normalize_crlf(r.stdout)
        if actual != expected:
            return CheckResult(
                name, "console", "FAIL", False,
                "stdout differs from expected (after CRLF normalization)",
                {"actual": actual[:500], "expected": expected[:500]},
            )
        return CheckResult(name, "console", "RUN-VERIFIED", True, "stdout diff clean")

    # No expected value supplied -- exit code alone is the check.
    return CheckResult(name, "console", "RUN-VERIFIED", True,
                        f"ran, exit code {r.returncode} as expected (no output diff configured)")


# ─────────────────────────────────────────────────────────────────────────
# §2b/§2c — GUI-class checks (Xvfb + screenshot/recording, in one process)
# ─────────────────────────────────────────────────────────────────────────

def _have_xvfb() -> bool:
    return shutil.which("Xvfb") is not None and shutil.which("import") is not None


def run_gui_check(project_root: str, binary: str, spec: Dict[str, Any],
                   display: str = ":97") -> CheckResult:
    name = spec["name"]
    if not _have_xvfb():
        return CheckResult(name, "gui", "SKIP", None,
                            "Xvfb/ImageMagick not available in this environment -- "
                            "GUI-class checks cannot run headless here, unrelated to the build itself")

    bin_path = os.path.join(project_root, binary)
    if not os.path.exists(bin_path):
        return CheckResult(name, "gui", "SKIP", None,
                            f"binary not found: {bin_path} -- build it first, this isn't a "
                            "verification finding")
    if not os.access(bin_path, os.X_OK):
        return CheckResult(name, "gui", "FAIL", False, f"binary exists but isn't executable: {bin_path}")

    warmup = spec.get("warmup_seconds", 3)
    rec_seconds = spec.get("recording_seconds", 0)

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        xvfb = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1024x768x24"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
        env["DISPLAY"] = display
        try:
            app = subprocess.Popen([bin_path], env=env, cwd=project_root,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            time.sleep(max(warmup, 1))

            evidence: Dict[str, Any] = {}

            # Resolve the real app window id rather than capturing the root
            # window -- under some Xvfb/Mesa/GLX combinations the root
            # window capture comes back blank even though the app is
            # genuinely rendering (a real, reproducible gap, not a guess --
            # see the fallback below which preserves the old behavior when
            # no window can be found, e.g. a console-only or not-yet-mapped app).
            win_id = None
            win_title = spec.get("window_title")
            if win_title:
                wr = _run(["xdotool", "search", "--name", win_title], timeout=5, env=env)
                lines = [l for l in wr.stdout.strip().splitlines() if l.strip()]
                win_id = lines[0] if lines else None
            capture_target = ["-window", win_id] if win_id else ["-window", "root"]

            baseline_path = None
            if spec.get("capture_baseline"):
                baseline_path = os.path.join(tmp, f"{name}_baseline.png")
                _run(["import", *capture_target, baseline_path], timeout=15, env=env)
                if not (os.path.exists(baseline_path) and os.path.getsize(baseline_path) > 0):
                    baseline_path = None
            evidence["baseline_screenshot"] = baseline_path

            # Real interaction injection -- this is what makes a GUI check
            # test RESPONSIVENESS (per the gui-behavioral-verification skill)
            # instead of a single static launch-and-look. Each interaction is
            # {"type": "click", "x": int, "y": int, "button": 1,
            #  "hold_seconds": 0.3} or {"type": "key", "keysym": "Return"}.
            # windowfocus (not windowactivate) is used deliberately -- no
            # window manager is running under Xvfb, so _NET_ACTIVE_WINDOW is
            # unsupported and windowactivate errors out; windowfocus plus a
            # window-relative mousemove is what actually gets a synthetic
            # click delivered to the app in this headless setup.
            for action in spec.get("interactions", []):
                if win_id:
                    _run(["xdotool", "windowfocus", win_id], timeout=5, env=env)
                if action.get("type") == "click":
                    mv = ["xdotool", "mousemove"]
                    if win_id:
                        mv += ["--window", win_id]
                    mv += [str(action.get("x", 0)), str(action.get("y", 0))]
                    _run(mv, timeout=5, env=env)
                    time.sleep(0.2)
                    button = str(action.get("button", 1))
                    _run(["xdotool", "mousedown", button], timeout=5, env=env)
                    time.sleep(action.get("hold_seconds", 0.3))
                    _run(["xdotool", "mouseup", button], timeout=5, env=env)
                elif action.get("type") == "key":
                    _run(["xdotool", "key", action.get("keysym", "")], timeout=5, env=env)
                time.sleep(action.get("settle_seconds", 0.5))

            shot_path = os.path.join(tmp, f"{name}.png")
            shot = _run(["import", *capture_target, shot_path], timeout=15, env=env)
            got_shot = shot.returncode == 0 and os.path.exists(shot_path) and os.path.getsize(shot_path) > 0
            evidence["screenshot"] = shot_path if got_shot else None

            rec_path = None
            if rec_seconds > 0 and shutil.which("ffmpeg"):
                rec_path = os.path.join(tmp, f"{name}.mp4")
                _run(["ffmpeg", "-y", "-f", "x11grab", "-video_size", "1024x768",
                      "-i", display, "-t", str(rec_seconds), "-r", "20", rec_path],
                     timeout=rec_seconds + 15, env=env)
                if not (os.path.exists(rec_path) and os.path.getsize(rec_path) > 0):
                    rec_path = None
            evidence["recording"] = rec_path

            app_crashed = app.poll() is not None
            stderr_tail = ""
            if app_crashed:
                try:
                    stderr_tail = app.stderr.read()[-2000:]
                except Exception:
                    pass
        finally:
            for p in (locals().get("app"), xvfb):
                if p is not None:
                    try:
                        p.send_signal(signal.SIGTERM)
                        p.wait(timeout=5)
                    except Exception:
                        try:
                            p.kill()
                        except Exception:
                            pass

        if app_crashed:
            return CheckResult(name, "gui", "FAIL", False,
                                f"process exited during warmup -- {stderr_tail}", evidence)
        if not got_shot:
            return CheckResult(name, "gui", "RUN-VERIFIED", None,
                                "process ran cleanly but the root-window screenshot came back "
                                "empty/failed -- known Xvfb/Mesa gotcha (Guide C §2b), not "
                                "necessarily a real bug; report as unconfirmed visually, not failed",
                                evidence)

        verify_script = spec.get("verify_script")
        if not verify_script:
            return CheckResult(name, "gui", "RUN-VERIFIED", True,
                                "screenshot captured, no verify_script configured to assert on it "
                                "numerically (Guide C §2b-1) -- write one before treating this as "
                                "visually confirmed", evidence)

        vs_path = os.path.join(project_root, verify_script)
        try:
            vr = _run([sys.executable, vs_path, "--screenshot", shot_path]
                      + (["--baseline-screenshot", baseline_path] if baseline_path else [])
                      + (["--recording", rec_path] if rec_path else []),
                      timeout=60, cwd=project_root)
        except Exception as e:
            return CheckResult(name, "gui", "FAIL", False,
                                f"verify_script failed to run: {e}", evidence)

        try:
            verdict = json.loads(vr.stdout.strip().splitlines()[-1])
            ok = bool(verdict.get("ok"))
            detail = verdict.get("detail", "")
            evidence["verify_script_verdict"] = verdict
        except Exception:
            ok = vr.returncode == 0
            detail = f"verify_script did not emit parseable JSON verdict; raw stdout: {vr.stdout[:500]}"

        tier = "VISUAL-VERIFIED" if ok else "FAIL"
        return CheckResult(name, "gui", tier, ok, detail, evidence)


# ─────────────────────────────────────────────────────────────────────────
# Project-specific scripts (Guide A §0 Phase 2 manifest entries)
# ─────────────────────────────────────────────────────────────────────────

def run_project_specific(project_root: str, spec: Dict[str, Any]) -> CheckResult:
    name = spec["name"]
    script = os.path.join(project_root, spec["script"])
    args = spec.get("args", [])
    if not os.path.exists(script):
        return CheckResult(name, "project_specific", "SKIP", None,
                            f"script not found: {script} -- write it before this check can run "
                            "(Guide C §2b-1: don't fall back to eyeballing because it's missing)")

    cmd = [script] if os.access(script, os.X_OK) else [sys.executable, script]
    try:
        r = _run(cmd + args, timeout=spec.get("timeout", 60), cwd=project_root)
    except Exception as e:
        return CheckResult(name, "project_specific", "FAIL", False, f"script errored: {e}")

    try:
        verdict = json.loads(r.stdout.strip().splitlines()[-1])
        ok = bool(verdict.get("ok"))
        detail = verdict.get("detail", "")
        evidence = {"verdict": verdict}
    except Exception:
        ok = r.returncode == 0
        detail = (r.stdout[-1000:] if ok else f"{r.stdout[-500:]}\n{r.stderr[-500:]}")
        evidence = {}

    return CheckResult(name, "project_specific", "RUN-VERIFIED" if ok else "FAIL", ok, detail, evidence)


# ─────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────

def lint_manifest_classes(manifest: Dict[str, Any]) -> List[str]:
    """Advisory, not blocking: flags a check's declared 'class' when it
    structurally doesn't match the kind of check it is. A console_check
    is exact-diff by nature -- marking one 'visual' is almost always a
    copy-paste mistake. A gui_check claiming 'deterministic' is an
    unusual claim (real, but rare -- e.g. a fixed-seed software
    rasterizer) worth a human/AI double-checking rather than assuming;
    per Guide C's own §2b-1, an assumption stated up front beats one
    discovered after the fact. A missing 'class' field isn't wrong, just
    unclassified -- flagged so it doesn't quietly stay that way forever."""
    warnings: List[str] = []
    for check in manifest.get("console_checks", []):
        cls = check.get("class")
        if cls is None:
            warnings.append(f"console_check '{check.get('name')}' has no 'class' field")
        elif cls != "deterministic":
            warnings.append(f"console_check '{check.get('name')}' is class={cls!r} -- "
                             "console checks are exact-diff by nature, expected 'deterministic'")
    for check in manifest.get("gui_checks", []):
        cls = check.get("class")
        if cls is None:
            warnings.append(f"gui_check '{check.get('name')}' has no 'class' field")
        elif cls == "deterministic":
            warnings.append(f"gui_check '{check.get('name')}' claims class='deterministic' -- "
                             "unusual for rendered output; confirm this is really "
                             "bit-reproducible, not just usually consistent")
    for check in manifest.get("project_specific_scripts", []):
        if check.get("class") is None:
            warnings.append(f"project_specific_script '{check.get('name')}' has no 'class' field")
    return warnings


def validate_gui_self_tests(project_root: str, manifest: Dict[str, Any]) -> List[str]:
    """A gui_check's verify_script is untrustworthy until it's been shown to
    be able to fail -- see the gui-behavioral-verification skill. A check
    that declares a 'mutation_fixture' (path to a deliberately-wrong
    screenshot) gets that proof enforced here: the verify_script MUST reject
    it. A check with a verify_script but no mutation_fixture isn't blocked --
    old manifests predate this convention -- but it's flagged loudly so it
    doesn't quietly stay unproven forever, same spirit as guide_a_coverage_check.py
    reporting UNCOVERED rather than silently passing."""
    warnings: List[str] = []
    for check in manifest.get("gui_checks", []):
        name = check.get("name", "?")
        vs = check.get("verify_script")
        if not vs:
            continue  # no verify_script at all is already caught elsewhere (RUN-VERIFIED, not a pass)
        fixture = check.get("mutation_fixture")
        if not fixture:
            warnings.append(
                f"gui_check '{name}' has a verify_script but no 'mutation_fixture' -- "
                "it has never been proven able to fail. Add a deliberately-wrong "
                "screenshot and confirm the script rejects it before trusting a PASS "
                "from this check (gui-behavioral-verification skill)."
            )
            continue
        fixture_path = os.path.join(project_root, fixture)
        vs_path = os.path.join(project_root, vs)
        if not os.path.exists(fixture_path):
            warnings.append(f"gui_check '{name}' declares mutation_fixture={fixture!r} "
                             "but that file doesn't exist")
            continue
        try:
            vr = _run([sys.executable, vs_path, "--screenshot", fixture_path], timeout=30, cwd=project_root)
            verdict = json.loads(vr.stdout.strip().splitlines()[-1])
            if bool(verdict.get("ok")):
                warnings.append(
                    f"gui_check '{name}': verify_script PASSED against its own known-bad "
                    f"mutation_fixture ({fixture}) -- this check cannot fail and should not "
                    "be trusted until fixed. A PASS from this check currently proves nothing."
                )
        except Exception as e:
            warnings.append(f"gui_check '{name}': could not run self-test against "
                             f"mutation_fixture -- {e}")
    return warnings


def verify(manifest_path: str, use_cache: bool = False, cache_path: Optional[str] = None) -> Dict[str, Any]:
    manifest = json.load(open(manifest_path))
    project_root = os.path.dirname(os.path.abspath(manifest_path))
    binary = manifest.get("binary", "")
    is_gui = bool(manifest.get("gui", False))

    cache = None
    if use_cache:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
        import cache_lib
        cache = cache_lib.Cache(cache_path or os.path.join(project_root, ".guide_c_verify_cache.json"))

    results: List[CheckResult] = []

    # Only console_checks are cached -- they're the deterministic class
    # (same binary + same args + same expected value -> same real answer,
    # every time). GUI checks and project-specific scripts are NOT cached
    # here: a GUI check's actual rendered output can depend on things a
    # file hash can't see (driver/GPU state, timing), and project-specific
    # scripts are free to implement their own caching internally if their
    # own check is genuinely deterministic -- this orchestrator doesn't
    # assume that on their behalf.
    for spec in manifest.get("console_checks", []):
        results.append(run_console_check(project_root, binary, spec,
                                          cache=cache, cache_key_prefix=manifest_path))

    # Fail-fast: a failing console check already proves the build broken.
    # Paying the Xvfb/screenshot cost to also check the frontend on a build
    # already known to be wrong is pure waste -- backend correctness gates
    # frontend responsiveness checking, not just orders before it.
    console_failed = any(r.ok is False for r in results)
    if is_gui and not console_failed:
        for spec in manifest.get("gui_checks", []):
            results.append(run_gui_check(project_root, binary, spec))
    elif is_gui and console_failed:
        for spec in manifest.get("gui_checks", []):
            results.append(CheckResult(
                spec.get("name", "?"), "gui", "SKIP", None,
                "skipped -- a console check already failed, so the build is known "
                "broken; frontend responsiveness can't be meaningfully checked on a "
                "backend that's already wrong"))

    for spec in manifest.get("project_specific_scripts", []):
        results.append(run_project_specific(project_root, spec))

    n_fail = sum(1 for r in results if r.ok is False)
    n_skip = sum(1 for r in results if r.ok is None)
    n_pass = sum(1 for r in results if r.ok is True)

    return {
        "project": manifest.get("project", "?"),
        "target": manifest.get("target", "?"),
        "gui": is_gui,
        "results": [r.__dict__ for r in results],
        "summary": {"pass": n_pass, "fail": n_fail, "skip": n_skip, "total": len(results)},
        "class_warnings": lint_manifest_classes(manifest),
        "gui_self_test_warnings": validate_gui_self_tests(project_root, manifest),
        "known_limitations": manifest.get("known_limitations", []),
        "overall_ok": n_fail == 0,
    }


def print_human(report: Dict[str, Any]) -> None:
    print(f"project:  {report['project']}  (target={report['target']}, gui={report['gui']})")
    print()
    for r in report["results"]:
        tag = {"True": "PASS", "False": "FAIL", "None": "SKIP"}[str(r["ok"])]
        print(f"[{tag}] ({r['kind']}) {r['name']} -- {r['tier']}")
        if r["ok"] is not True:
            print(f"       {r['detail']}")
    print()
    s = report["summary"]
    skip_note = f" ({s['skip']} skipped)" if s["skip"] else ""
    print(f"SUMMARY: {s['pass']}/{s['total'] - s['skip']} passed{skip_note}")
    if report["known_limitations"]:
        print("known limitations (pre-existing, not new findings):")
        for k in report["known_limitations"]:
            print(f"  - {k}")
    if report.get("class_warnings"):
        print("\nADVISORY -- manifest 'class' field issues (not blocking, but check these):")
        for w in report["class_warnings"]:
            print(f"  - {w}")
    print()
    print("OVERALL: " + ("OK" if report["overall_ok"] else "NEEDS ATTENTION -- see FAIL lines above"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, help="path to guide_c_manifest.json")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON only")
    ap.add_argument("--cache", action="store_true",
                     help="Cache console-class check results (see verify/cache_lib.py). "
                          "GUI checks and project-specific scripts are never cached here. "
                          "Off by default.")
    ap.add_argument("--cache-path", default=None)
    args = ap.parse_args()

    report = verify(args.manifest, use_cache=args.cache, cache_path=args.cache_path)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
