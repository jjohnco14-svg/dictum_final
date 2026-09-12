# Writing Dictum (`.dict`) Source By Hand — Full Reference

This is a complete reference for writing `.dict` source files directly
— no AI generation loop, no grammar-constrained sampling, just text you
(a human or an AI assistant with no prior exposure to this codebase)
write once and compile deterministically. It targets Dictum v0.1.47+
(includes the XOR operator and the multi-file/header-generation fixes).

**Confidence key**, used throughout:
- **[VERIFIED]** — actually compiled, linked with real `gcc`/`g++`, and
  run, with output checked against an expected value, during the
  writing of this guide.
- **[TRACED]** — confirmed correct by reading the actual parser source
  (`compiler/dictumc/parser.py`), but not independently compiled here.
  Treat with slightly more caution than [VERIFIED] items.

If you are an AI writing `.dict` source from this guide: **do not
invent syntax that isn't listed here.** Every keyword this language
recognizes is a specific, literal English word or phrase the parser
matches exactly — there is no forgiving natural-language fallback. If
a construct you want isn't in this document, don't guess; use a
simpler, confirmed-working construct instead, or fall back to `import
from C`/`import from C++` and call a real library function.

**Guide A's role in triage (not just authoring).** This document isn't
only consulted while writing `.dict` code — it's the syntax authority
Guide B's triage checks against. When `dict_triage.py` classifies a
failure as **Case A** (see `GUIDE_B_triage_protocol.md` §2), the
determining question is literally "does this match documented syntax
in this file, yes or no" — not a judgment call, a lookup. Keeping this
document accurate and complete is therefore part of what makes Case A
detection reliable: an undocumented-but-real keyword here would show
up as a false Case C (an AI concluding the compiler is broken because
the syntax "isn't in the reference," when the reference is just
incomplete). `verify/guide_a_sync_check.py` exists specifically to
catch that failure mode — it diffs this document's documented keywords
against the parser's real reserved-word list and fails loudly on any
gap, the same way `guide_a_coverage_check.py` fails loudly on an
unverified roadmap claim.

---

## 0. Starting a new project — the two-phase process [NEW]

Guide A is the project's mind: before any `.dict` line gets written,
it decides what the project *is* and what "correct" will mean for it.
That decision happens in two phases, and both live in one file:
`SOURCE_OF_TRUTH_<project>.md`, in the project root (see
`SOURCE_OF_TRUTH_CNC_VIBECODER.md` for a real, working example of the
shape this document takes once a project is underway).

### Phase 1 — write the source of truth (birds-eye view)

Before generating any code, write:

- **What the project is** — one paragraph, plain language: what it
  does, what platform/target it runs on, what class it is (console or
  GUI — Guide C branches its entire verification strategy on this).
- **Folder / file structure** — every file the project will contain
  and, in one line each, what it's responsible for. Don't invent this
  as you go; decide it up front so Guide B and Guide C both know where
  something *should* live before they go looking for why it doesn't.
