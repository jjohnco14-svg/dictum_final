# Guide C: Target Verification & Packaging Protocol

You are receiving a build that has already cleared Guide B — it
compiles and links for one or more declared targets. Your job is
different from Guide B's: confirm the binary actually *behaves*
correctly on each declared target, package it, **and fix what you
find** — you are the final check before something ships, not a report
generator. The one boundary that still holds: you don't edit the
compiler itself (`emit_c.py`/`emit_cpp.py`/the parser/validator) —
that's a different codebase, and a wrong-codegen finding (Case C)
still goes back to Guide B (§2d, §5). Everything at the *application*
level — the project's own `.dict`/C source, build config, packaging,
camera/geometry setup, event wiring — is yours to fix, using the same
discipline Guide B holds itself to (§0 of that document): fix it,
re-run the check that failed, re-run everything else that passed
before to confirm you didn't break it, and say plainly what you fixed
and how you verified it.

This guide has two kinds of checks. §§0-4 below are the **general**
checks — they apply to any Dictum project, console or GUI, unchanged.
On top of those, every project's `SOURCE_OF_TRUTH_<project>.md` (Guide
A §0, Phase 2) carries a **Guide C Test Manifest** — project-specific
checks written by Guide A because they don't generalize (cnc_vibecoder's
grbl-dialect check, its camera/geometry sanity checks). Read that
manifest first; it tells you what, beyond the general checks below,
this specific project needs.

**In practice, run `verify/guide_c_verify.py --manifest
guide_c_manifest.json`** (or `run_selftest.py --verify-target
guide_c_manifest.json`) rather than hand-driving the Xvfb/`import`/
ffmpeg sequences below one bash call at a time — it executes every
console check, every GUI check (Xvfb bring-up, screenshot, optional
recording, teardown, all in one process), and every project-specific
script the manifest lists, then returns one structured verdict. The
bash snippets in §§2a-2c below are the mechanism the script
implements, not a replacement for it — read them to understand *what*
it's doing or to extend it for a new check shape, not to re-type them
by hand every session. A missing binary or missing project-specific
script reports as `SKIP` ("not built yet"), never a false `FAIL` — see
the manifest schema (`verify/guide_c_manifest.schema.json`) for the
full shape.

**Or, for the whole thing in one call**, `run_pipeline.py` (also
`run_selftest.py --full-check`) runs Guide B's project-mode triage,
then this document's checks via `guide_c_verify.py`, then the Guide A
coverage check, in that fixed order — stopping at Guide B on a real
failure rather than wasting an Xvfb pass verifying target behavior on a
build that doesn't even compile. This is the actual single entry point
for "is this project done," start to finish.

**Confidence key** (same convention as Guides A/B, extended for this
guide's specific concern — which target something was actually
checked on):

- **[BUILT]** — compiled and linked for the target. Nothing run yet.
- **[RUN-VERIFIED]** — console-class program: actually executed, real
  output diffed against an independently-known-correct expected value.
- **[VISUAL-VERIFIED]** — GUI-class program: executed under a real
  headless display, a real screenshot captured and inspected, matched
  expected content (not just "didn't crash").
- **[CI-VERIFIED]** — confirmed on real target infrastructure (a real
  Windows runner, not Wine). The authoritative tier for Windows.
- **[UNVERIFIED-CROSS]** — cross-compiled and linked for a target this
  environment cannot natively execute, but never actually run for that
  target. Exists specifically so a Windows binary never silently
  inherits the confidence of a Linux run just because they share
  source.

Never report a tag stronger than what you actually did. "It's
[BUILT]" and "it's [RUN-VERIFIED]" are different claims requiring
different evidence — same non-negotiable rule Guide B holds for
compiling vs. behaving correctly.

---

## 1. Read the Build Manifest and README — don't infer target/GUI
status or expected behavior yourself

Guide A §19 / Guide B §1a define the manifest. You need three fields:
`TARGET`, `GUI`, and `LIBRARIES`. If `GUI` is genuinely absent (an old
submission predating the manifest requirement), you may fall back to
scanning the emitted source for a window-init call as a heuristic
(`InitWindow`, `rl_InitWindow`, `glfwCreateWindow`, `SDL_CreateWindow`,
or similar) — but if that's ambiguous, stop and ask rather than guess.
Guessing wrong here means either wasting a full Xvfb/Wine round-trip on
a console program, or missing a real rendering bug on a GUI one.

Alongside the manifest, every submission should also carry a
`README.md` (Guide A §20) describing what the program is supposed to
do and what correct output/behavior looks like. **This README, not
your own guess and not Guide B's improvised expected value, is your
primary source for the "independently known-correct expected value"
every check below asks you to compare against.** If a submission
reaches you with no README and Guide B's handoff (§6 of that document)
didn't include one either, say so explicitly and ask for one rather
than inventing what "correct" should look like — the whole point of
requiring it upstream is that Guide C shouldn't have to guess intent.

