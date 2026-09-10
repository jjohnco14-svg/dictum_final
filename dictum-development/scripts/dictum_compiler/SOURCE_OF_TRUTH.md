# Dictum — Source of Truth

Canonical reference for where each fact about the Dictum language actually
lives, and what's been verified true about the compiler as of v0.1.38.
Written because the project's core recurring failure mode has been the
same fact about the language living in more than one hand-maintained
place with no sync mechanism — this document is meant to prevent a new
instance of that pattern by saying, explicitly, "this is the one place."

## 1. Type vocabulary

**Single source of truth: `compiler/dictumc/type_registry.py`.**

Every primitive type (name, word tokens, C type, C++ type, numeric?,
usable as a single bare word?, valid as a variable's type?) is one entry
in `PRIMITIVES`. Nothing else should hand-declare a type name, a C/C++
type mapping, or a type-related word list.

Consumers (all derive from the registry, none hand-maintain their own copy):
- `parser.py` — `_TERMINAL_TYPES`, `_PRIMITIVE_SUFFIXES`
- `validator.py` — `PRIMITIVE_TYPES`, `NUMERIC_TYPES`
- `emit_c.py` / `emit_cpp.py` — `self.types` (Dictum name → C/C++ type)
- `grammar.py` — `TYPE_WORDS`
- `out/bridge.js` — queries `type_registry.py` directly via a `python3`
  subprocess (`getRealTypeWords`, `getRealPrimitiveTypeNames`) — does NOT
  regex-scrape grammar.py's source text (that approach broke the moment
  `TYPE_WORDS` became a computed value instead of a literal `{...}`; see
  changelog 0.1.37).
- Static `.gbnf` files (`grammar/dictum_safe.gbnf`, `dictum_unsafe.gbnf`)
  — CANNOT `import` Python. Kept in sync via
  `sync_gbnf_typewords.py`, which must be re-run after any
  `type_registry.py` change. This is the one remaining manual step;
  everything else is automatic.

**Recursive/compound type forms** (`list of <T>`, `unique/shared/weak/raw
handle/pointer to <T>`, `const ref <T>`, `handle to bytes`) are NOT in the
registry — they're hand-coded recursive control flow in `parser.py`'s
`parse_type()`, which genuinely needs to recurse into an inner type. The
registry exports the *building-block words* those forms consume
(`WRAPPER_WORDS`) so `grammar.py`/the `.gbnf` files still know about them,
without needing parser.py's control flow to change.

## 2. Keyword vocabulary

**Single source of truth: `parser.py`'s actual parsing code — nothing
else should be treated as authoritative.**

Unlike types, keywords don't have a registry yet; `grammar.py`'s
`KEYWORDS` set is still a hand-maintained mirror of what the parser
accepts (fixed to match as of 0.1.38, but not automatically kept in sync
going forward). `architecture_test.py`'s Test 2 checks this by extracting
every word literal the parser actually compares against
(`match_word('x')`, `expect_word('x')`, etc.) and diffing against
`grammar.py`'s declared set — **run this after adding any new keyword to
the parser**, since nothing else will catch a gap automatically the way
the type registry does.

## 3. The GBNF files' actual purpose (don't over-trust their strictness)

`grammar/dictum_safe.gbnf` / `dictum_unsafe.gbnf` are what real
koboldcpp Build-tier generation is constrained by (loaded directly in
`out/commands.js` / `out/extension.js`). Their `top-level-item` rule is
**deliberately loose**: `identifier` matches any bare alphabetic word, so
most keyword-vs-vocabulary gaps are invisible in practice (the word is
still producible via the identifier fallback). What is NOT covered by
that fallback, and therefore genuinely blocks generation if missing:
**bare punctuation** — `:` (mandatory on every `program`/`module`/
`shape`/`action` opener), `.` (field access), `-` (negative numbers), `#`
(comments). These were entirely missing until 0.1.35, meaning the grammar
could not produce a single valid Dictum program of any kind. Fixed, and
verified via `gbnf_check.py` (a real GBNF parser + matcher, not a
approximation) against the project's full real `.dict` corpus.

**If you add a new symbol/punctuation character to the language, it must
be added to the `punctuation` rule in both `.gbnf` files by hand** — this
is not derived from anything, and the `identifier` fallback will NOT save
you (it only covers `[a-zA-Z_][a-zA-Z0-9_]*`).

## 4. C vs C++ backend: NOT source-compatible for everything

`emit_c.py` and `emit_cpp.py` are two largely-parallel, independently
hand-written transpiler implementations. This is a structural risk in
itself: a bug fixed in one has repeatedly needed the identical fix
hand-applied to the other (module preamble ordering, sibling/`use`d-module
call resolution, `RAW_MALLOC`-family redeclaration, the `Use`-in-body
whitelist gap — all found and fixed twice, once per backend, this
session). **Whenever you fix a codegen bug in one backend, check the
other for the same bug before considering it done.**
`architecture_test.py`'s Test 3 (backend parity) automates the "did you
forget the other backend" check across the full `foundation_test.py`
corpus — treat any new gcc/g++ divergence it reports as a real bug unless
it's added to `KNOWN_BACKEND_DIVERGENCES` with a documented reason.

**Currently known, deliberate, documented divergence** (not a bug, a real
architectural limitation — see `SKILL_BUILD.md`'s Atomics section):
`ATOMIC_*`/`CAS_*` unsafe tokens are not source-compatible between
backends. C expands to `__atomic_fetch_add(ptr, ...)` (needs a plain
`T*`); C++ expands to `ptr->fetch_add(...)` (needs `std::atomic<T>*`).
Picking a backend for atomics-using code is a real upfront decision.

## 5. The compile gate is two-phase on purpose — don't test with only Phase 1

`transpiler.py`'s `compileCheck()` (used by the real `dictum.run` command
via `out/extension.js`) runs `gcc/g++ -fsyntax-only` (Phase 1) THEN a full
compile-and-link (Phase 2), unconditionally. This is deliberate and
important: C treats calling an undeclared function as a WARNING
(`-Wimplicit-function-declaration`), not an error — a hallucinated or
typo'd callee name (a highly plausible weak-model mistake, e.g.
`calc_distance` instead of `distance`) passes Phase 1 silently and is only
caught by Phase 2's link failure (`undefined reference to ...`). **If you
write a test harness or tooling that checks compilation, always run both
phases** — `-fsyntax-only` alone will produce false "PASS" results for
this exact failure mode. (Confirmed via `simulate_vibecoding.js`; this was
initially mis-diagnosed as a gap in the real pipeline during this
session's own investigation, before re-checking against the actual
two-phase design and finding it already handled correctly. The mistake
was in the test, not the compiler — worth remembering when investigating
future "why did this pass when it shouldn't have" reports too.)

## 6. Known, real, currently-unfixed limitations (not bugs — documented decisions)

- **Atomics are backend-incompatible.** See §4.
- **Module-scope tracking for `use` is file-global, not scope-local**
  (0.1.38). A same-named plain top-level action defined elsewhere in a
  file that also `use`s a module exporting an action with that name could
  resolve to the wrong one. Low real-world risk; full fix needs
  scope-aware tracking, judged not worth the complexity yet.
- **`bytes` is a raw `uint8_t*`, distinct from `handle to bytes` (opaque
  `void*`).** Both exist; pick deliberately.

## 7. Permanent test suite (run all of these after any compiler change)

- `run_selftest.py` — behavioral + historical-regression tests (existed
  before this session).
- `foundation_test.py` — every LANGUAGE_REFERENCE.md example + a
  registry-driven feature matrix, through validate → both backends →
  GBNF reachability.
- `gbnf_check.py` — standalone real GBNF parser/matcher; use directly to
  check "can this exact string be produced under grammar constraint."
- `architecture_test.py` — hunts specifically for vocabulary/logic
  duplication drift (the pattern behind most bugs found this session),
  not "does this program compile."
- `sync_gbnf_typewords.py` — run after any `type_registry.py` change.
- `simulate_vibecoding.js` — exercises the real, shipped `chunking.js`/
  `graph.js`/`retryLoop.js` against a synthetic Plan, including a
  deliberately-injected bug, to check the real Build/Review/retry
  orchestration logic (not just the Python compiler) end to end.

## 8. Continuing sessions, project-wide codegraph, and skills (v0.1.39)

Three related additions, all additive (no core compiler files touched,
verified by identical `run_selftest.py`/`foundation_test.py`/
`architecture_test.py` results before and after).

**Continuing Plan/Build/Review (Part 1).** `graph.js` already tracked
every open document workspace-wide before this was built — the actual gap
was that `_runGenerate` (Plan) never consumed it, and there was no way to
patch an existing action instead of duplicating it. Now: Plan gets an
"EXISTING CODE CONTEXT" section built from `graph.buildPromptContext`
whenever the graph is non-empty; a new `MODIFY` plan-item category
(parallel to `OPERATION`) signals a change rather than an addition; and
`out/patchEngine.js` finds and replaces the named block in place, applied
before validation (not after) in `_runBuildChunk`. Falls back to append
whenever a target can't be confidently found. `[MODE: fresh|continue]`
and `[FILE: name.dict]` directives, parsed in `validator.js`.

**Project-wide codegraph (Part 2).** `project_builder.py` already had a
`dictum.project.json` manifest and dependency parsing — for a completely
separate, non-AI compile/link pipeline (`dictum.buildProject`), unwired
from the Plan/Build/Review commands entirely. `out/projectScan.js` closes
the actual gap (proactive discovery of files nobody's opened in a tab
yet), reusing `graph.js`'s existing `indexSource` rather than writing a
third independent symbol extractor (there are already two: `graph.js` and
`project_builder.py`'s `parse_deps` — for different consumers, not
duplicated further). **Known scope limit, not a hidden gap**: `[FILE:]`
directive parsing and target resolution (`resolveTargetFile`) are done;
actually wiring `_runBuild` to write to more than one physical file live
in a single session is the next step, not this one.

