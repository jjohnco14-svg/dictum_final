---
name: dictum-development
description: Write, compile, triage, and verify Dictum (.dict) programs efficiently, end to end. Use this skill whenever the person mentions Dictum, .dict files, writing code in Dictum's plain-English syntax, or asks to build/fix/verify a Dictum project -- even if they just say "write a dict program that does X" or paste .dict source without naming the language. Also use it for anything touching this project's own pipeline concepts: Guide A/B/C, SOURCE_OF_TRUTH.md, Guide C manifests, Case A/B/C/D triage, or the compiler at compiler/dictumc_cli.py. This skill bundles the real compiler and every real syntax gotcha found by actually compiling code, so use it instead of guessing at Dictum syntax from general knowledge -- Dictum's syntax is a fixed, literal grammar, not a forgiving natural-language parser.
---

# Dictum Development

Dictum is a plain-English-syntax language that transpiles to real C or
C++ and compiles with gcc/g++. This skill binds together the whole real
pipeline this project has built: the four-phase Guide A→B→C process,
the compiler itself (bundled in `scripts/dictum_compiler/`), and every
syntax mistake this project's own development has actually hit and
fixed. The goal is writing correct `.dict` code in fewer round trips,
not more.

**The one rule that matters most:** Dictum's parser matches a fixed set
of literal English words and phrases. It is not a forgiving
natural-language parser. If a construct isn't in
`references/GUIDE_A_dict_language_reference.md`, don't guess a
plausible-sounding phrasing -- check the reference, or compile a
one-line test to find out for real. Every gotcha in this file was found
by an actual compile failure, not by reading the grammar and assuming.

## The pipeline, in brief

```
Phase 0   Discovery conversation -- ask questions, present a concept
          summary, get explicit confirmation BEFORE writing any code.
             |
Phase 1   Write SOURCE_OF_TRUTH_<project>.md: birds-eye view + a
          version-tagged roadmap ([R1] v1 Does X., [R2] v2 Does Y.).
             |
Phase 2   Append a Guide C Test Manifest to the same file: turn each
          [Rn] into a concrete, checkable assertion.
             |
Author    Write the .dict file(s) against the roadmap/manifest that
          already exists -- see "Syntax quick reference" below first.
             |
Guide B   Compile for real, classify any failure, loop until clean.
             |
Guide C   Run the Phase 2 manifest against the real binary + confirm
          coverage.
             |
Deliver   Package for the client -- they get the built artifact and a
          plain-English test report, never the .dict source.
```

Full detail on each phase: `references/GUIDE_0_PIPELINE_ORCHESTRATION.md`
(the phase handoffs and the file-based resume protocol for picking up a
project cold, with no memory of prior sessions), `references/GUIDE_B_triage_protocol.md`
(Case A/B/C/D classification), `references/GUIDE_C_target_verification.md`
(manifest format, console vs. GUI checks).

**Skip phases proportionally to the task.** A quick one-off script
doesn't need a full Phase 0 conversation and a versioned roadmap --
use judgment. The full pipeline is for a real project with a client or
a v1/v2 boundary, not every three-line program.

## The compiler: where it is and how to run it

The real compiler lives in `scripts/dictum_compiler/compiler/`. Every
command below is real and tested against it as of this skill's
authoring -- if any `--help` output looks different in your copy,
trust the live `--help`, not this file.

**Single file, quick compile/check:**
```
python3 scripts/dictum_compiler/compiler/dictumc_cli.py FILE.dict --backend c --compile --output OUT_BINARY
```
(`--output`/`-o` is the real flag. `--out` happens to also work via
argparse abbreviation-matching, but don't rely on that -- it's fragile
against future flags.)

