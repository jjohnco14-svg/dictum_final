#!/usr/bin/env python3
"""
verify_static_link.py — confirms a built binary is actually statically
linked, via real `ldd`, not by trusting that the `-static` build flag was
passed.

Why this needs its own check rather than trusting the build flag: glibc
static linking has real, well-known gotchas -- some functions (NSS-based
ones: getaddrinfo/getpwnam and similar) can silently pull in a dynamic
dependency even with -static passed, depending on what the program calls
and how the local toolchain's glibc was built. "I passed -static" and
"this binary actually has zero dynamic dependencies" are different claims,
and only the second one is what a client-deliverable "runs anywhere,
chmod +x" promise actually requires.

Usage:
    python3 verify_static_link.py /path/to/binary [--json]

Exit 0 + ok=true only when `ldd` reports the binary isn't dynamic at all
(the "not a dynamic executable" message, or a musl-style equivalent) --
NOT when it merely reports zero *unresolved* dependencies, which is a
different and weaker claim (a binary can dynamically link against libc
itself while resolving every symbol just fine).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def check(binary_path: str) -> dict:
    try:
        r = subprocess.run(["ldd", binary_path], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return {"ok": None, "detail": "ldd not available in this environment -- cannot verify"}
    except Exception as e:
        return {"ok": False, "detail": f"ldd failed to run: {e}"}

    output = (r.stdout + r.stderr).strip()
    # ldd's real "this is static" signal -- exit code alone isn't reliable
    # across ldd implementations/versions, so match on the actual message.
    is_static = "not a dynamic executable" in output.lower()

    # A binary that's "mostly static" but still links vdso (the kernel's
    # own in-process page, not a real shared library -- every process on
    # Linux has this, static or not) is still a genuine static binary for
    # this purpose. Anything else listed is a real, remaining dependency.
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    non_vdso_deps = [l for l in lines if "linux-vdso.so" not in l and "not a dynamic executable" not in l.lower()]

    if is_static:
        return {"ok": True, "detail": "ldd confirms: not a dynamic executable", "ldd_output": output}
    if not non_vdso_deps:
        return {"ok": True, "detail": "ldd shows only linux-vdso.so.1 (kernel page, not a real "
                                        "shared-library dependency) -- effectively static", "ldd_output": output}
    return {"ok": False,
            "detail": f"binary has {len(non_vdso_deps)} real dynamic dependenc(y/ies) -- "
                       "not actually static, despite whatever build flags were passed",
            "ldd_output": output, "remaining_dependencies": non_vdso_deps}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("binary")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = check(args.binary)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["detail"])
        if result.get("remaining_dependencies"):
            for d in result["remaining_dependencies"]:
                print(f"  {d}")
    return 0 if result["ok"] else (1 if result["ok"] is False else 2)


if __name__ == "__main__":
    sys.exit(main())
