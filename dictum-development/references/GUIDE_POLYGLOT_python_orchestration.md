# Python Orchestration + Dictum Kernel — When and How to Split a Project Across Both

Use this when a project has a mix of "glue code" (I/O, argument parsing,
calling an LLM, CLI/HTTP handling, file wrangling) and "logic that must
be right" (a calculation, a control rule, a pricing/dosage/tolerance
check — anything where a wrong answer costs money, safety, or trust).
Don't write the whole thing in Dictum, and don't write the
verification-critical part in Python either. Split it.

## The one-paragraph version

**Python orchestrates. Dictum verifies. There is no Python backend and
none is planned** — Dictum doesn't need to be a general-purpose
language competing with Python's ecosystem; it only needs to be the
part of the program where "I can prove this is right, on 3 backends,
byte-for-byte" actually matters. Python has no memory-safety failure
class the way C/C++ does (no buffer overflows, no undefined behavior,
no raw pointers) — its risk is ordinary logic bugs and exceptions, both
things a test suite and a type checker already handle well. That's
exactly why it's the right choice for everything Dictum *isn't* good
at, and exactly why the boundary between them — not either side alone
— is the one place this split can go quietly wrong.

## Decision table

| This kind of code...                                   | Goes in     | Why |
|----------------------------------------------------------|-------------|-----|
| CLI/argument parsing, file I/O, HTTP, calling an LLM/API | **Python**  | ecosystem, iteration speed, no verification story needed |
| A calculation, rule, or control loop a wrong answer is expensive for | **Dictum**  | native, byte-reproducible, `dictum check` across 3 backends |
| Direct access to a C/C++ library Dictum doesn't reimplement | **C/C++ via `import from C`/`C++`** | already solved, see `GUIDE_A_dict_language_reference.md` §13-14 |

If you're not sure which side a piece of logic belongs on, ask: **if
this is wrong, does it just look bad, or does someone lose money/get
hurt/lose trust?** "Looks bad" → Python is fine. Anything else →
Dictum.

## The real workflow, step by step

1. **Write the Dictum kernel** — one or more `action`s with a plain
   scalar signature (see "what's bindable" below). Nothing exotic:
   this file's whole job is to be simple enough to audit and verify.
2. **Compile it to C and build a shared library:**
   ```
   python3 scripts/dictum_compiler/compiler/dictumc_cli.py kernel.dict --backend c --output kernel.c
   gcc -std=c11 -O2 -fPIC -shared -I scripts/dictum_compiler/compiler/runtime kernel.c -o libkernel.so -lm
   ```
   (There's no `--shared` flag on `dictumc_cli.py` itself yet — the
   generated C is a plain, real, ctypes-compatible C ABI, so a normal
   `gcc -shared` build is all that's needed. `dictum check` still works
   on the same source for cross-backend verification before you ship
   it as a `.so`.)
3. **Generate the binding — never hand-write ctypes argtypes:**
   ```
   python3 scripts/dictum_compiler/compiler/tools/dictum.py emit-binding kernel.dict --lib ./libkernel.so --out kernel_binding.py
   ```
   This is the step that actually matters. See "why not just write
   ctypes by hand" below — this isn't a convenience wrapper, it's
   closing a real, reproduced silent-wrong-answer bug class.
4. **Import and call it from Python, by keyword, always:**
   ```python
   from kernel_binding import calculate_tariff
   result = calculate_tariff(weight_kg=10.0, distance_km=100.0, rate_class=2)
   ```
   The generated wrapper is keyword-only on purpose — `calculate_tariff(10.0, 100.0, 2)`
   is a hard `TypeError`, not a maybe-swapped-maybe-not silent risk.
5. **Write the `## Language Boundary` section** in the project's
   `SOURCE_OF_TRUTH_<project>.md` (Guide A §0 Phase 1b — see
   `GUIDE_A_dict_language_reference.md` for the exact format) and run:
   ```
   python3 scripts/dictum_compiler/compiler/verify/language_boundary_check.py \
       --source-of-truth SOURCE_OF_TRUTH_<project>.md --project .
   ```
   This is what makes "which language, and why" a decision a reviewer
   can check instead of trust — it doesn't just read the markdown, it
   re-parses the kernel and confirms every `exposes:` name really
   exists and is really bindable.

A complete, real, working example of all five steps together: `tests/polyglot/pricing_example/`
in the compiler bundle (`SOURCE_OF_TRUTH_pricing_example.md`,
`pricing_kernel.dict`, `orchestrator.py`).

## Why not just write ctypes by hand

Because it was tried, deliberately, to see what breaks. A real Dictum
kernel — `calculate_tariff(weight_kg, distance_km, rate_class)`, all
real numbers — was called via hand-written `ctypes` with
`weight_kg`/`distance_km` **swapped** at the call site. Both are
`c_double`. `ctypes` has no way to know two doubles were swapped — the
call ran, returned a real number, **112.8 instead of the correct
14.25**. No crash. No warning. That is the exact "wrong answer that
compiles and runs cleanly" failure class this whole project treats as
its top risk (see `SOURCE_OF_TRUTH.md`'s own history of exactly this
bug shape inside the compiler) — now shown to be just as real at the
Python/Dictum boundary. `dictum emit-binding`'s keyword-only wrappers
are the direct fix: the same swap attempted through the generated
binding either has to name the arguments explicitly (visible, auditable
in the caller's own code) or throws `TypeError` outright. There is no
third, silently-wrong outcome left.

## What's bindable right now (and what isn't)

`dictum emit-binding` only binds actions whose ENTIRE signature is
built from plain scalar types: `whole number`, `fractional number`,
`truth value`, `byte`, the fixed-width `i16`/`u16`/`i32`/.../`f32`/`f64`
family, plus `text` **as a parameter only**. Everything else is refused
per-action, with a clear reason, rather than guessed at:

- `text` as a **return** type — a returned string's ownership/lifetime
  (static literal vs. a runtime-built buffer) isn't verified end-to-end
  yet; binding it could hand Python a dangling or leaked pointer.
- `opaque pointer`, `result`, shapes, and container types (list/map/set)
  — no verified-safe ctypes representation for these yet.
- Generic (`any T`) actions — no single fixed ABI to bind.

If a kernel action needs one of these, either restructure it to return
a plain scalar (e.g. a status code plus an out-parameter of a supported
type) or don't expose that specific action across the boundary — do
the string handling on the Python side, or inside the kernel with
another Dictum action other than the one you bind.

## What this doesn't cover

This is deliberately narrow. It does not (and isn't trying to) cover:
gRPC/HTTP/message-queue interop, calling INTO Python FROM Dictum (the
direction is Python→Dictum only, on purpose — Dictum stays a leaf, not
an orchestrator), or a build-system integration that produces the
`.so` as part of a normal `dictum build` (there's no `--shared` flag
yet — step 2 above is a plain `gcc -shared` call for now). There is
older, unrelated, **unwired and untested** code in
`dictumc/polyglot_*.py` pursuing a much heavier multi-backend/gRPC
vision from this project's very first commit — it was never
integrated into the real pipeline and this workflow does not build on
it or depend on it.