**Nim backend (`--backend nim`):** genuinely verified end-to-end this
session (not just "it transpiles") -- see SOURCE_OF_TRUTH.md §30/§30a
for the real bugs that had to be fixed to get there. It self-provisions
its own Nim compiler on first use (`dictumc/nim_bootstrap.py`: checks a
vendored copy, then PATH, then auto-downloads the official release into
`compiler/vendor/nim/`) -- no separate `apt install nim` step needed.
`--install-nim` pre-warms it without compiling anything.
`import from C`/`import from C++` FFI works on this backend, including
against real system libraries (proven against a live `-lsqlite3`) --
but any backend needs `--link LIBNAME` (repeatable) to actually link
one; the transpile step alone never discovers `-l` flags on its own.

**Multi-file project (the normal case for anything beyond a toy example):**
```
python3 scripts/dictum_compiler/compiler/project_builder.py PROJECT_DIR --backend c --verbose
```
Builds every `.dict` file in `PROJECT_DIR` into `PROJECT_DIR/build/`,
handles cross-file linking (shapes, exported headers, imported-C
externs) automatically. Add `--static` for a client deliverable that
needs to run without matching shared libs installed.

**Diagnose a failure (Guide B, the fast path -- one call instead of
hand-parsing gcc output):**
```
python3 scripts/dictum_compiler/compiler/dict_triage.py FILE_OR_PROJECT_DIR --backend c --json
```
Returns `{"case": "A"|"B"|"C"|"D", ...}`. **Case A** = fix the `.dict`
file. **Case B** = genuinely ambiguous, ask a specific question, don't
guess. **Case C** = looks like a real compiler bug -- this changes
shared infrastructure every future project depends on, so treat it as
needing a real regression test and a second look, not a quick patch.
**Case D** = a declared library isn't "blessed" for this target yet.