---

## 2. Program-class branching

Every Dictum-built program is one of two classes. Verification is
completely different between them — this is the core structural
decision this guide makes.

### 2a. Console/headless class (`GUI: no`)

No display machinery needed at all.

```bash
./your_binary [args] > actual_output.txt
echo "exit code: $?"
diff actual_output.txt expected_output.txt
```

If the program writes a file instead of stdout (a G-code file, a log,
etc.), diff the file directly. This is [RUN-VERIFIED] once the diff is
clean and the exit code is what's expected.

**One real, verified gotcha for cross-target console checks:** a
Windows build of the same source may write `\r\n` line endings where a
Linux build writes `\n`, purely due to C runtime text-mode differences
— this is expected, correct behavior, not a bug. Normalize before
diffing across targets:
```bash
tr -d '\r' < windows_output.txt > normalized.txt
diff normalized.txt linux_expected_output.txt
```
Don't let this expected difference get misreported as a Case C bug
back to Guide B.

### 2b. GUI class (`GUI: yes`)

Needs a real, running display server the program can actually connect
to — this is not optional or skippable, and reading the code is not a
substitute (a window-init call that's correct on paper can still fail
at runtime for reasons invisible without actually running it, same
principle as Guide B §1).

**For `TARGET: linux`:**
```bash
Xvfb :99 -screen 0 800x600x24 &
XVFB_PID=$!
sleep 2
DISPLAY=:99 ./your_binary &
APP_PID=$!
sleep 3   # let it actually get past init and render at least one frame
DISPLAY=:99 import -window root screenshot.png
kill $APP_PID $XVFB_PID 2>/dev/null
```

**For `TARGET: windows`**, same idea, with Wine in the chain:
```bash
Xvfb :99 -screen 0 800x600x24 &
sleep 2
DISPLAY=:99 wine your_binary.exe &
APP_PID=$!
sleep 5   # Wine's own init adds latency — give it longer than native
DISPLAY=:99 import -window root screenshot_windows.png
kill $APP_PID 2>/dev/null
```

Then verify the resulting PNG — see §2b-1 below. Don't grade it by
eye against a description in your own head; that's exactly the failure
mode this section exists to prevent (a real example from this
project's history: a screenshot was declared "confirmed" from a
5-pixel sample, then two messages later it turned out there was no
reliable way to actually view the image content in that context at
all — the confidence was narrated, not measured).

### 2b-1. Verify numerically, with a script decided in advance [NEW]

