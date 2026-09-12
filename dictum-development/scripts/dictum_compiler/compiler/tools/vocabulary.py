#!/usr/bin/env python3
"""
vocabulary.py — `dictum vocabulary`: one machine-readable artefact unifying
everything an AI author may legally say in Dictum, generated FRESH from the
real registries every time it runs. Never hand-maintained.

THE GAP THIS CLOSES (HANDOFF.md §9.1 / SOURCE_OF_TRUTH.md "the crux")
-----------------------------------------------------------------------
"What exists" was scattered across four places with no machine-readable
union:
  - grammar keywords          -> dictumc/grammar.py       (a Python set)
  - 92 stdlib functions        -> dictumc/stdlib_registry.py (a Python dict)
  - 10 blessed bindings        -> blessed/manifests/*.json
  - the language spec (prose)  -> references/GUIDE_A_*.md  (stale)

An AI author had to read the compiler's own source to know what it may
say -- and even then still got it wrong: `repeat N times` (missing
`using COUNTER`), map syntax, `produce failure with text`, `to the power
of` -- three-plus times in a single session, WITH the reference open.
That is not a human-ergonomics footnote; the AI is the intended author,
so every syntax miss is an authoring failure, fresh every session (a
human learns a grammar once; an AI does not carry that memory forward).

This command answers three questions without grepping source:
  1. Does X exist at all (keyword / stdlib function / blessed binding)?
  2. What is its exact callable form / signature?
  3. Is it verified ("blessed") on the backend I'm targeting?

WHAT THIS v1 DOES NOT COVER
-----------------------------
Full BNF-level extraction of every parseable sentence FORM straight from
parser.py's recursive-descent productions (e.g. the exact shape of
`repeat N times using i`) is a larger project -- parser.py is control
flow, not a data table, so there is no single structure to introspect
for that yet. This command unifies the three real DATA-TABLE registries
(keywords, stdlib, blessed libraries), which is fully derived and can
never drift from the code because it IS the code, plus one small,
explicitly-labeled, HAND-CURATED `common_mistakes` section covering the
known recurring sentence-form gotchas. The two sections are kept
visibly separate in the output (`"source": "registry"` vs `"source":
"curated"`) so a consumer never mistakes the curated list for an
exhaustive grammar. Closing that gap for real is tracked as follow-on
work: a grammar-derived sentence-form extractor from parser.py/grammar.py,
not a second hand-maintained list.

`common_mistakes` must be kept in sync with
dictum-development/SKILL.md's "Syntax quick reference" section, which is
the authoritative human-facing source for the same gotchas -- this file
is the machine-readable mirror of it, not an independent list.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = HERE
COMPILER_DIR = os.path.dirname(TOOLS_DIR)
MANIFEST_DIR = os.path.join(COMPILER_DIR, "blessed", "manifests")
BACKENDS = ("c", "cpp", "nim")

sys.path.insert(0, COMPILER_DIR)

# ---------------------------------------------------------------------------
# Hand-curated, explicitly-labeled: the recurring sentence-form mistakes
# this project's own AI-authored development actually hit. Mirror of
# dictum-development/SKILL.md's "Syntax quick reference" -- update both
# together.
# ---------------------------------------------------------------------------
COMMON_MISTAKES = [
    {
        "wrong": "repeat 5 times",
        "right": "repeat 5 times using i",
        "note": "The loop counter name is required, not optional.",
    },
    {
        "wrong": "if x is greater than 3",
        "right": "if x is greater than 3 then",
        "note": "`if COND` with no `then` is a parse error. Else-branch keyword is `otherwise`, not `else`.",
    },
    {
        "wrong": "the length of nums   (nums is a list)",
        "right": "the count of nums",
        "note": "`length` is text-only (strlen-equivalent). Lists/sets/maps use `the count of X`.",
    },
    {
        "wrong": "put 30 at \"alice\" in ages   (vs)   put 30 into total",
        "right": "map assignment uses `put V at K in NAME`; plain assignment uses `put V into TARGET`",
        "note": "Two different statements disambiguated by the keyword right after the value (`at` vs `into`) -- do not confuse them.",
    },
    {
        "wrong": "takes x as whole number and y as whole number",
        "right": "takes whole number and whole number",
        "note": "`import from C`/`import from C++` parameter lists are bare types joined by `and` -- no parameter names.",
    },
    {
        "wrong": "nums as list of whole number with values [1, 2, 3]",
        "right": "nums as list of whole number with values 1, 2, 3",
        "note": "List literals are `with values` (plural, comma-separated), never bracket syntax.",
    },
    {
        "wrong": "x to the power of 2   (as a bare top-level expression form guess)",
        "right": "see references/GUIDE_A_dict_language_reference.md for the exact `to the power of` production before using it",
        "note": "Flagged in HANDOFF.md §2 as one of the forms actually mis-produced this session -- confirm against the reference, don't guess from how it reads.",
    },
    {
        "wrong": "produce failure \"message\"",
        "right": "produce failure with text \"message\"",
        "note": "Flagged in HANDOFF.md §2 as one of the forms actually mis-produced this session.",
    },
]


def _load_grammar_and_types():
    from dictumc.grammar import DictumGrammar
    return sorted(DictumGrammar.KEYWORDS), sorted(DictumGrammar.TYPE_WORDS)


def _load_stdlib():
    """Return the 92 stdlib entries, each tagged with its real (not
    assumed) status per backend: c/cpp status comes from the same
    real/stub/missing classification run_selftest.py's §1 static
    inventory performs (grepping the real runtime/*.h body, not trusting
    the registry's mere existence); nim status comes from whether the
    function has a real entry in nim_stdlib.NIM_STDLIB."""
    from dictumc.stdlib_registry import STDLIB_ACTION_FAMILIES
    from dictumc.nim_stdlib import NIM_STDLIB

    try:
        import run_selftest
        # run_inventory() unconditionally prints its own report via
        # run_selftest.log() -- fine for a human running run_selftest.py
        # directly, but fatal here: it would land on the SAME stdout as
        # this command's own --json output and corrupt it. This tool's
        # own summary already surfaces the counts that matter, so the
        # inner report is suppressed rather than duplicated.
        with contextlib.redirect_stdout(io.StringIO()):
            real, stub, missing = run_selftest.run_inventory()
    except Exception as exc:  # pragma: no cover -- degrade, don't crash
        real, stub, missing = [], [], []
        print(f"warning: could not run c/cpp stdlib inventory ({exc}); "
              f"c_cpp_status will be 'unknown' for all entries", file=sys.stderr)

    real_set, stub_set, missing_set = set(real), set(stub), set(missing)

    out = []
    for name, (c_impl, params, returns) in sorted(STDLIB_ACTION_FAMILIES.items()):
        if name in real_set:
            c_cpp_status = "real"
        elif name in stub_set:
            c_cpp_status = "stub"
        elif name in missing_set:
            c_cpp_status = "missing"
        else:
            c_cpp_status = "unknown"
        out.append({
            "name": name,
            "c_impl": c_impl,
            "params": params,
            "returns": returns,
            "c_cpp_status": c_cpp_status,
            "nim_available": name in NIM_STDLIB,
        })
    return out


def _load_blessed_libraries():
    """One entry per blessed/manifests/*.json, with real per-target
    verification verdicts from import_c_registry.is_blessed() (the
    authoritative source -- a manifest's own `_verified` block is a
    point-in-time snapshot; the registry is what dict_triage.py's Case D
    check actually queries)."""
    try:
        from dictumc import import_c_registry as reg
        reg_available = True
    except Exception:
        reg = None
        reg_available = False

    out = []
    if not os.path.isdir(MANIFEST_DIR):
        return out
    for fname in sorted(os.listdir(MANIFEST_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(MANIFEST_DIR, fname)
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as exc:
            print(f"warning: skipping unparseable manifest {fname}: {exc}", file=sys.stderr)
            continue
        lib = data.get("library", fname[:-5])
        if reg_available:
            verified = {t: reg.is_blessed(lib, t) for t in BACKENDS}
        else:
            verified = dict(data.get("_verified", {}))
        out.append({
            "library": lib,
            "link": data.get("link", []),
            "headers": data.get("headers", []),
            "functions": [
                {
                    "alias": fn.get("alias", fn.get("c_name")),
                    "c_name": fn.get("c_name"),
                    "params": fn.get("params", []),
                    "returns": fn.get("returns"),
                }
                for fn in data.get("imports", [])
            ],
            "verified": verified,
        })
    return out


def build_vocabulary() -> dict:
    keywords, type_words = _load_grammar_and_types()
    stdlib = _load_stdlib()
    blessed = _load_blessed_libraries()

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "keywords": {
            "source": "registry",
            "derived_from": "dictumc/grammar.py DictumGrammar.KEYWORDS",
            "count": len(keywords),
            "items": keywords,
        },
        "type_words": {
            "source": "registry",
            "derived_from": "dictumc/type_registry.py all_type_words()",
            "count": len(type_words),
            "items": type_words,
        },
        "stdlib": {
            "source": "registry",
            "derived_from": "dictumc/stdlib_registry.py STDLIB_ACTION_FAMILIES "
                             "(status cross-checked against runtime/*.h and nim_stdlib.py)",
            "count": len(stdlib),
            "items": stdlib,
        },
        "blessed_libraries": {
            "source": "registry",
            "derived_from": "blessed/manifests/*.json + dictumc/import_c_registry.py",
            "count": len(blessed),
            "items": blessed,
        },
        "common_mistakes": {
            "source": "curated",
            "derived_from": "dictum-development/SKILL.md 'Syntax quick reference' "
                             "(hand-maintained -- keep the two in sync)",
            "count": len(COMMON_MISTAKES),
            "items": COMMON_MISTAKES,
        },
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit raw JSON (default: human summary)")
    ap.add_argument("--section", choices=["keywords", "type_words", "stdlib",
                                           "blessed_libraries", "common_mistakes"],
                     help="print only one section")
    args = ap.parse_args(argv)

    vocab = build_vocabulary()

    if args.section:
        payload = vocab[args.section]
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"{args.section} ({payload['count']} entries, source={payload['source']}):")
            for item in payload["items"]:
                print(f"  {item}")
        return 0

    if args.json:
        print(json.dumps(vocab, indent=2))
        return 0

    print(f"dictum vocabulary — generated {vocab['generated_at']}")
    for key in ("keywords", "type_words", "stdlib", "blessed_libraries", "common_mistakes"):
        sec = vocab[key]
        print(f"  {key:<20} {sec['count']:>4}  ({sec['source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