**Skills as curated library bundles (Part 3A).** Confirms the "Option A"
design (see earlier discussion): zero compiler changes needed. A skill is
`skills/library/<name>/*.dict` (real shapes + `import_c` bindings) plus
optional `SKILL_PLAN_<name>.md`/`SKILL_BUILD_<name>.md` addenda, loaded by
`out/skills.js`. `dictum.activeSkill` is orthogonal to the existing
`[SKILL: general/unsafe/concurrent]` plan directive (domain vs.
safety-tier — both layer independently). First real skill: `gamedev`
(the raylib subset from this session's 3D game work). `'general'`
(default) is a verified true no-op.

**If you add a new skill**: don't add new primitive types for it (see §1
and the Option A/B discussion) unless a concrete need proves shapes +
`import_c` genuinely insufficient — that should be rare. Drop a `.dict`
bindings file in `skills/library/<name>/`, optionally add the two
addendum markdown files, and it's picked up automatically — no code
change needed in `skills.js` itself.

## 9. Test suite (updated)

- `run_selftest.py`, `foundation_test.py`, `gbnf_check.py`,
  `architecture_test.py`, `sync_gbnf_typewords.py` — unchanged, see §7.
- **`extensions_test.py`** (new) — Parts 1/2/3A specifically: patch
  correctness (including a real compile check, not just string
  inspection), project discovery/exclude/manifest-parity, skill loading
  and no-op verification for the default case.
- **`e2e_test.js`** (new) — all three parts together in one realistic
  session, including a full graph clear + re-scan from disk between the
  initial build and the continuation, specifically to prove a genuinely
  new session (not just in-process state) can continue correctly.

Version at time of writing: **0.1.39**.

## 10. Codegraph pattern database -- storage/lookup mechanism (v0.1.46)

Built in response to Cell 9/10/11's Kaggle findings: GBNF grammar
constraints (chunk_grammar.py) restrict a generated chunk's *shape*, but
several real, live failures showed they can't restrict its *content* --
a small model that's never seen Dictum in training fills an open slot
with the nearest Python/C/JS habit instead (`countdown` instead of the
plan's `Count`, invented `<name>`/`[Person.name]` string interpolation,
swapped unsafe-token param order, ...). Tightening the grammar further
only relocates the hallucination to a different escape hatch each time
(see Cell 11's own "known remaining limitations" notes).

**What this is:** a small file-based pattern store --
`codegraph/patterns/<pattern_ref>.json`, one file per construct, same
filesystem-as-database convention as `skills/library/<name>/*.dict` and
`graphify-out/cache/ast/*.json` (no new storage dependency) -- plus a
loader/binder/renderer (`compiler/dictumc/pattern_graph.py`) and a
Node-side bridge (`out/patternGraph.js`, same spawn/stdin/stdout
contract as `normalizeDictum.js`) that turns a `pattern_ref` (+ optional
params) into a ready-to-inject few-shot context block: description,
stated preconditions, known common mistakes, and a concrete correct
Dictum example -- so the Build prompt can show the model real Dictum for
the specific construct it's about to generate, not just constrain the
token shape it emits.

**What this is not, yet:** not wired into `_runBuild`/the Build prompt
itself (that's the next step once there's a real pattern set to wire
in); not wired into `chunk_grammar.py`'s GBNF generation (a pattern
could later carry an exact-shape grammar fragment, but that's a
separate, larger integration -- see `codegraph/PATTERN_SCHEMA.md`'s
"Deliberately NOT done yet" section); not a Plan-phase `pattern_ref`
directive yet (parallel to how `[SKILL: name]`/`[FILE: name]` already
work) -- that requires updating the Plan prompt/`validator.js`, also
deferred. This commit is the storage + lookup + binding mechanism and
its tests only, seeded with one real pattern (`while-loop` -- not
coincidentally the exact construct behind Tier3's undeclared-variable
failure) so the plumbing has something real to run against; the rest of
the pattern set (print-interpolation, pointer-ops, unsafe-RAW_MALLOC/
RAW_FREE/ATOMIC_FAA, ...) is intentionally a separate follow-up.

**Files added:**
- `codegraph/PATTERN_SCHEMA.md` -- full field contract + rationale.
- `codegraph/patterns/*.json` -- 10 patterns (hello-world, import-c,
  shape-declaration, shape-actions, while-loop, pointer-ops, unsafe-
  malloc, atomic-increment, importc-math, importc-raylib), all
  cross-validated against `validated_patterns.json` (200 real
  transpiler-run examples supplied separately, 100% pass rate) -- see
  `pattern_graph_test.py`'s Layer 5 and each pattern's own
  `requires`/`common_mistakes` for what's exactly reproduced vs. a
  documented coverage limit (structural body variation not captured by
  recorded params, for `while-loop`/`shape-actions`/`importc-raylib`
  specifically).
- `compiler/dictumc/pattern_graph.py` -- load/validate/bind/render +
  `--bridge`/`--list` CLI (same `{ok: true|false|null}` three-way
  contract as `normalize_dictum.py --bridge`). Adds a `field_list` param
  type (structured, not scalar -- a list of `[name, type]` pairs
  rendered as indented shape-field lines) for `shape-declaration.json`/
  `shape-actions.json`.
- `compiler/dictumc/pattern_graph_test.py` -- self-test, five layers
  (in-process API, the actual CLI subprocess contract, schema-violation
  fixtures in an isolated scratch dir, every shipped pattern loads
  cleanly, and a cross-check of every pattern's `example` field against
  `validated_patterns.json`'s real base entries when that dataset file
  is present on disk). Run directly:
  `python3 compiler/dictumc/pattern_graph_test.py`.
- `out/patternGraph.js` -- Node bridge (`renderPatternContext`,
  `listPatterns`), not yet called from any Build-path file.

**Bugfix found by this data, applied to `chunk_grammar.py`:**
`UNSAFE_ARITY["ATOMIC_FAA"]` was hardcoded to 2 (pointer, delta) when
the unsafe-token grammar work landed -- based on the Cell 9-11 test
suite's own plan text ("ATOMIC_FAA Counter 1"), which never mentioned a
result variable and used a bare variable instead of a pointer to it.
`validated_patterns.json`'s 21/21 real transpiler-run ATOMIC_FAA
examples all show a **three**-parameter form --
`[ATOMIC_FAA: <pointer> : <delta> : <result-variable>]` -- so
`UNSAFE_ARITY["ATOMIC_FAA"]` is now 3. Both the grammar's arity and the
test suite's plan text were wrong in the same direction; this fixes the
grammar side. See `codegraph/patterns/atomic-increment.json` for the
corrected canonical example and the preconditions this construct
actually needs (target variable, a pointer to it, and a result
variable, all declared via `keep` first).

Version at time of writing: **0.1.46**.

## 11. Production-readiness gap list, and what's closed so far (v0.1.47)

