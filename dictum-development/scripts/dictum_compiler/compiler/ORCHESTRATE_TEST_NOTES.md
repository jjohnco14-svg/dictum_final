# orchestrate.py — what was actually tested, honestly

## Proven end-to-end, in this sandbox, with the real tools underneath

**Compile loop (Case A retry):** a real project with `keep x as banana
with value 5` — `banana` isn't a type. `orchestrate_compile_loop` ran
the real `dict_triage.py`, got back `case: "A"`, `Line 2: Unknown type
'banana'`, fed that exact diagnostic to a stub fixer, which applied the
fix (`banana` -> `whole number`), and the retry compiled clean. Real
subprocess call to `dict_triage.py --json` both times, only the
"write the fix" step stubbed.

**Verify loop (behavioral retry):** a real project that compiled fine
but printed `result:6` when the manifest's `console_checks` expected
`result:5` (via `expected_stdout_file`). `orchestrate_verify_loop` ran
the real `run_pipeline.py`, got back `overall_ok: false` with the exact
`actual`/`expected` mismatch in `guide_c.results`, fed that to the stub
fixer, which corrected the value, and the second real `run_pipeline.py`
call returned `overall_ok: true` — the loop's real stopping condition,
not an assumption.

Both runs used the actual `dict_triage.py`/`run_pipeline.py` binaries
this project ships, called via `subprocess` exactly the way a human
running Guide B/C by hand would, parsing the same `--json` output a
person would otherwise read by eye.

## Code-reviewed, NOT independently reproduced with a live failure

- **Case B (ambiguous) / Case C (compiler bug) / Case D (unblessed
  library) stop-and-escalate paths.** The code (`orchestrate.py`'s
  `if case == "B"/"C"/"D": raise OrchestrationError(...)`) is a direct,
  simple branch on the same `case` field the Case A path already proved
  parses correctly from real `dict_triage.py` JSON — but I didn't
  manufacture a real Case C/D failure to watch it stop. Low risk (it's
  a straight `if`, not a loop with room for a subtle bug), but flagged
  honestly rather than claimed as tested.
- **`--llm-backend anthropic`** — real HTTP call structure (correct
  endpoint, headers, request body), but never actually invoked: no
  `ANTHROPIC_API_KEY` in this sandbox. Test this yourself before
  trusting it unattended.
- **`--llm-backend lmstudio`** — same real-call structure, but this
  sandbox has no route to your machine's `localhost`. Only runnable
  where LM Studio actually is.
- **The retry-budget-exhausted path** (`max_retries` reached without a
  clean compile/verify) — reviewed, not reproduced with a stub that
  deliberately never fixes anything.

## What this means if you're going to run it unattended

Trust the two loops' core mechanics — they're real. Do NOT point
`--llm-backend anthropic`/`lmstudio` at an unattended overnight run
without first watching it handle at least one real Case A and one real
Case C on your own machine, with your own model — a model that writes
a plausible-looking but subtly wrong fix on a Case C is exactly the
scenario this design tries to prevent (stop and escalate, don't
auto-patch the compiler), and that specific path is the one part of
this script not yet watched happen for real.
