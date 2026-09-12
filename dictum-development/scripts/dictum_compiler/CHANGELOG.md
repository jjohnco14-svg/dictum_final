# Changelog

## Unreleased — `phrased as`: dictations for foreign functions; blessed libraries 6 → 10; three emitter-drift extractions

**`phrased as` — a dictation attached to an FFI binding.** Dictum's premise
is that code reads like language, but anything reached through FFI was
excluded from it: `call llama_eval with ctx and tokens giving r`. A binding
can now carry its own sentence:

```
import from C++ the action llama_eval takes opaque pointer and opaque pointer
    produces whole number as llama_eval
    phrased as "evaluate {} on {}"
```

and every call site downstream reads `evaluate ctx on tokens giving r`.
Works on `import from C` and `import from C++`. It lowers to an ordinary
call, so it is backend-agnostic *by construction* and required no emitter
changes — deliberately, so the feature cannot become a fourth drift surface.
Verified identical on c/cpp/nim. Two guards, because a wrong phrase fails
silently rather than loudly: placeholder count must equal the action's
arity, and a phrase must begin with a literal word. R97.

**Blessed libraries 6 → 10**: added `uuid`, `expat`, `pcre2`, `libm`, each
verified by real compile+link+run on all three backends and recorded in the
registry with provenance.

**Three shared-semantics extractions against emitter drift** — the systemic
cause of nearly every silent-wrong-answer bug in this project:

- printf conversion (R94). emit_c and emit_cpp were only ~35% textually
  similar here yet contained the *same* bug — a known integer falling
  through to a heuristic that guessed from the variable NAME, so
  `keep price as whole number` printed `price=0.000000`. Textual similarity
  does not predict drift; semantic duplication does.
- expression type inference (R95). Identical inference, different spelling
  only. Breaking the shared rule did **not** fail the then-95-test suite —
  no test exercised a comparison whose inferred type mattered — so R95 now
  compares the two emitters directly on the same AST.
- call-name resolution (R96). **Found a live bug**: emit_cpp was missing
  both the reserved-name sanitize (so `action sqrt` compiled on c and nim
  and *failed* on cpp) and the R18 FFI-alias guard. Those two rules pull in
  opposite directions on the same identifier, which is exactly why one
  implementation beats three.

**`tools/dictum.py`** — one build command. Resolves link flags from the
manifests (scanning shim sources too), compiles and links C shims, orders
nim's `--passL` correctly, and attaches errors to their fix
(`undefined reference to SDL_Init` → "comes from SDL2 — add --link SDL2").
`dictum check` builds on all three backends and compares **output**, which
is the highest-yield bug signal in the project and was previously only an
internal tool.

Suite: 93 → 98 regression, 6/6 behavioral.

## Unreleased — R39: proved the C++ backend's identical Attempt line-mapping fix, closing a same-fix-unverified-on-one-side gap

The Attempt-block #line fix (previous entry) was applied identically to
CppEmitter on a read-the-code basis but only proved with a dedicated
repro+regression test on the C side. R39 does the same for C++: a real
C++-keyword collision (`giving class`) through `dict_triage.py --backend
cpp`, confirmed mapping to the exact real line. Full suite: 40/40
regression, 6/6 behavioral.

## Unreleased — fixed a real, reproduced #line mapping bug in Attempt blocks (both backends)

`_emit_own_line()` added to `CEmitter`/`CppEmitter`: `Attempt` blocks
emit several lines directly from their own handler, and a single #line
directive was auto-incrementing incorrectly for lines after the first —
reproduced with a real repro that landed 2 lines off, on a misleading,
unrelated line. Fixed and re-verified against the exact same repro.
R38 added. Full suite: 39/39 regression, 6/6 behavioral.

## Unreleased — real #line directives + debug_mapper.py (cheap-call error mapping), -Werror on both compile paths