A 14-item gap list was compiled (self-review against the real codebase,
plus a real user-reported gap #14) to identify what stands between the
current compiler/extension and something honestly callable "production
ready." Full list, current status:

| # | Gap | Status |
|---|---|---|
| 1 | MEMORY/SAFETY unconstrained on tool-mode providers | **Closed** |
| 2 | Compile errors point at generated C, not Dictum source | **Closed** |
| 3 | `body_dictum` still free text on covered tiers (TYPE/OPERATION/MODIFY) | **Closed** |
| 4 | Single-file output only (no real multi-file transpile+link, and nothing wired that mechanism into the extension) | **Closed** |
| 5 | stdlib bindings breadth | Not started (LLM/Robot/Speech genuinely need real model weights/hardware this environment can't provide -- see §21) |
| 6 | Tagged unions/bitfields | Not started |
| 7 | Header export | **Closed** — see §21 |
| 9 | Dynamic collections (map/dict/set, growable list) | **Closed.** C++: any type (§23). C: `growable list of whole number` (§22), `map of text to whole number`/`set of whole number` via real hash tables (§24). |
| 10 | Behavioral verification gate (tests derived from plan items) | Not started — hardest item on the list; needs a real definition of "correct," not just error detection |
| 11 | IDE intelligence (completion/definition/hover providers) | Not started |
| 12+13 | Scoped libclang integration + soft-keyword scoping | Not started — largest single item on the list, a genuinely new parsing subsystem |
| — | XOR bitwise operator (found separately, not on the original 14-item list) | **Closed** — see CHANGELOG "Unreleased" |
| — | `parse_keep` `with no value`/`with all values` dangling-token bug (found separately) | **Closed** — see CHANGELOG "Unreleased" |
| — | `list of T` as an action parameter (found separately) | **Closed on both backends** — C fixed first (`(T*, size_t)` pair), C++ verified independently, found broken worse, fixed separately (`std::vector<T>`) — see CHANGELOG "Unreleased" |
| — | `project_builder.py` silently ignoring an explicit `--backend`/`--cpp-standard` on a fresh workspace (found separately) | **Closed** — see §12 below |
| 14 | Real TLS (`dictum_tls.h`'s stubs wired to OpenSSL/mbedTLS) | **Closed** — see §21 |

See `CHANGELOG.md`'s 0.1.47 entry for full technical detail on gaps
1–4 and the three bugs found and fixed while verifying them (a C++
forward-declaration bug for top-level sibling `Action`s, a `parseStderr`
misclassification bug affecting every caller, and a temp-directory
cleanup-ordering bug in the new multi-file compile-gate wiring). The
short version of what changed, for anyone updating this table later:

- **Gap #1/#3** live in `out/toolSchema.js` (`SCHEMA_APPLICABLE_TIERS`,
  `_statementSchema()`, the `unsafe_ops` shape) and
  `compiler/dictumc/emit_c.py` (`unsafe_op_names()`, the same
  derive-don't-hand-copy pattern §1's type registry already established
  for types — this is the same fix shape applied to the unsafe-op
  vocabulary).
- **Gap #2** lives in `compiler/dictumc/emit_c.py`/`emit_cpp.py`
  (`_emit_marked()`, the `@dictum-line:N` markers) and
  `out/transpiler.js` (`buildDictumLineMap`, `translateCompilerOutput`).
- **Gap #4** has two real parts, and both had to be done for the gap to
  actually be closed: the multi-file transpile/link mechanism itself
  (`transpileFile`/`transpileProject`/`compileCheckProject`/
  `cleanupProjectDir` in `out/transpiler.js`) is necessary but not
  sufficient — `out/extension.js`'s `_runCompileGate` had to actually be
  rewired to call it (via the new `compileCheckSmart` unifying wrapper
  and `projectScan.js`'s pre-existing `findProjectFiles`/
  `loadOrDiscoverManifest`, previously used only for codegraph indexing)
  for a real cross-file project to ever pass the interactive Build
  compile gate.

**Testing note specific to this section:** `out/extension.js` requires
the `vscode` module, which only exists inside a real VS Code host
process — it cannot be `require()`'d or executed standalone the way
`out/transpiler.js`/`out/toolSchema.js` can. The `_runCompileGate` wiring
in gap #4 was therefore verified by extracting its actual logic into a
standalone, fully-tested function (`compileCheckSmart`, exercised for
real by `test_gap4_extension_wiring.js`) and confirming `extension.js`'s
call site passes the right shape to it (syntax-checked via `node -c`,
and manually traced against `projectScan.js`'s real exported function
names) — not by running the extension inside an actual VS Code instance,
which this environment cannot do. If a discrepancy ever appears here, it
would most likely be in that untested seam (the exact plumbing inside
`_runCompileGate`, not `compileCheckSmart` itself).

Version at time of writing: **0.1.47**.

## 12. CLI-side Guide B triage (`compiler/dict_triage.py`) [NEW]

Gap #2 (§11) closed the *VS Code extension's* path from a gcc/g++ error
back to a real Dictum line (`out/transpiler.js`'s `buildDictumLineMap`/
`translateCompilerOutput`, reading the `@dictum-line:N` markers
`emit_c.py`/`emit_cpp.py` already emit). That logic was never reachable
from the plain CLI/batch pipeline `GUIDE_B_triage_protocol.md` describes
(`dictumc_cli.py --compile`, `project_builder.py` + `make`) — anyone
running Guide B by hand on a submission outside the extension had to
re-derive the C-line → Dictum-line mapping themselves, every time.

`compiler/dict_triage.py` is that same mapping logic, ported to Python,
wrapped into a full automated pass over Guide B §1/§1a/§2's mechanical
steps for one submission (single `.dict` file or a project directory):
parses+validates in-process (Case A, with exact line numbers straight
from the real lexer/parser/validator), compiles with real gcc/g++ and
maps any failure back to the real `.dict` line (Case C), checks declared
`LIBRARIES` against `blessed/` (Case D — honestly reported as
"unverifiable" rather than falsely "blessed," since no target-tagged
`import_c_registry.py` exists yet, see Guide B §2a), and runs the
resulting binary against an `--expected-output` if one is given. It
also has `--emit-regression-stub`, which appends a templated `Rn` test
to `run_selftest.py` in the existing `R1..R24` shape, with the failing
`.dict` source embedded.

Reachable as `python3 compiler/run_selftest.py --triage <file-or-dir>
[options]` or directly as `python3 compiler/dict_triage.py <file-or-dir>
[options]`.

**A real bug was found and fixed while building this (R24, see
`run_selftest.py`):** `project_builder.py`'s `load_or_create_manifest()`
baked `'backend': 'c'`/`'cpp_standard': 17` into its auto-discover
default for any workspace without a pre-existing `dictum.project.json`,
so `build_project()`'s `manifest.get('backend', backend)` always found
that hardcoded value first and never fell through to the caller's real
`backend`/`cpp_standard` arguments — meaning `project_builder.py <dir>
--backend cpp` silently built C instead of C++ on any fresh project
directory, with no error or warning. Root-caused to those two keys not
belonging in the "nothing on disk yet" default at all (they're exactly
the fields callers pass explicit overrides for); fixed by omitting them
from that default so an on-disk `dictum.project.json` from a previous
run still wins unchanged, but a fresh workspace now genuinely respects
the caller's argument. Verified via `test_r24_project_builder_backend_
override` (real `--backend cpp` invocation on a fresh dir, asserts the
`.cpp` file — not `.c` — was written, the resolved backend was
persisted, and the emitted C++ actually compiles+links+runs with g++).
This bug was independent of Guide B/`dict_triage.py` itself — it lives
entirely in `project_builder.py`, pre-dates this session's triage work,
and would have silently affected any direct CLI use of `--backend cpp`
on a new project.



## 13. CLI-side Guide C orchestrator (`compiler/verify/guide_c_verify.py`) [NEW]

Same relationship to `GUIDE_C_target_verification.md` that
`dict_triage.py` (§12) has to Guide B: that document's checks (console
diff, Xvfb+screenshot GUI capture, project-specific scripts from a
project's Guide C Test Manifest) used to mean an AI hand-driving
~10-15 separate bash calls (start Xvfb, sleep, launch, sleep,
screenshot, kill, run each verify script separately, ...) every
session. `guide_c_verify.py` (also reachable as `run_selftest.py
--verify-target <guide_c_manifest.json>`) does all of it in one call
and returns one structured JSON verdict.

Schema for the manifest it consumes: `verify/guide_c_manifest.schema.json`.
It's the JSON counterpart to a project's `SOURCE_OF_TRUTH_<project>.md`
Guide C Test Manifest section (Guide A §0, Phase 2) — the markdown is
for humans, this is what the orchestrator actually executes, and
keeping them in sync is Guide A's job.

Verified end-to-end in this session, including two real bugs found and
fixed while building it (same discipline as everything else in this
document — compiled, run, and fixed for real, not assumed working):

- The screenshot-capture subprocess call wasn't given the `DISPLAY`
  env var it needed, so every GUI-class check silently reported the
  known "root-window screenshot came back empty" gotcha (Guide C §2b)
  even when the display was actually working — confirmed by running a
  real X11 client (`xclock`) under Xvfb, seeing the false-empty result,
  fixing the missing `env=env` on that call, and re-running the exact
  same check to confirm a real, non-empty screenshot.
- A missing or non-executable target binary crashed the whole
  orchestrator with an unhandled `FileNotFoundError` instead of
  reporting one clean `SKIP` for that check — found by testing against
  a manifest for a project whose binary genuinely isn't built yet
  (`cnc_vibecoder`, no `.exe`/binary in this environment), fixed by
  checking existence/executability before invoking, and confirmed
  end-to-end (that same manifest now reports 4 honest `SKIP`s instead
  of a crash).

Regression test **R25** in `compiler/run_selftest.py` covers the
console-class path deterministically (Xvfb-independent, so it holds in
any CI environment); the GUI path was verified manually against a real
`xclock` process under Xvfb in this session, since a CI-safe
regression for it would need Xvfb present in the test environment
itself, which isn't guaranteed the way `gcc` is.

Version at time of writing: **0.1.51**.

## 14. Pipeline hardening pass — items #2-6 from the improvement roadmap [NEW]

All verified end-to-end in this session (compiled, run, and in several
cases a real bug found and fixed while building — not assumed working
from a read-through). Full suite: **34/34** regression, 6/6 behavioral.

- **#6 Case D hardening** — `dictumc/import_c_registry.py`, a real
  target-tagged blessing registry backing the `is_blessed()` hook
  `dict_triage.py` already expected. Seeded empty on purpose (couldn't
  fetch real dev headers in this sandbox to seed genuine data — refused
  to fabricate a blessing). CLI: `--register <lib> <target> --toolchain
  ... --note ...`. **R27**.
- **#4 Guide A/parser drift** — `verify/guide_a_sync_check.py` imports
  `dictumc/grammar.py`'s real `KEYWORDS` set and flags any keyword never
  mentioned anywhere in Guide A's prose. First version (backtick-only
  matching) produced ~90 false positives from ordinary prose ("for each",
  "is equal to"); switched to a whole-document word match, which surfaced
  a real, plausible gap list (`constructor`/`destructor`/`method`/
  `private`/`public`/`virtual`/`override`/`unsafe`/`ref`/`unique`/`weak`/
  `syscall`/`transmute` and others — Guide A appears to have zero OOP/
  memory-safety/FFI-detail coverage for constructs the grammar actually
  parses). **R28**.
- **#5 Incremental caching** — `verify/cache_lib.py`: a cache key built
  from file content + a "compiler fingerprint" (mtime/size of every
  compiler .py file + real `gcc`/`g++ --version` strings), so ANY
  compiler change invalidates every cached verdict, never just a version
  string someone forgot to bump. Wired into `dict_triage.py --cache`
  (whole-file triage) and `guide_c_verify.py --cache` (console-class
  checks only — GUI checks and project-specific scripts are deliberately
  never cached here, since rendered output and arbitrary scripts can't
  be assumed deterministic from a file hash alone). **R29, R30**.
- **#2 Deterministic/visual split** — `verify/selftest_lib.py`: the same
  `@regression`/PASS-FAIL-SKIP rigor this file's own `run_selftest.py`
  uses, packaged so any Dictum *project* (not just the compiler) can
  build its own exact-diff regression suite, with a `--json` mode whose
  output matches `guide_c_verify.py`'s `project_specific_scripts`
  contract exactly — confirmed by actually plugging a synthetic suite in
  as a manifest entry and running it through `guide_c_verify.py` for
  real. Also added `lint_manifest_classes()` to `guide_c_verify.py`:
  advisory (non-blocking) warnings when a check's declared `class`
  structurally doesn't match its kind (a `console_check` marked
  `'visual'`, a `gui_check` claiming `'deterministic'`, or a missing
  `class` field entirely). **R31, R32**.
- **#3 Unified driver** — `run_pipeline.py` (`run_selftest.py
  --full-check`): Guide B → Guide C → Guide A coverage check, one call,
  fixed order, hard stop at Guide B on a real failure (verifying target
  behavior on a build that doesn't compile is meaningless, so Guide C is
  never even attempted in that case — confirmed via `stopped_at` /
  `guide_c: null` in the report). Real integration bug found and fixed
  while wiring this: Guide B's project-mode triage normally builds into
  an ephemeral temp dir and deletes it right after the run check (correct
  for Guide B alone) — but Guide C needs the binary to still exist.
  Fixed by having `triage_project()` report a real `bin_path` whenever
  `keep_artifacts=True`, and having `run_pipeline.py` request that and
  transparently repoint the manifest's `binary` field at the real build
  output before handing off to Guide C. Confirmed via a real build, not
  just a code read. **R33**.

Version at time of writing: **0.1.51**.

## 15. Freelance-deliverable checklist — status [NEW]

Mapped against a concrete client-deliverable checklist (static binary,
README, optional source, test report; static-linked + ldd-verified;
locked/reproducible compiler version; one command = one verdict). All
new tools below verified end-to-end in this session, including negative
cases (deliberately broken inputs), not just the success path.

**Built and verified:**
- **Static linking + real verification** — `project_builder.py --static`
  (`-static -static-libgcc[-libstdc++]`), plus `verify/verify_static_link.py`,
  a real-`ldd`-based check (not "the flag was passed") wired into
  `dict_triage.py --static` / `run_pipeline.py --static`, gating the
  overall verdict. Confirmed against a real static binary (`ldd` reports
  "not a dynamic executable") and a real dynamic one (correctly FAILs,
  lists the actual remaining dependencies). **R34**.
- **Client package assembler** — `verify/package_for_client.py`. Takes a
  passing `run_pipeline.py` report, assembles {renamed binary, plain-
  English README, a test report scrubbed of all internal jargon
  (confirmed: no "Dictum"/".dict"/"Guide A/B/C"/"triage" anywhere in
  what ships), optional generated-C-only source}. Hard guard
  (`_assert_no_dict_files`) walks the staged deliverable right before
  zipping and refuses to package if a `.dict` file is anywhere in it,
  under any flag combination — tested directly against a directory with
  a deliberately-leaked `.dict` file to confirm the guard itself fires,
  not just that the normal copy path happens to avoid it. Also confirmed
  refusing to package a report that isn't `overall_ok`, and one with no
  persisted binary. **R35**.
- **Reproducibility / build provenance** — `verify/reproducibility_check.py`.
  Builds the same `.dict` project twice, independently, and confirms the
  binaries are byte-identical (sha256) — proving the build process
  itself is deterministic, not just that unchanged source produces an
  unchanged result trivially. Stamps a real "compiler fingerprint"
  (reusing `cache_lib.compiler_fingerprint()`) and a git commit hash if
  available, so "locked compiler version" is a real, checkable artifact
  attached to a build rather than a promise. Confirmed on a real double
  build (byte-identical, as expected), and separately confirmed the
  mismatch-detection branch itself fires correctly via a controlled
  injected mismatch (didn't rely on the real build happening to be
  reproducible to prove the negative path works). **R36**.
- **One command = one verdict** — already covered by `run_pipeline.py`
  (§14, R33), now also carrying `--static` through.

**Explicitly NOT built, and worth being honest about:**
- **"Walk away for an hour" autonomous loop.** Everything above verifies
  and detects efficiently; nothing here autonomously goes from a plain-
  language project description to working `.dict` source without a
  human/AI driving each fix iteration. That's the actual bar the
  checklist's "honest gate" sets, and it isn't met by this pipeline —
  this pipeline makes *verification* fast, not *generation* autonomous.
- **Case D blessing data.** The registry mechanism (§14) is real; the
  data in it is still empty (no dev headers available in this sandbox to
  seed genuine entries).
- **Windows builds.** Out of scope per the checklist itself ("later
  problem") — no work done here.

Version at time of writing: **0.1.51**.

## 16. Real `#line` directives (cheap-call error mapping) + `-Werror` [NEW]

Both from the user's own proposed file list — the two items on that list
that weren't already built. Verified end-to-end, including a real found-
and-fixed bug and one honestly-documented remaining limitation.

- **`dictumc/line_directives.py` + `dictumc/debug_mapper.py`** (both new)
  — `emit_c.py`/`emit_cpp.py` now additively emit a real C `#line N
  "file.dict"` directive right alongside the existing `/* @dictum-line:N
  */` comment (nothing removed — see `line_directives.py`'s docstring
  for why both exist). `debug_mapper.py` maps a gcc/g++ diagnostic back
  to `.dict` in three tiers: (1) gcc already reports a `.dict` path
  directly, via the `#line` directive — the fast path, no line-map
  needed at all, confirmed via a genuine Case C error (a C-keyword
  collision, `keep int as...`) three levels deep inside a `while` loop,
  reported by gcc as `t.dict:5:17: error: ...` with **the actual .dict
  source line quoted with a caret**, since gcc reads the real file off
  disk once `#line` points at it; (2) falls back to the existing marker
  map; (3) genuinely unmapped. Wired into `dict_triage.py`'s Case C path
  (`debug_mapper.map_gcc_output` now called instead of the older
  `translate_compiler_output`, which stays in the file, now unused, in
  case a future revert is ever needed). **R37**.
  - Threading the real `.dict` filename (not a placeholder) required
    fixing three call sites that constructed a `Transpiler`/
    `StdlibTranspiler` without `source_path`: `dict_triage.py`'s own
    `try_parse_and_validate`, and both `project_builder.py` call sites
    (single-file and multi-file project mode) — found and fixed while
    wiring this, confirmed via a real compile showing the placeholder
    `<dict-source>` replaced by the actual filename in gcc's output.
  - **Found, reproduced, and FIXED**: `Attempt` blocks (both backends —
    the C backend's setjmp-style handling and the C++ backend's
    try/catch) emit several physical lines directly from their own
    handler — `/* attempt */`, `dictum_error_clear();`, the result
    assignment, `if (!DICTUM_HAS_ERROR()) {` on the C side; `try {`, the
    result assignment, `} catch (...) {` on the C++ side — not via a
    nested body statement's own `_emit_marked` call. A single `#line N`
    at the top of such a statement auto-increments for the rest, so a
    later line's error gets the wrong number. **Reproduced for real**: a
    C-keyword collision (`attempt call get_value giving int`) was
    reported by gcc as **2 lines off**, landing on a completely
    unrelated `end program` line with a misleading quoted snippet — this
    was worse than merely "imprecise," it was actively misleading. Fixed
    by adding `_emit_own_line(node, text)` (mirrored on both
    `CEmitter`/`CppEmitter`) — re-asserts a fresh `#line` before every
    line a statement's own handler emits directly, not just the first.
    Re-ran the exact same repro after the fix: gcc now reports
    `t.dict:6:13`, the real line, quoting the real `attempt` statement.
    **R38** covers this on the C backend end-to-end (through the real
    `dict_triage.py` CLI, not just the isolated emitter); **R39** does
    the identical proof for the C++ backend (a real C++-keyword
    collision, `giving class`, through `dict_triage.py --backend cpp`)
    — the C++ fix was applied on the same read-the-code basis as the C
    one, but initially only the C side had a dedicated repro+regression
    test; R39 closes that "applied the same fix but only proved it once"
    gap rather than leaving the C++ side as an unverified assumption.
- **`-Werror`** added to both compile paths (`dict_triage.py`'s
  `_gcc_compile`, `project_builder.py`'s release `CFLAGS` — deliberately
  NOT the debug+ASan path, so a stray style warning never blocks a real
  ASan-finding debugging session). Verified safe empirically — ran the
  full suite with it in place before committing to it, rather than
  assuming the generated C was warning-clean.

Version at time of writing: **0.1.51**.

## 21. Gaps #7 and #14 closed for real: header export wiring + OpenSSL TLS

**Gap #7 — header export.** The AST-based exporter
(`emitter.get_header_output()`, driven by top-level `export shape`/
`export action`/`export`ed globals) already existed and was already
wired into the single-file CLI (`dictumc_cli.py` writes `result["h_code"]`/
`result["hpp_code"]` to disk). It was never wired into
`project_builder.py` — the real multi-file build path every actual
project (including this repo's own `run_pipeline.py`/`dict_triage.py`/
the VS Code extension) goes through. `StdlibTranspiler.run()` was
already computing `result['h_code']`/`result['hpp_code']` for exports;
`build_project()` simply never read either key back out, so a real
project's exports never reached disk — an external C/C++ consumer had
nothing to `#include` against the compiled object, even though
`dictum_types.h` already carried the struct shape (shapes are always
aggregated there regardless of `export`) with no matching function
prototype anywhere.

Reproduced first (a project with `export shape Point`/`export action
add` built with `project_builder.py` produced "0 headers"), then fixed
by writing `result.get('h_code')`/`result.get('hpp_code')` to
`<file>_export.{h,hpp}` alongside the existing per-`module` header
generation (unrelated mechanism, kept separate — that one is for
cross-file `.dict`-to-`.dict` linking, not the `export` keyword).
Verified end-to-end, not just as a string check on the header's
contents: a genuinely separate external C program `#include`s the
generated header and links against the compiled object, producing the
correct runtime value. **R40** covers this through the real
`project_builder.build_project()` entry point.

**Gap #14 — real TLS.** `dictum_tls.h` was a dead stub in two ways at
once: every function body was an explicit `/* not yet implemented */`
placeholder, AND its function names (`dictum_tls_connect`/`dictum_tls_recv`)
didn't match what `STDLIB_ACTION_FAMILIES` actually calls
(`dictum_tls_wrap`/`dictum_tls_handshake`/`dictum_tls_send`/
`dictum_tls_receive`/`dictum_tls_close`) — so filling in the old TODOs
under the old names would still not have closed the gap; nothing in the
registry could ever have reached that file.

Rewrote it against real OpenSSL (`SSL_CTX`/`SSL`, `TLS_client_method()`),
matching the handle-typedef convention `dictum_mutex_handle_t` already
established (`typedef struct dictum_tls_conn *dictum_tls_context_t`).
Link flags (`-lssl -lcrypto`) were already present in `emit_c.py`'s
`_MODULE_LDFLAGS["Tls"]` from earlier defensive plumbing — only the
header implementation itself was missing.

**A real bug was found and fixed while building this:** a doc comment
reading `SSL*/SSL_CTX*` contains a literal `*/`, which silently closed
the file's C block comment early and corrupted everything after it into
compile errors — caught immediately by gcc on the first real compile
attempt, not by re-reading the file.

Verified end-to-end against a real Python `ssl`-wrapped loopback server
with a real self-signed cert (openssl-generated): a genuine TLS
handshake, an encrypted send, and an encrypted receive, confirmed
byte-for-byte (`echo:hello over tls`). **R41** covers this. Stdlib
inventory moved from 79 real / 2 stub / 11 missing to **84 real / 0
stub / 8 missing** (of 92) — the 5-function delta is exactly Tls's own
entry count, confirming the classifier picked up the real
implementation rather than the count changing for an unrelated reason.

**Honestly out of scope for gap #5 (stdlib breadth) in this
environment:** the remaining 8 missing functions are LLM (`load`/
`infer`/`unload`), Robot (`move`/`sensor`/`state`), and Speech (`tts`/
`stt`). These aren't compiler-only gaps the way #7/#14 were — a genuine
implementation needs actual model weights (LLM; `huggingface.co` is not
on this sandbox's network allowlist), real robot hardware or at minimum
a defined wire protocol to simulate against (Robot), and a real
TTS/STT engine (Speech; installable via apt but not attempted this
session — scoped out to stay within what could be built *and* proven
real in the time available, rather than stubbing a "real" implementation
that's actually just a differently-shaped stub).

Version at time of writing: **0.1.51** (package.json still reads
0.1.47 — pre-existing drift from several "Unreleased" CHANGELOG entries
never having bumped it; not a new issue introduced this session).

## 22. Gap #9 partially closed: `growable list of whole number` (C backend only)

Scoped down deliberately from the full gap #9 (map/dict/set + growable
list, both backends) to something buildable and provably real in one
pass: a genuine dynamic array for `whole number` elements, C backend
only. Map, set, dict, and the C++ backend remain entirely unimplemented
-- this is a real partial close, not a disguised full one.

**New surface added:**
- Type: `growable list of whole number` (`type_registry.py`'s
  `WRAPPER_WORDS` gained `growable`; `parser.py`'s `parse_type()` parses
  the form before the existing `list of`/`array of` branch).
- Statement: `add VALUE to NAME` (new `AddToList` AST node; new
  `parser.py` dispatch case; new `validator.py` case that checks the
  target is actually a declared growable list and the value's inferred
  type matches the element type -- confirmed rejecting both a wrong
  element type and a non-list target with real compile errors, not
  silently miscompiling either).
- Runtime: `runtime/dictum_glist.h` -- `dictum_glist_t` (a real value
  struct: `int32_t* data; size_t len; size_t cap;`), with
  `dictum_glist_new/add/get/len/free`. Amortized-doubling growth via
  `realloc`, bounds-checked reads (sets a real runtime error via the
  existing `dictum_error_set`/`DICTUM_HAS_ERROR()` mechanism rather than
  reading past the buffer).
- Emitter wiring: `item N of NAME` and `the count of NAME` both check
  `declared_vars[name] == "dictum_glist_t"` and route to
  `dictum_glist_get`/`dictum_glist_len` instead of raw C-array indexing
  / the fixed-list `_count` convention.

**Three real bugs found by actually compiling and running a test
program (not by review), all fixed:**

1. `dictumc_cli.py`'s `--out` flag names the output *binary*, not the
   `.c` source (the source lands at `<out>.c`) -- a self-inflicted
   confusion during testing, not a compiler bug, but worth noting since
   it produced a genuinely confusing first symptom (reading the
   "generated C" turned out to be reading an ELF binary).
2. **Real bug:** the Program body's `main()`-statement whitelist in
   `emit_c.py` (`isinstance(stmt, (If, While, ForEach, Repeat,
   Assignment, Print, Assert, FuncCall, UnsafeBlock, Attempt, Use))`)
   had no `AddToList` case, so every `add X to NAME` inside a `program`
   block was silently dropped -- zero emitted code, no error, no
   warning. (Action-body statement emission, a separate code path, was
   fine.) Fixed by adding `AddToList` to that tuple.
3. **Real bug:** `dictum_glist_new()` is a function call; C forbids
   function calls as global/file-scope initializers
   (`initializer element is not constant`, caught directly by gcc). A
   `growable list of whole number` declared at `program`-level scope
   went through a separate "PHASE 2: global variables" pre-pass in
   `emit_c.py` that didn't know about growable lists and emitted
   `dictum_glist_t nums = dictum_glist_new();` as a bare global. Fixed
   by giving it the same defer-to-`main()` treatment already used for
   `room_for`/`NewExpr` globals (declare bare, assign in `main()` via
   `_main_inits`).

Also caught (by gcc's own `-Wformat`, not by review): `dictum_glist_len`
returns `size_t`, but Dictum's `%d`-based printing expects `int` for
`whole number` -- fixed with an explicit `(int)` cast at the one call
site this pass added, rather than changing `dictum_glist_len`'s return
type (the same, pre-existing, unrelated `size_t`-vs-`%d` mismatch also
existed for fixed-list `_count` variables -- left open at the time
this was written, closed later in \u00a729).

Verified end-to-end through the real `dictumc_cli.py --compile` CLI
(not the emitter in isolation): three `add` calls followed by `the
count of`/`item N of` reads produce the exactly correct real-run output
`count:3 item0:10 item2:30`. Negative-path checks also verified for
real: `growable list of text` is rejected at compile time (only `whole
number` is implemented), and `add ... to` a plain `whole number`
variable is rejected as a type error. **R42** covers all of this.

**Also fixed in passing:** an inaccuracy in this session's own earlier
Guide A documentation edit -- `the length of X` was incorrectly
described as also working on `list of T`; re-checking `parser.py` while
building this confirmed `length` is `strlen`-only (text), and list
length uses the entirely separate `count` keyword/unary-op. Corrected
in `GUIDE_A_dict_language_reference.md` and re-verified clean against
`verify/guide_a_sync_check.py`.

Regression suite after this gap: **43/43** (R42 added). Stdlib
inventory unaffected by this gap (growable list is core language
surface, not a stdlib module).

Version at time of writing: **0.1.51**.

## 23. Gap #9 extended: `map of K to V`/`set of T` (C++), growable list generalized to C++ (any type)

**Growable list on C++, generalized beyond §22's C-side scoping.** C++'s
`list of T` already mapped to a real `std::vector<T>` before this pass
(pre-existing, correct code) -- so `growable list of T` on the C++
backend is defined as identical to `list of T`: both are `std::vector<T>`
for ANY element type, since std::vector already grows via `push_back`.
Verified with both `whole number` and `text` elements end to end
(`count:2 item0:alice`), unlike the C backend which is `whole number`-only
by design (no generics without a hand-rolled per-type system).

**Two more real, pre-existing bugs found and fixed while wiring this**
(neither introduced by this session -- both were latent in the C++
backend's existing `list of T` support, only surfaced because gap #9
required actually exercising `add`/`count`/indexed-read against it):

1. `the count of NAME` on a `std::vector`-backed list used the same C
   `sizeof(x)/sizeof(x[0])` trick the fixed-size-array path uses --
   meaningless for `std::vector`'s real memory layout (a small fixed
   control-block size, not proportional to element count). Confirmed:
   printed `count:6` for a genuinely empty vector. Fixed by adding a
   `_is_vector_type()` check that routes to `.size()` instead.
2. `item N of NAME` printed with a hardcoded `%d` format regardless of
   the collection's actual element type. Confirmed: indexing into a
   `growable list of text` printed a garbage integer (`item0:1674768414`)
   instead of the real string. Fixed by resolving the collection's
   declared element type in `_format_spec()`'s `IndexAccess` case
   (previously had no case at all) and picking `%s`/`%f`/`%d`
   accordingly.

**New: `map of K to V` / `set of T`, C++ backend only, any type**
(`std::unordered_map<K,V>` / `std::unordered_set<T>` -- real generics,
so unlike growable list's C-side restriction, there is no element-type
scoping needed here at all). New syntax:

- `put VALUE at KEY in NAME` -- map assignment (extends the existing
  `put` statement's dispatch; distinguished from the pre-existing
  `put VALUE into TARGET` form by checking for `at` vs `into` right
  after the value, so neither form regresses the other).
- `the value at KEY in NAME` -- map lookup, via `.at()` (throws on a
  missing key -- a real, visible failure rather than `[]`'s usual
  silent default-insert footgun). Extends the existing `the value ...`
  transparent-wrapper idiom the same way, disambiguated by checking for
  a following `at`.
- `NAME contains VALUE` -- membership check, new infix comparison
  keyword next to the existing `is greater than`/`is equal to`/etc.
  family. Maps to `.find() != .end()` for a map (key check) or
  `.count() > 0` for a set/vector.
- `add VALUE to NAME` (existing statement, gap #9's original growable
  list syntax) now also works on `set of T` -- routes to `.insert()`
  instead of `.push_back()` based on the variable's declared type.

Verified end to end through the real `dictumc_cli.py --compile` CLI:
building a `map of text to whole number`, doing two `put`s, reading one
back via `the value at ... in`, checking `contains` for both a present
and absent key (including the `otherwise` branch), and a
`set of whole number` with a duplicate `add` correctly deduplicating
(`tag count:2` after adding 1, 2, 1) -- all produced exactly correct
output in one real run.

Four negative-path checks also verified for real: a wrong key type on
`put`, `add` to a map (rejected -- `add` is list/set-only), `contains`
on a plain `whole number` variable (rejected), and `map of ...`/`set of
...` rejected entirely on the C backend (validator returns `False` in
non-`cpp_mode` rather than reaching a crash in `emit_c.py`, which has
no map/set implementation at all).

**A self-inflicted bug caught and fixed immediately, worth recording
honestly:** an early `str_replace` while wiring `MapGet`/`Contains`
type inference into `validator.py` accidentally deleted the
`def infer_type(...)` method signature line, silently merging its body
into `check_expression` as unreachable dead code and removing
`infer_type` as a callable method entirely. Caught immediately by
re-running a syntax/import check before proceeding further (`python3 -c
"import ast; ast.parse(...)"` then a real module import), not by
review -- fixed by restoring the correct function boundary.

**Honestly still open for gap #9:** `map of K to V` / `set of T` on the
C backend (would need a real hand-rolled hash table -- a materially
different, larger effort than growable list's realloc-based array,
since a hash table needs real hashing/bucketing/collision handling, not
attempted this session).

Regression suite after this pass: **44/44** (R43 added). Version at
time of writing: **0.1.51**.

## 24. Gap #9 completed: `map of text to whole number` / `set of whole number` on the C backend

Closes the last remaining piece of gap #9. Real open-addressing hash
table implementations, not a growable-list-plus-dedup-check pretending
to be a hash table:

- `runtime/dictum_gset.h` -- `set of whole number`. Real integer hash
  (splitmix32-style finalizer, not `key % cap`, which clusters badly on
  sequential keys). Linear probing with tombstones, real amortized
  resize at load factor 0.7.
- `runtime/dictum_map.h` -- `map of text to whole number`. Real FNV-1a
  string hash (not a placeholder like summing character codes, which
  collides badly on anagrams). Owned keys (`strdup`'d on insert, freed
  on `dictum_map_free`) so the map's lifetime doesn't depend on the
  caller's string outliving it. `.at()`-style `dictum_map_get` sets a
  real runtime error on a missing key rather than silently returning a
  default.

**Scope, same reasoning as growable list on C:** exactly one key/value
pairing (`text` -> `whole number`) and one element type (`whole
number`) -- C has no generics, so this is a hand-rolled, per-type-pair
table, not a generic one. `validator.py` rejects any other combination
(e.g. `map of whole number to whole number`, `set of text`) at
compile time with a clear message, confirmed via two negative-path
tests.

**Wiring:** `type_to_c()` maps both to their real runtime struct types;
`_has_gset_or_map()` gates the two new `#include`s the same way
`_has_growable_list()` already gated `dictum_glist.h`; `AddToList` now
checks the declared C type to route to `dictum_gset_add` vs
`dictum_glist_add`; `MapPut`/`MapGet`/`Contains` all got real C
emission alongside their existing C++ emission from §23. The same
global-scope defer-to-`main()` fix from §22 (a function call is not a
legal C file-scope initializer) was needed again for both
`dictum_gset_new()`/`dictum_map_new()`, and the same Program-body
statement-whitelist bug pattern was pre-empted by adding `MapPut`
alongside `AddToList` in that tuple before it could recur.

**Verified for real, not just compiled:** the same text-keyed-map +
whole-number-set program from §23's C++ test, now run through the C
backend end to end (`alice age:30`, `count:2`, `no carol`, `tag
count:2`, `has 2` — all correct). A stress test adding keys `0..9`
sequentially (the classic pathological case for naive
`key % cap` hashing, since sequential keys would all cluster in the
first few buckets under a bad hash) plus two duplicates, forcing a
real resize past the initial capacity of 8 -- correctly reports
`count:10`, `has 7`, `no 100`. **Both programs also re-compiled and
re-run under a real AddressSanitizer build, clean** -- no
use-after-free, no buffer overflow, no leak reported in either the hash
set's or hash map's resize/probe logic.

**One test-harness bug caught and fixed while building the regression
test** (a harness bug, not a compiler bug -- same class of mistake as
an earlier session's `.c`-vs-binary confusion with `--out`): the
ASan-compile step initially pointed at a guessed source filename
instead of the real `<out-binary-name>.c` path `dictumc_cli.py --out`
actually produces. Caught by the test failing with a real "file not
found" error on first run, fixed by using the correct path.

Regression suite after this pass: **45/45** (R44 added; R43's own
negative-path assertion was also updated, since it had asserted *all*
`map of ...` types would be rejected on C -- true when R43 was written,
made stale by this very gap being extended, updated to check a
key/value combination that's still genuinely unsupported instead).

Version at time of writing: **0.1.51**.

## 25. Gap #9-adjacent: real GUI capability proven, and a real cross-file ABI bug found + fixed (GAP-EXTERN-SHARE)

Set out to confirm that Dictum's existing `import from C` mechanism +
the `blessed/raylib.dict` bridge already supports real GUI programs,
with no new stdlib module needed. Confirmed true, but proving it
surfaced a real, previously-invisible correctness bug.

**The proof:** built real raylib from source (git clone, cmake, static
lib), compiled a real Dictum program (`InitWindow`/`ClearBackground`/
`DrawRectangle`) through `project_builder.py`, linked against real
raylib, ran headlessly under Xvfb, took a real framebuffer screenshot
via raylib's own `TakeScreenshot()` (sidesteps the documented Xvfb/GLX
root-window-capture gotcha, §2b). Pixel-exact correct.

**The real bug, found by pushing further:** `DrawCircle(x, y, 60.0,
color)` -- a function with a `float` argument mixed with `int`
arguments -- rendered nothing at all when called across a file
boundary (main.dict calling into raylib.dict's declarations).
Screenshot-verified: the circle's expected center pixel was plain
background. Root cause: `project_builder.py`'s cross-file header
sharing (`generate_header()`) only ever ran for files declared with
`module X`. A plain top-level file (exactly what a copied
`blessed/raylib.dict` bridge is) got zero prototype-sharing with
sibling files. Without a real prototype visible, gcc's implicit-
declaration fallback misclassified the float argument's register under
the real x86-64 SysV ABI -- silent corruption, not a crash. Confirmed
the generated Makefile's default `-Werror` would catch this as a hard
build failure on the *intended* path -- reproducing it required
deliberately compiling without `-Werror`, matching how a person
manually iterating easily could.

**Important note on isolating the repro:** a single lone float/double
argument does NOT actually exercise this bug -- it lands in XMM0 via
default argument promotion regardless of prototype visibility. The
real regression test (R47) deliberately mirrors `DrawCircle`'s actual
shape (int, int, float, struct) with a `Combine(whole number,
fractional number) -> whole number` function instead, encoding both
arguments into one distinguishable result so a misclassified argument
produces an unambiguously wrong value, not a subtly-off one.

**The fix:** new `dictum_externs.h`, aggregating every file's real
`extern` declarations project-wide (not just module-declared files),
included (after `dictum_types.h`) by any file with no shapes of its
own. Split into its own header rather than folded into
`dictum_types.h` because the two have different duplication rules in
C -- a shape's `typedef struct {...} Name;` genuinely conflicts if a
file both defines `Name` itself and includes a shared copy, but an
`extern` declaration is always safe to see more than once.

Found and fixed three more real bugs while building this fix, each
caught immediately by a real compile error, not by review:
- `dictum_externs.h` referenced `dictum_text` without defining it
  (missing the same guarded-typedef pattern `dictum_core.h` uses) --
  `unknown type name 'dictum_text'`.
- Missing `#include <stdint.h>` in the new header after splitting it
  out of `dictum_types.h` (which provided it transitively before).
- An include-ordering bug: two separate string-prepend operations put
  `dictum_externs.h` BEFORE `dictum_types.h` (each prepend puts its own
  line first, so the second one ends up ahead) -- but `dictum_externs.h`
  references shape types (`Color`, `Camera3D`, ...) only
  `dictum_types.h` defines. Fixed by combining both into one prepend in
  the correct order.

**Also found, correctly isolated, and left open (separate bug, out of
scope for this fix):** `call ... giving VAR` mis-infers `VAR`'s type
as `whole number` for any imported C function returning `fractional
number`, rather than using the function's real declared return type.
Found while designing the R47 repro; deliberately avoided by using a
`whole number`-returning function for R47 so the test isolates only
the ABI-corruption bug it's meant to prove, not conflate it with this
separate, still-open one.

**Honest, narrower scope remaining:** `dictum_externs.h` deliberately
does NOT `#include dictum_types.h` itself (avoids re-triggering the
duplicate-shape-typedef problem for a file that defines its own
shapes). This means a shape-DEFINING file calling an extern from
ANOTHER file, whose signature references a shape it doesn't itself
define, is not yet covered.

Regression suite after this fix: **R47** added (renumbered from R45 --
see the merge note in \u00a726 below for why).

## 26. Merge note: this fix was developed in a parallel session and reconciled here

This fix (\u00a725 above) was built and verified in a separate continuation
of this project that branched before the raygui/LSP work below (\u00a727)
landed. When the two were reconciled, `project_builder.py` was a clean
merge (the raygui/LSP work never touched that file), but the
regression-suite numbering collided -- both sessions independently used
"R45" for a real, different test. Resolved by renumbering the
extern-sharing test to **R47** (after the raygui/LSP work's real R45
and R46) rather than overwriting either. Full suite re-verified after
merging: **48/48**, and the actual `DrawCircle` visual reproduction
re-run end-to-end against the fully merged codebase -- pixel-exact
correct (`(0, 255, 0)` center, `(30, 30, 200)` background), confirming
the merge didn't just pass tests in isolation but the real, original
motivating bug is genuinely fixed in the combined codebase.

## 27. Real GUI widget support: raygui bindings (verified present and functional, not authored this pass)

The following was found already present and was independently
verified (not just read) while doing the \u00a725/\u00a726 merge above --
recorded here since it wasn't previously written into this file:

- `blessed/raygui.dict` -- real bindings (`GuiEnable`, `GuiWindowBox`,
  and ~40 others), matching real raygui API names.
- `blessed/raygui_wrappers.c` -- addresses a real, non-obvious FFI gap:
  Dictum has no address-of operator, so raygui's `int*`/`bool*`
  out-param widgets (checkboxes, sliders, spinners) need a wrapper that
  takes the value in, calls the real widget function with `&local`,
  and returns the updated value -- a sound, immediate-mode-compatible
  design.
- `blessed/thirdparty/raygui.h` -- a real, genuine vendored raygui
  header (6460 lines), not fabricated.
- `dictumc/emit_c.py`'s `use Raylib`/`use Raygui` fix -- stops
  auto-`#include`ing the real system header when it would conflict
  with a program's own locally-declared shape of the same name (e.g. a
  program-defined `shape Color`) -- a real, pre-existing bug
  independent of raygui specifically. Regression: **R46**.
- `scripts/generate_import_c.py`'s ENUM canonical-type fix -- under
  raygui's own documented `RAYGUI_STANDALONE` build define, `bool` is
  `typedef enum { false, true } bool`, an ENUM, not C99 `_Bool`. A
  `bool *active` out-param (e.g. `GuiToggle`, `GuiCheckBox`) was being
  silently classified as directly bindable via an opaque pointer --
  which isn't actually callable from Dictum (no address-of a local) --
  instead of correctly being flagged as needing a wrapper. Regression:
  **R45**.
- `compiler/lsp/dictum_lsp.py` -- a real language server, independently
  functionally tested here (not just read): fed it `keep x as banana
  with value 5`, got back a real diagnostic (`"Unknown type 'banana'"`
  at the correct line) sourced from the actual `validator.py`, not a
  reimplementation. Imports the real `dictumc` package
  (`Lexer`/`Parser`/`Validator`/`DictumGrammar`) directly. Completion
  pulls from `DictumGrammar.KEYWORDS`, the parser's own real reserved-
  word list -- the same anti-drift principle `verify/guide_a_sync_check.py`
  already established elsewhere in this project.
- `compiler/lsp/dictumLanguageClient.ts` -- present but honestly
  self-documented as not yet wired into `package.json`, consistent with
  this project's own earlier-recorded finding (`NOTES_EXTENSION_STATUS.md`)
  that `src/extension.ts`/`out/extension.js` (the actual VS Code
  extension host) are not present in this repo at all. The LSP server
  itself is real and independently runnable; the VS Code integration
  step is not done.

Version at time of writing: **0.1.51**.

## 28. Fixed: `call FUNC giving VAR` type inference for imported functions (the bug flagged, left open, in §25)

Closes the separate, real bug found while building §25/§26/§27's
GAP-EXTERN-SHARE fix and deliberately left open at the time: `call
Halve with 7.0 giving result` (where `Halve` is declared via `import
from C`/`import from C++` to return `fractional number`) emitted
`int32_t result = Halve(7.0);` -- silently truncating `3.5` to `3`.

**Root cause:** `action_return_types` -- the registry
`_infer_type_from_expr`'s `FuncCall` branch reads to type an
auto-declared `call FUNC giving VAR` target -- was only ever populated
for native Dictum `action` declarations. An `import from C`/`import
from C++` function's real declared return type was never recorded, so
inference fell through to `None`, and the caller's own fallback
(`... or "int32_t"`) silently produced a wrong, truncating type for
anything actually returning `fractional number` (or `text`, or
anything else non-`whole number`).

**On the C++ backend specifically, this was a broader gap than on C:**
`action_return_types` didn't exist on `CppEmitter` at all -- meaning
`_infer_type_from_expr` had no `FuncCall` case whatsoever, so EVERY
`call ... giving` (not just imports -- native actions too) silently
defaulted to `int32_t` unless the value already matched one of the
other inference cases (`Literal`/`Identifier`/`BinaryOp`/`NewExpr`).

**The fix, both backends:**
- Register the real declared return type in `action_return_types`
  wherever a callable is declared: the existing `Action` branch (now
  also on C++, which didn't do this before), and the `ImportC`/
  `ImportCpp` branches (new on both backends).
- **Cross-file case** (the harder one -- a function declared in one
  `.dict` file, called from another): each file compiles through its
  own fresh `StdlibTranspiler`/`CEmitter`/`CppEmitter` instance, so a
  registration made while processing file A never survives into file
  B's instance -- the same cross-file-isolation problem \u00a725's
  `dictum_externs.h` fix already solved for extern prototypes. Solved
  the same way: `project_builder.py`'s existing pre-pass (which already
  builds `project_shapes`/`project_actions` project-wide registries)
  now also scans every file's real parsed AST for
  `Action`/`ImportC`/`ImportCpp` nodes into a new
  `project_import_return_types` dict, threaded into each file's real
  emission via a new `extra_import_return_types` parameter on
  `StdlibTranspiler.run()` -- mirroring the existing
  `extra_shapes`/`extra_actions` pattern exactly. Seeded into the
  emitter's `action_return_types` BEFORE that file's own nodes are
  emitted, so the file's own declarations (registered live during
  emission) still correctly take precedence over anything seeded from
  elsewhere for the same name.

Verified for real, not just as a generated-source string check:
same-file case, cross-file case (compiled, linked against a real
external `Halve` implementation, and run -- `half:3.500000`, not
truncated), and the C++ backend (compiled and run once linkage was
matched correctly -- see the honest note below). Full regression suite
re-confirmed clean after this fix: **49/49**. New regression: **R48**.

**One more real, separate, pre-existing bug found while verifying the
C++ case, deliberately left open (out of scope for this fix, same
discipline as \u00a725 leaving THIS bug open at the time):** the C++
backend's `ImportC` handler emits `extern <ret> <name>(<params>);`
without `extern "C"` linkage. Since C++ compiles that declaration with
C++ name-mangling rules by default, linking against a real C library
(mangled-name mismatch) fails -- confirmed with a real `g++` link
error, `undefined reference to 'Halve(double)'`, when the external
implementation was compiled with correct C linkage. This was unrelated
to \u00a728's fix specifically (the line that needed fixing wasn't touched
by it) and affects any C++-backend program doing `import from C`
against a real external C object -- flagged honestly at the time,
closed in \u00a729 below.

Version at time of writing: **0.1.51**.

## 29. All remaining flagged-but-open bugs closed

Closes every concrete, previously-flagged-but-unfixed bug found across
this project's own history (not counting large unimplemented-feature
gaps like #5/#6/#10/#11/#12+13, which are scoped-out future work, not
bugs in existing functionality):

1. **Fixed-list `_count` size_t/%d mismatch** (flagged, not fixed, in
   §22): the same `(int)` cast pattern already applied to
   `dictum_glist_len`/`dictum_gset_len`/`dictum_map_len` is now also
   applied at the point `the count of NAME` reads a fixed list's
   `_count` variable. Verified for real: `keep nums as list of whole
   number with values 1, 2, 3, 4, 5` -> `the count of nums` now
   compiles to `(int)nums_count` and runs to `count:5`.

2. **C++ backend missing `extern "C"` linkage** (flagged, not fixed, in
   §28): `import from C`'s extern declaration on the C++ backend now
   correctly wraps the real symbol in `extern "C"`, so it isn't
   C++-mangled the way the declaration itself would otherwise be
   compiled -- while the real external object (genuine C, or C++ with
   its own `extern "C"`) exports the plain, unmangled name. Verified
   for real: compiled, linked against a genuinely `extern "C"`-compiled
   implementation, and ran -- `half:3.500000`, where the link
   previously failed outright with `undefined reference to
   'Halve(double)'`.

Both covered by **R49**, verified end-to-end (not just as generated-
source string checks): real compiles, real links against real external
implementations, real correct numeric output. Full regression suite:
**50/50**.

**One item deliberately NOT touched, and why:** the narrower scope
noted in §25 -- a file that defines its own shapes calling an extern
from another file whose signature references a shape it doesn't
itself define -- remains unaddressed. This is a documented design
boundary, not a bug: no real test, repro, or working program in this
project's history has ever actually hit it (unlike the three items
above, each of which had a concrete failing repro before its fix). The
smallest correct fix would require per-shape include-guards threaded
through both `project_builder.py`'s header generation AND every
per-file shape-typedef emission site in `emit_c.py` -- a broader,
riskier change than any of today's fixes for a case that has not yet
caused an actual failure. Left flagged rather than "fixed" by a
refactor wide enough to risk the 50/50 suite this session worked hard
to earn.