- **The governing architecture split**, if there is one (e.g.
  cnc_vibecoder's Dictum-for-anything-safety-critical vs.
  plain-C-for-infrastructure-FFI-can't-express rule). This is what
  keeps later sessions from re-litigating a decision that was already
  made.
- **Roadmap / capabilities** — what the full, finished program is
  actually meant to be capable of, phrased as concrete, checkable
  claims ("imports a DXF profile and simulates the cut," not "has nice
  visuals"). **Tag each claim with a short ID** — `[R1]`, `[R2]`, ... —
  right in the markdown, e.g. `- [R1] Imports a DXF stock profile.`
  Every claim here becomes a candidate test in Phase 2 — vague claims
  produce vague, unverifiable tests, so write these as precisely as
  you'd want them checked, and the ID is what lets Phase 2 (and
  `verify/guide_a_coverage_check.py`) prove nothing got dropped between
  the two.

- **Version-tag every claim** — `[Rn]` alone says *what*, not *when*.
  Add a version tag next to it: `- [R1] v1 Imports a DXF stock
  profile.` `v1` is the confirmed-scope MVP from the Phase 0 discovery
  conversation; `v2`, `v3`, ... are explicitly deferred features the
  person mentioned or that are obvious next steps, not yet committed
  to. This matters for two real reasons:
  - **It keeps v1 honest and shippable.** Without a version boundary,
    "nice to have someday" claims silently inflate what Guide B/Guide C
    have to treat as required-for-done, and a real v1 deliverable never
    arrives because it's competing with v3 ideas for the same
    `known_gaps` list.
  - **It gives a future session (or a fresh conversation with no
    memory of this one) an explicit, ordered backlog** instead of
    having to re-derive "what's next" from a flat list or from asking
    the person to repeat themselves.

  Append a **`## Version Checklist`** section after the roadmap,
  grouping the same `[Rn]` IDs by version:
  ```
  ## Version Checklist

  ### v1 (current target)
  - [ ] [R1] Imports a DXF stock profile.
  - [ ] [R2] Simulates the cut path in real time.

  ### v2 (confirmed, deferred)
  - [ ] [R5] Exports G-code for a real GRBL controller.

  ### v3 (mentioned, not yet confirmed in scope)
  - [ ] [R8] Multi-material stock support.
  ```
  Check a box only once that `[Rn]`'s Phase 2 manifest check actually
  passes for real (Guide C, not "the code looks done") — this
  checklist is a status report grounded in real verification, not a
  todo list marked done by intention.

### Phase 2 — write the Guide C test manifest

Append a `## Guide C Test Manifest` section to the same
`SOURCE_OF_TRUTH_<project>.md`. This is the part of Guide A's job that
used to only happen informally (a README Guide C had to interpret) —
now it's explicit and lives next to the roadmap it was derived from.
For each roadmap/capability claim from Phase 1, write down:

- **What "correct" looks like**, in a form a script can check —an
  exact expected string/file diff for console behavior; for anything
  visual, a concrete, numeric assertion (an expected on-screen size
  range, an expected color-coverage percentage, a monotonic property
  across a sequence of frames) rather than a description for a human
  to eyeball. See Guide C §0a for why this has to be numeric, not
  descriptive.
- **Which general Guide C check already covers it** (console diff,
  GUI screenshot, packaging check — Guide C §0) vs. **what needs a
  project-specific check** written just for this project (Guide C
  §0a) — e.g. cnc_vibecoder's grbl-dialect verification and its
  camera/geometry sanity checks are project-specific; no other Dictum
  project needs them, so they don't belong in Guide C's general
  section.
- Anything from Phase 1's roadmap that genuinely can't be checked
  automatically yet — say so explicitly rather than leaving a silent
  gap Guide C has no way to know exists. Add it to the manifest's
  `known_gaps` with its roadmap ID and a one-line reason.
- **Every `[Rn]` ID from Phase 1 must end up either referenced by a
  check's `covers` list or listed in `known_gaps`.** Run
  `python3 verify/guide_a_coverage_check.py --source-of-truth
  SOURCE_OF_TRUTH_<project>.md --manifest guide_c_manifest.json` after
  writing the manifest (and again any time Phase 1's roadmap changes)
  — it fails loudly on any `[Rn]` with neither, instead of that gap
  sitting invisible until something breaks in the field. (Corrected
  from an earlier draft of this doc, which referenced a
  `run_selftest.py --check-coverage` flag that doesn't exist —
  `run_selftest.py --help` confirms it; `run_pipeline.py
  --source-of-truth ...` also runs this same check internally as its
  own Stage 3, so a full pipeline run doesn't need this invoked
  separately.)

This manifest is what makes Guide C able to do more than generic
checks on a project it's never seen before — it reads Phase 2 of
*this* file the same way it always reads the general checks in its own
document.

---

## 1. Program structure [VERIFIED]

```
program my_program

    print the text "hello"

end program
```

- `program Name` ... `end program`. **No colon** after `Name`.
- A file may contain a `program` (the entry point, must have exactly
  one `main`-equivalent per compiled executable) and/or one or more
  `module` blocks (reusable code, no entry point of its own).
- `end program` / `end module` / `end action` / etc. — the word after
  `end` is optional in most cases (the parser accepts a bare `end`
  too), but always write it out for clarity.

---

## 2. Types [VERIFIED / TRACED]

| Dictum type | C/C++ type | Status |
|---|---|---|
| `whole number` | `int32_t` | [VERIFIED] |
| `decimal number` | `double` | [TRACED] |
| `text` | `const char*` | [VERIFIED] |
| `truth value` | `bool` | [TRACED] |
| `count` | `size_t` | [TRACED] |
| `bytes` | `uint8_t*` | [TRACED] |
| `nothing` | `void` (return type / zero-arg marker only) | [VERIFIED] |
| `opaque pointer` | `void*` | [VERIFIED] |
| `list of T` / `array of T` | array of T (`T*` + `size_t` count as an action parameter) | [VERIFIED, including as an action parameter — see §12] |

**[NEW — found this session, cnc_vibecoder DXF/STL/grbl work] A whole
second tier of primitive types exists and is real, but was completely
absent from this table.** Found by reading
`compiler/dictumc/type_registry.py` (the single canonical source for
Dictum's type vocabulary — see that file's own docstring for why it
exists: `u8`/`u64` used to be parseable but missing from the
validator's type set, `f32` had to be hand-added in five separate
places, `bytes` parsed but had no C mapping at all — the exact kind of
silent-drift bug this reference table itself is trying to prevent by
existing). `f32` specifically is [TRACED]-verified in practice: it's
used for every `Rectangle`/`Vector3` field throughout this project's
shipped, compiling, linking, running `raygui_bridge.dict` and
`main.dict` (e.g. `keep panel_box as Rectangle with no value` /
`set x of panel_box to 0.0` where `x` is declared `as f32`). The rest
are [TRACED] from the canonical source but not individually
worked-example-verified in this session:

| Dictum type | C/C++ type | Status |
|---|---|---|
| `f32` | `float` | [TRACED — f32 specifically also confirmed in shipped, running code] |
| `f64` | `double` | [VERIFIED — see below] |
| `i16` | `int16_t` | [VERIFIED — see below] |
| `i32` | `int32_t` | [TRACED] |
| `i64` | `int64_t` | [TRACED] |
| `u8` | `uint8_t` | [TRACED] |
| `u16` | `uint16_t` | [TRACED] |
| `u32` | `uint32_t` | [TRACED] |
| `u64` | `uint64_t` | [TRACED] |
| `byte` | `uint8_t` | [TRACED] |
| `decimal` | `double` | [TRACED] (single-word terminal form of `decimal number`) |
| `bool` | `bool` | [TRACED] (single-word terminal form of `truth value`) |
| `fractional number` | `double` | [TRACED] (synonym for `decimal number`) |
| `handle to bytes` | `void*` | [TRACED] |
| `result` | `void*` | [TRACED] |

**[NEW — found in a later session] `i16` and `f64` were themselves a
real instance of the exact drift pattern this note already warns
about** — they were simply missing from `type_registry.py`'s
`PRIMITIVES` list entirely (not merely undocumented here — the parser
would reject them outright), unlike their siblings `u8`/`u16`/`u32`/
`u64`/`i32`/`i64`/`f32`, which all worked. Fixed by adding both to
`PRIMITIVES` with the correct C mapping (`int16_t`, `double`); verified
by declaring a shape with `f32`/`f64`/`i16`/`u8` fields side by side,
compiling and linking for real, and confirming the generated C struct
actually contains `double b;` / `int16_t c;` (not, say, both silently
collapsing to the same width). Regression test **R22** in
`compiler/run_selftest.py` covers this exact shape.

If you need one of these and it doesn't behave as expected, the
canonical answer is always `type_registry.py`'s `PRIMITIVES` list, not
this table or any other file — this table is a convenience copy of a
subset of it, prone to exactly the kind of gap that produced this
note.

**There is no bare `number` type.** Always write `whole number` or
`decimal number`. This is the single most common mistake.

**There is no documented conversion between `whole number` and
`decimal number`.** [NEW — found this session] Confirmed by trying to
use one where the other was expected and hitting a real compile/link
mismatch; there is no `as a decimal`-style cast construct anywhere in
this language. If a value needs to end up as the other numeric type,
have the *C-side FFI function itself* return the type actually needed
downstream (e.g. a function that's semantically an integer count but
feeds into `decimal number` arithmetic elsewhere should just declare
`produces decimal number` in C and in its `import from C` line) —
don't try to convert on the Dictum side.

---

## 3. Variables — `keep` [VERIFIED]

```
keep a as whole number with value 12
keep name as text with value "Jaden"
keep nums as list of whole number with values 1, 2, 3, 4, 5
keep p as SomeShape with no value
```

Forms after `with`:
- `with value EXPR` — single initial value. [VERIFIED]
- `with values EXPR, EXPR, ...` — list/array literal, comma or `and`
  separated. [VERIFIED]
- `with no value` — declared, not yet initialized (needed for shape
  instances you'll fill in field-by-field). [VERIFIED — this exact
  clause had a real parser bug until this version; see §12]
- `with all values EXPR` — fill every element with one value.
  [VERIFIED to parse cleanly; had the same bug as `with no value`
  until this version, see §12]
- `with room for EXPR` — reserve capacity without initializing.
  [TRACED]

---

## 4. Assignment — `put` and `set` [VERIFIED]

```
put i plus 1 into i
put total plus i into total
set x of p to 3
```

- `put EXPR into TARGET` — general assignment. Keyword is **`into`**,
  not `in`.
- `set TARGET to EXPR` — equivalent alternate form, reads naturally
  for field writes. Keyword is **`to`**.
- Field target syntax: `x of p` or `p.x` both work as an lvalue
  [TRACED for the dotted form; `X of Y` confirmed VERIFIED].

**Reassigning an existing variable from a function call result:** use
`call ACTION with ARGS giving EXISTING_VAR` — **not**
`set EXISTING_VAR to ACTION with ARGS` or
`put ACTION with ARGS into EXISTING_VAR`. [NEW — found this session]
`keep VAR as TYPE with value ACTION with ARGS` (a function call as the
initializer, at the moment of declaration) is separately confirmed
working — real, already-verified code throughout this document and
`cnc_vibecoder` does this. But *re*assigning an *already-declared*
variable from a call result was never confirmed to work via
`set`/`put`, and `call ... giving` is the proven-safe form for that —
use it.

**`opaque pointer with no value`, used conditionally later:** if a
variable declared `with no value` is read anywhere in the same
function body — even inside a branch that's only reachable after
another branch has definitely assigned it — the compiler's
use-before-init check flags it, because it doesn't reason across
branches. [NEW — found this session] If the real initial value isn't
known yet at declaration time, initialize it with a real, harmless
call right away (e.g. open a small placeholder file) rather than
`with no value`, matching how `simulator/animator.dict` always does
this (`keep reader as opaque pointer with value gcode_reader_open with
gcode_path` — never `with no value` even though the real path is only
known at the call site).

---

## 5. Printing [VERIFIED]

```
print the text "label:" and some_variable and ", more:" and other_var
```

`print` **always** requires the literal words `the text` right after
it — `print result` alone is a parse error, even for a single
variable. Chain multiple values with `and`.

**No automatic space is inserted between chained values.**
`print the text "hello," and name` for `name = "world"` prints
`hello,world`, not `hello, world`. If you want a space, put it in a
literal: `print the text "hello, " and name`.

---

## 6. Operators

### Arithmetic [TRACED, standard forms]
`plus`, `minus`, `times`, or the prefix forms `the sum of A and B`, `the
difference of A and B`, `the product of A and B`, `the quotient of A
and B`, `the remainder of A and B`.

**`A divided by B` is also valid infix syntax** [VERIFIED this
session — confirmed via real, already-compiling code
(`simulator/animator.dict`) using it directly, e.g.
`stock_h divided by 2.0`] even though it wasn't listed above
alongside `plus`/`minus`/`times`. Both `A divided by B` and
`the quotient of A and B` work; this table just wasn't exhaustive.

**No parentheses in arithmetic expressions.** [NEW — found this
session] There is no evidence anywhere in this language of grouping
via `(...)` in an arithmetic expression — real working code never
does it, and a parenthesized sub-expression
(e.g. `25.0 plus (power times 150.0)`) should not be assumed to work.
Break compound expressions into separate `keep` statements instead,
one binary operation per line — this is the pattern used everywhere
in every real, verified example in this document and in the
`cnc_vibecoder` codebase.

### Bitwise [VERIFIED — all four, both backends]
```
keep r as whole number with value the bitwise and of a and b
keep r as whole number with value the bitwise or of a and b
keep r as whole number with value the bitwise xor of a and b
keep r as whole number with value the bitwise not of a
```
The leading `the` is mandatory. `bitwise not` is unary (only takes
`of a`, no second operand).

### Shifts [VERIFIED]
```
keep r as whole number with value the left shift of a by 2
keep r as whole number with value the right shift of a by 2
```

### Comparison [VERIFIED for greater-than; rest TRACED, symmetric pattern]
| Dictum | C |
|---|---|
| `is equal to` | `==` |
| `is not equal to` | `!=` |
| `is greater than` | `>` |
| `is greater than or equal to` | `>=` |
| `is less than` | `<` |
| `is less than or equal to` | `<=` |

---

## 7. Conditionals [VERIFIED]

```
if a is greater than b then
    print the text "a wins"
otherwise if a is equal to b then
    print the text "tie"
otherwise
    print the text "b wins"
end if
```

`if COND then` ... `otherwise if COND then` ... `otherwise` ... `end
if`. No `elif`/`else if` keyword — it's always `otherwise if`.

---

## 8. Loops

### While [VERIFIED — confirmed correct sum 1..5 = 15]
```
keep i as whole number with value 0
while i is less than 5 repeat
    put i plus 1 into i
end while
```
`while COND repeat` ... `end while` (or `end repeat` — both accepted).

### For-each [VERIFIED]
```
for each n in nums repeat
    print the text "item:" and n
end for
```
`for each ITEM in COLLECTION repeat` ... `end for`. Works on both a
locally-declared list and a `list of T` action parameter (see §2, §12).

### Repeat N times [TRACED]
```
repeat 5 times using i
    print the text "tick"
end repeat
```
`repeat COUNT times using COUNTER_NAME` ... `end repeat`.

### Break [TRACED]
```
stop repeating
```
The only loop-exit keyword; always both words, `stop repeating`.

---

## 9. Actions (functions) [VERIFIED]

```
action toggle_flags takes a as whole number and b as whole number produces whole number
    return the bitwise xor of a and b
end action
```

- Parameters: `takes X as TYPE and Y as TYPE and ...`. Zero params:
  `takes nothing` (do not just omit `takes` entirely).
- Return type: `produces TYPE`.
- Return a value: `return EXPR`.
- **These words — `takes`/`produces`/`return` — belong to the
  *declaration* side. The *call* side uses different words entirely
  (`with`/`giving`, next section). Mixing the two up is the single
  easiest hand-authoring mistake.**

---

## 10. Calling actions [VERIFIED]

```
keep result as whole number with value 0
call toggle_flags with 12 and 10 giving result
call SomeModule.toggle_flags with 12 and 10 giving result
```

- `call NAME with ARG and ARG giving RESULT_VAR`.
- `call` is a **statement**, not an expression. You cannot write `keep
  x as whole number with value call foo with 1 giving nothing` — that
  will not parse as you expect. Always: declare the variable first
  (`with value 0` or similar placeholder), then `call ... giving` it
  on its own line.
- Module-qualified calls use dot notation: `ModuleName.action_name`.

---

## 11. Shapes (structs) [VERIFIED]

```
shape Point holds
    x as whole number
    y as whole number
end shape
```

```
keep p as Point with no value
set x of p to 3
set y of p to 4
print the text "x:" and x of p and "y:" and y of p
```

- `shape Name holds` — **no colon**, and fields are declared bare
  (`fieldname as TYPE`), **not** with `keep`.
- Field access/assignment: `FIELD of INSTANCE` (verified) or
  `INSTANCE.FIELD` (traced) — both are valid lvalue/rvalue forms.

---

## 11a. Shapes with methods, constructors, destructors, access control (C++ backend) [TRACED]

`grammar.py`/`parser.py` recognize a fuller class-like form inside `shape
... holds` on the C++ backend. Confirmed by reading `parser.py`'s
`parse_shape`/`parse_method`/`parse_constructor`/`parse_destructor`, not
independently compiled here:

```
shape Widget extends Base holds
    private
        id as whole number
    public
        constructor takes id as whole number produces nothing
            set id of this to id
        end constructor

        method greet takes nothing produces nothing
            print the text "hi"
        end method

        destructor produces nothing
            print the text "cleanup"
        end destructor
end shape
```

- **`extends PARENT`** — alternative to `is a PARENT`; both set the same
  parent field.
- **`public` / `private` / `protected`** — bare access-control words on
  their own line inside `holds`; every field/method/constructor declared
  after one applies that access level until the next one changes it.
  Default is `public`.
- **`method NAME takes ... produces TYPE ... end method`** — same
  parameter shape as `action`.
- **`constructor takes ... produces nothing ... end constructor`** — a
  shape can declare more than one (overloads); return type is always
  `nothing`.
- **`destructor produces nothing ... end destructor`** — at most one per
  shape, no parameters.
- `virtual` and `override` are reserved grammar words for this same
  C++-backend class path (method dispatch modifiers) but this session
  did not trace or compile their handling — treat as **[UNVERIFIED]**
  until confirmed against `parser.py`/`emit_cpp.py` directly.

## 11b. Tagged enum-like variants — `possibilities` [TRACED]

```
possibilities Direction
    north
    south
    east
    west
end possibilities
```

A flat named list of variants, no payload per variant (that's gap #6 on
the project's open list — tagged unions with data are not implemented).

---

## 11c. Error handling — `attempt` / `assert` [TRACED]

```
attempt call risky_thing giving result
    print the text "got:" and result
on failure with err
    print the text "failed:" and err
end attempt
```

- `attempt` wraps a single `call ... giving NAME` (or a bare expression
  call). `on success` / `on failure [with NAME]` blocks are both
  optional; omit `on failure` entirely and errors simply fall through.
- `assert CONDITION` — a bare condition, no message argument in the
  current grammar.
- Inside an action, `produce success with VALUE` / `produce failure with
  text "msg"` produce the two sides of that same result convention.

## 11d. `unsafe` blocks, `extern fn ... @syscall(...)`, `transmute` [TRACED]

```
extern fn raw_write takes fd as whole number and buf as handle to bytes and n as whole number produces whole number
    @syscall("write")

unsafe:
    call raw_write with fd and buf and n giving bytes_written
end unsafe
```

- `extern fn NAME takes ... produces TYPE` followed by `@syscall("name")`
  declares a direct syscall-backed FFI stub — reserved for the lowest
  trust tier alongside `import from C`.
- `unsafe: ... end unsafe` is a block modifier, not a value; it also
  accepts bracketed low-level tokens like `[TOKEN_NAME: params]` and
  `[VERIFY:CATEGORY_ID]` inline, which is how the MEMORY/SAFETY tool-mode
  tiers (gap #1) get their raw operations into source.
- `transmute EXPR as TYPE` — a bare bit-reinterpret cast, distinct from a
  normal type-narrowing cast.

## 11e. Reference/ownership type keywords — `ref`, `unique`, `weak` [TRACED]

Already documented for `shared`/`raw` in §2; the same forms exist for:

- **`unique handle to T`** / **`unique pointer to T`** — single-owner
  smart pointer (C++ backend).
- **`weak handle to T`** / **`weak pointer to T`** — non-owning observer
  form of the same smart-pointer family.
- **`ref T`** — plain reference type; **`const ref T`** is the
  const-qualified form (already covered).

## 11f. Math/text helper words not yet listed — `sine`, `cosine`, `tanh`,
`exponential`, `square root of`, `modulo`, `length`, `empty` [TRACED]

These are additional forms of the "the X of/Y" expression family in §6,
confirmed against `parser.py`'s expression-word dispatch:

- `the sine of X`, `the cosine of X`, `the tanh of X`, `the exponential
  of X` — single-argument transcendental functions (map to C `sin`,
  `cos`, `tanh`, `exp`).
- `the square root of X` — note the three-word form, not `the square of`.
- `X modulo Y` — infix, same family as `plus`/`minus`.
- `the length of X` — **text only** (compiles to `strlen`). List length
  uses the separate `the count of X` keyword instead (own `count`
  unary-op token in the parser, not the same `length` token) — confirmed
  by re-checking parser.py/emit_c.py while building gap #9's growable
  list support; an earlier draft of this doc incorrectly said `length`
  also worked on `list of T`. `the count of X` also now works on
  `growable list of whole number` (§11j below).
- `X is empty` — comparison form, equivalent to `X == empty`.

## 11g. `export`, `define` [TRACED]

- **`export`** — prefix on a top-level `program`/`module`/`shape`/
  `action` declaration (`export shape Point holds ...`) marking it
  visible across files for header-generation purposes (§7/§15's
  multi-file linking). Gap #7 (real header export) is still open — this
  keyword exists in the grammar/parser today but does not yet drive an
  actual generated `.h` file end to end.
- **`define`** — a top-level declaration parsed by `parse_define()`;
  this session did not trace its emitted output far enough to give a
  confirmed example. Treat as **[UNVERIFIED]** pending a real compile.

## 11k. `map of K to V` / `set of T` — real hash collections [VERIFIED]

```
keep ages as map of text to whole number with no value
put 30 at "alice" in ages
put 25 at "bob" in ages
print the text "alice age:" and the value at "alice" in ages
print the text "count:" and the count of ages
if ages contains "alice" then
    print the text "has alice"
otherwise
    print the text "no alice"
end if

keep tags as set of whole number with no value
add 1 to tags
add 2 to tags
add 1 to tags
print the text "tag count:" and the count of tags
```

Compiled and run for real on **both backends** (`dictumc_cli.py
--compile`, R43 for C++, R44 for C).

- **`put VALUE at KEY in NAME`** — map assignment/update. Distinct from
  the existing `put VALUE into TARGET` (plain assignment) — disambiguated
  by checking for `at` vs `into` right after the value, so both forms
  coexist.
- **`the value at KEY in NAME`** — map lookup. A missing key is a real
  runtime error (C++: `.at()` throws; C: `dictum_map_get` sets the same
  error state `attempt` blocks check), not a silent default value.
- **`NAME contains VALUE`** — membership check, new infix keyword next
  to the existing `is greater than`/`is equal to` family. Works on both
  `map of K to V` (checks keys) and `set of T` (checks elements).
- **`add VALUE to NAME`** (the same statement growable list uses) also
  works on `set of T` — inserts, silently no-ops if already present
  (a set's defining property).
- **`the count of NAME`** works on map/set too, same keyword as
  growable list.

**Scope, honestly:**
- **C++ backend** — any key/value/element type at all (`std::unordered_map`/
  `std::unordered_set`, real generics).
- **C backend** — exactly `map of text to whole number` and `set of
  whole number` (hand-rolled hash tables — `runtime/dictum_map.h`/
  `dictum_gset.h` — real FNV-1a/splitmix32 hashing, linear probing with
  tombstones, amortized resize; not a generic implementation, since C
  has no generics). Any other combination on C is a compile-time error,
  confirmed rejecting `map of whole number to whole number` and `set of
  text`.

## 11j. `growable list of whole number` — real dynamic array [VERIFIED]

```
keep nums as growable list of whole number with no value
add 10 to nums
add 20 to nums
add 30 to nums
print the text "count:" and the count of nums
print the text "item0:" and item 0 of nums
```

Compiled and run for real (`dictumc_cli.py --compile`, C backend, R42
regression test): prints `count:3 item0:10 item2:30`.

- **Distinct from the fixed-size `list of T`** (§11e/existing sections)
  — this is a genuine runtime-resizable array (`runtime/dictum_glist.h`,
  realloc-based amortized growth), not a plain C array.
- **`add VALUE to NAME`** — appends. `NAME` must already be declared
  `growable list of T`; adding to anything else is a compile-time error.
- **`item N of NAME`** — bounds-checked read (existing indexing syntax,
  §11 above); out-of-range reads set a real runtime error rather than
  reading past the buffer.
- **`the count of NAME`** — real element count. Note: **not** `the
  length of NAME` — see the correction in §6 above; `length` is
  text-only (`strlen`).
- **Current scope, honestly:** on the **C backend**, only `growable
  list of whole number` is implemented — any other element type
  (`growable list of text`, of a shape, etc.) is a compile-time error
  by design, not a silent miscompile. On the **C++ backend**,
  `growable list of ANY_TYPE` works (real `std::vector<T>`, verified
  with both `whole number` and `text` elements — see §11k just above
  for `map`/`set`, which are now also real on both backends).

## 11i. `release` — explicit resource release [TRACED]

```
release my_handle
release the buffer of my_shape
defer release my_handle
```

- `release NAME` — releases/frees the named handle immediately.
- `release the FIELD of OBJ` — releases a specific field of a shape
  instance.
- `defer release NAME` — schedules the same release to run at scope
  exit, RAII-style, instead of immediately.

## 11h. Reserved-but-inert words — `fn`, `taking`, `holding`

- **`fn`** — only appears as part of the fixed `extern fn ... @syscall`
  form above (§11d); it is not a general action-declaration keyword.
- **`action taking A as T1 and B as T2 produces T3`** — an anonymous
  *function-type* annotation (e.g. for a callback parameter's declared
  type), distinct from declaring an actual `action`.
- **Passing an action BY NAME as a value** — an already-declared
  `action`'s bare name, used where a value of that function-type is
  expected, is a real, verified higher-order call — not just the type
  annotation above, but actually *producing* a value of that type:
  ```
  action twice takes n as whole number produces whole number
      keep r as whole number with value 0
      put n times 2 into r
      return r
  end action

  action apply takes f as action taking A as whole number produces whole number and v as whole number produces whole number
      keep r as whole number with value 0
      call f with v giving r
      return r
  end action

  program p
      keep out1 as whole number with value 0
      call apply with twice and 21 giving out1
      print the text "r=" and out1
  end program
  ```
  Compiled, run, and confirmed `r=42` on all three backends — R85 in
  `compiler/run_selftest.py`, fixture at `compiler/tests/hof/`. Worth
  knowing: the C++ backend's own action-typed *FFI* parameters (an
  `import from C`/`C++` callback, as opposed to this Dictum-internal
  case) need the raw C function-pointer spelling, not `std::function` —
  see §14's `import from C++`/callback notes and R98 if you're binding
  a callback into a third-party C library rather than passing a Dictum
  action to another Dictum action as shown here.
- **`holding`** — reserved in the grammar's word list alongside `holds`,
  but no current parser rule actually consumes it as functional syntax.
  Do not use it expecting `holds`-equivalent behavior; treat as
  **inert/reserved for a future form**, not documented usage.

---

## 12. Known limitations — confirmed by hand-testing, avoid these patterns

1. **No TLS/HTTPS.** `dictum_tls.h` is stubbed. Networking code that
   needs to speak HTTPS will not work. Plain sockets (`use Net`) are
   real.
2. **`module`/`program`/`shape ... holds` never take a trailing
   colon.** If you see or generate example code with one, it's wrong
   — this was a real, since-fixed bug in one internal tool
   (`project_builder.py`), not a language feature.

~~Passing a `list of T` as an action parameter~~ — **fixed on both
backends.** The C backend emits a real `(T*, size_t)` pair
(`int32_t* nums, size_t nums_count`). The C++ backend independently
had its own, worse bug (a non-existent type name plus a raw
AST-object-repr leak into list literals) — fixed separately, and maps
`list of T` to a real `std::vector<T>`, which just works with the
existing generic parameter-passing, `for each`, and indexing code with
no special-casing needed. Both verified end to end: compiled, linked,
run, output checked against a hand-computed expected sum. Covered by
regression tests R8 (C) and R9 (C++) in `compiler/run_selftest.py`.

This is a good example of why you should never assume a fix in one
backend implies anything about the other — the C++ bug here was not
just "the same fix, not yet ported," it was independently worse,
and needed its own root-cause trace, not a copy-paste of the C
approach (C++'s real `std::vector<T>` made the correct fix simpler
than C's manual pointer/count threading, not just a port of it).

---

## 13. FFI — calling real C libraries: `import from C` [VERIFIED]

This is how you bind to a real C function without writing any actual C
code yourself. It does **not** require the library's `.h` header to be
present at Dictum-compile time — it emits its own `extern` declaration
and links against the real compiled library (`.so`/`.a`) at gcc time.

```
program sqlite_demo

    import from C the action sqlite3_libversion takes nothing produces text as sqlite3_libversion

    keep version as text with value "unknown"
    call sqlite3_libversion giving version
    print the text "sqlite3 version:" and version

end program
```

Compiled and linked against the real system `libsqlite3.so` while
writing this guide — printed the actual installed SQLite version
string, no mocking.

**Syntax:** `import from C the action REAL_C_SYMBOL_NAME takes TYPE
and TYPE ... produces RETURN_TYPE as DICTUM_ALIAS`

- `REAL_C_SYMBOL_NAME` must be the library's real exported symbol name
  (e.g. `sqlite3_open`, not something you invent).
- `takes nothing` for zero-argument functions.
- `as DICTUM_ALIAS` — the name you'll actually call from Dictum code.
  It's fine (and common in the blessed bridges) for this to be
  identical to the real symbol name.
- **Pointer arguments/returns** (`sqlite3*`, `void*`, etc.) map to
  `opaque pointer` in the `takes`/`produces` list. You then pass Dictum
  values of matching shape — typically you'll be threading an opaque
  handle you got back from one imported function into the next one.
- **Out-parameters — `the address of NAME`** — a C signature that wants
  a pointer slot to write into (`sqlite3_open`'s `sqlite3 **ppDb`, "give
  me the address of a local so you can fill it in") is callable directly
  via the address-of operator, with **no hand-written C shim**:
  ```
  import from C the action sqlite3_open takes text and opaque pointer produces whole number as sqlite3_open
  import from C the action sqlite3_close takes opaque pointer produces whole number as sqlite3_close

  program noshim
      keep db as opaque pointer with no value
      keep rc as whole number with value 0
      call sqlite3_open with "mydb.db" and the address of db giving rc
      print the text "open_rc=" and rc
      call sqlite3_close with db giving rc
  end program
  ```
  Compiled, linked against the real `libsqlite3.so`, and run on all
  three backends (C, C++, Nim) with no shim — R83 in
  `compiler/run_selftest.py`, fixture at `compiler/tests/addressof/`.
  Two things worth knowing about the semantics: (1) taking the address
  of an **uninitialized** variable (`with no value`) is not treated as
  reading it — that's precisely what an out-parameter needs, and the
  validator has an explicit exemption for it; (2) `the address of` on a
  **container** (a `list`/`growable list`/`map`/`set`) yields the
  address of the real underlying buffer on every backend, not the
  address of a wrapper object — this matters because getting it wrong
  on the C++/Nim side is a real, previously-hit segfault (see R86).
- **`--link LIBNAME`** (repeatable, e.g. `--link sqlite3 --link m`) is
  the CLI flag that actually links the external library — pass one for
  every real system library your `import from C` calls into.
  `dictumc_cli.py` does not auto-discover this from the source file on
  any backend (C, C++, or Nim) — the transpile step alone genuinely
  never produces a working binary against sqlite3/raylib/sdl2/openssl
  without it. (There *is* a `#[link "libname"]` source-level directive,
  but it's only understood by the separate polyglot pipeline, not the
  `--backend c/cpp/nim` path this guide is about — don't reach for it
  here.)
- **Real, verified, working example** (all three backends, including
  Nim — Nim needed no header, `text` maps to `cstring` in an FFI
  signature specifically, not the `string` a native Dictum variable
  gets):
  ```
  import from C the action sqlite3_libversion takes nothing produces text as sqlite3_libversion

  program sqlite_info:
      keep ver as text with value ""
      call sqlite3_libversion giving ver
      print the text "sqlite3 version:" and ver
  end program
  ```
  ```
  python3 dictumc_cli.py sqlite_info.dict --backend nim --run --link sqlite3
  ```
  prints the real, actual version of whatever `libsqlite3` is
  installed on the machine running it.

**A curated, already-correct set of these exist for you** — don't
regenerate from scratch if one already exists:
`compiler/blessed/sqlite3.dict`, `raylib.dict`, `sdl2.dict`,
`glfw.dict`, `openssl.dict`. These were generated by
`scripts/generate_import_c.py` parsing the *real* system headers via
libclang, so their signatures are guaranteed correct against the
actual library ABI — copy the specific `import from C` lines you need
out of these files rather than hand-typing your own guess at a
signature.

**openssl.dict specifically** gives you real EVP digest/HMAC/RAND
bindings (hashing, encryption primitives) — it does **not** include
any TLS/SSL handshake functions (no `SSL_CTX`/`SSL_connect`), so it
does not get you HTTPS despite being "the OpenSSL bridge."

### 13a. `phrased as` — giving a foreign function a natural-language call form [VERIFIED]

An `import from C`/`import from C++` binding can carry an additional
`phrased as "..."` clause that registers a natural-language sentence
form for calling it, so the call site reads like the rest of Dictum
instead of `call c_alias with ... giving ...`:

```
import from C the action sqlite3_libversion takes nothing produces text as db_version phrased as "the database version"
import from C the action abs takes whole number produces whole number as c_abs phrased as "the magnitude of {}"

program main
    keep v as text with value ""
    the database version giving v
    keep m as whole number with value 0
    the magnitude of 0 minus 42 giving m
    print the text "abs=" and m
end program
```
Compiled and run on all three backends, all agreeing on `abs=42` — R97
in `compiler/run_selftest.py`.

- **`{}` is a positional placeholder** — one per parameter, in order.
  The placeholder count must exactly match the bound action's arity; a
  phrase with the wrong number of `{}`s is rejected at parse time, not
  silently mis-called.
- **A phrase must start with a literal word**, not a placeholder — `"{}
  squared"` is rejected for the same reason: a call site starting with
  a value rather than a recognizable word isn't parseable as a
  sentence.
- This lowers to an ordinary call at the AST level — **zero emitter
  changes were needed for any backend** — so it can never become a
  fourth place backend drift can hide.
- Use this for FFI bindings you'll call often enough that the raw
  `call ... with ... giving ...` form would otherwise be the only
  non-natural-language-reading part of an otherwise natural-language
  program.

---

## 14. FFI — calling C++: `import from C++` [TRACED, not compiled in this session]

```
import from C++ the action some_function takes whole number produces whole number as some_alias
```

Same shape as `import from C`, but dispatched via the `C++` token
(literally the two characters `+` `+` after `C`, parsed one at a
time). There is also a `container` item type for binding STL
containers, which has more complex syntax — if you need this, read
`parse_import_cpp` in `compiler/dictumc/parser.py` directly rather
than guessing, since it wasn't independently verified while writing
this guide.

---

## 15. Multi-file projects [VERIFIED]

**mask_utils.dict:**
```
module mask_utils

    action toggle_flags takes a as whole number and b as whole number produces whole number
        return the bitwise xor of a and b
    end action

end module
```

**main.dict:**
```
program mask_demo

    use mask_utils

    keep result as whole number with value 0
    call mask_utils.toggle_flags with 12 and 10 giving result

    print the text "result:" and result

end program
```

Build the **directory**, not a single file:
```bash
python3 compiler/project_builder.py /path/to/project_dir --backend c --out /path/to/project_dir/build
cd /path/to/project_dir/build && make
./mask_demo
```

`use ModuleName` pulls in a sibling `.dict` file in the same project
directory by module name (no file path). This is different from
`import ModuleName from "path/to/file.dict"` [TRACED], which takes an
explicit file path — use `use` for same-project modules.

**`use` now genuinely works end-to-end for shapes, `import from C`
FFI bindings, and cross-file action calls** — a file that only
`use`s a shape, an FFI import, or an action defined in a *sibling*
file (never redeclares it itself) validates, compiles, links, and
runs correctly. This was NOT true before this session (see §18 for
the full list of what was silently broken and is now fixed and
covered by regression tests R11–R19 in `compiler/run_selftest.py`).
If you hit anything that looks like this class of bug again — a
cross-file reference that should obviously work per this doc but
doesn't — it's almost certainly a genuine compiler bug, not a mistake
in your `.dict` source; see §17 for how to verify and §18 for the
debugging pattern that found all nine of these.

---

## 16. Compiling a single file directly (no project)

```bash
python3 compiler/dictumc_cli.py my_program.dict --backend c --compile --output my_program
./my_program
```

`--backend cpp` for C++. `--compile` runs the real two-phase gcc gate
(syntax-check, then full link) — always use it; without it you only
get emitted source with no correctness guarantee at all.

---

## 17. How to verify what you wrote actually works

Compiling clean is necessary, not sufficient. Before considering any
hand-written `.dict` program done:

1. Compile with `--compile` (real gcc gate, both phases).
2. Actually **run** the resulting binary.
3. Compare its output against an independently-known-correct expected
   value (compute it in your head, in Python, or from the real
   library's own documentation — not from another LLM's guess).
4. If it's meant to be reused, add it as a case in
   `compiler/run_selftest.py` following the existing `R1`-`R10`
   pattern, so it can't silently regress later.

Every example in this document was held to that exact standard.

### If you don't have gcc or codebase access: use `dict_syntax_check.py`

If you're generating `.dict` files without access to the full compiler
or a C/C++ toolchain, there's a standalone, single-file syntax checker
at the repo root: `dict_syntax_check.py`. It requires nothing but a
plain Python 3 interpreter (standard library only — no dependencies to
install).

```bash
python3 dict_syntax_check.py my_program.dict
python3 dict_syntax_check.py some_directory/          # checks every .dict file in it
python3 dict_syntax_check.py file_a.dict file_b.dict   # multiple files at once
```

**What it actually checks, and why it's trustworthy for that scope:**
it tokenizes and parses your file using the exact same lexer/parser
code the real compiler uses (literally the same source files,
concatenated into one, not a rewritten approximation) — so a PASS here
means "this is real, syntactically valid Dictum," by construction, not
by guesswork. It will correctly reject the kinds of mistakes this very
guide warns about (`print result` without `the text`, `put X in Y`
instead of `into`, and so on) with the same error message the real
compiler would give.

**What it does NOT check** — and this matters, don't over-trust a
PASS: it does not run gcc, so it does not know whether your program
compiles, links, or does the right thing at runtime. It does not
resolve `use` imports across files. It does not catch every semantic
mistake — for instance, it will *not* flag `keep x as number` (missing
`whole`/`decimal`) as an error, because that specific check happens
later, in the real compiler's validator stage, not in parsing itself.
A PASS from this tool means "worth sending onward for real
compilation," not "guaranteed correct."

Use it as a fast, free first pass to catch the most common category of
mistake before every submission goes through a full compile-and-review
round.

---

## 18. Multi-file cross-file bug hunt (this session) — nine compiler bugs, one project bug

A real multi-file project (`cnc_vibecoder`, a CNC toolpath generator +
raylib 3D simulator) was run all the way through: transpile → gcc
compile → link → **actual execution**, per the standard in §17. It
surfaced a chain of nine genuine compiler bugs, all in the
cross-file/`use` path, that a single-file test never would have
caught, plus one bug in the project's own hand-written source. All
nine compiler bugs are now fixed and each has a dedicated regression
test (**R11–R19**) in `compiler/run_selftest.py`. Read this section if
you hit something that smells like the same class of bug again — the
debugging *pattern* (find where per-file state silently doesn't span
files) is more useful than memorizing the specific list.

**The pattern behind all nine:** `project_builder.py` builds a
multi-file project by transpiling each `.dict` file **separately**,
each with its own fresh `Validator`/`CEmitter` instance. Some piece of
state that should have been *project-wide* (known the moment any file
`use`s it) was instead only ever populated from **that one file's own
AST** — so it worked perfectly for a file that both defines and uses
something, and silently broke the instant `use` crossed a file
boundary. This bug shape showed up independently at three different
layers (validator, emitter, project_builder's header generator), and
each had to be fixed at its own layer — fixing it once at one layer
did not fix the others.

| # | Bug | Layer | Symptom |
|---|-----|-------|---------|
| R11 | Cross-file shape types (`use X` + a var of a shape `X` defines) failed validation | `Validator.validate()` only ever saw its own file's `collect_globals()` | `Unknown type 'Vector3'` + a cascade of `unknown variable` errors |
| R12 | Cross-file `import from C` actions failed validation | `collect_globals()` never handled `ImportC`/`ImportCpp` nodes at all (only the per-statement `validate_import()` did, too late for cross-file) | `Call to unknown action` warning |
| R13 | A module-scope global initialized from another module-scope constant | The module-scope `VarDecl` emit path lacked the constant-expression guard the Program-scope one already had; a module-only file (no `program` block) also has no `main()` to defer a non-constant init into | gcc: `initializer element is not constant` |
| R14 | `dictum_text` typedef emitted *after* cross-file `#include`s that declare prototypes using it | Emission-order bug in the Program header block | gcc: `unknown type name 'dictum_text'` |
| R15 | `use` statements re-processed a second time from inside `main()`'s body | `Use` was in PHASE 5's per-statement whitelist, and by then `_includes_emitted` was already true | A literal `#include "..."` line appears inside the generated `main()` function |
| R16 | A local variable inside an action body, initialized via a function call, was deferred into `main()` instead of initialized in place | The same `VarDecl` emit path is shared between true module/global scope (where C requires a constant initializer) and local/function scope (where it doesn't) — it didn't check which one it was in | `'file' undeclared`, `'filename' undeclared` inside `main()` — a **runtime crash waiting to happen**, not just a warning |
| R17 | Cross-file call-name mangling: `use X` + a bare call to an action `X` defines resolved to the *unmangled* name at the call site, while the definition got the module-prefixed name | `local_modules` / `_module_actions` (used to decide the C symbol name) were also only ever populated from the current file's own AST | gcc/ld: `undefined reference to 'emit_header'` (etc.) |
| R18 | An `import from C` alias equal to a libc-reserved name (`sqrt`, `sin`, `cos`, ...) got renamed to `dictum_<name>` at the call site, but the `extern`/declaration side used the real, unmangled name | `_resolve_call_name()`'s libc-collision-avoidance rename applies to genuine Dictum-defined actions; it should not apply to a deliberate FFI passthrough | ld: `undefined reference to 'dictum_sqrt'` |
| R19 (severe) | FFI (`import from C`) prototypes never appeared in the per-module shared cross-file header at all — only genuine Dictum `action` definitions with a `{ ... }` body were extracted | `generate_header()`'s regex only matched function *definitions*, never `extern ...;` declarations or the `static inline` alias wrappers | **Compiles with only a warning** (`implicit declaration of function`), links fine, then **silently truncates any non-`int` FFI return value** (confirmed via `gdb`: a real 64-bit `FILE*` from `fopen` was truncated to 32 bits, segfaulting three calls later, deep inside `fprintf`) |

**Why R19 is flagged severe:** it's the one bug on this list that does
not show up as a compile error or a link error — only a warning gcc
doesn't fail on by default. If you're testing "does it compile", this
one slips through every time. The only way it surfaced was running
the actual binary under `gdb` and reading register values at the
point of the crash. This is the concrete version of the §17 rule
"compiling clean is necessary, not sufficient" — here, "compiling
clean, and linking clean" *still* wasn't sufficient.

**The one non-compiler bug found the same way:** the CNC project's own
`gcode_validator.dict` rejected every cutting move with `target.z less
than 0.0`, but standard CNC convention is that cutting *into* material
means going *below* a `Z = 0` reference surface — i.e. negative Z is
correct and expected for a real cut. Every toolpath action's opening
rapid move (`Z = safe_z`, positive) passed validation, and its very
next move (the plunge to cutting depth, negative Z) always failed and
returned early — so the generated G-code silently had *only*
positioning moves and no actual cutting passes, no error, no crash.
This was invisible without actually reading the generated `.nc` file
and the program's own stdout (`print`ed `VALIDATION FAIL: Z below
zero` four times, once per operation) — a good example of why §17
step 3 ("compare against an independently-known-correct expected
value") matters even when everything else looks fine.

---

---

## 18b. A tenth compiler bug (later session): nested `if` inside a plain `otherwise`

Found the same way as §18 — building a real project (`cnc_vibecoder`'s
sidebar UI) and running it, not just compiling it. **Symptom:** a
confusing `Unknown top-level 'if'` error, reported many lines away
from the actual mistake, whenever an `if` statement was nested inside
a plain `otherwise` block (no such error when nested inside a `then`
block — confirmed by isolating both cases separately).

**Root cause**, confirmed by instrumenting the real `Lexer` and
reading the actual token stream (not guessed): `parser.py`'s
`parse_if()`, right after matching `otherwise`, called
`consume_newlines()` — which strips NEWLINE, INDENT, *and* DEDENT
tokens indiscriminately. That's too greedy for this one spot: the very
next check exists to tell "a chained `otherwise if`" (real tokens:
`if` immediately, no INDENT, same physical line) apart from "a nested
fresh `if` statement" (real tokens: NEWLINE, INDENT, then `if`, on the
next line). With the INDENT already eaten by the over-eager
`consume_newlines()`, both cases looked identical to that check — so a
genuinely nested `if` got mis-parsed as this `if`'s own `otherwise if`
clause, silently stealing tokens meant for the enclosing block.

**Fixed**: at both places this check happens (the first-level
`otherwise`/`otherwise if` check, and the equivalent one inside a
deeper `otherwise if ... otherwise` chain), only strip NEWLINE tokens
before the check — not INDENT/DEDENT. Regression test **R21** in
`compiler/run_selftest.py` covers this exact shape (nested `if`/`otherwise`
inside an outer `otherwise`) and checks the actual runtime output, not
just that it compiles.

**Practical effect for anyone writing `.dict` by hand**: nesting an
`if` inside a plain `otherwise` branch is now safe and behaves exactly
like nesting inside a `then` branch always did. If you're reading an
older `.dict` file that flattens this into two separate top-level `if`
blocks to avoid the bug (a workaround used in `cnc_vibecoder` before
this fix), that workaround is no longer necessary, though it isn't
wrong either — both forms now produce correct results.

---

## 18c. `dict_syntax_check.py` can go stale and give false negatives — always regenerate after a `parser.py` fix

Found while building `cnc_vibecoder`'s DXF/STL import UI (same "build a
real project, run every tool against it" discipline as §18/§18b).
**Symptom:** `dict_syntax_check.py` reported `SYNTAX ERROR: Unexpected
token NEWLINE` on a `main.dict` file that used a nested `if` inside a
plain `otherwise` block — the exact construct §18b's fix made valid.
Feeding the same source directly to the real, live
`compiler/dictumc/parser.py` (`from dictumc.parser import Parser`)
parsed it with no error at all.

**Root cause**: `dict_syntax_check.py` is not itself hand-maintained —
its own header comment says so — it's a generated, frozen
concatenation of `lexer.py` + `ast_nodes.py` + `type_registry.py` +
`parser.py`, produced by
`scripts/build_dict_syntax_check.py`, specifically so the standalone
checker can never *silently* disagree with the real compiler about
what's valid syntax. But "can't silently disagree" only holds if the
snapshot is regenerated every time those source files change. §18b's
nested-if-in-`otherwise` fix landed in the real `parser.py` (and is
covered by regression test R21) without the snapshot being
regenerated — so the standalone checker kept the pre-fix parsing logic
and kept reporting the pre-fix bug as if it still existed, on
perfectly valid code.

**Fixed**: ran `python3 scripts/build_dict_syntax_check.py` from the
repo root, which regenerates `dict_syntax_check.py` from the current
`lexer.py`/`ast_nodes.py`/`type_registry.py`/`parser.py`. Confirmed
fixed by re-running the checker against the same file (now passes) and
the compiler's own `run_selftest.py` (22/22 regression tests pass,
including R21).

**Practical effect for anyone using this checker**: if
`dict_syntax_check.py` rejects code that this reference document says
should be valid, do not assume the code is wrong and rewrite it to
avoid the construct. First check whether the checker itself is stale —
either regenerate it (`scripts/build_dict_syntax_check.py`) if you
have write access to the compiler repo, or independently confirm
against the real parser directly (`Parser(Lexer(source).tokenize()).parse()`)
before trusting the checker's verdict. This is the same "a tool
reporting failure isn't automatically right" lesson as trusting gcc
error messages over assumptions (§17) — it applies to Dictum's own
tooling too, not just to C/C++ compiler output. **Rule, restated from
the regeneration script's own docstring**: any change to
`lexer.py`, `ast_nodes.py`, `type_registry.py`, or `parser.py` is not
complete until `scripts/build_dict_syntax_check.py` has been re-run.
Guide B §4 already required this for Case C fixes in that area; this
session is a real example of what happens when that step is skipped.

---

## 18d. The same staleness recurred, worse, when merging two independently-fixed snapshots [NEW]

§18c documented the first case: `dict_syntax_check.py` going stale
after a single `parser.py` fix. A later session found a second,
compounded case while merging two separately-produced copies of the
compiler that had each fixed different things — one had the §18b
nested-`if` parser fix but not the `i16`/`f64` type additions
(§2/R22); the other had `i16`/`f64` and a real
`generate_import_c.py` (§13/Guide B §2a) but its own copy of
`dict_syntax_check.py` had **never been regenerated at all** across
either round of changes — it still contained the pre-§18b buggy
`consume_newlines()` call at both fix sites, *and* had no `i16`/`f64`
entries whatsoever, meaning it silently predated both fixes.

**The lesson this adds beyond §18c**: don't assume either copy's
`dict_syntax_check.py` is the "current" one just because one round of
edits happened after the other, or because a file merge only touched
`type_registry.py`/`run_selftest.py` and looked untouched otherwise.
When combining work from more than one source (two sessions, two
branches, two people), regenerate `dict_syntax_check.py` fresh via
`scripts/build_dict_syntax_check.py` from the merged
`lexer.py`/`ast_nodes.py`/`type_registry.py`/`parser.py` rather than
picking either existing snapshot — a snapshot that "looks recent" can
still silently predate a fix that landed in a different copy of the
repo. Confirmed fixed by regenerating and diffing the result against
both prior copies: it now reflects both the nested-`if` fix and the
`i16`/`f64` additions that neither individual copy's checker had
together.

---

## 19. Build Manifest

Guides B and C need to know your target before doing anything with
your submission. Every `.dict` submission — single file or project
directory — must be accompanied by a short, plain-text Build Manifest.
For a project directory, put it in `MANIFEST.txt` at the project root.
For a single file, put it as a comment block at the top of the file.

```
TARGET: linux | windows | both
BACKEND: c | cpp
CPP_STANDARD: 17 | 20 | 23        (only present if BACKEND: cpp)
LIBRARIES: comma-separated real library names used via `import from C`/`C++`, or `none`
GUI: yes | no
```

**Rules for filling this out:**

- `GUI: yes` if any `import from C`/`C++` binding you used initializes
  a window (e.g. the raylib bridge's `rl_InitWindow`, or any SDL/GLFW
  equivalent). Guide C uses this single field to decide whether it
  needs headless-display verification (Xvfb, and Wine if the target is
  Windows) or can just run the binary directly and check its output.
  Getting this field right matters — an unnecessary GUI check wastes a
  round-trip, and a missed one means a window-opening bug ships
  unverified.
- If you don't know the target yet, write `TARGET: linux`. `.dict`
  source has no platform-conditional syntax — there is no way to write
  "do X on Windows, Y on Linux" inside a `.dict` file itself — so the
  manifest is the *only* place platform intent belongs. Never try to
  encode platform branching into the `.dict` source.
- **Do not guess whether a library is "blessed" for the declared
  target.** Just name what you actually used (`LIBRARIES: raylib,
  sqlite3`); Guide B checks blessing status against its own
  target-tagged registry. If something isn't blessed for your
  declared target, that's Guide B's job to detect and route, not
  yours to work around.
- List every `import from C`/`C++` library you used, even ones you
  believe are already blessed. Guide B still needs the full list to
  decide which parts of the build need cross-target verification —
  don't only list the ones you think are new.

A submission with no manifest should be treated by Guide B as
`TARGET: linux, BACKEND: c, LIBRARIES: none, GUI: no` — the narrowest,
least-assuming default — never assumed to be Windows-ready or
GUI-capable without being told.

---

## 20. README — describing what the program is supposed to do [NEW]

The Build Manifest (§19) tells Guides B and C *how* to build and run
your submission. It deliberately says nothing about *what the program
is supposed to do* or *what correct behavior looks like* — and both
Guide B (§0) and Guide C (throughout) repeatedly need to "compare
against an independently known-correct expected value" to actually
verify anything. Without this section, that expected value either has
to be reverse-engineered from the `.dict` source itself (unreliable —
the source could encode the wrong intent and still look internally
consistent) or invented on the spot by whoever's running the pipeline.

Every submission — single file or project directory — must therefore
also include a short `README.md` alongside the Build Manifest (same
location: project root for a directory, or immediately after the
manifest comment block for a single file). It is plain prose, not a
structured format like the manifest, and should cover:

- **What the program is for**, in one or two sentences — the actual
  goal, not a restatement of the code.
- **Expected behavior/output, concretely enough to verify against.**
  For a console/headless program (`GUI: no`): what the output (stdout
  or a written file) should actually contain — specific values,
  ranges, line counts, or a computable expected result, not "it should
  work correctly." For a GUI program (`GUI: yes`): what should
  visually be on screen once it's running — e.g. "a single window,
  dark background, a red rectangle in the top-left quadrant" — plus,
  if the program is meant to animate or respond to input, what should
  visibly *change* over time or in response to a specific action (this
  is what Guide C §2c's screen-recording check needs to confirm
  against — a static description alone can't verify motion).
- **Anything you're intentionally not implementing yet**, so an
  incomplete feature doesn't get reported as a broken one.

This is not a substitute for the manifest's machine-parseable fields —
keep both. The manifest says how to build it; the README says what
"correct" means once it's built and running.

**If you don't know what correct output looks like precisely enough to
write this section** (e.g. you're translating an ambiguous request),
say so explicitly in the README rather than guessing — this is the
same "don't guess, ask" discipline as Guide B's Case B, applied before
the submission ever reaches Guide B.

---

## 21. Tooling — building, checking, and knowing what exists [NEW]

Everything above is the language itself. These are the real,
already-built tools that go with it — worth knowing before reaching
for a hand-rolled `gcc`/`Makefile` invocation or grepping compiler
source to answer "does X exist."

- **`tools/dictum.py`** — one command instead of knowing every backend's
  own build steps by hand (`make` for c/cpp, `build.sh` for nim,
  `--link` flags `import from C` doesn't carry, `--passL` ordering for
  nim). `dictum build <path> [--backend c|cpp|nim]` builds a single file
  or a project directory and resolves link flags from the blessed
  manifests automatically. `dictum check <path>` builds on **all three**
  backends and diffs the output — cross-backend VALUE disagreement has
  been this project's single highest-yield bug signal (it caught a C++
  shadowing bug that a 94-test suite and a full feature×context matrix
  both missed). `dictum libs` shows which libraries are blessed, on
  which targets.
- **`dictum vocabulary [--json]`** — one machine-readable artefact
  (regenerated fresh from the real registries every time, never
  hand-maintained) covering every grammar keyword, all 92 stdlib
  signatures with live per-backend status, and every blessed library's
  real bindings. Use this — not memory, not grepping compiler source —
  to check "does X exist" or "what's its exact signature" before
  writing a call to it.
- **The Nim stdlib bridge (`dictumc/nim_stdlib.py`)** — `use
  Text`/`File`/`Math`/etc. work identically on the **Nim backend**, not
  just C/C++. This used to be the single biggest gap making Nim a
  second-class backend (any stdlib-using program failed on Nim with
  "undeclared identifier"); it's real now, auto-enabled with no extra
  flag, and stdlib output is confirmed byte-identical across all three
  backends (R84 in `compiler/run_selftest.py`). Current coverage: 40 of
  92 stdlib functions have a Nim mapping — check `dictum vocabulary`'s
  `nim_available` field per function rather than assuming.