New: `dictumc/line_directives.py`, `dictumc/debug_mapper.py`. Modified:
`emit_c.py`/`emit_cpp.py` (additive #line emission), `transpiler.py` +
`project_builder.py` (thread real .dict filename through, 3 call sites
fixed), `dict_triage.py` (Case C now uses debug_mapper; -Werror added).
R37 added. See SOURCE_OF_TRUTH.md §16 for full detail, including an
honestly-documented, NOT-yet-fixed limitation in `Attempt`-block line
mapping (real, found by reading the emission code, not swept under the
rug). Full suite: 38/38 regression, 6/6 behavioral.

## Unreleased — freelance-deliverable checklist: static linking + real ldd verification, client package assembler with a hard .dict guard, reproducibility/provenance check

New: `project_builder.py --static`, `verify/verify_static_link.py`,
`verify/package_for_client.py`, `verify/reproducibility_check.py`. See
SOURCE_OF_TRUTH.md §15 for full detail, including what's honestly still
missing (an autonomous generate-and-fix loop -- this pass only makes
verification cheaper and more complete, not generation autonomous).
R34-R36 added. Full suite: 37/37 regression, 6/6 behavioral.

## Unreleased — pipeline hardening pass: items #2-6 (Case D registry, Guide A/parser drift check, incremental caching, deterministic/visual split + shared project selftest lib, unified run_pipeline.py)

See SOURCE_OF_TRUTH.md §14 for full detail on all five. Highlights: a
real bug found and fixed in `run_pipeline.py` while wiring Guide B into
Guide C (Guide B's ephemeral build dir was being deleted before Guide C
could use the binary — fixed by exposing `bin_path` and repointing the
manifest). Full suite: 34/34 regression, 6/6 behavioral.

## Unreleased — guide_c_verify.py: automated Guide C orchestration, + R23 SKIP/FAIL fix

New tool (`compiler/verify/guide_c_verify.py`, also reachable as
`run_selftest.py --verify-target`) that runs an entire Guide C session
— console-class diffs, Xvfb+screenshot GUI capture, and every
project-specific script listed in a project's `guide_c_manifest.json`
(Guide A §0 Phase 2) — in one call instead of ~10-15 hand-driven bash
commands per session. See SOURCE_OF_TRUTH.md §13 for full detail,
including two real bugs found and fixed while building it (a missing
`DISPLAY` env var on the screenshot subprocess call, and an unhandled
crash on a missing target binary — both verified fixed via a real
re-run, not just a code diff).

Also: `run_selftest.py`'s R23 no longer hard-`FAIL`s when `libclang`
isn't `pip install`ed on this machine — that's an environment gap, not
a code bug, so it now reports a distinct `SKIP` with the exact install
command, and doesn't count against the pass/fail total. Real code bugs
and unmet environment dependencies are different findings and now read
as different findings.

## Unreleased — dict_triage.py: automated Guide B triage for the CLI/batch pipeline, + project_builder.py backend-override fix

New tool (`compiler/dict_triage.py`, also reachable as `run_selftest.py
--triage`) that automates Guide B's §1/§1a/§2 mechanical steps for a
single `.dict` file or a project directory: parse+validate in-process
(Case A, exact line from the real parser/validator), real gcc/g++
compile with failures mapped back to the actual `.dict` line (Case C),
`LIBRARIES` vs. `blessed/` check (Case D), and run+diff against an
`--expected-output`. `--emit-regression-stub` appends a templated `Rn`
test to `run_selftest.py`.

This is the CLI-side counterpart to the earlier Gap #2 fix (see
SOURCE_OF_TRUTH.md §11), which closed the same C-line → Dictum-line
mapping problem only inside the VS Code extension
(`out/transpiler.js`). The underlying `@dictum-line:N` marker mechanism
(`emit_c.py`/`emit_cpp.py`) was already shared by both; only the
consumer logic was extension-only until now. See SOURCE_OF_TRUTH.md §12
for full detail.

