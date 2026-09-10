"""
line_directives.py — emits real C `#line` directives, shared by
emit_c.py and emit_cpp.py.

Why this exists alongside the `/* @dictum-line:N */` comment marker
(kept, not removed -- see below): a `#line N "file.dict"` directive is
the C preprocessor's OWN native source-mapping mechanism. gcc/g++ reads
it and reports every diagnostic after it -- errors, warnings, and notes
alike -- as coming directly from `file.dict:N`, with zero post-
processing needed. The comment marker requires dict_triage.py to scan
the generated C, build a line map, and rewrite gcc's stderr text after
the fact; a `#line` directive gets the same result from gcc for free,
and covers cases a text-rewrite pass might miss (a multi-line
diagnostic, a note attached to a `-Wall`/`-Werror` warning, a column
computed from macro expansion) since it's the compiler's own model of
"what file/line am I looking at," not a regex applied to its output
afterward.

This is added ADDITIVELY, not as a replacement: the `/* @dictum-line:N */`
comment still gets emitted right alongside every `#line` directive (see
emit_c.py/emit_cpp.py's `_emit_marked`). If a `#line`-driven diagnostic
ever behaves unexpectedly on some gcc/g++ version or platform, the
existing marker-based fallback in dict_triage.py still works unchanged
-- this doesn't remove a tested, working mechanism, it adds a stronger
one in front of it. debug_mapper.py (the consumer of this) checks for a
`#line`-native `.dict` path first and only falls back to the marker map
when one isn't present.
"""

from __future__ import annotations


def format_line_directive(line_no: int, source_filename: str) -> str:
    """Returns a real C `#line` directive string (no trailing newline --
    caller's `emit()` adds it, matching how the comment marker is emitted).

    `source_filename` is escaped for use inside a C string literal
    (backslashes and double quotes) -- not usually needed for a plain
    Linux path, but a filename could contain either in principle, and an
    unescaped one would produce invalid C, which is a worse failure than
    the diagnostic-mapping feature this exists to add.
    """
    escaped = source_filename.replace("\\", "\\\\").replace('"', '\\"')
    return f'#line {line_no} "{escaped}"'


DEFAULT_SOURCE_FILENAME = "<dict-source>"
