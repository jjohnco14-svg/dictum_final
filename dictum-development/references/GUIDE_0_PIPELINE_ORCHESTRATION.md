# Guide 0 — Pipeline Orchestration

**Read this first, on every Dictum project, in every conversation —
including (especially) a fresh one with no memory of prior sessions.**

Guides A, B, and C are each real and each independently useful, but
none of them says how they chain together, and none of them says what
happens *before* Guide A (someone has to actually decide what the
project is). This document is the missing piece: the full pipeline
from "a person says they want something" to "a verified deliverable,"
and — because chat memory cannot be relied on — a way to figure out
*from the project's files alone*, with zero conversation history,
exactly what stage a project is at and what to do next.

If you are an AI picking up a project cold, skip to **§5 (Resume
Protocol)** first. It tells you which file to read to find out where
you are. Only then come back to the phase that applies.

---

## 1. The whole pipeline, one page

```
Phase 0   Discovery conversation with the person          (this doc, §2)
             |
             v  explicit "yes, that's the final project" confirmation
             |
Phase 1   Write SOURCE_OF_TRUTH_<project>.md, roadmap       (Guide A §0)
          half — birds-eye view + version-tagged [Rn] claims
             |
Phase 2   Append the Guide C Test Manifest to the same       (Guide A §0)
          file — turn each [Rn] into a checkable assertion
             |
Author    Write the .dict file(s) + a README, against       (Guide A,
          the language reference                             the rest of it)
             |
Guide B   Compile for real, classify any failure against     (Guide B,
          Guide A's syntax reference (Case A: fix .dict /     checking
          Case B: ask / Case C: fix the compiler / Case D:    against
          bless a library), loop until it compiles, links,    Guide A)
          and runs clean
             |
Guide C   Run the Phase 2 manifest against the real binary   (Guide C)
          + guide_a_coverage_check.py (every [Rn] has a
          check or an honest known_gaps entry)
             |
Deliver   package_for_client.py (client never receives the    (Guide C's
          .dict source, only the built artifact + a plain-    packaging
          English test report)                                 tooling)
```

Nothing here is new machinery — every step already exists as real,
gcc-verified tooling (see the SOURCE_OF_TRUTH.md changelog for each
piece). This document is the map between the pieces, not a new piece.

**Guide A is not just consulted before authoring — it's an active
input to Guide B.** Case A detection (§3 below, and Guide B §2) is
literally "does this match Guide A's documented syntax" — so Guide A
isn't a one-time reference you read once and set aside; it's the
ground truth Guide B's triage checks every single failure against.
Keeping it accurate (via `verify/guide_a_sync_check.py`) is part of
keeping triage reliable, not a separate documentation chore.

---

## 2. Phase 0 — the discovery conversation (NEW: not previously written down)

This is the step that used to only happen informally, in whatever way
a given conversation happened to go, which is exactly why it didn't
survive a fresh session. Do it explicitly, in this order:

1. **Ask clarifying questions** until you could describe the finished
   thing to a stranger without guessing. Typical gaps: what platform
   does it run on, is it console or GUI (Guide C branches its entire
   strategy on this), what's genuinely required vs. nice-to-have, what
   does "done" look like to the person asking.
2. **Present the plan back** as a short, concrete concept summary —
   not implementation detail yet, just: what it is, what it does, what
   it doesn't do. This is the person's chance to say "no, actually—"
   before any file exists.
3. **Get an explicit confirmation** ("yes, that's the final project" or
   equivalent) before writing anything. Don't infer confirmation from
   silence or from the conversation moving on.
4. Only once confirmed: the confirmed concept summary from step 2 *is*
   the raw material for Phase 1's "what the project is" paragraph —
   write it into `SOURCE_OF_TRUTH_<project>.md` essentially verbatim,
   then derive the tagged `[Rn]` roadmap claims from it.

**Why this has to be a distinct, named phase:** Guide A's Phase 1
already says to write a roadmap of concrete, checkable claims — but it
silently assumes those claims are already known. They aren't, at the
start of a real engagement; they're what Phase 0 produces. Skipping
straight to Phase 1 without an explicit Phase 0 is how a project ends
up with a roadmap that's actually the AI's guess at what the person
meant, discovered wrong three phases later.

**What Phase 0 does *not* try to solve:** genuine ambiguity that
survives the discovery conversation is Guide B's Case B, not a Phase 0
failure — if after asking, the right behavior for some specific edge
case still isn't decidable, say so explicitly in the roadmap or defer
that specific question to whoever's driving Guide B when it comes up,
rather than blocking the whole project on it.

---

## 3. Phases 1–2, authoring, Guide B, Guide C

These are each already fully specified in their own documents — this
section only states how they hand off to each other, not their
internals:

- **Phase 1/2 → authoring:** the roadmap and manifest exist *before*
  any `.dict` code is written, not derived from it afterward. Writing
  `.dict` against an already-decided spec is a fundamentally different
  (and easier, more honest) task than writing `.dict` and then
  rationalizing a spec to match what got built. Author against `v1`'s
  checklist first — a `v2`/`v3` claim isn't yours to start on until the
  person has confirmed v1 is actually done (Guide C passing, coverage
  clean) and wants to move the boundary.
