"""
type_semantics.py — ONE source of truth for the type questions that are
backend-independent.

WHY THIS EXISTS
---------------
emit_c.py, emit_cpp.py and emit_nim.py are three separately hand-written
emitters. Nearly every silent-wrong-answer bug in this project was DRIFT
between them, and the sharpest example is worth stating precisely:

    `_format_spec` decides which printf conversion a value needs.
    emit_c and emit_cpp implement it separately and are only ~35%
    textually similar -- yet BOTH contained the same bug: a KNOWN integer
    type fell through to a heuristic that guessed from the VARIABLE NAME,
    so `keep price as whole number with value 100` printed
    "price=0.000000" on both backends. Two independent implementations,
    one identical wrong answer, found only by a generated variable that
    happened to be called `distinct_2`.

Textual similarity did not predict that (35% is low). What predicts it is
SEMANTIC duplication: both were answering the SAME QUESTION with separately
maintained code. That is the drift surface worth removing, and it is
removable without the full shared-IR rewrite -- these questions have one
correct answer regardless of target language.

A fix applied here lands on every backend at once, which is the property
the three-emitter design otherwise lacks.

SCOPE: only genuinely backend-independent facts belong here. How to SPELL a
type in C vs Nim is backend-specific and stays in each emitter. What a type
fundamentally IS -- integer, floating, textual, boolean -- is not.
"""
from __future__ import annotations
from typing import Optional

# Canonical Dictum type names. Every spelling the language accepts maps to
# exactly one of these.
INTEGER = "integer"
FLOATING = "floating"
TEXTUAL = "textual"
BOOLEAN = "boolean"
BYTES = "bytes"
POINTER = "pointer"
UNKNOWN = "unknown"

# Dictum surface spellings -> canonical kind. The synonym set matters:
# the validator once compared element types by EXACT STRING and rejected
# `add 1.5 to <growable list of decimal number>` because the literal
# inferred as 'fractional number' -- a DOCUMENTED synonym of the declared
# 'decimal number'. Keeping every spelling in one table prevents that class.
_DICTUM_KIND = {
    "whole number":      INTEGER,
    "int":               INTEGER,
    "number":            INTEGER,
    "byte":              BYTES,
    "decimal number":    FLOATING,
    "fractional number": FLOATING,
    "decimal":           FLOATING,
    "float":             FLOATING,
    "text":              TEXTUAL,
    "truth value":       BOOLEAN,
    "bool":              BOOLEAN,
    "opaque pointer":    POINTER,
}

# Generated C/C++ type spellings -> canonical kind. Used when an emitter
# only has the lowered type in hand.
_C_KIND = {
    "int32_t": INTEGER, "int": INTEGER, "int8_t": INTEGER, "int16_t": INTEGER,
    "uint16_t": INTEGER, "uint32_t": INTEGER, "unsigned": INTEGER,
    "long": INTEGER, "int64_t": INTEGER, "uint64_t": INTEGER,
    "size_t": INTEGER,
    "uint8_t": BYTES,
    "double": FLOATING, "float": FLOATING,
    "dictum_text": TEXTUAL, "const char*": TEXTUAL, "char*": TEXTUAL,
    "std::string": TEXTUAL,
    "bool": BOOLEAN,
    "void*": POINTER,
}


def normalize(type_name: Optional[str]) -> str:
    """Collapse a Dictum type spelling to its canonical form.

    `fractional number` and `decimal number` are the same type; comparing
    them as raw strings is a bug, and was one.
    """
    if not type_name:
        return ""
    t = type_name.strip()
    kind = _DICTUM_KIND.get(t)
    if kind is None:
        return t
    for canonical, k in (("whole number", INTEGER), ("decimal number", FLOATING),
                         ("text", TEXTUAL), ("truth value", BOOLEAN),
                         ("byte", BYTES), ("opaque pointer", POINTER)):
        if k == kind:
            return canonical
    return t


def same_type(a: Optional[str], b: Optional[str]) -> bool:
    """True if two Dictum type spellings denote the same type."""
    return normalize(a) == normalize(b)


def kind_of(type_name: Optional[str]) -> str:
    """Canonical KIND of a type, accepting either a Dictum spelling or a
    lowered C/C++ spelling. Returns UNKNOWN rather than guessing."""
    if not type_name:
        return UNKNOWN
    t = type_name.strip()
    if t in _DICTUM_KIND:
        return _DICTUM_KIND[t]
    if t in _C_KIND:
        return _C_KIND[t]
    t2 = t.rstrip("*").strip()
    if t2 in _C_KIND:
        return _C_KIND[t2] if not t.endswith("*") else POINTER
    if t.endswith("*"):
        return POINTER
    return UNKNOWN


def printf_spec(type_name: Optional[str]) -> Optional[str]:
    """printf conversion for a KNOWN type, or None when genuinely unknown.

    Returning None matters: the callers used to fall back to a heuristic
    that guessed from the VARIABLE NAME, which is how an int called `price`
    got printed with %f. A name guess is a last resort for an UNKNOWN type,
    never an override of a known one -- so this function refuses to guess,
    and the caller decides what to do with None.
    """
    k = kind_of(type_name)
    if k == INTEGER:
        return "%d"
    if k == BYTES:
        return "%d"
    if k == FLOATING:
        return "%f"
    if k == TEXTUAL:
        return "%s"
    if k == BOOLEAN:
        return "%d"
    if k == POINTER:
        return "%p"
    return None


def is_numeric(type_name: Optional[str]) -> bool:
    return kind_of(type_name) in (INTEGER, FLOATING, BYTES)


def is_integral(type_name: Optional[str]) -> bool:
    return kind_of(type_name) in (INTEGER, BYTES)
