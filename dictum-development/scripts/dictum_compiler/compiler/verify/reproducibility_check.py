#!/usr/bin/env python3
"""
reproducibility_check.py — proves a project's build is actually
reproducible (not just assumed to be), and stamps the exact compiler
state a build was produced with, so "rebuild 3 months later must produce
identical output" is something checked, not promised.

What this checks, concretely: builds the same .dict project TWICE, into
two separate directories, and confirms the resulting binaries are
byte-identical (sha256 comparison) -- not just "the .dict source is
unchanged" (trivially true) but "the actual compile+link process itself
is deterministic," which is the thing that can quietly break (embedded
timestamps, non-deterministic build IDs, unordered symbol tables from a
toolchain change) without anyone noticing until a client asks for a
rebuild and gets a different binary.

What it stamps for provenance: a "compiler fingerprint" (reusing
cache_lib.compiler_fingerprint -- mtime+size of every compiler .py file,
plus the real gcc/g++ --version strings) and, if the compiler tree is
inside a git repo, the real commit hash. This is what "locked compiler
version" actually means in practice -- not a version string someone
might forget to bump, but a real fingerprint of the exact files that
produced this exact binary.

This does NOT prove the build is *correct* -- pair it with
run_pipeline.py for that. It only proves the build is *reproducible*,
which is a narrower, independently useful claim (a project can be
reproducibly wrong; this doesn't catch that, on purpose -- that's what
Guide B/C are for).

Usage:
    python3 reproducibility_check.py --project path/to/project [--static] [--backend c|cpp] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.path.dirname(HERE)  # .../compiler
sys.path.insert(0, COMPILER_DIR)
sys.path.insert(0, HERE)


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(path: str) -> Optional[str]:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                            capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _build_once(project_dir: str, out_dir: str, backend: str, static: bool) -> Optional[str]:
    """Returns the built binary's path, or None if the build failed."""
    import project_builder
    result = project_builder.build_project(workspace=project_dir, backend=backend,
                                            out_dir=out_dir, static=static)
    if not result["success"]:
        return None
    make = subprocess.run(["make"], cwd=out_dir, capture_output=True, text=True, timeout=90)
    if make.returncode != 0:
        return None
    target_name = None
    mf = os.path.join(out_dir, "Makefile")
    if os.path.exists(mf):
        for line in open(mf, encoding="utf-8"):
            if line.startswith("TARGET"):
                target_name = line.split("=", 1)[1].strip()
                break
    if not target_name:
        return None
    bin_path = os.path.join(out_dir, target_name)
    return bin_path if os.path.exists(bin_path) else None


def check(project_dir: str, backend: str = "c", static: bool = False) -> Dict[str, Any]:
    import cache_lib
    project_dir = os.path.abspath(project_dir)

    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        bin1 = _build_once(project_dir, os.path.join(t1, "build"), backend, static)
        bin2 = _build_once(project_dir, os.path.join(t2, "build"), backend, static)

        if not bin1 or not bin2:
            return {"ok": False, "detail": "one or both builds failed -- not a reproducibility "
                                             "question until both builds succeed at all",
                    "compiler_fingerprint": cache_lib.compiler_fingerprint(os.path.join(COMPILER_DIR, "dictumc")),
                    "git_commit": _git_commit(COMPILER_DIR)}

        hash1, hash2 = _sha256_of_file(bin1), _sha256_of_file(bin2)
        reproducible = hash1 == hash2

    return {
        "ok": reproducible,
        "detail": ("two independent builds produced byte-identical binaries" if reproducible else
                   f"two independent builds of the SAME .dict source produced DIFFERENT binaries "
                   f"(sha256 {hash1[:12]}... vs {hash2[:12]}...) -- the build is not currently "
                   "reproducible; a rebuild later is not guaranteed to match what a client received"),
        "binary_sha256": hash1 if reproducible else None,
        "compiler_fingerprint": cache_lib.compiler_fingerprint(os.path.join(COMPILER_DIR, "dictumc")),
        "git_commit": _git_commit(COMPILER_DIR),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--backend", default="c", choices=["c", "cpp"])
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = check(args.project, backend=args.backend, static=args.static)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["detail"])
        print(f"compiler_fingerprint: {result['compiler_fingerprint']}")
        print(f"git_commit: {result['git_commit']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