**Bug found and fixed while building this — R24:**
`project_builder.py`'s `load_or_create_manifest()` hardcoded
`'backend': 'c'` / `'cpp_standard': 17` into its auto-discover default
for any workspace without a pre-existing `dictum.project.json`, so
`build_project()` always found those values before falling through to
the caller's actual `backend`/`cpp_standard` arguments —
`project_builder.py <dir> --backend cpp` silently built C instead of
C++ on any fresh project directory, with no error or warning. Root
cause: those two keys don't belong in the "nothing on disk yet"
default, since they're exactly what callers pass explicit overrides
for. Fixed by omitting them from that default; an existing on-disk
`dictum.project.json` still wins unchanged. Verified end-to-end (real
`--backend cpp` CLI invocation on a fresh dir → asserts `.cpp`, not
`.c`, was written, the resolved backend persisted correctly, and the
emitted C++ genuinely compiles+links+runs with g++). Full regression
suite re-run and confirmed passing (24/25 — the one pre-existing
failure is an unrelated `pip install libclang` environment gap, not a
code issue). Added as **R24**.

## Unreleased — dict_syntax_check.py: standalone syntax-only validator for Guide A

New single-file tool (`dict_syntax_check.py`, repo root) for the
two-AI vibecoding workflow: the AI writing `.dict` source (Guide A) can
now check its own output locally, without gcc and without codebase
access to the rest of the compiler.