- **Authoring → Guide B:** the moment a `.dict` file exists, it goes
  through Guide B's real-compile-and-classify loop (§1 and §2 of that
  document) before anyone looks at behavior — a project that doesn't
  compile has nothing worth behavior-checking yet. Case A's
  determination ("is this a `.dict` mistake") is a direct lookup
  against `GUIDE_A_dict_language_reference.md`, not a separate
  judgment — this is Guide A acting as an input to Guide B's process,
  not just something read once before writing code.
- **Guide B → Guide C:** only once Guide B reports clean (compiles,
  links, runs) does Guide C's manifest-driven verification start.
  `run_pipeline.py` already encodes this ordering as a hard stop, not
  a suggestion — see that script's own docstring.
- **Guide C → delivery:** a project isn't done when Guide C's checks
  pass; it's done when every `v1`-checklist `[Rn]` from Phase 1 is
  accounted for (`guide_a_coverage_check.py` is what proves that, not a
  human skimming the manifest) and `package_for_client.py` has produced
  the client-facing artifact. `v2`/`v3` items remaining unchecked is
  expected and fine — that's what the version boundary is for.

---

## 4. What autonomy this does and doesn't give you

Chaining these phases together (optionally as a scripted loop around
`dict_triage.py` / `run_pipeline.py` / `guide_a_coverage_check.py`)
gets you a genuinely unattended **Phase-1-through-Guide-C** loop for
the common case: an AI can author the `.dict`, hit a Case A mistake,
fix it, re-run, and keep going without a human watching every cycle,
because the manifest gives it a real, mechanical stopping condition
instead of "looks right."

It does **not** remove the human/AI judgment calls at the seams:

- **Phase 0** is inherently a conversation — no amount of tooling
  replaces asking a real person what they actually want.
- **Case B** (Guide B) is Guide B's own name for "this can't be
  resolved without asking" — the pipeline surfaces it clearly instead
  of guessing, it doesn't make it go away.
- **Case C fixes** (a genuine compiler/emitter bug or gap) change
  shared infrastructure every future project depends on. Auto-applying
  those unsupervised is a materially different risk than auto-fixing
  one project's `.dict` typo — keep Case C fixes gated behind a real
  regression test and, ideally, a second opinion, the same discipline
  this project's own CHANGELOG has followed for every Case C fix to
  date.
- **Writing Phase 2's numeric assertions** ("what correct looks like,
  in a form a script can check") is real interpretive work translating
  a plain-language claim into a concrete check — an AI can do it, but
  it's judgment, not a mechanical derivation from the claim text.

---

## 5. Resume protocol — figuring out where a project stands, with zero memory

A fresh conversation has no memory of prior sessions. It does not need
any: the project's own files are a complete, sufficient record of
where things stand, if you read them in this order.

1. **Does `SOURCE_OF_TRUTH_<project>.md` exist in the project root?**
   - No → Phase 0 hasn't happened yet (or wasn't written down). Start
     there. Do not skip to writing `.dict` code from a verbal
     description alone.
   - Yes → read it. Does it have a roadmap with tagged `[Rn]` claims?
     - No → Phase 1 is incomplete; finish it before continuing.

2. **Does the same file have a `## Guide C Test Manifest` section?**
   - No → Phase 2 is incomplete. Do this before trusting any behavior
     the code currently appears to have — an untested claim isn't a
     verified one just because the code happens to compile.
   - Yes → Phase 1/2 are done. The manifest is now the ground truth for
     "what should be true," not this conversation's assumptions.

3. **Do the `.dict` file(s) described in the roadmap exist?**
   - No → authoring hasn't started (or isn't finished). Write them
     against the roadmap/manifest that already exists — don't
     re-derive requirements from scratch.
   - Yes → continue.

4. **Run Guide B for real — don't assume from a prior summary that it
   still compiles:**
   ```
   python3 dict_triage.py <file>.dict
   ```
   or, for a whole project: `project_builder.py` / the project-mode
   path `run_pipeline.py` calls internally. Whatever the last session
   claimed, the actual compiler output right now is the only thing
   that matters — treat any stale "it compiled last time" claim in a
   conversation summary as unverified until re-run.

5. **If Guide B is clean, run Guide C for real:**
   ```
   python3 run_pipeline.py --project <dir> --manifest guide_c_manifest.json \
       --source-of-truth SOURCE_OF_TRUTH_<project>.md --backend <c|cpp>
   ```
   Read the real `overall_ok`/`stopped_at` verdict it returns. Don't
   infer project status from anything other than this command's actual
   output run just now.

6. **Confirm coverage, if you didn't already pass `--source-of-truth`
   to `run_pipeline.py` above** (if you did, it already ran this
   internally as its own Stage 3 — check `report["coverage_ok"]` in its
   output rather than re-running anything). Standalone invocation:
   ```
   python3 verify/guide_a_coverage_check.py \
       --source-of-truth SOURCE_OF_TRUTH_<project>.md \
       --manifest guide_c_manifest.json --json
   ```
   confirms every `[Rn]` is either covered or honestly listed in
   `known_gaps`. Only at this point is the project actually in a
   deliverable state.

**The governing rule for resuming any project:** trust the files and
the real tool output from commands run *in this session*, never a
conversation summary's claim about what passed before. A prior
session's "regression suite is 45/45" is a fact about the past, not a
guarantee about the code as it sits on disk right now — re-run it.
