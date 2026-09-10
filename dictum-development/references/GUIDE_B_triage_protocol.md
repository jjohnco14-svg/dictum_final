# Dictum Triage Protocol — For the AI With Codebase Access

You are receiving hand- or AI-vibecoded `.dict` files from another AI
that only has `GUIDE_A_dict_language_reference.md` (the language
reference) — it has never seen this codebase. Your job is to run each
submitted `.dict` file for real, decide what kind of problem you're
looking at, and handle it correctly. This document is the protocol.
Read it fully before touching any file.

You also have `docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md` in this
repository — the same content as Guide A. Treat it as the single
source of truth for what correct `.dict` syntax looks like.

---

## 0. The standard you are held to

Every fix that has survived scrutiny in this project's history — XOR,
the multi-file header bug, the `with no value` dangling-token bug, the
`list of T` parameter bug — followed exactly one pattern:

1. Compile it.
2. Link it (real `gcc`/`g++`, real two-phase gate — `--compile` flag).
3. Run the resulting binary.
4. Compare its output against an **independently known-correct**
   expected value — computed by hand, in Python, or from the real
   library's own documentation. Never "looks plausible" or "another
   AI said this is right."
5. Re-run the **full** `compiler/run_selftest.py` suite and confirm
   every existing test still passes.
6. Add a new regression test to `run_selftest.py`, following the
   existing `R1`-`R10` naming and structure, so the bug can never
   silently come back.

**"The error message went away" is never sufficient evidence that
something is fixed.** A patch that makes a symptom disappear without
you understanding *why* the original code produced that symptom is not
a fix — it's a guess that got lucky, or didn't. This project's history
has a two-part example of exactly this risk, worth knowing in full:
the `list of T` action-parameter bug was fixed correctly for the C
backend first (traced to the exact place `emit_c.py` mapped a
list-typed parameter to a bare scalar, fixed to emit a real
`T*`/`size_t` pair, verified end to end) — but the C++ backend was
silently left untouched in that same round, and turned out to be
**more broken than before** for the identical input (it emitted an
invalid type name and leaked raw internal object text into generated
source instead of real values). That gap was only caught because the
C++ backend was checked *independently*, not assumed fine because the
C fix worked. It was then fixed properly on its own terms — the
correct C++ fix (`std::vector<T>`) turned out to be *simpler* than
porting C's approach, once someone actually looked, not a rushed
patch. Both halves of this story matter: "the C version works now"
is not evidence the C++ version does, and a bug found-but-deferred is
not a bug abandoned — it got fixed correctly precisely because nobody
pretended it was fixed before it was.

If you cannot complete steps 1-6 for a given issue in this session,
say so explicitly rather than presenting a partial fix as complete.
"Found, root-caused, not yet fixed — needs a dedicated pass" is a
legitimate and honest outcome, exactly as it was for the C++ half of
the `list of T` bug for one full round before it got its own proper
fix.

---

## 1. First step, always: run it for real

```bash
# Single file:
python3 compiler/dictumc_cli.py path/to/file.dict --backend c --compile --output /tmp/out
/tmp/out

# Also check the other backend if the construct isn't obviously C-specific:
python3 compiler/dictumc_cli.py path/to/file.dict --backend cpp --compile --output /tmp/out_cpp
/tmp/out_cpp

# Multi-file project (a directory of .dict files):
python3 compiler/project_builder.py path/to/project_dir --backend c --out path/to/project_dir/build
cd path/to/project_dir/build && make && ./<binary_name>
```

Never evaluate a `.dict` file by reading it and reasoning about
whether it "looks correct." Compile it. This project's own history is
full of constructs that looked obviously right on paper and failed for
reasons invisible until actually run (the `with no value` bug is a
perfect example — visually correct, silently broken by a token-stream
quirk).

### About `dict_syntax_check.py`

