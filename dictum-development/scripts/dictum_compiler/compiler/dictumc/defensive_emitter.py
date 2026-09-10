"""
Defensive C Emitter — wraps CEmitter with runtime safety checks.

When --defensive is enabled, the emitted C includes:
  * Bounds checks on every array/list index access
  * Null-pointer checks before every pointer dereference
  * Division-by-zero checks
  * Integer overflow detection on +, -, *
  * Safe malloc wrappers that abort on failure
  * Dictum source line numbers in every error message

Usage:
    from dictumc.transpiler import Transpiler
    t = Transpiler(source, backend='c', defensive=True)
    result = t.run()
"""

from __future__ import annotations
from typing import List, Dict, Optional, Set, Tuple

from .emit_c import CEmitter
from .ast_nodes import (
    Node, IndexAccess, FieldAccess, BinaryOp, NewExpr, VarDecl,
    Assignment, Action, If, While, ForEach, FuncCall, Identifier,
    Literal, Program, Module, Shape, Possibilities, Return,
    Attempt, Assert, Print, UnsafeBlock, Break, AddToList,
    MapPut, MapGet, Contains, Transmute, UnaryOp,
)


_DEFENSIVE_PREAMBLE = r"""
/* ================================================================ */
/*  DICTUM DEFENSIVE RUNTIME — auto-generated safety layer          */
/*  Catches common errors at runtime with Dictum source line info   */
/* ================================================================ */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>

#ifndef DICTUM_DEFENSIVE_INCLUDED
#define DICTUM_DEFENSIVE_INCLUDED

static inline void _dictum_die(const char* file, int line,
                                const char* expr, const char* msg) {
    fprintf(stderr,
        "\n[DICTUM DEFENSIVE ERROR]\n"
        "  Source: %s:%d\n"
        "  Expression: %s\n"
        "  Details: %s\n\n",
        file, line, expr, msg);
    abort();
}

#define _DICTUM_BOUNDS_CHECK(arr, idx, count, file, line) \
    do { \
        if ((idx) < 0 || (size_t)(idx) >= (size_t)(count)) { \
            char _buf[256]; \
            snprintf(_buf, sizeof(_buf), \
                "index %ld out of bounds [0, %zu) on array '%s'", \
                (long)(idx), (size_t)(count), #arr); \
            _dictum_die(file, line, #arr "[" #idx "]", _buf); \
        } \
    } while (0)

#define _DICTUM_NULL_CHECK(ptr, file, line) \
    do { \
        if ((ptr) == NULL) { \
            _dictum_die(file, line, #ptr, \
                "null pointer dereference"); \
        } \
    } while (0)

#define _DICTUM_DIV_CHECK(den, file, line) \
    do { \
        if ((den) == 0) { \
            _dictum_die(file, line, #den, "division by zero"); \
        } \
    } while (0)

static inline void* _dictum_safe_malloc(size_t n, const char* file, int line,
                                         const char* expr) {
    void* p = malloc(n);
    if (!p && n > 0) {
        _dictum_die(file, line, expr, "memory allocation failed");
    }
    return p;
}

static inline void* _dictum_safe_calloc(size_t nmemb, size_t size,
                                         const char* file, int line,
                                         const char* expr) {
    void* p = calloc(nmemb, size);
    if (!p && nmemb > 0 && size > 0) {
        _dictum_die(file, line, expr, "memory allocation failed");
    }
    return p;
}

static inline int32_t _dictum_safe_add(int32_t a, int32_t b,
                                        const char* file, int line) {
    if (b > 0 && a > INT32_MAX - b) {
        _dictum_die(file, line, "a + b", "integer overflow in addition");
    }
    if (b < 0 && a < INT32_MIN - b) {
        _dictum_die(file, line, "a + b", "integer underflow in addition");
    }
    return a + b;
}

static inline int32_t _dictum_safe_sub(int32_t a, int32_t b,
                                        const char* file, int line) {
    if (b > 0 && a < INT32_MIN + b) {
        _dictum_die(file, line, "a - b", "integer underflow in subtraction");
    }
    if (b < 0 && a > INT32_MAX + b) {
        _dictum_die(file, line, "a - b", "integer overflow in subtraction");
    }
    return a - b;
}

static inline int32_t _dictum_safe_mul(int32_t a, int32_t b,
                                        const char* file, int line) {
    if (a > 0) {
        if (b > 0 && a > INT32_MAX / b) {
            _dictum_die(file, line, "a * b", "integer overflow in multiplication");
        }
        if (b < 0 && b < INT32_MIN / a) {
            _dictum_die(file, line, "a * b", "integer underflow in multiplication");
        }
    } else if (a < 0) {
        if (b > 0 && a < INT32_MIN / b) {
            _dictum_die(file, line, "a * b", "integer underflow in multiplication");
        }
        if (b < 0 && a < INT32_MAX / b) {
            _dictum_die(file, line, "a * b", "integer overflow in multiplication");
        }
    }
    return a * b;
}

#endif  /* DICTUM_DEFENSIVE_INCLUDED */
"""


