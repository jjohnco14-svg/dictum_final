"""
structured_errors.py — turns a subset of Case A parser errors into a real
repair-loop payload instead of raw parser prose (HANDOFF.md §9.2).

THE GAP THIS CLOSES
--------------------
`dict_triage.py --json` already existed and already classified failures
into Case A/B/C/D, but a Case A error's payload was just whatever the
parser's exception happened to say -- e.g. both `repeat 4 times` (missing
`using i`) and `if x is greater than 3` (missing `then`) produce the
IDENTICAL generic message `"Expected word, got NEWLINE at line N"`. An AI
consuming that JSON gets a location but has to re-derive what's actually
wrong from scratch -- exactly the authoring-failure class HANDOFF.md §2
names as the top-tier reliability problem (this project's own AI author
got these exact forms wrong, more than once, WITH the reference open).

The fix isn't a better parser error message (the parser's own error
recovery genuinely can't always tell "missing `using`" from "missing
`then`" -- both just look like "ran out of tokens on this line" to it).
Instead, this module independently re-examines the OFFENDING SOURCE LINE
against a small set of known, real mistake patterns -- the same ones
curated in tools/vocabulary.py's `common_mistakes` (kept in sync; this is
the machine-actionable form of the same knowledge, not a second list to
drift from it) -- and when one matches, attaches:

    {"construct": "repeat", "expected": "repeat <n> times using <counter>",
     "got": "repeat 4 times", "fix": "add `using <counter>` -- e.g. ..."}

alongside (never instead of) the original `line`/`message`, so a consumer
that doesn't recognize the enrichment still gets exactly what it got
before.

WHAT THIS DOES NOT DO
-----------------------
This is a small, explicit pattern list, not a general grammar-diff engine
-- see HANDOFF.md §9.1's own module docstring for the equivalent honesty
note. An error whose source line doesn't match one of these patterns is
returned unchanged (`line`/`message` only) -- never a fabricated
guess. Growing this list should stay in lockstep with
tools/vocabulary.py's `common_mistakes` (and, ideally, eventually be
generated from the same real mistakes discovered by writing more real
programs, the way every entry currently here was).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _repeat_missing_using(text: str) -> Optional[Dict[str, str]]:
    stripped = text.strip()
    m = re.match(r'^repeat\s+.+\s+times\s*$', stripped)
    if not m:
        return None
    if re.search(r'\busing\b', stripped):
        return None  # has `using` somewhere unusual but present -- not this mistake
    return {
        "expected": "repeat <n> times using <counter>",
        "fix": f"add `using <counter>` -- e.g. `{stripped} using i`",
    }


def _if_missing_then(text: str) -> Optional[Dict[str, str]]:
    stripped = text.strip()
    if not re.match(r'^if\b', stripped):
        return None
    if re.search(r'\bthen\s*$', stripped):
        return None  # already has it
    return {
        "expected": "if <condition> then",
        "fix": f"add `then` at the end of the line -- `{stripped} then`",
    }


def _produce_failure_missing_with_text(text: str) -> Optional[Dict[str, str]]:
    stripped = text.strip()
    if not re.match(r'^produce\s+failure\s+"', stripped):
        return None
    fixed_line = re.sub(r'^produce\s+failure\s+', 'produce failure with text ', stripped)
    return {
        "expected": 'produce failure with text "..."',
        "fix": f"add `with text` -- `{fixed_line}`",
    }


# construct name -> matcher(source_line_text) -> {"expected", "fix"} | None
# Mirror of tools/vocabulary.py's COMMON_MISTAKES -- keep both in sync.
PATTERNS: List[tuple] = [
    ("repeat", _repeat_missing_using),
    ("if", _if_missing_then),
    ("produce_failure", _produce_failure_missing_with_text),
]


def enrich_error(error: Dict[str, Any], source_lines: List[str]) -> Dict[str, Any]:
    """Given one {"line": int|None, "message": str} error and the full
    source split into lines (1-indexed access via line-1), return the
    same dict enriched with construct/expected/got/fix if the offending
    line matches a known pattern, otherwise the dict unchanged.

    Checks the reported line FIRST, then one line back. The underlying
    parser error frequently points at where it gave up, not at the real
    mistake -- confirmed on real repros: `repeat 4 times` on line 2
    (missing `using`) reports its SyntaxError at line 3 (the next
    token's line, since the newline-then-INDENT/next-statement is what
    actually fails to parse), and `if x is greater than 3` on line 3
    (missing `then`) reports at line 4, the exact same way. Checking one
    line back before giving up catches both real cases; the enriched
    payload reports the CORRECTED line (where the real mistake is), not
    the parser's original (downstream) line, so a consumer editing
    `fix` at the reported line edits the right one."""
    line_no = error.get("line")
    if not line_no:
        return error
    for candidate in (line_no, line_no - 1):
        if candidate < 1 or candidate > len(source_lines):
            continue
        text = source_lines[candidate - 1]
        for construct, matcher in PATTERNS:
            hit = matcher(text)
            if hit:
                return {
                    **error,
                    "line": candidate,
                    "construct": construct,
                    "expected": hit["expected"],
                    "got": text.strip(),
                    "fix": hit["fix"],
                }
    return error


def enrich_errors(errors: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    source_lines = source.splitlines()
    return [enrich_error(e, source_lines) for e in errors]