**Full verification (Guide C + coverage, one call):**
```
python3 scripts/dictum_compiler/compiler/run_pipeline.py --project PROJECT_DIR \
    --manifest guide_c_manifest.json --source-of-truth SOURCE_OF_TRUTH_x.md --backend c --json
```
Runs Guide B first (hard stop on failure -- never wastes a screenshot
pass on a build that's already broken), then Guide C's manifest checks,
then the coverage check. Read `overall_ok`/`stopped_at` in the output.

**The autonomous retry loop** (for iterating without a human watching
every cycle): `scripts/dictum_compiler/compiler/orchestrate.py`. Drives
the compile-fix-verify loop above automatically on Case A and on real
manifest failures, but stops and surfaces Case B/C/D rather than
guessing -- see that file's own docstring and
`scripts/dictum_compiler/compiler/ORCHESTRATE_TEST_NOTES.md` for what's
actually been tested versus what's real-but-unverified in your specific
environment (the live-LLM backends need your own API key/local model
and haven't been run end-to-end here).

**Current, real project status** (what's implemented, what's a known
gap, every bug found and fixed with its regression test number):
`scripts/dictum_compiler/SOURCE_OF_TRUTH.md`. Skim this before assuming
a feature does or doesn't exist -- it's a real, continuously-updated
record, not aspirational documentation.

## Syntax quick reference (the fast path -- read this before writing code)

These are real mistakes made and fixed during this project's own
development, distilled so they don't have to be rediscovered by
compiling and failing first. Full reference:
`references/GUIDE_A_dict_language_reference.md`.

**Variables & basic types**
```
keep x as whole number with value 5
keep name as text with value "Jaden"
keep nums as list of whole number with values 1, 2, 3, 4, 5
```
`with values` (plural, comma-separated) for a list literal -- not
bracket syntax like `[1, 2, 3]`.

**Loops -- the counter name is required**
```
repeat 5 times using i
    print the text "hi"
end repeat
```
`repeat N times` alone is a parse error -- it's always
`repeat N times using COUNTER_NAME`.

**`if` requires `then`**
```
if x is greater than 3 then
    print the text "big"
otherwise
    print the text "small"
end if
```
`if COND` without `then` is a parse error. The else-branch keyword is
`otherwise`, not `else`.

**Growable collections**
```
keep nums as growable list of whole number with no value
add 10 to nums
print the text "count:" and the count of nums
print the text "item0:" and item 0 of nums
```
Note **`the count of X`**, not `the length of X` -- `length` is
text-only (`strlen`); using it on a list is a real, separate mistake
this project's own docs made once. C backend: `growable list of whole
number`/`set of whole number`/`map of text to whole number` only (no
generics in C). C++ backend: any element/key/value type, since
`std::vector`/`std::unordered_map`/`std::unordered_set` are generic.

**Maps and sets**
```
keep ages as map of text to whole number with no value
put 30 at "alice" in ages
print the text "age:" and the value at "alice" in ages
if ages contains "alice" then
    print the text "yes"
end if

keep tags as set of whole number with no value
add 1 to tags
```
`put V at K in NAME` (map assignment) is a **different statement** from
`put V into TARGET` (plain assignment) -- both are real, disambiguated
by `at`/`into` right after the value. Don't confuse them.

**Calling C/C++ libraries -- parameter types are bare, no parameter names**
```
import from C the action DrawCircle takes whole number and whole number and fractional number and Color produces nothing as DrawCircle
```
Not `takes x as whole number and ...` -- that's a real mistake this
project's own test-writing made. Parameters are just a list of bare
types joined by `and`.

**`call ... giving` infers the result variable's type from the
callee's real declared return type** (fixed after being a real bug --
see SOURCE_OF_TRUTH.md §28). Works correctly for `fractional number`-
returning `import from C`/`import from C++` functions and native
actions on both backends now, so don't work around it with an explicit
type -- but if you see a value getting silently truncated to a whole
number, that's the exact symptom of this class of bug; check
`the value's actual declared source type` before assuming the .dict
code is wrong.

**GUI programs work today** via `import from C` + the blessed bindings
in `scripts/dictum_compiler/compiler/blessed/raylib.dict` and
`raygui.dict` -- these are real, tested bridges (see
SOURCE_OF_TRUTH.md §25/§27), not stubs. Copy the bindings you need into
your project as a sibling `.dict` file (multi-file linking via
`project_builder.py` handles the rest) rather than re-declaring FFI
bindings from scratch.

## When something doesn't compile

1. Run `dict_triage.py --json` on it before hand-debugging the gcc
   output yourself -- it maps the error back to the exact `.dict` line
   and classifies which of Case A/B/C/D you're dealing with.
2. If Case A: cross-check the exact construct against
   `references/GUIDE_A_dict_language_reference.md` before guessing at
   a fix -- most Case A mistakes are a documented-but-misremembered
   syntax form (see the quick reference above for the most common
   ones).
3. If it looks like Case C (compiler bug, not your `.dict`): treat this
   seriously. Reduce to the smallest failing repro, check whether
   `scripts/dictum_compiler/compiler/run_selftest.py` already covers
   this case, and if you do fix it, add a real regression test the same
   way every fix in `SOURCE_OF_TRUTH.md` does -- a fix without a test is
   the kind of thing that quietly regresses later.
4. Never guess your way past Case B. Ask the specific question.

## Verifying real behavior, not just "it compiled"

"Compiles and runs without crashing" and "does what was asked" are
different claims. Guide C's manifest is what separates them -- write
concrete, numerically-checkable assertions for each roadmap claim (an
exact stdout diff, a pixel color, an exit code), not vague ones. Run
`verify/guide_a_coverage_check.py` (bundled at
`scripts/dictum_compiler/compiler/verify/guide_a_coverage_check.py`) to
confirm every roadmap claim has a real check behind it or an honest
`known_gaps` entry -- never a silent gap.

For a GUI program specifically: raylib's own `TakeScreenshot()` (real
framebuffer readback) is more reliable under headless Xvfb than
capturing the X11 root window, which has a documented gotcha with
GLX/Mesa rendering not compositing into the root window's pixmap. See
`references/GUIDE_C_target_verification.md` §2b.
