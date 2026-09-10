#!/usr/bin/env python3
"""
Regenerates dict_syntax_check.py from the real, canonical source files
(compiler/dictumc/lexer.py, ast_nodes.py, type_registry.py, parser.py).

WHY THIS SCRIPT EXISTS:
dict_syntax_check.py is a standalone snapshot/concatenation of those
four files, built this way specifically so it can never *silently*
diverge from what the real compiler accepts (see its own header
comment for the full reasoning). But a snapshot is exactly that: a
copy, taken at one point in time. If any of the four source files are
changed later -- most obviously, any bugfix to parser.py -- the
standalone copy does NOT update itself. Left unnoticed, that turns
dict_syntax_check.py into precisely the kind of second, silently
drifting source of truth it was built to avoid.

RULE: any time compiler/dictumc/lexer.py, ast_nodes.py,
type_registry.py, or parser.py changes, re-run this script before
calling the change done. This is not optional cleanup -- it's part of
what "the fix is complete" means for any change touching those files.
Guide B's triage protocol (GUIDE_B_triage_protocol.md §4) requires
this as part of any Case C fix in that area.

Usage:
    python3 scripts/build_dict_syntax_check.py
    (run from the repository root; writes dict_syntax_check.py in place)
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DICTUMC_DIR = REPO_ROOT / "compiler" / "dictumc"
OUTPUT_PATH = REPO_ROOT / "dict_syntax_check.py"

CLI_WRAPPER = '''

# ============================================================================
# CLI driver — syntax-only validation, no C/C++ emission, no gcc required.
#
# This intentionally reuses the REAL lexer.py + ast_nodes.py +
# type_registry.py + parser.py from the Dictum compiler, concatenated
# unmodified above (only the package-relative `from .lexer import ...` /
# `from .ast_nodes import ...` / lazy `from .type_registry import ...`
# lines were adjusted, since everything now lives in one file). This is
# a deliberate choice: a fresh, hand-written re-implementation of
# Dictum's grammar rules would be a second source of truth that can
# silently drift from what the real compiler actually accepts --
# exactly the class of problem this project has already been bitten by
# more than once (e.g. the `match_word()` OR-vs-AND bug, the
# colon-assumption bug in project_builder.py's separate lightweight
# scanner). Reusing the real parsing code means this tool can never
# disagree with dictumc_cli.py about whether something is valid syntax,
# by construction -- PROVIDED it is kept in sync. See
# scripts/build_dict_syntax_check.py, which generated this file: any
# change to the real lexer.py/ast_nodes.py/type_registry.py/parser.py
# requires re-running that script, or this file silently goes stale.
#
# What this DOES check: that a .dict file tokenizes and parses cleanly
# -- i.e. it is syntactically well-formed Dictum, using real keywords
# in a structure the real grammar accepts.
#
# What this does NOT check (by design -- these need the full compiler):
#   - Whether it emits correct C/C++ (needs emit_c.py / emit_cpp.py)
#   - Whether it compiles and links (needs a real gcc/g++ + the full gate)
#   - Whether it produces correct runtime behavior
#   - Cross-file references (`use OtherModule`) -- this tool checks one
#     file's syntax in isolation; it does not resolve imports
#   - Type errors, undeclared-variable use, or other semantic issues
#     that only the validator/emitter layers catch
#
# A "PASS" from this tool means "worth sending to the AI with full
# compiler + gcc access (Guide B)" -- it does not mean "guaranteed to
# compile, link, and run correctly." Treat it as a fast, free first
# filter that catches the most common category of mistake (wrong
# keyword, wrong word order, a dangling token) before spending a full
# Guide-B round-trip on it.
# ============================================================================

import sys
import argparse
from pathlib import Path


def check_source(source: str, label: str) -> tuple[bool, str]:
    """Tokenize + parse `source`. Returns (ok, message)."""
    try:
        tokens = Lexer(source).tokenize()
    except Exception as e:
        return False, f"[{label}] LEX ERROR: {e}"
    try:
        nodes = Parser(tokens).parse()
    except SyntaxError as e:
        return False, f"[{label}] SYNTAX ERROR: {e}"
    except Exception as e:
        return False, f"[{label}] UNEXPECTED ERROR while parsing: {type(e).__name__}: {e}"
    if not nodes:
        return False, f"[{label}] parsed with no error, but produced zero top-level statements — likely an empty or whitespace-only file"
    kinds = ", ".join(sorted({type(n).__name__ for n in nodes}))
    return True, f"[{label}] OK — parsed {len(nodes)} top-level statement(s): {kinds}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate that a .dict file is syntactically valid Dictum "
                    "(parse-only — no C/C++ emission, no gcc required)."
    )
    ap.add_argument("paths", nargs="+", help=".dict file(s) or a directory of them")
    args = ap.parse_args()

    files: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.dict")))
        else:
            files.append(path)

    if not files:
        print("No .dict files found to check.")
        return 1

    all_ok = True
    for f in files:
        try:
            source = f.read_text()
        except Exception as e:
            print(f"[{f}] COULD NOT READ FILE: {e}")
            all_ok = False
            continue
        ok, msg = check_source(source, str(f))
        print(msg)
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print(f"All {len(files)} file(s) are syntactically valid Dictum.")
        print("(This does not guarantee they compile, link, run, or do the right thing —")
        print(" only that they use real Dictum syntax correctly. Send to the full")
        print(" compiler + gcc pipeline for the rest.)")
        return 0
    else:
        print("One or more files failed. Fix the reported syntax errors before")
        print("sending these to the full compiler pipeline.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
'''


def strip_relative_imports(parser_src: str) -> str:
    parser_src = parser_src.replace("from __future__ import annotations\n", "")
    parser_src = parser_src.replace("from .lexer import Token, TokenType\n", "")
    parser_src = re.sub(r"from \.ast_nodes import \([^)]*\)\n", "", parser_src)
    parser_src = parser_src.replace(
        "from .type_registry import primitive_suffixes, terminal_type_words",
        "# (primitive_suffixes, terminal_type_words defined earlier in this same file)",
    )
    return parser_src


def main() -> int:
    lexer_src = (DICTUMC_DIR / "lexer.py").read_text()
    ast_src = (DICTUMC_DIR / "ast_nodes.py").read_text()
    typereg_src = (DICTUMC_DIR / "type_registry.py").read_text()
    parser_src = strip_relative_imports((DICTUMC_DIR / "parser.py").read_text())

    header = "from __future__ import annotations\n\n"
    core = header + lexer_src + ast_src + typereg_src + parser_src
    full = core + CLI_WRAPPER

    # Sanity check: the generated file must itself be valid Python
    # before we write it out, so a bad regeneration never silently
    # overwrites a working checker with a broken one.
    import ast as _ast
    _ast.parse(full)

    OUTPUT_PATH.write_text(full)
    print(f"Wrote {OUTPUT_PATH} ({len(full.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
