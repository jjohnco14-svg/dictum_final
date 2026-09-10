"""
debug_mapper.py — maps a gcc/g++ diagnostic back to `.dict` file/line,
preferring the `#line`-native path (gcc already says the right file/line
directly, for free) over dict_triage.py's older marker-forward-fill map
(kept as a fallback, not removed -- see line_directives.py's module
docstring for why both exist).

This is the "cheap call" win: for a diagnostic inside a real statement
body (the common case), gcc's own stderr ALREADY reads
`main.dict:7:3: error: ...` once emit_c.py/emit_cpp.py emit real `#line`
directives -- there is nothing left to compute. dict_triage.py used to
have to scan the whole generated C file, build a C-line -> Dictum-line
map, and rewrite every diagnostic line through that map. With `#line` in
place, that whole step is skipped for every diagnostic gcc already
attributes to a `.dict` path -- only the rarer cases (preamble/global-
decl lines emitted before any `#line`, or a toolchain that for some
reason didn't honor the directive) still need the marker-map fallback.

Public API mirrors dict_triage.py's existing `translate_compiler_output`
closely on purpose, so wiring this in is a small, additive change rather
than a rewrite of Case C's call site.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

_GCC_DIAG_RE = re.compile(
    r'^(?P<path>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|note):\s*(?P<msg>.*)$'
)


def map_gcc_output(
    gcc_stderr: str,
    c_src_path: str,
    dict_path: str,
    marker_line_map: Optional[Dict[int, int]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Rewrites gcc/g++ stderr so every diagnostic reads as a `.dict`
    file/line reference. Three tiers, in priority order:

    1. gcc already reports a path ending in `.dict` (or matching
       dict_path's basename) directly -- this is the `#line`-native case.
       Nothing to compute; pass the line through as-is, tagged
       source="line_directive".
    2. gcc reports the generated C/C++ file, and `marker_line_map` (the
       existing `/* @dictum-line:N */`-derived map) has an entry for that
       line -- rewrite it, tagged source="marker_fallback". Exactly what
       dict_triage.py already did before this module existed.
    3. Neither -- genuinely unmapped (preamble/global-decl emission, or a
       diagnostic inside a runtime header), tagged mapped=False, same as
       before.
    """
    diagnostics: List[Dict[str, Any]] = []
    out_lines: List[str] = []
    c_base = os.path.basename(c_src_path)
    dict_base = os.path.basename(dict_path)
    marker_line_map = marker_line_map or {}

    for raw_line in gcc_stderr.split("\n"):
        m = _GCC_DIAG_RE.match(raw_line)
        if not m:
            out_lines.append(raw_line)
            continue

        path = m.group("path")
        path_base = os.path.basename(path)
        severity = m.group("severity")
        msg = m.group("msg")
        line_no = int(m.group("line"))
        col_no = int(m.group("col"))

        if path_base.endswith(".dict") or path_base == dict_base:
            # Tier 1 -- gcc already did the work via a real #line directive.
            diagnostics.append({
                "severity": severity, "dict_line": line_no, "dict_col": col_no,
                "message": msg, "mapped": True, "source": "line_directive",
            })
            out_lines.append(raw_line)  # already correct, no rewrite needed
            continue

        if path == c_src_path or path_base == c_base:
            dict_line = marker_line_map.get(line_no)
            if dict_line is not None:
                # Tier 2 -- fall back to the marker-derived map.
                diagnostics.append({
                    "severity": severity, "c_line": line_no, "c_col": col_no,
                    "dict_line": dict_line, "message": msg, "mapped": True,
                    "source": "marker_fallback",
                })
                out_lines.append(f"{dict_path}:{dict_line}: {severity}: {msg}")
                continue
            # Tier 3 -- genuinely unmapped.
            diagnostics.append({
                "severity": severity, "c_line": line_no, "c_col": col_no,
                "dict_line": None, "message": msg, "mapped": False, "source": "unmapped",
            })
            out_lines.append(
                f"{dict_path}:?: {severity}: {msg}  "
                f"[unmapped -- generated-source line {line_no} has no #line directive "
                f"or preceding @dictum-line marker; likely preamble/global-decl emission]"
            )
            continue

        out_lines.append(raw_line)  # a diagnostic from an unrelated file (e.g. a runtime header)

    return "\n".join(out_lines), diagnostics
