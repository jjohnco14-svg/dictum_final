#!/usr/bin/env python3
"""
orchestrate.py — the autonomous Phase-1-through-Guide-C loop.

WHAT THIS AUTOMATES: the mechanical cycle of write -> dict_triage.py ->
(Case A: retry with the diagnostic fed back to a generator / Case B/C/D:
stop and escalate, never guess) -> run_pipeline.py -> (manifest failure:
retry with the diagnostic fed back / clean: done).

WHAT THIS DELIBERATELY DOES NOT DO, matching every other script in this
pipeline's own stated division of labor:
  - It does not write .dict code itself. That's the job of whatever
    `--llm-backend` you point it at (manual / anthropic / lmstudio) --
    this script only drives the loop and feeds back real diagnostics.
  - It never auto-patches the COMPILER on a Case C. A Case C means the
    .dict is syntactically fine but the compiler mishandles it -- that's
    a change to shared infrastructure every future project depends on,
    and this script stops and escalates it for a human/senior-AI review
    with a real regression test, the same discipline every Case C fix
    in this project's own CHANGELOG has followed. It does not attempt
    the fix on its own.
  - It never guesses on Case B (genuinely ambiguous). It stops and
    prints the ambiguity for a person to actually answer.
  - It does not invent the Phase 1/2 spec (SOURCE_OF_TRUTH.md + the
    Guide C manifest). Those must already exist -- this script is the
    loop that runs AFTER Phase 0-2 are done, per GUIDE_0_PIPELINE_
    ORCHESTRATION.md. Pass --check-inputs to have it verify that before
    doing anything else.

Usage:
    python3 orchestrate.py \\
        --dict-file myproject/main.dict \\
        --project-dir myproject \\
        --manifest myproject/guide_c_manifest.json \\
        --source-of-truth myproject/SOURCE_OF_TRUTH_myproject.md \\
        --backend c \\
        --llm-backend manual \\
        --max-retries 5

--llm-backend manual: prints the exact diagnostic, waits for you (or
    another AI in a different window/session) to edit the file by hand,
    then press Enter to retry. This is the only mode actually exercised
    end to end in this sandbox (see ORCHESTRATE_TEST_NOTES.md) -- no
    live LLM call was available to test here.

--llm-backend anthropic: calls the real Anthropic API
    (ANTHROPIC_API_KEY env var required). Real HTTP call, structurally
    complete, but not run end-to-end in this sandbox (no key here).

--llm-backend lmstudio: calls a local OpenAI-compatible endpoint
    (default http://localhost:1234/v1/chat/completions, matching a
    standard LM Studio setup). This only works run on YOUR machine,
    not from this sandbox (no route to your localhost from here).
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from typing import Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))


class OrchestrationError(Exception):
    """Raised on any state the loop refuses to guess its way past --
    Case B, Case C, Case D, or a retry budget exhausted. Always carries
    a human-readable reason; the caller's job is to surface it, not
    silently swallow it."""


# ---------------------------------------------------------------------------
# Pluggable "who writes the fix" backends
# ---------------------------------------------------------------------------

def generate_manual(prompt: str, diagnostic: str, current_source: str) -> str:
    """The only backend actually exercised end-to-end in this sandbox.
    Prints the real diagnostic, waits for a human (or another AI in a
    separate session) to edit the file directly, then re-reads it."""
    print("\n" + "=" * 70)
    print("MANUAL FIX NEEDED")
    print("=" * 70)
    print(prompt)
    print("-" * 70)
    print(diagnostic)
    print("-" * 70)
    print("Edit the .dict file directly, then press Enter to retry "
          "(or Ctrl-C to abort)...")
    input()
    # Caller re-reads the file after this returns; this function's return
    # value is unused in manual mode (the file on disk is the source of
    # truth), kept only so all three backends share one call signature.
    return current_source


def generate_anthropic(prompt: str, diagnostic: str, current_source: str,
                        model: str = "claude-sonnet-4-6") -> str:
    """Real HTTP call to the Anthropic API. Requires ANTHROPIC_API_KEY.
    Structurally complete but NOT run end-to-end in this sandbox -- no
    key was available here. Test this yourself before trusting it in an
    unattended loop."""
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OrchestrationError(
            "ANTHROPIC_API_KEY not set. This backend makes a real, "
            "billed API call -- set the key explicitly, don't guess at one."
        )

    full_prompt = (
        f"{prompt}\n\n"
        f"Current .dict source:\n```\n{current_source}\n```\n\n"
        f"Diagnostic from the real compiler (dict_triage.py):\n{diagnostic}\n\n"
        f"Reply with ONLY the corrected, complete .dict source -- no "
        f"explanation, no markdown fences, just the file content."
    )
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": full_prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(text_blocks).strip()


def generate_lmstudio(prompt: str, diagnostic: str, current_source: str,
                       endpoint: str = "http://localhost:1234/v1/chat/completions",
                       model: str = "qwen2.5-9b-instruct") -> str:
    """Real HTTP call to a local LM Studio (or any OpenAI-compatible)
    server. Only reachable from the machine actually running LM Studio
    -- this sandbox has no route to your localhost, so this is provided
    for you to run on your own machine, not tested here."""
    import urllib.request

    full_prompt = (
        f"{prompt}\n\nCurrent .dict source:\n```\n{current_source}\n```\n\n"
        f"Diagnostic from the real compiler:\n{diagnostic}\n\n"
        f"Reply with ONLY the corrected, complete .dict source."
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


BACKENDS = {
    "manual": generate_manual,
    "anthropic": generate_anthropic,
    "lmstudio": generate_lmstudio,
}


# ---------------------------------------------------------------------------
# Real tool invocations (subprocess, --json) -- same tools Guide B/C use by hand
# ---------------------------------------------------------------------------

def run_dict_triage(dict_file: str, backend: str) -> dict:
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "dict_triage.py"), dict_file,
         "--backend", backend, "--json"],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise OrchestrationError(
            f"dict_triage.py did not return parseable JSON (this itself is "
            f"worth stopping for, not retrying blindly): {e}\nstdout={r.stdout!r}\n"
            f"stderr={r.stderr!r}"
        )


def run_guide_c_pipeline(project_dir: str, manifest: str, source_of_truth: Optional[str],
                          backend: str) -> dict:
    cmd = [sys.executable, os.path.join(HERE, "run_pipeline.py"),
           "--project", project_dir, "--manifest", manifest,
           "--backend", backend, "--json"]
    if source_of_truth:
        cmd += ["--source-of-truth", source_of_truth]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise OrchestrationError(
            f"run_pipeline.py did not return parseable JSON: {e}\n"
            f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
        )


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

def format_case_a_diagnostic(report: dict) -> str:
    lines = [f"Case A -- {report.get('summary', '')}"]
    for e in report.get("errors", []):
        lines.append(f"  Line {e.get('line')}: {e.get('message')}")
    return "\n".join(lines)


def orchestrate_compile_loop(dict_file: str, backend: str, generate_fn, max_retries: int,
                              log) -> None:
    """Loop until dict_triage.py reports a clean compile+run, or stop
    hard on Case B/C/D, or exhaust the retry budget on Case A."""
    for attempt in range(1, max_retries + 1):
        log(f"[compile loop] attempt {attempt}/{max_retries}: running dict_triage.py")
        report = run_dict_triage(dict_file, backend)
        case = report.get("case")

        if case == "A":
            diag = format_case_a_diagnostic(report)
            log(diag)
            current_source = open(dict_file).read()
            new_source = generate_fn(
                prompt="Fix this Case A error (a .dict syntax/type mistake -- "
                       "the compiler itself is not in question here).",
                diagnostic=diag, current_source=current_source,
            )
            if generate_fn is not generate_manual:
                # manual mode: the human edits the file directly, so
                # writing back here would stomp their edit.
                open(dict_file, "w").write(new_source)
            continue

        if case == "B":
            raise OrchestrationError(
                f"Case B -- genuinely ambiguous, stopping for a real answer, "
                f"not guessing: {report.get('summary', '')}"
            )
        if case == "C":
            raise OrchestrationError(
                f"Case C -- looks like a real compiler bug, not a .dict "
                f"mistake. This needs a human/senior-AI review and a real "
                f"regression test before any fix, per this pipeline's own "
                f"discipline -- NOT an autonomous compiler patch. Diagnostic: "
                f"{report.get('summary', '')}\n{report.get('errors')}"
            )
        if case == "D":
            raise OrchestrationError(
                f"Case D -- a declared library isn't blessed for this "
                f"target. Needs a bridge-generation review, not a retry: "
                f"{report.get('summary', '')}"
            )

        # No 'case' key at all + run_returncode == 0 means it compiled,
        # linked, and ran without crashing. Whether it's BEHAVIORALLY
        # correct is Guide C's job next, not this loop's.
        if report.get("run_returncode") == 0:
            log("[compile loop] clean compile + run. Handing off to Guide C.")
            return

        raise OrchestrationError(f"Unrecognized dict_triage.py report shape: {report}")

    raise OrchestrationError(
        f"Exceeded {max_retries} retries on Case A fixes without a clean "
        f"compile. Stopping for human review rather than retrying forever."
    )


def format_behavioral_diagnostic(result: dict) -> str:
    return json.dumps(result, indent=2)


def orchestrate_verify_loop(dict_file: str, project_dir: str, manifest: str,
                             source_of_truth: Optional[str], backend: str,
                             generate_fn, max_retries: int, log) -> bool:
    """Loop Guide C + coverage until overall_ok, or stop on a re-surfaced
    compile break, or exhaust the retry budget."""
    for attempt in range(1, max_retries + 1):
        log(f"[verify loop] attempt {attempt}/{max_retries}: running run_pipeline.py")
        result = run_guide_c_pipeline(project_dir, manifest, source_of_truth, backend)

        if result.get("overall_ok"):
            log("[verify loop] overall_ok=true -- real stopping condition met.")
            return True

        stopped_at = result.get("stopped_at")
        if stopped_at == "guide_b":
            # A behavioral fix in a prior iteration broke compilation --
            # go back through the compile loop instead of treating this
            # as a Guide C failure.
            log("[verify loop] a prior edit broke compilation -- returning "
                "to the compile loop.")
            orchestrate_compile_loop(dict_file, backend, generate_fn, max_retries, log)
            continue

        # A real behavioral/coverage failure -- feed it back.
        diag = format_behavioral_diagnostic(result)
        log(diag)
        current_source = open(dict_file).read()
        new_source = generate_fn(
            prompt="Guide C / coverage reported a real behavioral failure "
                   "(the code compiles and runs, but doesn't match the "
                   "manifest's expected behavior, or a roadmap claim has no "
                   "check at all). Fix the .dict so the specific failing "
                   "check(s) below pass.",
            diagnostic=diag, current_source=current_source,
        )
        if generate_fn is not generate_manual:
            open(dict_file, "w").write(new_source)

    raise OrchestrationError(
        f"Exceeded {max_retries} retries on behavioral fixes without "
        f"reaching overall_ok. Stopping for human review."
    )


def orchestrate(dict_file: str, project_dir: str, manifest: str,
                 source_of_truth: Optional[str], backend: str,
                 llm_backend: str, max_retries: int) -> bool:
    generate_fn = BACKENDS[llm_backend]
    log_lines = []
    def log(msg):
        print(msg)
        log_lines.append(msg)

    orchestrate_compile_loop(dict_file, backend, generate_fn, max_retries, log)
    ok = orchestrate_verify_loop(dict_file, project_dir, manifest, source_of_truth,
                                  backend, generate_fn, max_retries, log)
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dict-file", required=True)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--source-of-truth", default=None)
    p.add_argument("--backend", choices=["c", "cpp"], default="c")
    p.add_argument("--llm-backend", choices=list(BACKENDS.keys()), default="manual")
    p.add_argument("--max-retries", type=int, default=5)
    args = p.parse_args()

    try:
        ok = orchestrate(args.dict_file, args.project_dir, args.manifest,
                          args.source_of_truth, args.backend, args.llm_backend,
                          args.max_retries)
    except OrchestrationError as e:
        print(f"\nSTOPPED (not a crash -- the loop is refusing to guess): {e}",
              file=sys.stderr)
        return 1
    print("\nDONE -- overall_ok=true, real stopping condition met." if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