Version at time of writing: **0.1.51**.

## 30. Nim backend (`--backend nim`) made real, and the Nim compiler auto-provisions itself (closes v5.1's "install Nim yourself" gap)

**Starting state, discovered by actually compiling with a real `nim c`
for the first time (not just checking that source came out):** the
v5.1 README's own test table claimed "✅ Transpile" for the Nim backend
across every sample program, which was true and also misleading --
"transpiles" only means `emit_nim.py` produced *some* Nim text.
Nothing in this project had ever fed that text to a real Nim compiler
before this pass. It didn't compile. Not once. Confirmed with Nim
1.6.14 (apt) on a clean `hello world`:

```
program hello:
    print the text "Hello, Dictum!"
end program
```//emits `echo 'Hello, Dictum!'` -- a Nim **character literal**
(single quotes), a hard compile error for anything but exactly one
codepoint.

**Eight real bugs found and fixed in `emit_nim.py`, each with a
minimal failing repro before the fix and a real `nim c` compile +
run confirming the fix after, plus a permanent regression test
(R50-R57 in `run_selftest.py`, following the same pattern as every
fix above):**

- **R50 — string literals.** `expr_to_nim()` rendered Python strings
  via `repr()`, which emits single-quoted output. Nim's single quotes
  are a character literal, not a string. Added `_nim_string_literal()`
  (proper double-quoting + `\n`/`\t`/`\r`/`\\`/`\"`/control-char
  escaping) and used it everywhere a string literal is emitted
  (scalars and list-literal elements).
