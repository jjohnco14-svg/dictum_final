#!/usr/bin/env python3
"""
guide_a_sync_check.py — flags drift between Guide A's prose and the real
grammar it's documenting.

The gap this closes: dict_triage.py's Case A always runs the REAL parser/
validator (dictumc/grammar.py's `DictumGrammar.KEYWORDS`), so its answers
are always correct regardless of whether Guide A's markdown is up to date.
But an AI *writing new* `.dict` source works from Guide A's prose, not from
grammar.py directly -- so if someone adds/removes a keyword in the grammar
and forgets to update the doc, dict_triage will still correctly reject the
resulting bad guess (that safety net doesn't break), but the AI will have
burned a round-trip discovering a mismatch the doc could have told it
about directly.

This script:
  - imports dictumc/grammar.py for real and reads DictumGrammar.KEYWORDS --
    the actual ground truth, not a second copy of the keyword list
  - checks whether each real keyword appears anywhere in Guide A's
    markdown as a plain word (case-insensitive, word-boundary match --
    not just backtick-quoted, since most of Guide A documents a keyword
    through an example sentence or section header rather than
    backtick-wrapping every single token)
  - reports any real keyword that never appears at all (UNDOCUMENTED --
    an AI writing from the doc alone would never learn this construct
    exists)

Calibration note: an earlier version of this script only matched
backtick-quoted single words, which produced ~90 false positives (common
words like "for", "as", "true" appear constantly in ordinary prose without
being individually backtick-quoted, even where the surrounding phrase *is*
documented -- e.g. "for each", "is equal to"). The looser whole-document
word match cuts that down to the genuine candidates (constructor/
destructor/method/private/public/virtual/override/unsafe/ref/unique/weak/
syscall/transmute and similar), at the cost of being unable to tell
"documented" from "the word merely appears in unrelated prose" -- so
still confirm each UNDOCUMENTED entry by eye rather than treating the list
as a mechanical proof of a gap, only as a shortlist worth checking.

This is NOT a full semantic diff (it can't tell if a *usage example* in
the doc is still valid grammar, only whether the vocabulary is mentioned
at all) -- it deliberately stays at the vocabulary level, which is what's
cheap and reliable to check mechanically.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Set

_WORD_RE = re.compile(r"[a-z]+")


def words_in_doc(markdown_path: str) -> Set[str]:
    text = open(markdown_path, encoding="utf-8", errors="replace").read().lower()
    return set(_WORD_RE.findall(text))


def real_keywords(dictumc_dir: str) -> Set[str]:
    sys.path.insert(0, dictumc_dir)
    import grammar  # type: ignore
    return set(grammar.DictumGrammar.KEYWORDS)


def check(guide_a_path: str, dictumc_dir: str) -> dict:
    keywords = real_keywords(dictumc_dir)
    mentioned = words_in_doc(guide_a_path)

    undocumented = sorted(kw for kw in keywords if kw.lower() not in mentioned)

    return {
        "real_keyword_count": len(keywords),
        "undocumented": undocumented,
        "ok": not undocumented,
    }


def print_human(report: dict) -> None:
    print(f"Real keywords in grammar.py: {report['real_keyword_count']}")
    if report["undocumented"]:
        print(f"\nUNDOCUMENTED -- real, parseable keywords that never appear anywhere in "
              f"Guide A, even loosely ({len(report['undocumented'])}) -- confirm each by eye, "
              f"this is a shortlist, not a proof:")
        for kw in report["undocumented"]:
            print(f"  {kw}")
    else:
        print("\nEvery real keyword appears somewhere in Guide A.")
    print()
    print("OVERALL: " + ("OK" if report["ok"] else "NEEDS ATTENTION -- see UNDOCUMENTED above"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--guide-a", required=True)
    ap.add_argument("--dictumc-dir", required=True, help="path to the dictumc/ package directory")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report = check(args.guide_a, args.dictumc_dir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