**Built by reusing the real `lexer.py` + `ast_nodes.py` +
`type_registry.py` + `parser.py` verbatim**, concatenated into one
file with only the package-relative import lines stripped — not a
fresh reimplementation of the grammar. This was a deliberate choice:
a hand-written second parser would be a second source of truth that
can silently drift from what the real compiler actually accepts,
which is exactly the class of bug this project has already been bit
by more than once (the `match_word` OR-vs-AND bug, the colon-mismatch
bug in `project_builder.py`'s separate lightweight scanner). Reusing
the real parsing code means this tool cannot disagree with
`dictumc_cli.py` about what's valid syntax, by construction.

Verified: correctly passes genuinely valid `.dict` source (including
multi-file projects, shapes, lists, XOR) and correctly rejects real,
previously-seen mistakes (`print result` without `the text`, `put X
in Y` instead of `into`) with the same error the real parser would
give. Also confirmed it correctly does **not** flag `keep x as number`
(bare `number` instead of `whole number`) as an error — that's a
semantic/type-registry check the real parser also defers to a later
validator stage, not a grammar-level rejection, so the standalone
tool's scope matches the real parser's scope exactly, including its
limitations. Cross-checked against the real CLI in the same test to
confirm agreement, not just independent pass/fail. Added as **R10**.

Explicitly out of scope, documented in the tool's own header comment:
C/C++ emission correctness, compile/link success, runtime behavior,
cross-file `use` resolution, and semantic/type checks — those still
need the full compiler + gcc (Guide B's job).

## Unreleased — emit_cpp.py list-of-T fix (closes the C++ half of the earlier list-parameter gap)

Follow-up to the previous session's `list of T` action-parameter fix,
which was scoped to `emit_c.py` only. Verified independently against
the C++ backend (not assumed fixed) and found it was not just
unfixed but actively worse for this construct than before.

### Root cause 1: `type_to_cpp()` only matched the suffix type spelling

Dictum source uses the prefix spelling everywhere (`list of T`/`array
of T` — see `parser.py`'s `parse_type`). `type_to_cpp()` only handled
the suffix spelling (`T list`/`T array`), which nothing in the actual
grammar produces. A prefix-spelled list type fell through to the
generic identifier fallback, producing a syntactically invalid,
non-existent type name like `list_of_whole_number` instead of
`std::vector<T>`. This is the same class of bug as the already-fixed
"MISSING-01" issue in `emit_c.py`'s `type_to_c()`, never ported to
this file. Fixed by matching the prefix form the same way.

### Root cause 2: list-literal elements stringified with bare `str()`

Once root cause 1 was fixed and this code path became reachable,
`VarDecl`'s list-literal-initializer branch called plain `str(v)` on
each element. This is correct for a raw Python primitive but produces
the Python `repr()` of the underlying AST node when elements arrive as
nested `Literal` objects instead — this was the exact mechanism behind
the `Literal(line=10, value=1)` text observed leaking into generated
C++ source. Fixed to mirror `emit_c.py`'s existing correct dual-path
handling (`expr_to_cpp(v)` for non-primitive elements).

### Design choice: `std::vector<T>` uniformly, not a ported `(T*, size_t)` pair

The C fix threads a manual `T*`/`size_t` pair through parameters and
call sites because C has no real container type. C++ does — once
`type_to_cpp()` correctly maps `list of T` to `std::vector<T>`,
existing generic code (action parameter emission, `for (auto& x :
collection)`, `operator[]` indexing, call-site argument passing) all
handles it correctly with **no further special-casing needed**,
because none of those call sites were ever C-specific to begin with.
This is simpler and more idiomatic than mirroring C's approach, and
required no changes outside `type_to_cpp()` and the `VarDecl`
list-literal branch.

Verified: the same round-trip test as the C fix (local list → action
parameter → `for each` → returned sum), now on `--backend cpp` —
compiled (including through the real two-phase gcc/g++ gate), linked,
run, output checked (`sum:15` / `sum:25` depending on test data,
matching hand-computed expected values). Confirmed the emitted
signature is a real `std::vector<int32_t>`, and that neither the
bogus type name nor the raw-repr leak reappear. Added as **R9** in
`run_selftest.py`. Full suite: 10/10 regression, 6/6 behavioral, no
regressions from either change.

## Unreleased — XOR operator fix, project_builder.py header-generation bug, hand-authoring guide

Follow-up session, done outside the AI/vibecoding loop entirely — all
changes hand-written and verified against the real pipeline.

### XOR bitwise operator (SOURCE_OF_TRUTH.md gap #12, "not yet started")

`compiler/dictumc/parser.py`'s bitwise-prefix-expression handler had
`and`/`or`/`not` wired but was missing `xor` — a single missing `elif`
branch, not a design gap. Both `emit_c.py` and `emit_cpp.py` emit
`BinaryOp` generically off `node.op`, so no emitter changes were
needed once the parser produced `op='^'`. Also added `'xor'` to
`grammar.py`'s `KEYWORDS` set so grammar-constrained AI generation can
produce it too, not just hand-written source.

Verified: compiled and ran on both backends (`12 XOR 10 == 6`, matches
Python's `^`). Full `run_selftest.py` suite re-run clean after the
change (6/6 behavioral, then 7/7 after R6 below was added).

### project_builder.py: parse_deps() colon-requirement bug (found while manually testing multi-file + XOR together)

`parse_deps()`'s lightweight regex scanner — used only by the
standalone `project_builder.py` CLI path (not the interactive-Build
`compileCheckSmart` path from gap #4, which has its own, correct test
coverage) — required a trailing colon after `module Name`, `program
Name`, and `shape Name holds`. Real Dictum syntax has no such colon
(confirmed against `parser.py`'s actual `parse_module`/`parse_shape`).
Because of this, `fi['modules']` was always empty for real source,
header generation for cross-file `#include`s silently never fired
("0 headers" in build output with no error), and any project with a
real cross-file call failed to link with a missing-header compile
error. Fixed by removing the colon requirement from all three
patterns.

Verified: a real two-file project (a `program` calling into a sibling
`module`'s action, which itself uses the newly-fixed XOR operator) now
builds, generates its header, links, and runs correctly end to end.

### New regression test: R6 (`compiler/run_selftest.py`)

Builds the exact colon-less module/program scenario above through the
real `project_builder.py` CLI, asserts the header file actually gets
written, then links and runs the result and checks the XOR-derived
output. Added to the permanent suite so this can't silently regress.

### New: docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md

A comprehensive, AI-consumable language reference for writing `.dict`
source by hand and compiling it directly (no AI generation loop) —
covers types, variables, control flow, actions, shapes, multi-file
projects, and `import from C`/`import from C++` FFI bindings (with a
real, verified SQLite call linked against the actual system library).
Every construct is explicitly marked [VERIFIED] (actually compiled and
run while writing the guide) or [TRACED] (confirmed by reading the
parser source only) so nothing is presented with more confidence than
it's actually earned.

### parser.py: `match_word()` misused as sequential-AND, actually variadic-OR (found while testing shapes/lists for the hand-authoring guide)

`match_word(*words)` matches if the **current single token** is any one
of the given alternatives — it is not "match this word, then that
word." Two call sites in `parse_keep()` used it as if it were
sequential: `match_word('no', 'value')` for the `with no value` clause,
and `match_word('all', 'values')` for `with all values X`. In both
cases only the first word got consumed, leaving the second dangling as
an unparsed token that then broke the *next* statement's parse with a
confusing, unrelated-looking error. Fixed both call sites to do the
real two-step match (`match_word('no')` then `expect_word('value')`,
same pattern for `all`/`values`). Audited the rest of the file for the
same call shape — no other instances found.

Verified: `keep p as Point with no value` followed by real field
sets/reads now compiles, links, and runs correctly (confirmed field
values round-trip correctly through a real shape). `with all values X`
now compiles without leaving a dangling token. Added as R7 in
`run_selftest.py`.

### Fixed: passing a `list of T` as an action parameter (previously documented as known-but-not-fixed, above)

Root cause: `emit_c.py`'s `type_to_c()` strips the `list of `/`array of `
wrapper down to the bare element type `T` wherever it's called — correct
for a locally-declared list (which gets its own separate `T name[size]`
+ `size_t name_count` pair emitted by the `VarDecl` handler), but wrong
for an action **parameter**, where the stripped type was interpolated
straight into the C signature as a scalar `T name`. That silently
dropped both the pointer-ness and the `_count` companion the callee's
body actually depends on (indexing, `for each x in nums`, `the count of
nums`), producing the previously-documented `nums_count` undeclared
compile error.

Fixed in `compiler/dictumc/emit_c.py`:
- Added `action_param_types`, a registry of each action's raw (unmangled)
  Dictum params, populated for every action up front in
  `_collect_fwd_sig()` (which already runs for all actions before any
  body is emitted) — so a call site can always look up whether the
  callee expects a list argument, regardless of definition order.
- Added `_param_decl_parts()`, which expands any `list of T` / `T list`
  parameter into a real `(T*, size_t)` pair — `T* name, size_t
  name_count` — instead of collapsing it to a bare scalar. Used for the
  forward declaration, the real function definition, and the
  multi-file header-export path, so all three can't drift apart.
- The function-body scope now registers both `name` (as a pointer) and
  `name_count` (as `size_t`) in `declared_vars` for a list parameter, so
  indexing/`for each`/`the count of` inside the callee resolve correctly.
- Call sites (`FuncCall` in `expr_to_c()`) now look up the callee's
  param types and append the matching `name_count` argument whenever a
  list-typed parameter position is reached (currently supports the
  common case of a bare identifier argument; a non-identifier list
  expression surfaces a loud comment instead of silently-wrong C, since
  it has no `_count` companion to reach for).
- Companion fix: `the count of X` previously always used a
  `sizeof(X)/sizeof(X[0])` trick, which is correct for a true local
  array but silently wrong for a list *parameter* (now a pointer) —
  `sizeof(pointer)/sizeof(element)` is not the real count. It now uses
  the real `X_count` variable directly whenever one is tracked (true for
  both list parameters and locally-declared lists), falling back to the
  sizeof trick only when no count variable is tracked at all.

Scoped to the C backend (`emit_c.py`), which is the default/primary
backend. The C++ backend (`emit_cpp.py`) has a separate, pre-existing,
broader bug where `type_to_cpp()` doesn't recognize the `list of T`
prefix form at all (only the `T list` suffix form) — a distinct issue
from the one documented here, not attempted in this pass.

Verified: a locally-declared `list of whole number` passed to a
separate action, which sums it via `for each n in nums repeat` and
returns the result, now compiles clean (including under `-Wall -Wextra
-Werror`), links, and runs, producing the correct sum. Added as **R8**
in `run_selftest.py`, which also asserts the emitted C signature and
call site directly (`int32_t* nums, size_t nums_count` /
`sum_list(values, values_count)`), not just the runtime answer, so a
future regression that happens to get the right number via some other
path is still caught.

`docs/DICT_LANGUAGE_REFERENCE_FOR_AI.md` §12 updated to remove the
"avoid this pattern" warning now that it's fixed.



This release closes four items from the 14-item "production readiness"
gap list (tracked in `SOURCE_OF_TRUTH.md` §11), plus three real bugs
found along the way while verifying them. Everything below was verified
against the real pipeline — real `dictumc_cli.py`, real `gcc`/`g++`, real
linking, real execution — not mocked. **69 checks passing** across the
new/updated regression tests, plus the full pre-existing
`compiler/dictumc/regression_suite.py` (18/18, zero regressions).

### Gap #1 — MEMORY/SAFETY unconstrained on tool-mode providers

Tool-calling (schema-constrained) providers previously had no JSON schema
for MEMORY/SAFETY tier chunks, so those chunks fell back to unconstrained
free-text prompting — defeating the whole point of tool mode for exactly
the highest-risk category of generated code (raw pointers, atomics,
manual memory management).

- `compiler/dictumc/emit_c.py` — added `unsafe_op_names()`: derives the
  full recognized `[TOKEN: ...]` name list (100 names) directly from
  `_emit_unsafe_token`'s own source via `ast`, instead of a hand-copied
  list that could silently drift out of sync (exactly the failure mode
  `SOURCE_OF_TRUTH.md` already warns about for `grammar.py`'s old
  `KEYWORDS` list).
- `out/toolSchema.js` — `SCHEMA_APPLICABLE_TIERS` now includes
  `MEMORY`/`SAFETY`. Added a narrower `unsafe_ops` action-body JSON shape
  (vs. free-text `body_dictum`) for those two tiers, with the op-name
  field enum-described from the real `unsafe_op_names()` list via a
  `python3` subprocess bridge. `jsonChunkToDictum` renders that into real
  `[TOKEN: p1 : p2]` bracket syntax inside a proper `unsafe: ... end
  unsafe` block.
- `out/extension.js` — both `_generateChunkDictumText` call sites now
  thread `tierName` through.

**Verified:** `test_gap1_toolschema.js` (10/10), `test_gap1_pipeline.sh`
(7/7 — real parse → validate → `emit_c.py` → `gcc` → run round-trip,
including a real `RAW_MALLOC`/`RAW_FREE` pair and the real
`__atomic_fetch_add` intrinsic, not a fallback stub).

**Known scope limit:** a MEMORY/SAFETY chunk whose plan text implies an
ordinary if/while/simple-statement *alongside* the unsafe block isn't
representable in this schema yet — that rarer mixed case still falls
back to unconstrained prompting. The common case (one item = one action
= one unsafe block) is fully covered.

### Gap #2 — Compile errors pointed at generated C, not Dictum source

`gcc`/`g++` errors referenced line numbers in the generated `.c`/`.cpp`
file, which neither the user nor the retrying model ever looks at —
making both the compile-gate retry prompt and the human-facing panel
effectively useless for any error the model couldn't already guess.

- `compiler/dictumc/emit_c.py` / `emit_cpp.py` — added `_emit_marked()`
  to both `CEmitter` and `CppEmitter`: emits `/* @dictum-line:N */`
  right before a statement's generated code. Wired into every real
  statement-block loop (action/method/constructor/destructor bodies,
  if/while/foreach/repeat bodies, attempt success/failure bodies, unsafe
  blocks, top-level `main()`).
- `out/transpiler.js` — added `buildDictumLineMap()` (parses the markers
  into a C-line → Dictum-line map) and `translateCompilerOutput()`
  (rewrites `gcc`/`g++`'s `file:LINE:COL: error: ...` header lines to
  reference the Dictum line; message text and source-context lines are
  left byte-for-byte as the compiler produced them). `compileCheck()` now
  returns a `dictumErrors` field alongside the raw `errors`.
- `out/extension.js` — `_runCompileGate` prefers `dictumErrors`, falling
  back to raw `errors` when translation wasn't possible (e.g. an error
  inside a runtime header, not user code).

**Verified:** `test_gap2_linemap.js` (7/7, three of which shell out to
real `dictumc_cli.py` + real `gcc`/`g++`).

**Known scope limit:** only statements inside actual control-flow/
action/method bodies are marked. The `Program` node's top-level phased
passes (global variable declarations, forward-declaration emission) are
deliberately not instrumented — `gcc` essentially never points at those,
and instrumenting that multi-pass-reordering code safely was higher-risk
than the value it would add.

### Bugfix (found while testing gap #2) — sibling `Action` never forward-declared

A top-level `action ... end action` block that's a **sibling** of
`program ... end program` (not nested inside it) was never forward-
declared before use. `gcc` tolerated this via implicit-int-return
declaration (a warning, not a hard error) — silently assuming the wrong
return type for any action that actually returns a pointer/handle or a
`double`. `g++` correctly rejects it outright.

- `compiler/dictumc/emit_c.py`, `emit_cpp.py` — both emitters gained a
  `_file_top_level_actions` attribute, populated once per compile via the
  same pre-scan pattern already used for `_file_has_produce_failure` /
  `_file_has_attempt_nodes`.
- `compiler/dictumc/transpiler.py`, `polyglot_transpiler.py` — wired the
  pre-scan into every driver (`Transpiler.run`, `StdlibTranspiler.run`,
  and the standalone `CppEmitter` instantiation in
  `polyglot_transpiler.py`).

**Verified:** `test_fwd_decl_bug.sh` (7/7 — real emit on both backends,
real `g++ -fsyntax-only`, real compile + run producing the correct
output, and a real `gcc -Werror=implicit-function-declaration` check
that would have caught the old bug on the C backend).

### Gap #3 — `body_dictum` still free text on covered tiers

Even on TYPE/OPERATION/MODIFY tiers (already schema-covered by gap #1's
predecessor work), an action's *body* was still one large free-text
string — giving a tool-calling provider no more real structure than
plain prompting for the part of the chunk most likely to contain a
hallucinated construct.

- `out/toolSchema.js` — added `_statementSchema()`: a flat, fully-
  required, `additionalProperties:false` schema with a `kind` enum over
  `keep/set/if/call/return/while/other`. TYPE/OPERATION/MODIFY tier
  actions now use an array of these (`statements`) instead of one
  `body_dictum` string. One level *deeper* (an `if`'s then/else branch, a
  `while`'s loop body, any expression slot) stays free-text Dictum, per
  the fix's stated scope. Statement kinds outside the six covered ones
  use `kind:'other'` with the statement in `raw_dictum` — the same
  fallback they always had, now living inside a structured list.

Grammar details (verified against `parser.py`, not assumed): `if` uses
`then`/`otherwise` (no `else` keyword); `while` uses `... repeat` / `end
while` (no `then`, no colon); `produce failure` requires the literal word
`text` before its message, `produce success` does not.

**Verified:** `test_gap3_statements.js` (12/12, including a real
end-to-end compile+run of generated text covering all six statement
kinds). MEMORY/SAFETY tiers are unaffected — still gap #1's `unsafe_ops`
shape.

### Bugfix (found while testing gap #4) — validator warnings misclassified as hard errors

`parseStderr()`'s generic `[Line N]` regex (`bareLineMatch`) wasn't
anchored to the start of the line and ran *before* the `dictumc:
warning:` check — so `dictumc: warning: [Line N] <msg>`
(`validator.py`'s real, correct format for every warning it emits) was
misclassified as a hard error. This made `transpile()`/`transpileFile()`
report `success:false` for any program that only had a warning (e.g. the
validator's "Call to unknown action" warning for a symbol resolved via
cross-file import, which the validator doesn't currently follow) even
though the program transpiled and compiled fine. This affected **every**
caller of `parseStderr`, not just multi-file projects.

- `out/transpiler.js` — reordered the checks so the specific `dictumc:
  warning:` prefix (with an optional embedded `[Line N]`, now correctly
  extracted instead of always defaulting to line 0) is checked *before*
  the generic bare `[Line N]` pattern.

**Verified:** `test_parsestderr_bug.js` (5/5).

### Gap #4 — Single-file output only → real multi-file transpile + link

Two parts, both required for this to be an actually-closed gap rather
than just a library function nobody calls:

**Part A — the multi-file transpile/link mechanism itself** (already
present as `transpileFile`/`transpileProject`/`compileCheckProject`/
`cleanupProjectDir` in `out/transpiler.js`, confirmed real via
`test_gap4_multifile.js`, 3/3 — real `dictumc_cli.py`, real multi-TU
`gcc`/`g++` link, real execution across the link boundary producing the
correct cross-file result, and correct per-file Dictum-line error
translation for a failure *inside the imported file specifically*).

**Part B — actually wiring it into the extension** (the part that was
missing before this release): nothing in `out/extension.js` ever called
those functions — `_runCompileGate` always used the single-file
`transpile()`/`compileCheck()` pair, so a real cross-file project could
never pass the interactive Build compile gate at all; the import
transpiled fine standalone and only failed at link time, which the old
single-file path had no way to even attempt.

- `out/transpiler.js` — added `compileCheckSmart(entryDictPath,
  generatedCode, siblingDictPaths, ...)`: a single entry point that picks
  the single- or multi-file path and returns one unified result shape.
  With no siblings, it's byte-for-byte the original
  `transpile()`+`compileCheck()` sequence (no behavior change for the
  common case). With real siblings on disk, it stages the in-progress
  generated code under the entry file's real basename plus copies of each
  sibling's *current* on-disk content into a scratch dir, then runs the
  real multi-file transpile/link.
- `out/extension.js` — `_runCompileGate` now resolves the active file's
  real project siblings via `projectScan.js`'s existing
  `loadOrDiscoverManifest`/`findProjectFiles` (previously only used for
  codegraph indexing, never for the compile gate) and routes through
  `compileCheckSmart`.

**Bug found and fixed while verifying this wiring:** `compileCheckSmart`'s
first draft deleted the temp output directory — which holds the linked
binary — in a `finally` block that ran before the caller ever saw
`binPath`, silently unlinking the binary out from under any caller that
tried to use it. Fixed by only auto-cleaning the output directory on
failure paths where no usable binary exists; on success it's returned as
`outDir` and cleaned up by the caller once done (same contract
`compileCheckProject`'s existing callers already follow).

**Verified:** `test_gap4_extension_wiring.js` (4/4) — no-siblings parity
with the old path, a real sibling file linked in and actually *run*
across the boundary (not just compiled), a broken sibling surfaced as a
real named error instead of silently dropped from the link, and a broken
entry file still caught before any link attempt in multi-file mode too.

**Known scope limit:** `_runCompileGate`'s sibling resolution lists every
`.dict` file in the project except the entry file — it does not parse
the entry's own `import` statements to link in only the files actually
referenced. For a project with unrelated `.dict` files that don't import
each other, this means the compile-and-link phase compiles more TUs than
strictly needed (harmless — unreferenced symbols simply aren't called —
but slightly slower than the minimum). Narrowing to actual import-graph
resolution is a reasonable follow-up but wasn't required to close this
gap's stated scope (a real cross-file project failing to link at all).

### Remaining gaps (not started this release)

Gaps #5–#14 from `SOURCE_OF_TRUTH.md` §11 (stdlib bindings breadth,
tagged unions/bitfields, header export, dynamic collections, the
behavioral verification gate, IDE intelligence providers, scoped
libclang integration + soft-keyword scoping, and real TLS) are
unstarted. See that document for sizing notes.

---

## 0.1.46 — Codegraph pattern database (storage/lookup mechanism)

See `SOURCE_OF_TRUTH.md` §10 for full details — pattern storage/lookup/
binding mechanism, seeded with one real pattern; not yet wired into the
Build prompt itself.

## 0.1.39 and earlier

See `SOURCE_OF_TRUTH.md` for the canonical per-topic history (type
vocabulary, keyword vocabulary, GBNF grammar, continuing sessions /
project-wide codegraph / skills, and earlier). This file starts tracking
release-shaped entries from 0.1.46 onward; earlier work is documented
there instead of duplicated here.