- **R51 — mixed-type `print`.** `print the text "x:" and n` (n a
  number) emitted `echo "x:" & n`, and Nim's `&` only concatenates
  strings -- real type-mismatch error. Every non-string-literal part
  is now wrapped in Nim's `$` stringify operator before concatenation;
  `$` on an already-string value is the identity, so this is safe
  without needing full static type inference at this call site.
- **R52 — `repeat N times using i` loop-variable typing.** Every
  `whole number` in a Dictum program is emitted as Nim's `int32`, but
  `for i in 0 ..< N:` lets Nim infer `i`'s type from the untyped range
  literal, which defaults to Nim's native (64-bit) `int`. Any later
  arithmetic mixing that `i` with a real `int32` variable (e.g.
  `result * i` inside the loop) failed with a type mismatch. The range
  is now anchored explicitly: `for i in 0'i32 ..< int32(N):`.
- **R53 — modulo.** The parser normalizes `X modulo Y` down to
  `BinaryOp(op='%', ...)` before any backend sees it (`parser.py`).
  C/C++ pass `%` straight through (it's valid there), so this was
  invisible on those backends -- but Nim has no `%` operator on
  integers (reserved for strings/bitsets), so `_BIN_OP_MAP` needed an
  explicit `"%": "mod"` entry the same way `"divided by": "div"`
  already existed for the sibling operator.
- **R54 — `the count of X`.** `"the count of X"` parses to
  `UnaryOp(op='count', operand=X)` (see `parser.py`'s `_one` helper),
  never a `FuncCall`. The Nim emitter's special-case for `count`
  checked `isinstance(node, FuncCall)` -- a type that node is never
  actually is -- so it silently fell through to the generic prefix-op
  path and emitted the mangled `(countnums)` instead of `len(nums)`.
  Moved the special-case into the real `UnaryOp` branch (covers
  `length` the same way); kept the old `FuncCall` check as a defensive
  no-op in case some other path ever constructs one directly.
- **R55 — `Table[K, V]`/`HashSet[T]` default values.** `_zero_value()`
  built the default-value expression by slicing the type string with
  `nim_type[6:]`/`nim_type[8:]` and re-appending `"]()"`, but
  `type_to_nim()` already returns the type with its own closing
  bracket (`"Table[string, int32]"`), so the result was
  `initTable[string, int32]]()` -- an extra `]`, a real syntax error.
  Now just prepends `"init"` to the already-complete type string.
- **R56 — `add to X` on a set.** `AddToList` always emitted
  `X.add(val)`, but Nim's `HashSet[T]` has no `.add()` -- set insertion
  is `.incl()`. `add to X` is the same Dictum statement for both
  growable lists and sets, so the emitter now branches on `X`'s
  declared Nim type (tracked in `self.declared_vars`, populated at
  `VarDecl` time) to pick `.incl()` vs `.add()`.
- **R57 — missing `std/tables`/`std/sets` imports.** The one and only
  import-emission pass runs once, at the top of `Program`, and only
  ever looks at explicit `use` statements -- but `Table[]`/`HashSet[]`
  types are discovered later, while emitting each `VarDecl`'s body via
  `type_to_nim()`. A program using `map of ... to ...`/`set of ...`
  with no matching `use` compiled against undeclared `Table`/`HashSet`
  identifiers. `get_output()` now does a final textual pass over the
  fully emitted source, adding `import std/tables`/`import std/sets`
  right after any existing import block if those types appear and the
  import isn't already present.

**Verified for real** (not generated-source string checks): `hello`,
recursive `fibonacci`, `factorial` (0-indexed-loop-aware), `sum_list`,
`primes`, a basic `shapes` (struct-style, field-only -- methods remain
C++-backend-only per §11a of the language reference), and a combined
growable-list + map + set program -- all compiled with a real `nim c`
and ran to the correct output. Regression suite: **8 new tests
(R50-R57)**, all passing against a real Nim compiler.

**A second, separate gap this closes: the Nim compiler no longer has
to be manually installed.** New module `dictumc/nim_bootstrap.py`
resolves a working `nim` in order: (1) a previously-vendored copy
under `compiler/vendor/nim/<platform>/`, (2) `nim` already on PATH (so
an existing apt/choosenim/homebrew install is respected, never
duplicated), (3) auto-download the official prebuilt release for the
current OS/arch from `nim-lang.org/download/nim-{VERSION}-...` into
the vendor dir, verified by actually running `nim --version` on the
result before trusting it. `dictumc_cli.py`'s `_compile_nim()` now
calls this instead of shelling out to a bare `"nim"`, so
`--backend nim --run` provisions its own compiler on first use with no
separate `apt install nim` step. Added `--install-nim` (pre-warm
without compiling anything) and `download_nim.sh`/`download_nim.bat`
wrapper scripts.

**Honest verification gap, flagged rather than silently claimed:** the
PATH-detection fast path is real-tested (found a real apt-installed
Nim 1.6.14 correctly, skipped the network entirely). The download URL
pattern (`nim-lang.org/download/nim-2.2.10-linux_x64.tar.xz` for
Linux; `nim-{V}_x64.zip`, MinGW-bundled, for Windows) is confirmed
correct against Nim's real, documented release layout and the current
stable version (2.2.10, released 2026-04-24) -- but the actual
download+extract path has **not** been run end-to-end from an
environment that can reach nim-lang.org (this session's sandbox
network allowlist doesn't include it). macOS has no official prebuilt
Nim binary; the bootstrap falls back to `brew install nim` if
Homebrew is present, otherwise raises a clear, actionable error rather
than guessing a path -- also unverified live in this session, no macOS
machine available.

**One more real, separate, pre-existing bug found incidentally while
regression-testing this fix, deliberately NOT touched (out of scope --
this section is about the Nim backend):** the C/C++ backends' plain
`dictumc_cli.py FILE.dict --backend c --compile` path (as opposed to
the multi-file `project_builder.py` path) produces an `undefined
reference to 'dictum_main'` link error and/or a missing
`dictum_glist.h` compile error on stdlib-using or growable-list
programs in this session's environment -- reproduced identically both
before and after every Nim-related change in this section, so it is
provably unrelated to any of R50-R57. This looks like the raw CLI's
`_compile_c`/`_compile_cpp` never adding a `-I runtime` include path or
linking the runtime `.c` sources the way `project_builder.py` does for
multi-file builds, but that's a hypothesis, not a confirmed root
cause -- flagged honestly, same discipline as every other "found but
not yet fixed" item in this document, rather than either hiding it or
scope-creeping into fixing it here.

### 30a. Real end-to-end FFI verification, and a bigger gap it surfaced: no backend ever linked an external library

Asked directly "what can I actually build with the Nim backend's
`import from C`, since it needs no bindings" -- answering that for
real (not from the language reference's description of the feature)
required proving a `.dict` program could call into a *real* system
library, not just transpile a plausible-looking FFI declaration.
Picked `blessed/sqlite3.dict`'s `sqlite3_libversion`/
`sqlite3_threadsafe` (zero pointer-arithmetic complexity, so any
failure would be about the FFI/link mechanism itself, not incidental
program logic) and pushed it all the way to a real `nim c` compile,
real link against the system's real `-lsqlite3`, and a real run.

**It didn't work on the first, second, or third try, and each failure
was real:**

- **No mechanism existed, on any backend, to link an external
  library.** `dictumc_cli.py --compile`/`--run` built its gcc/g++/nim
  command lines with a hardcoded `-lm` and nothing else -- there was
  no CLI flag, no `.dict`-source directive respected by the standard
  (non-polyglot) pipeline, nothing. (`#[link "..."]` *parses* via
  `polyglot_parser.py`, but that's a separate, secondary pipeline the
  main `--backend c/cpp/nim` path never invokes.) So even a
  syntactically perfect `import from C` bridge to sqlite3/raylib/sdl2/
  openssl could transpile clean and still fail to link, on every
  backend, always -- this was never Nim-specific. Fixed with a new
  `--link LIBNAME` CLI flag (repeatable: `--link sqlite3 --link m`),
  threaded into `_compile_c`/`_compile_cpp` (`-lLIBNAME`) and
  `_compile_nim` (`--passL:-lLIBNAME`).
- **R-NIM-9 — fabricated header filename.** `emit_nim.py`'s `ImportC`
  handling built `header = f"{action_name}.h"` (e.g.
  `"sqlite3_libversion.h"`) and told Nim's `{.importc, header: ...}.}`
  pragma to `#include` it. That file has never existed -- a real
  `fatal error: sqlite3_libversion.h: No such file or directory` from
  the underlying gcc pass Nim shells out to. The `ImportC` AST node
  never carried a real header name to begin with (`parser.py`'s
  `parse_import_c` doesn't parse one -- confirmed by reading it, not
  assumed). Fixed by dropping the header pragma entirely and adding
  `cdecl`: `{.importc: "real_symbol", cdecl.}` with no header, which
  makes Nim self-declare a matching `extern` C prototype instead of
  including a nonexistent one -- exactly what the C backend has always
  done for the same construct (see `ImportC` in `emit_c.py`: a plain
  forward declaration, no header, linker resolves the real symbol).
- **R-NIM-10 — `text` in an FFI signature must be `cstring`, not
  `string`.** With R-NIM-9 fixed, it compiled *and linked* -- and
  segfaulted on the very first call
  (`SIGSEGV: Illegal storage access`, `gc.nim:286 asgnRef` in the
  traceback). `type_to_nim()` maps Dictum's `text` to Nim's `string`
  everywhere, which is correct for native Dictum values (Nim-GC-
  managed) but wrong for an `import from C` signature: a real C
  function returning `const char*` returns a raw pointer, and Nim's
  GC tried to read a managed-string header out of memory that was
  never one. Added `type_to_nim_ffi()` -- identical to `type_to_nim()`
  except `text` -> `cstring` -- used only for `ImportC`/`ImportCpp`
  parameter and return types, never for ordinary Dictum variables.
- **R-NIM-11 — `cstring` -> `string` needs an explicit `$` at the
  assignment site.** With R-NIM-10 fixed, the *proc* was correct but
  `call sqlite3_libversion giving ver` (`ver` declared `text`, i.e.
  Nim `string`) still failed: `type mismatch: got 'cstring' ... but
  expected 'string'` -- Nim does not implicitly widen `cstring` to
  `string` at a plain assignment. Added a small registry
  (`self.ffi_string_returns`, populated by name+alias whenever an
  `ImportC`/`ImportCpp` declares `produces text`) that the `Assignment`
  emission checks: if the RHS is a call to a known `text`-returning FFI
  function and the target is declared `string`, wrap the value in
  `$(...)` (Nim's real, correct conversion).

**Real, live, verified result** (regression R58): the compiled binary
printed the actual installed system SQLite's real version string
(`3.45.1`, cross-checked against `dpkg -s libsqlite3-0` in this
session) and real threadsafe flag -- not a mocked or hand-typed
expected value.

**What this proves is buildable today, and what's honestly still
open:** scalar/pointer-threading FFI (numbers, bools, `opaque pointer`
handles passed straight through from one call's return into the next
call's argument, `text` in either direction) now genuinely works
end-to-end against a real linked system library, on the Nim backend,
via `--link`. What it does **not** yet cover, discovered while trying
to push further into `sqlite3_open`/`sqlite3_exec` for a real
open-query-close round trip: `sqlite3_open`'s `sqlite3 **` out-param
needs the *address of* a local `opaque pointer` variable, and Dictum
has no "address of"/by-reference mechanism anywhere in the parser at
all (`grep`-confirmed empty) -- not a Nim gap, a language-wide one.
Flagged rather than worked around; a workaround here would be exactly
the kind of incremental, half-verified scope creep this document
exists to prevent. `sqlite3_exec`'s callback-based query path has the
same open question for a different reason (C function pointers into
Dictum-side code) and also wasn't attempted this session.

Version at time of writing: **0.1.51**.

