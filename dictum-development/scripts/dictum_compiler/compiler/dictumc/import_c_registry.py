"""
import_c_registry.py — target-tagged blessing registry for `import from C`
libraries (Guide B §2a's Case D, referenced by dict_triage.py's
check_library_blessing()).

Problem this replaces: a `blessed/<lib>.dict` file existing at all used to
be the only signal dict_triage.py had, and that signal is genuinely unsafe
to trust across targets -- a bridge verified against Linux's libsqlite3
says nothing about whether the exact same bridge links correctly against
Windows' sqlite3.dll (different ABI, different calling convention on some
platforms, different available symbols). Guide B §3 calls this mistake out
by name. Before this file existed, dict_triage.py could only ever answer
"unverifiable, check manually" for Case D -- correct, but not useful.

This registry stores a real per-`<library>/<target>` verdict, populated
ONLY by an actual compile+link+run check against that target's real
toolchain -- never by "the name matches an existing bridge" inference.
It starts empty on purpose. A library/target pair with no entry is
`is_blessed() -> None` ("unverifiable" -- same honest fallback as before),
not `False` and never a guessed `True`. Nothing in this file fabricates a
blessing; every entry recorded here should trace back to a real run,
recorded with `--register` below.

Storage: a JSON sidecar (import_c_registry.json, same directory) so the
data survives independently of this module's code and is easy to diff in
version control.

CLI:
    # Record a real verification you just ran (only do this after an
    # actual compile+link+run against the real target/toolchain):
    python3 import_c_registry.py --register sqlite3 linux \\
        --toolchain gcc-12 --note "compiled+linked+ran sqlite3_libversion()"

    # Query:
    python3 import_c_registry.py --query sqlite3 linux
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "import_c_registry.json")


def _load() -> dict:
    if not os.path.exists(DATA_PATH):
        return {}
    try:
        return json.load(open(DATA_PATH))
    except Exception:
        # A corrupt/unparseable registry must never be silently treated as
        # "nothing recorded" (which would just fall back to unverifiable,
        # fine) OR silently ignored while claiming success -- surface it.
        raise RuntimeError(f"import_c_registry.json exists but isn't valid JSON: {DATA_PATH}")


def _save(data: dict) -> None:
    json.dump(data, open(DATA_PATH, "w"), indent=2, sort_keys=True)


def is_blessed(library: str, target: str) -> Optional[bool]:
    """Returns True/False if a real verification is on record for this
    exact <library>/<target> pair, or None if nothing is recorded (the
    honest 'unverifiable' answer -- never guessed)."""
    data = _load()
    entry = data.get(library.strip().lower(), {}).get(target.strip().lower())
    return entry["blessed"] if entry else None


def get_entry(library: str, target: str) -> Optional[dict]:
    data = _load()
    return data.get(library.strip().lower(), {}).get(target.strip().lower())


def register(library: str, target: str, blessed: bool, toolchain: str, note: str) -> dict:
    """Records a real verification result. Caller is responsible for having
    actually run the compile+link(+run) check before calling this -- this
    function has no way to confirm that itself, which is exactly why it's a
    separate explicit step and not something dict_triage.py does automatically."""
    data = _load()
    lib_key = library.strip().lower()
    data.setdefault(lib_key, {})
    entry = {
        "blessed": bool(blessed),
        "toolchain": toolchain,
        "note": note,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    data[lib_key][target.strip().lower()] = entry
    _save(data)
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--register", nargs=2, metavar=("LIBRARY", "TARGET"))
    g.add_argument("--query", nargs=2, metavar=("LIBRARY", "TARGET"))
    ap.add_argument("--blessed", action="store_true", help="mark as blessed (default when --register is used)")
    ap.add_argument("--not-blessed", action="store_true", help="mark as explicitly NOT blessed (a real, verified failure)")
    ap.add_argument("--toolchain", default="", help="e.g. gcc-12, msvc-2022")
    ap.add_argument("--note", default="", help="what was actually checked")
    args = ap.parse_args()

    if args.register:
        library, target = args.register
        if args.not_blessed and args.blessed:
            print("ERROR: --blessed and --not-blessed are mutually exclusive", file=sys.stderr)
            return 2
        blessed = not args.not_blessed
        if not args.note:
            print("ERROR: --note is required -- record what was actually verified, "
                  "not just that a flag was passed", file=sys.stderr)
            return 2
        entry = register(library, target, blessed, args.toolchain, args.note)
        print(json.dumps({library.lower(): {target.lower(): entry}}, indent=2))
        return 0

    if args.query:
        library, target = args.query
        entry = get_entry(library, target)
        if entry is None:
            print(json.dumps({"library": library, "target": target, "blessed": None,
                               "detail": "no verification on record -- unverifiable, not unblessed"}, indent=2))
            return 1
        print(json.dumps({"library": library, "target": target, **entry}, indent=2))
        return 0 if entry["blessed"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