There is a standalone, single-file syntax-only checker at the repo
root (`dict_syntax_check.py`) that Guide A's AI may have access to and
may have already run against its own output before sending it to you.
It reuses the real lexer/parser verbatim, so a PASS from it means the
file is genuinely syntactically valid — it is not a separate,
possibly-wrong opinion you need to re-verify from scratch. What it
does **not** check is anything requiring gcc, cross-file resolution,
or semantic/type validity — so a submission that already passed it can
still be Case B (ambiguous intent) or Case C (a real compiler bug the
syntax level can't see). Don't skip your own full compile-and-run step
just because a submission arrives already syntax-checked — that tool
narrows what kind of problem you're likely looking at, it doesn't
replace verification.

---

## 1a. Read the Build Manifest before anything else [NEW]

Every submission should arrive with a Build Manifest (Guide A §19):
`TARGET`, `BACKEND`, `CPP_STANDARD`, `LIBRARIES`, `GUI`. Read it before
you classify or compile anything.

Every submission should also arrive with a `README.md` (Guide A §20)
describing what the program is supposed to do and what correct
behavior looks like. You don't strictly need it to compile and
triage — that's what the manifest is for — but you do need it on hand
to fill in "expected output" honestly in your own §0 verification
step, and you must pass it through to Guide C untouched (§6) so it
isn't left improvising expected behavior on its own.

- **No manifest present** → treat as `TARGET: linux, BACKEND: c,
  LIBRARIES: none, GUI: no` (the narrowest default — see Guide A §19).
  Don't assume Windows-readiness or GUI behavior that wasn't declared.
- **`LIBRARIES` lists anything** → before doing anything else, check
  each one against the target-tagged registry (§2a) for the declared
  `TARGET`. A library blessed for `linux` is not automatically blessed
  for `windows`, and vice versa — these are tracked as separate,
  independently-verified entries. If any declared library isn't
  blessed for the declared target, that's Case D (§2), not Case C —
  handle it before attempting a normal compile.
- **`GUI: yes`** → note this now; it determines which verification path
  Guide C needs once your build succeeds (§6).

---

## 2. Classify the failure

### Case A — the `.dict` file itself has a mistake

Signs: the error is a `SyntaxError` at a specific line/token that,
when checked against `GUIDE_A_dict_language_reference.md`, clearly
doesn't match documented syntax (e.g. `print result` instead of `print
the text ... and result`; `put X in Y` instead of `put X into Y`;
`number` instead of `whole number`; a `call` used inline as an
expression instead of as its own statement).

**Action:** Fix the `.dict` file directly. State plainly what was
wrong and what you changed, quoting the guide section that shows the
correct form. Re-compile, re-run, confirm the fix actually produces
correct *behavior*, not just a clean compile — a `.dict` file can
parse fine and still do the wrong thing (e.g. wrong operator, wrong
variable used, off-by-one logic). If you have any way to know or infer
the intended correct output (the file's own comments, an obvious
arithmetic identity, a stated goal from context), verify against it.

### Case B — the request is too vague to fix confidently

Signs: the `.dict` file (or the surrounding request) doesn't make it
clear what output is intended, so more than one "fix" is
plausible and they'd produce meaningfully different behavior.

**Action:** Don't guess. Ask a specific, narrow question — not "what
did you mean," but something like "this action returns whole number,
but the calling code treats the result as if it might be negative —
should negative results be clamped to 0, or is negative a valid
result here?" Wait for an answer before proceeding on that specific
point. You can still fix any other, unambiguous problems in the same
file while waiting.

### Case C — it's a real compiler/emitter/tooling bug or gap

Signs: the `.dict` source is syntactically correct per
`GUIDE_A_dict_language_reference.md`, but the compiler mishandles it —
wrong C/C++ output, a crash inside `dictumc`, a silent miscompile
(compiles clean but produces the wrong runtime result), or it hits
something explicitly listed as a known gap in
`SOURCE_OF_TRUTH.md` §11/§12 or in the language reference's §12/known-limitations
section.

**Action:** Full discipline from §0. Specifically:

1. **Root-cause it in the actual source**, not by pattern-matching a
   plausible-looking patch. Read the relevant file
   (`compiler/dictumc/parser.py`, `grammar.py`, `emit_c.py`,
   `emit_cpp.py`, or `compiler/project_builder.py`) and trace exactly
   why the wrong thing happens. If you can't explain the mechanism in
   one or two sentences, you haven't found the root cause yet — keep
   looking.
2. **Check whether the same bug shape exists elsewhere.** Several bugs
   in this project's history were one instance of a repeated mistake
   (e.g. `match_word(*words)` misused as sequential-AND appeared at
   two call sites; the colon-assumption regex bug appeared in three
   of five patterns in the same function). Grep for the same pattern
   before considering the fix complete.
3. **Fix it minimally** — the smallest change that addresses the real
   root cause, not a broader rewrite.
4. **Verify on both backends** if the construct isn't inherently
   backend-specific. Do not assume a C fix implies the C++ path was
   even touched — verify it independently, the same way this exact
   session caught the C++ list-parameter regression that a less
   careful check would have missed.
5. **Write a regression test** in `compiler/run_selftest.py`,
   continuing the `R1, R2, ... Rn` numbering, following the existing
   test shape: a minimal `.dict` source string, compile it via
   subprocess, assert on the compile result, link and run it, assert
   the output matches a known-correct value.
6. **Re-run the entire suite** (`python3 compiler/run_selftest.py`),
   not just your new test. Confirm every single test — behavioral and
   regression — passes. If anything else broke, you have not finished.
7. **Update `SOURCE_OF_TRUTH.md`** (the gap table / known-limitations
   list) and `CHANGELOG.md` with a precise account of what was wrong,
   what you changed, and how you verified it — matching the level of
   detail in the existing entries there, not a one-line "fixed X."
8. **Update `GUIDE_A_dict_language_reference.md` itself — required,
   not optional, for every completed Case C fix.** Guide A is the
   *only* input the other AI (the one writing `.dict` files) ever
   sees. If you fix a real bug here and don't also update Guide A, the
   next `.dict` file that AI writes will make the exact same mistake
   again, or keep avoiding a pattern that's no longer actually broken.
   Guide A must always reflect the current, real state of the
   compiler — not the state it was in when Guide A was last written.
   See §5 below for exactly what "update" means here.

If, after genuinely attempting steps 1-3, you cannot find the root
cause or a fix that survives steps 4-6, **stop and report it as a
found-but-unresolved gap**, exactly like the C++ `list of T` situation
in this document's own §0. Do not ship a patch you don't understand.

### Case A, extended — FFI declaration vs. hand-written implementation mismatch [NEW, found this session]

A specific Case A shape worth naming explicitly: the `.dict` file's
`import from C` declaration can be syntactically perfect and still be
**wrong about the real function's signature** — not because Dictum
mis-emitted anything, but because a hand-written C file implementing
that function (e.g. a wrapper like `cnc_wrappers.c`) drifted from the
declared contract. Confirmed this session: `raylib.dict` declared
several raylib wrapper functions (`rl_BeginMode3D`, `rl_DrawCube`,
`rl_DrawGrid`, etc.) with `decimal number` parameters (→ C `double`
per Guide A §2), but the hand-written `cnc_wrappers.c` implemented them
with `float` parameters instead. This compiled clean and linked clean
on both backends and both targets — the mismatch is invisible to gcc,
since `extern` declarations aren't checked against a same-name
definition's parameter types unless a real header is shared between
them. At runtime, the caller placed a full double-precision bit
pattern in the register the callee then read as a 32-bit float —
silent, garbage values, not a crash. Symptom: the program ran, the 2D
overlay (`DrawFPS`, integer-only args) rendered fine, but every
3D-space draw call (camera, cube, grid) received corrupted
coordinates and nothing appeared in the 3D view — confirmed by
screenshot pixel analysis (the expected wireframe color was absent
before the fix, present after).

**Fix pattern:** when a hand-written C file implements a function also
declared via `import from C`/`C++`, its parameter/return types must
match the *declared Dictum types' C mapping* (Guide A §2), not
whatever the underlying real library's native signature happens to
use. If the real library uses `float` and Dictum has no native
single-precision type, the wrapper should accept `double` (matching
the FFI contract) and narrow explicitly at the point it calls the real
library function — never let the mismatch live at the FFI boundary
itself. Check every parameter of every hand-written wrapper against
its own `import from C` declaration when this class of bug is
suspected — it's rarely just one function once found on one.

### Case D — a declared library isn't blessed for the declared target [NEW]

Signs: the Build Manifest (§1a) lists a library under `LIBRARIES` that
either has no entry at all in the target-tagged registry, or has an
entry for a *different* target than the one declared (e.g. blessed for
`linux`, but `TARGET: windows` was declared). This is not a `.dict`
mistake and not a compiler bug — it's a missing verified bridge for
this specific target. Do not attempt a normal compile first; a missing
or wrong-target bridge will either fail to link or, worse, silently
link against the wrong ABI if a same-named bridge for another target
happens to be present.

**Action — the bridge generation protocol, §2a below.** Never hand-type
a signature to unblock this, and never assume a same-named bridge from
another target is safe to reuse without regenerating and reverifying
it against the declared target's real headers.

---

## 2a. Bridge generation protocol (target-tagged) [NEW]

This is how Case D gets resolved, and it's the same procedure whether
the trigger was a Case D submission or you proactively want to bless a
new library ahead of time.

1. **Confirm the library is real and actually present for the
   declared target** — don't trust the manifest's claim alone:
   - `TARGET: linux` → `pkg-config --exists <lib>` or check the real
     header exists under `/usr/include`.
   - `TARGET: windows` → check for a MinGW-packaged header under
     `/usr/x86_64-w64-mingw32/include`. If the library only ships
     MSVC-only headers with no MinGW port, stop and report this
     plainly as **not bridgeable from a Linux-only pipeline** — don't
     fabricate a header to work around it (see §3).
2. **Generate, never hand-type.** Run
   `compiler/scripts/generate_import_c.py` against the real header
   found in step 1. This produces the `import from C`/`C++` lines
   mechanically, from the real ABI — the same process that produced
   the existing blessed bridges.

   **[UPDATED — this script now exists as a real, working
   implementation]** An earlier round of this protocol found that this
   script was referenced in `DICT_LANGUAGE_REFERENCE_FOR_AI.md` as
   what produced the existing blessed bridges, but only its *output*
   was present in the repo, not the tool itself. That gap is closed:
   `compiler/scripts/generate_import_c.py` is now a real implementation,
   covered by regression test **R23** in `run_selftest.py` (a direct
   binding, a struct-by-value shape, and an out-param function that
   correctly gets flagged as needing a wrapper rather than bound
   directly). Use it directly rather than reimplementing the parse
   step by hand.

   For reference — and as a fallback if you ever find yourself working
   from an older checkout where this script is genuinely still
   missing — here's what it does internally: install a real `libclang`
   Python binding, fetch the real header from its actual source (e.g.
   the library's GitHub repo — not from memory), and parse it directly:
   ```python
   import clang.cindex as cindex
   cindex.Config.set_library_file(<path to libclang.so>)
   index = cindex.Index.create()
   # Do NOT predefine the header's own include guard macro (e.g.
   # -DRAYGUI_H) -- that makes the preprocessor skip the entire file,
   # silently producing zero parsed functions with zero diagnostics.
   tu = index.parse(header_path, args=[...])
   for node in tu.cursor.get_children():
       if node.kind == cindex.CursorKind.FUNCTION_DECL:
           # node.spelling, node.result_type.spelling,
           # [(p.spelling, p.type.spelling) for p in node.get_arguments()]
   ```
   This gives the same real-ABI-or-nothing guarantee the script
   provides, just spelled out manually. Cross-check the parsed function
   count against a simple `grep` of the header's own API-export macro
   (e.g. `grep -c "^RAYGUIAPI"`) as a sanity check that the parse
   actually saw the real content — worth doing even when calling the
   real script, as a second signal that nothing silently no-opped.

   **A second real pattern found bridging `raygui`**: not every real C
   function can bind directly even once its signature is known. A
   function taking a real out-parameter (`int *active`, `bool *checked`,
   `float *value`, ...) can't be bound directly, because Dictum's
   `opaque pointer` type is for threading handles between calls, not
   for taking the address of a local variable (Guide A has no
   address-of construct). The fix is a thin, hand-written C wrapper in
   the project's own wrapper file (not the generated bridge) that takes
   the current value in, calls the real function with a local variable
   internally, and returns the updated value directly — e.g.
   `int cncgui_toggle_group(Rectangle bounds, const char *labels, int
   current_active)` wrapping `GuiToggleGroup(bounds, labels, &active)`.
   Bind the *wrapper*, not the raw function, via `import from C`. This
   is a legitimate, permanent part of the bridge for that function —
   not a workaround to remove later.
3. **Register per-target, not per-library.** Add the result to
   `import_c_registry.py` keyed by `<library>/<target>-<toolchain>`
   (e.g. `sqlite3/linux-gcc`, `sqlite3/windows-mingw`) — never
   overwrite or alias across targets, even for identical function
   names.
4. **Smoke-test it before blessing.** Compile, link, and run a minimal
   program using the new bridge for that specific target (cross-compile
   + Wine-run for Windows, native run for Linux — see Guide C §2 for
   the mechanics), and check its output against a known-correct value.
   Only mark it blessed once this passes.
5. **Add it as a permanent regression case** in `run_selftest.py`,
   same convention as any other Case C fix.
6. **Update Guide A** (§4 applies here exactly as it does for Case C) —
   the new bridge and its target scope need to be visible to the
   `.dict`-authoring AI, not just logged in your own report.

If a library needed for `TARGET: both` can only be bridged for one of
the two, say so explicitly in your report rather than silently
delivering a Linux-only or Windows-only result under a "both" label.

---

## 3. What you must never do

- Never silently rewrite a person's `.dict` file to route around a
  compiler bug without saying so. If a workaround is genuinely the
  fastest path forward for them right now, apply it *and* clearly
  separately log the underlying compiler bug as still-open — don't let
  a workaround be mistaken for a fix.
- Never claim something is "fixed" based only on the compile step
  succeeding. Compiling clean and behaving correctly are different
  claims requiring different evidence.
- Never claim a fix applies to "the compiler" when you only tested one
  backend. Say specifically which backend(s) you verified.
- Never skip re-running the full test suite because your specific new
  test passed. A fix that breaks something else is not a fix.
- Never invent `.dict` syntax that isn't in
  `GUIDE_A_dict_language_reference.md` when fixing a submitted file —
  if the guide doesn't document a construct you think you need, that's
  either a gap in the guide (flag it) or a sign you're reaching for
  something the language doesn't actually support (use a documented
  alternative instead).
- Never complete a Case C fix without updating Guide A (§4). A fix
  that only lives in your own report, and not in the document the
  `.dict`-authoring AI actually reads, will not prevent the same
  mistake next round.
- Never treat a bridge blessed for one target as valid for another
  just because the library/function name matches. Regenerate and
  reverify per §2a for each target independently.
- Never hand off a build to Guide C (§6) without a Build Manifest —
  Guide C has no other way to know whether it needs headless-display
  verification or a plain run-and-diff.
- Never claim a Windows target is "done" based only on a successful
  cross-compile/link. That confirms it built, not that it runs — see
  Guide C's confidence tags.

---

## 4. Keeping Guide A in sync — how to actually do it

This is the mechanism that makes the two-AI setup work over time
instead of the same bugs getting rediscovered every round. Guide A's
§18b (nested `if` inside a plain `otherwise`, fixed a session after
§18's original nine) is a recent worked example of exactly this
discipline in practice — root-caused via real lexer instrumentation,
not guessed at, fixed at the precise two call sites, verified against
both the failing case and the previously-working `otherwise if`
chaining feature (to confirm the fix didn't trade one bug for
another), and written back with the same tone/detail level as §18.

**When to update Guide A:**
- Every time you complete a real Case C fix (root-caused, fixed,
  verified, regression-tested).
- Every time you find a real bug but *don't* fix it this round —
  Guide A needs to know to steer around it, the same way it already
  documents the (now-closed) list-of-T limitation history.
- Every time you discover that something Guide A currently claims is
  broken is actually fine (a false limitation), or vice versa.
- **Never** for Case A or Case B outcomes (a `.dict` author's mistake,
  or a request that needed clarification) — those aren't compiler
  facts, they don't belong in a language reference.

**What "update" means, concretely:**
- If a construct was documented as broken/limited and you fixed it:
  replace that limitation entry with what actually works now, cite
  the regression test number, and briefly note what the fix covered
  (which backend(s), what the old failure mode was) — see the
  existing `list of T` entries in §12 of
  `docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md` for the tone and level of
  detail to match. Don't just delete the old warning — a short "this
  used to be broken, here's what changed" note helps the next reader
  trust the current claim more, the same way it helped you trust this
  guide's [VERIFIED] tags.
- If you found a **new** gap Guide A doesn't mention at all: add it to
  the relevant construct's section (or §12 if it doesn't fit
  elsewhere) with the same [VERIFIED]/[TRACED] confidence-tagging
  convention already used throughout the file. Say precisely what
  breaks and what to do instead, the way the C++ list-parameter entry
  does.
- If you fixed something on only one backend (as happened historically
  with the C fix landing before the C++ one): say exactly which
  backend(s) you verified, explicitly. Never let a single-backend fix
  read as if it applies everywhere — that specific miscommunication
  is what caused the C++ regression to go unnoticed for a full round
  in this project's own history.
- Keep every new/edited claim tagged [VERIFIED] (you actually compiled
  + ran + checked output) or [TRACED] (source-read only) — don't
  upgrade your own confidence tag just because a fix felt obviously
  correct. The whole point of the tagging convention is that it's
  earned by evidence, not asserted by confidence.
- **If your Case C fix touched `compiler/dictumc/lexer.py`,
  `ast_nodes.py`, `type_registry.py`, or `parser.py`, you must also
  re-run `python3 scripts/build_dict_syntax_check.py` before
  considering the fix complete.** `dict_syntax_check.py` (the
  standalone tool Guide A uses to self-check without gcc access) is a
  point-in-time snapshot of those four files, not a live reference —
  if you fix a parser bug and don't regenerate it, the standalone
  checker will keep silently accepting or rejecting things based on
  the *old, buggy* parser behavior, which is exactly the "second
  source of truth quietly drifts from reality" failure mode this
  whole tool was built to prevent. This step is as mandatory as
  updating Guide A itself — a parser fix that's live in the real
  compiler but stale in `dict_syntax_check.py` will actively mislead
  Guide A about what's actually valid.
- **This applies with extra force when merging or packaging together
  more than one independently-edited copy of the compiler** (two
  sessions, two branches, a "fixed" snapshot combined with a "source"
  snapshot). Guide A §18d documents a real case: each copy had fixed
  something the other hadn't, and neither copy's `dict_syntax_check.py`
  reflected both fixes together — one had never been regenerated at
  all across two separate rounds of source changes, despite looking
  otherwise up to date. Don't pick whichever copy's checker "looks
  newer"; regenerate fresh from the merged `lexer.py`/`ast_nodes.py`/
  `type_registry.py`/`parser.py` and diff the result against both
  prior copies to confirm it now reflects everything.

**Where to make the edit:** directly in
`docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md` inside the repository you
have access to. That file *is* Guide A — there is no separate copy to
keep in sync. When you hand back your report (§5), say explicitly
that you updated Guide A and roughly what changed, so the person
running this pipeline knows to re-share the updated file with the
`.dict`-authoring AI before its next round.

## 5. What to report back after handling a submission

For each `.dict` file processed, report:

1. **Classification** — Case A (dict-file mistake), B (needs
   clarification), or C (real compiler bug/gap).
2. **What was actually wrong** — the real mechanism, not just the
   symptom.
3. **What changed** — the `.dict` file, the compiler source, or
   nothing yet (if still open/Case B).
4. **Verification performed** — compiled? which backend(s)? linked?
   run? output compared against what expected value? full suite
   re-run and passing?
5. **If Case C and fixed:** the new regression test's name/number, and
   confirmation the full suite passes.
6. **If Case C and not yet fixed:** an honest statement that it's
   found and root-caused (or found but not yet root-caused) and needs
   a dedicated follow-up — not presented as resolved.
7. **Guide A sync status** — for any Case C outcome (fixed or not):
   confirm you updated `docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md` per §4
   and say what changed in it, or explicitly say why no update was
   needed (e.g. the bug was already documented there with an accurate
   [TRACED]/[VERIFIED] tag and nothing about the guide's claim itself
   was wrong). A Case C fix with no corresponding Guide A update is an
   incomplete report — flag it as such rather than omitting it.

This report is what lets the next round of work (by you, another AI,
or the person) pick up accurately instead of re-discovering the same
ground.

---

## 6. Handoff to Guide C [NEW]

Once a submission compiles, links, and (for Case A/C fixes) has been
run and checked once by you per §0, your job is done for correctness —
but not for target verification. Hand off to
`GUIDE_C_target_verification.md` with:

1. The Build Manifest (§1a) as received or corrected.
2. The README (§1a) as received — this, not your own improvised
   expected value, is Guide C's primary source for what "correct"
   means (Guide C §1). If a submission arrived without one, say so
   explicitly in the handoff rather than passing nothing along
   silently.
3. The build artifact(s) — the binary for each declared `TARGET`.
4. Whatever known-correct expected output you used for your own
   console check in §0/§2, so Guide C can reuse it alongside the
   README rather than invent a new one.

Guide C is a separate protocol deliberately — it verifies *target*
behavior (does the Windows build actually run, does a GUI window
actually render), which is a different kind of check than the
compiler/FFI correctness this document covers, and needs different
tooling (Xvfb, Wine) that has nothing to do with `.dict` or C/C++
correctness itself. Don't try to fold its checks into your own report;
reference its output instead once it's run.

**Guide C now also has the authority to fix what it finds, within its
own domain (§2d/§5 of that document)** — it no longer only routes
everything back here. It still hands genuine compiler/emitter bugs
(wrong C/C++ codegen — a Case C problem, this document's territory)
back to you rather than patching `emit_c.py`/`emit_cpp.py` itself,
since that's a different codebase than the target application it's
verifying. But an application-level bug it finds while verifying
target behavior (wrong camera setup, an unwired button handler, a
mesh built from the wrong coordinate convention — real examples from
this project's own history) is now Guide C's to fix and re-verify, not
just report.

---

## 7. Running this protocol in a restricted/headless sandbox [NEW]

Everything this document describes — `dictumc_cli.py`, `project_builder.py`,
`run_selftest.py`, and `dict_triage.py` (§1a onward) — only needs
`python3`, `gcc`/`g++`, and local file I/O. None of it needs network
access, `pip install`ing anything beyond what's already present, or a
display server. That means the entire Guide B pipeline (including
`run_selftest.py --triage <file.dict>`, which does §1/§1a/§2's
mechanical steps in one call instead of many) runs unmodified in a
plain headless sandbox that only has Python + a C/C++ compiler and no
GUI/browser/screenshot capability at all — that restriction only
matters for Guide C's GUI-class checks (§2b/§2c of that document),
never for Guide B's.