A screenshot (or frame from §2c's recording) only becomes evidence
once something with a fixed, pre-decided pass/fail contract has looked
at it — not a running commentary on what the image "seems to show."
Concretely:

- **Write the assertion before you render, not after.** "Green
  coverage should be roughly 15-35%" decided in advance is a check.
  "21.8% seems reasonable" decided after seeing the number is not — it
  can always be rationalized to fit whatever came out.
- **Project geometry analytically wherever you can**, instead of
  inferring size/position from pixels. Given the camera matrix and a
  mesh's known bounding box, the expected on-screen footprint is
  computable *before* a single frame renders — "the model fills 90% of
  the viewport" becomes a number comparison, not a description of a
  screenshot.
- **Classify pixels against fixed color ranges** (stock-gray %,
  target-green %, etc.) with hard thresholds, and **check monotonic
  properties across a sequence** where relevant (e.g. a fade should
  strictly decrease across 0/25/50/75/100% progress checkpoints, not
  just "look faded" in one frame).
- **Any project with this class of check writes its own small script**
  for it (e.g. `verify_render.py`) and lists it in that project's
  Guide C Test Manifest (Guide A §0, Phase 2) — this is what makes
  those checks project-specific rather than general. The script
  produces one structured pass/fail verdict per assertion, with the
  actual numbers, which you read and report — the same relationship
  `dict_triage.py` has to Guide B's checks (a program decides, you
  don't narrate a judgment call in its place).
- If a project's Test Manifest doesn't have one of these scripts yet
  for a check it needs, write it (following this project's existing
  verification code, if any, as a starting point) before attempting
  the check — don't fall back to eyeballing because the script doesn't
  exist yet.

**Known limitation, found and verified this session — report
honestly, don't paper over it:** `import -window root` can come back
with a small, essentially blank PNG (confirmed: 343 bytes, empty)
even when the target program's own log output confirms full raylib
initialization with no errors. The generic root-window capture is not
fully reliable in every Xvfb/Mesa/llvmpipe combination — root-window
composition and GL front/back-buffer timing can disagree. If this
happens:
- Increase the delay before capture (some programs take longer than
  3-5 seconds to actually present a frame under software rendering).
- Try capturing the specific window ID via `xdotool getactivewindow`
  + `import -window <id>` instead of `-window root`.
- If neither resolves it, report the run as [RUN-VERIFIED] (window
  initialized cleanly per program log, no crash) but explicitly
  **not** [VISUAL-VERIFIED] — don't upgrade the confidence tag just
  because the non-visual signals looked good. Say plainly that visual
  content itself is unconfirmed and needs a real-machine check.

---

## 2c. Animation/motion/interactive verification via screen recording [NEW]

A single screenshot proves a frame rendered. It does **not** prove
motion, a simulation loop actually advancing, or a UI control actually
responding to input over time — for those, a real recording is the
right tool, not a better screenshot.

```bash
Xvfb :94 -screen 0 1024x768x24 > /dev/null 2>&1 &
sleep 2
DISPLAY=:94 timeout 25 ./your_binary &
sleep 2
DISPLAY=:94 ffmpeg -y -f x11grab -video_size 1024x768 -i :94 -t 18 -r 20 recording.mp4 &
sleep 3
# ... synthetic input here, see the click gotcha below ...
wait   # let ffmpeg finish its -t duration
kill %1 %2 2>/dev/null
```

Everything — Xvfb start, app launch, the recording, and any synthetic
input — must happen **inside one shell invocation/session**. Some
sandboxed environments tear down background processes between
separate tool calls/sessions; splitting this across calls can kill
Xvfb or the app mid-recording for reasons that have nothing to do with
the program under test. If a recording or a click mysteriously stops
working between two otherwise-identical attempts, check this before
suspecting the app.

**A real, confirmed gotcha with synthetic clicks (`xdotool`):** an
instantaneous combined `xdotool click 1` does not reliably register
as a real button press with at least raylib/GLFW's input handling
under Xvfb — confirmed by clicking a real button at verified-correct
coordinates (checked via `xdotool getmouselocation` immediately after
the move) and observing the program's own output prove the click
never registered. **Explicit separate events with a real gap between
them does work**:
```bash
DISPLAY=:94 xdotool mousemove X Y
sleep 0.3
DISPLAY=:94 xdotool mousedown 1
sleep 0.2
DISPLAY=:94 xdotool mouseup 1
```
Don't conclude a UI control is broken from a failed instantaneous
`click` alone — confirm with the explicit mousedown/mouseup form
before reporting it as a real app bug.

**What actually proves motion, not just "the recording exists":**
extract frames at intervals (`ffmpeg -i recording.mp4 -vf fps=1
frame_%02d.png`) and either view them directly or diff them
objectively (e.g. via PIL/`numpy`, checking distinct color count or a
changed-pixel bounding box) rather than trusting file size or frame
count alone — video compression noise can make even a static scene
show small pixel-level differences between frames, so a naive
per-pixel diff threshold can produce false positives. The one
unambiguous signal for "did the simulation actually run and cut
something" is still the artifact it should have produced (the G-code
file's size/content, a log line, a written output) — check that
directly rather than inferring it from the recording alone.

**Confidence tag**: a program confirmed running *and* changing state
correctly over a real recorded interval — not just one static frame —
still reports as [VISUAL-VERIFIED] (the tag key in this guide doesn't
currently distinguish "one frame" from "a verified sequence"); note in
the report that the check was a recording, and roughly how the
program's state was confirmed to actually change over the interval,
so the reader knows the stronger form of evidence was used.

---

## 2d. When actual output doesn't match the README [NEW]

Sooner or later a diff will fail, or a screenshot/recording won't show
what the README said to expect. When that happens:

- **First figure out which side is wrong** — the mismatch could mean
  the compiler mis-translated correct `.dict` source (a real Case C
  compiler/emitter bug), the application's own `.dict`/C source
  encodes the wrong logic for the stated intent (an application bug,
  e.g. a wrong camera setup, an unwired handler, a coordinate-system
  mismatch — real examples from this project's history), or the
  README was inaccurate about intent. Trace it to the actual cause,
  same as Guide B §0 requires — "the diff is now clean" is not
  evidence of a fix if you don't know why it was failing.
- **Compiler/emitter bug (Case C) → route back to Guide B, don't fix
  it here.** `emit_c.py`/`emit_cpp.py`/the parser/validator are a
  different codebase; that's still Guide B's territory (§5).
- **Application-level bug → yours to fix, with Guide B's own
  discipline**: fix the actual root cause (not just the symptom you
  observed), re-run the specific check that failed, re-run every
  other check that previously passed for this target to confirm
  nothing regressed, and — if this project has a regression harness
  for application-level bugs — add a case so it can't silently come
  back. Report what was wrong, what you changed, and what you re-ran
  to confirm it, the same shape Guide B expects of itself.
- **README itself wrong** — don't silently "fix" the README to match
  observed behavior; that erases the actual intent. Flag the
  discrepancy explicitly so a human (or whoever owns Phase 1 of Guide
  A) decides which one is actually correct.

---

## 3. Windows-specific: two honest tiers, don't blur them

Wine is fast and free but is an approximation of real Windows — it can
diverge on GPU driver behavior, DPI scaling, and window-manager
quirks. Treat it accordingly:

- **Wine-on-Xvfb (§2b)** → the fast tier. Gets you [RUN-VERIFIED] or
  [VISUAL-VERIFIED] quickly, useful for catching gross breakage
  (crashes, missing symbols, obviously wrong output) during iteration.
- **Real `windows-latest` GitHub Actions runner** → the authoritative
  tier, [CI-VERIFIED]. Required before calling a Windows target
  genuinely done — set up a workflow that builds and runs the same
  regression suite (`run_selftest.py`) on real Windows infrastructure.

A Wine pass is a good sign, not proof. Don't let a clean Wine run get
reported upward as if it were a real-Windows confirmation.

---

## 4. Packaging

Once a target is verified to the tier appropriate for shipping it:

- **Static-link by default.** For a distributable binary, prefer
  static linking of the libraries the project depends on (e.g.
  `-static -static-libgcc` for the mingw Windows build) so the result
  is a single portable file with no "put the right DLL next to the
  exe" failure mode. Use dynamic linking only when explicitly
  requested or when a library is known not to support static linking.
- **Confirm the dependency list is what you expect** before calling a
  build portable:
  ```bash
  # Windows (from a Linux host, via the mingw toolchain):
  x86_64-w64-mingw32-objdump -p your_binary.exe | grep "DLL Name"
  ```
  For a statically-linked build this should show only standard system
  DLLs (`KERNEL32.dll`, `USER32.dll`, `GDI32.dll`, `msvcrt.dll`,
  `WINMM.dll`, `opengl32.dll`, and similar) — never a project-specific
  or mingw-runtime DLL. If one shows up, the static link didn't fully
  take and the binary isn't actually portable yet.

---

## 5. What you must never do

- Never report [VISUAL-VERIFIED] or [CI-VERIFIED] for something you
  only [BUILT] or [UNVERIFIED-CROSS]'d. State the tier you actually
  reached.
- Never treat a clean Wine run as equivalent to real Windows CI —
  they're different tiers (§3), not interchangeable evidence.
- Never patch `emit_c.py`/`emit_cpp.py`/the parser/validator yourself
  — a real compiler/emitter bug (Case C) always routes back to Guide
  B, no matter how small the fix looks from here.
- Never fix an application-level bug without first tracing it to its
  actual root cause. "The diff is clean now" without knowing why it
  was failing is a guess that got lucky, not a fix — same standard
  Guide B holds itself to (§0 of that document).
- Never claim a visual check passed based on your own description of
  an image. Every visual assertion needs a decided-in-advance,
  numeric, scripted check (§2b-1) with an actual pass/fail verdict —
  not a sentence about what the screenshot "seems to show."
- Never silently reinterpret a blank/failed screenshot as success
  because the program's log output looked clean. Report the visual
  check's actual outcome, separately from the non-visual signals.
- Never skip the CRLF-normalization step (§2a) and report a
  cross-target line-ending difference as a content bug.
- Never silently rewrite a README to match observed behavior when
  they disagree — flag the discrepancy instead (§2d).
- Never re-run only the check that failed after a fix. Re-run
  everything that previously passed for that target too, or a fix
  that quietly breaks something else ships unnoticed.

---

## 6. What to report back

For each target processed:

1. **Target and class** — e.g. `windows / GUI`.
2. **Highest confidence tag reached**, and exactly what evidence
   supports it (ran it? diffed what against what? screenshot captured
   and inspected, or not?).
3. **Packaging status** — static or dynamic, dependency list confirmed.
4. **Anything found that looks like a Case C compiler bug** — handed
   back to Guide B, not fixed here.
5. **Any application-level bug found and fixed here** — the actual
   root cause (not just the symptom), what changed, which check(s)
   confirmed the fix, and confirmation every previously-passing check
   for that target was re-run and still passes.
6. **Any known limitation hit** (e.g. the root-window screenshot
   gotcha in §2b) and how it was handled or worked around.
7. **Any mismatch between the README's stated expected behavior and
   what was actually observed** (§2d) — either fixed here (application
   bug, per #5) or handed to Guide B (compiler bug) or flagged as a
   README inaccuracy, with the specific expected-vs-actual detail in
   all three cases.
8. **Which checks came from this document (general) vs. from the
   project's own Guide C Test Manifest (Guide A §0, Phase 2)** — so
   gaps in project-specific coverage are visible, not silently absent.