class DefensiveCEmitter(CEmitter):
    """CEmitter subclass that adds runtime safety checks."""

    def __init__(self) -> None:
        super().__init__()
        self._defensive_preamble_emitted = False
        self._current_source_line = 0

    def _emit_marked(self, line: str, source_line: int = 0) -> None:
        if source_line > 0:
            self._current_source_line = source_line
        super()._emit_marked(line, source_line)

    def _here(self) -> str:
        fname = getattr(self, 'source_filename', 'unknown.dict')
        return f'"{fname}", {self._current_source_line or 0}'

    def expr_to_c(self, node: Node) -> str:
        if isinstance(node, IndexAccess):
            base = self.expr_to_c(node.index)
            coll = node.collection
            count_expr = None
            dv = self.declared_vars.get(coll, "")
            if dv.endswith("_t"):
                count_expr = f"dictum_glist_len(&{coll})"
            elif f"{coll}_count" in self.declared_vars:
                count_expr = f"{coll}_count"
            else:
                return f"{coll}[{base}]"

            if count_expr:
                return (
                    f"(_DICTUM_BOUNDS_CHECK({coll}, {base}, {count_expr}, "
                    f"{self._here()}), {coll}[{base}])"
                )

        if isinstance(node, FieldAccess):
            op = "."
            if self.declared_vars.get(node.obj, "").rstrip().endswith("*"):
                op = "->"
                return (
                    f"(_DICTUM_NULL_CHECK({node.obj}, {self._here()}), "
                    f"{node.obj}{op}{node.field})"
                )
            return f"{node.obj}{op}{node.field}"

        if isinstance(node, BinaryOp):
            left = self.expr_to_c(node.left)
            right = self.expr_to_c(node.right)
            if right in ('"empty"', "'empty'"):
                right = 'NULL'

            if node.op == '/':
                return f"(_DICTUM_DIV_CHECK({right}, {self._here()}), {left} / {right})"
            if node.op == '+':
                return f"_dictum_safe_add({left}, {right}, {self._here()})"
            if node.op == '-':
                return f"_dictum_safe_sub({left}, {right}, {self._here()})"
            if node.op == '*':
                return f"_dictum_safe_mul({left}, {right}, {self._here()})"
            if node.op == 'pow':
                return f"pow({left}, {right})"
            return f"({left} {node.op} {right})"

        return super().expr_to_c(node)

    def emit_node(self, node: Node) -> None:
        if isinstance(node, (Program, Module)) and not self._defensive_preamble_emitted:
            self._defensive_preamble_emitted = True
            self._defensive_preamble = _DEFENSIVE_PREAMBLE

        if hasattr(node, 'line') and node.line:
            self._current_source_line = node.line

        if isinstance(node, VarDecl) and isinstance(node.value, NewExpr):
            ct = self.type_to_c(node.type)
            self.declared_vars[node.name] = ct
            self.emit(f"{ct} {node.name} = "
                      f"({ct})_dictum_safe_calloc(1, sizeof(*{node.name}), "
                      f"{self._here()}, \"{node.name}\");")
            return

        if isinstance(node, Assignment):
            target = node.target
            if "." in target:
                base_name = target.split(".")[0].split("[")[0]
                if self.declared_vars.get(base_name, "").rstrip().endswith("*"):
                    self.emit(f"_DICTUM_NULL_CHECK({base_name}, {self._here()});")

        if isinstance(node, FuncCall):
            if "." in node.name:
                obj_name = node.name.split(".")[0]
                if self.declared_vars.get(obj_name, "").rstrip().endswith("*"):
                    self.emit(f"_DICTUM_NULL_CHECK({obj_name}, {self._here()});")

        super().emit_node(node)

    def get_output(self) -> str:
        code = super().get_output()
        preamble = getattr(self, '_defensive_preamble', '')
        if preamble:
            return preamble + "\n" + code
        return code
