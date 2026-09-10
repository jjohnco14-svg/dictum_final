"""
cache_lib.py — shared incremental-caching helper for dict_triage.py and
guide_c_verify.py.

The problem this solves: in an iterative fix loop (write a small `.dict`
change, re-triage, look at the result, write another small change,
re-triage again...) most of those re-triage calls re-check inputs that
didn't change at all -- the compiler itself, most of the `.dict` file,
most of the manifest. Re-running the whole pipeline from scratch every
time is correct but wasteful; this lets a verdict be served from cache
when nothing relevant actually changed, and computed fresh (and
invalidated) the moment anything relevant does.

Design choices, deliberately conservative (a stale-cache false PASS would
be far worse than a cache that occasionally misses when it could have
hit):
    - the cache key includes a "compiler fingerprint" (mtime+size of the
      actual compiler source files, not the compiler's version string
      someone might forget to bump) so ANY change anywhere in the
      compiler internals invalidates every cached verdict, even if the
      .dict file and manifest are untouched
    - the cache key includes the real gcc/g++ --version string, so a
      toolchain change (e.g. a CI image bump) also invalidates everything
    - cache entries never expire by time -- only by their key changing --
      so there's no risk of "it's been an hour, let's just trust it"
    - a corrupt cache file is treated as empty (fail open to "recompute
      everything"), never as an error that blocks the actual check
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any, Dict, List, Optional


def _file_fingerprint(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{path}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return f"{path}:MISSING"


def compiler_fingerprint(dictumc_dir: str) -> str:
    """Hash of every .py file's (size, mtime) under dictumc_dir, plus the
    real gcc/g++ --version strings. Changes to ANY of these invalidate
    every cache entry keyed with this fingerprint."""
    parts: List[str] = []
    for root, _dirs, files in sorted(os.walk(dictumc_dir)):
        for f in sorted(files):
            if f.endswith(".py"):
                parts.append(_file_fingerprint(os.path.join(root, f)))
    for tool in ("gcc", "g++"):
        try:
            v = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=5)
            parts.append(f"{tool}:{v.stdout.splitlines()[0] if v.stdout else '?'}")
        except Exception:
            parts.append(f"{tool}:unavailable")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def hash_inputs(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8", errors="replace")).hexdigest()


class Cache:
    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self._data: Dict[str, Any] = {}
        if os.path.exists(cache_path):
            try:
                self._data = json.load(open(cache_path))
            except Exception:
                self._data = {}  # fail open -- a corrupt cache never blocks a real check

    def get(self, key: str) -> Optional[Any]:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        try:
            json.dump(self._data, open(self.cache_path, "w"), indent=2, default=str)
        except OSError:
            pass  # best-effort -- a failed cache write must never fail the actual check
