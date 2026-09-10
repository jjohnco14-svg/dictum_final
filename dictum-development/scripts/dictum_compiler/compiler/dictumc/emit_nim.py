"""
Dictum Nim Emitter — emits Nim source from the AST.

Maps Dictum's natural-language AST to Nim source code.
Nim compiles to C, giving C-speed with better error messages,
built-in collections, and automatic memory management (ARC/ORC).

Usage:
    from dictumc.transpiler import Transpiler
    t = Transpiler(source, backend='nim')
    result = t.run()
"""

from __future__ import annotations
from typing import List, Dict, Optional, Set, Tuple, Any

from .ast_nodes import (
    Node, Program, Module, Shape, Method, Constructor, Destructor,
    VarDecl, Assignment, Action, FuncCall, Return, If, While, ForEach,
    Repeat, Attempt, Literal, Identifier, BinaryOp, UnaryOp,
    FieldAccess, IndexAccess, Assert, Print, ImportC, ImportCpp, ImportDict,
    UnsafeBlock, UnsafeToken, VerifyToken, ExternFn, Transmute, Use, Bind, NewExpr, LambdaExpr,
    Possibilities, HandleTypeDecl, Break, AddToList, MapPut, MapGet, Contains,
)

from .line_directives import format_line_directive, DEFAULT_SOURCE_FILENAME


def _nim_string_literal(s: str) -> str:
    """Render a Python string as a valid Nim double-quoted string literal.

    Nim strings use double quotes; single quotes are a *character*
    literal in Nim (exactly one codepoint) and produce a compile error
    for anything but a single character -- so Python's repr() (which
    emits single-quoted output) is never safe to hand to the Nim
    compiler here. See emit_nim.py regression: R-NIM-1.
    """
    out = ['"']
    for ch in s:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append('\\x%02x' % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_TYPE_MAP: Dict[str, str] = {
    "whole number":       "int32",
    "count":              "Natural",
    "fractional number":  "float64",
    "decimal number":     "float64",
    "decimal":            "float64",
    "truth value":        "bool",
    "bool":               "bool",
    "byte":               "uint8",
    "bytes":              "seq[uint8]",
    "text":               "string",
    "handle to bytes":    "pointer",
    "opaque pointer":     "pointer",
    "nothing":            "void",
    "u8":                 "uint8",
    "u16":                "uint16",
    "u32":                "uint32",
    "u64":                "uint64",
    "i16":                "int16",
    "i32":                "int32",
    "i64":                "int64",
    "f32":                "float32",
    "f64":                "float64",
    "result":             "pointer",
}

_BIN_OP_MAP = {
    "+":                  "+",
    "-":                  "-",
    "*":                  "*",
    "/":                  "/",
    "divided by":         "div",
    "modulo":             "mod",
    # The parser normalizes both `X modulo Y` and `X % Y` down to a
    # BinaryOp with op='%' (see parser.py) before any backend ever sees
    # it -- the "modulo" mapping above is never actually hit. C/C++ use
    # '%' natively so their emitters pass it through unchanged, but Nim
    # has no '%' operator on ints (it's reserved for strings/bitsets),
    # so it must be translated to `mod` here too. See emit_nim.py
    # regression: R-NIM-4.
    "%":                  "mod",
    "is less than":       "<",
    "is greater than":    ">",
    "is equal to":        "==",
    "is not equal to":    "!=",
    "is less than or equal to":    "<=",
    "is greater than or equal to": ">=",
    "and":                "and",
    "or":                 "or",
    "plus":               "+",
    "minus":              "-",
    "times":              "*",
    "bitwise xor":        "xor",
    "bitwise and":        "and",
    "bitwise or":         "or",
}

_UNARY_OP_MAP = {
    "not":                "not",
    "negative":           "-",
}


class NimEmitter:
    """Emits Nim source code from a Dictum AST."""

    def __init__(self, source_path: str = "") -> None:
        self.output: List[str] = []
        self.indent: int = 0
        self.source_path = source_path or DEFAULT_SOURCE_FILENAME
        self.declared_vars: Dict[str, str] = {}
        self.actions: Set[str] = set()
        self.shapes: Dict[str, Dict[str, str]] = {}
        self.current_module: Optional[str] = None
        self._imports: Set[str] = set()
        # Names of `import from C`/`import from C++` functions whose
        # real Dictum return type is `text` -- see R-NIM-11 below for
        # why this has to be tracked at all.
        self.ffi_string_returns: Set[str] = set()

    def emit(self, line: str = "") -> None:
        self.output.append("    " * self.indent + line)

    def type_to_nim(self, dt: str) -> str:
        dt = dt.strip()
        if dt.startswith("list of "):
            inner = self.type_to_nim(dt[8:])
            return f"seq[{inner}]"
        if dt.startswith("growable list of "):
            inner = self.type_to_nim(dt[17:])
            return f"seq[{inner}]"
        if dt.startswith("array of ") and " with " in dt:
            parts = dt.split(" with ")
            inner = self.type_to_nim(parts[0][9:])
            count = parts[1].split()[0]
            return f"array[{count}, {inner}]"
        if dt.startswith("map of ") and " to " in dt:
            rest = dt[7:]
            k, v = rest.split(" to ", 1)
            return f"Table[{self.type_to_nim(k)}, {self.type_to_nim(v)}]"
        if dt.startswith("set of "):
            inner = self.type_to_nim(dt[7:])
            return f"HashSet[{inner}]"
        for prefix in ("unique handle to ", "shared handle to ",
                       "weak handle to ", "raw pointer to ",
                       "handle to ", "pointer to "):
            if dt.startswith(prefix):
                inner = self.type_to_nim(dt[len(prefix):])
                if "handle" in prefix:
                    return f"{inner}"
                return f"ptr {inner}"
        if dt.startswith("const ref "):
            return self.type_to_nim(dt[10:])
        if dt.startswith("ref "):
            return self.type_to_nim(dt[4:])
        if dt.startswith("move "):
            return self.type_to_nim(dt[5:])
        return _TYPE_MAP.get(dt, dt)

    def _zero_value(self, nim_type: str) -> str:
        if nim_type in ("int32", "int64", "int16", "int8",
                        "uint32", "uint64", "uint16", "uint8",
                        "Natural", "int", "float", "float32", "float64"):
            return "0"
        if nim_type == "bool":
            return "false"
        if nim_type == "string":
            return '""'
        if nim_type == "pointer":
            return "nil"
        if nim_type.startswith("seq[") or nim_type.startswith("array["):
            return "@[]"
        if nim_type.startswith("Table["):
            # nim_type is already the full "Table[K, V]" string, so
            # slicing off the "Table[" prefix leaves "K, V]" -- it
            # already carries its own closing bracket. Appending
            # another "]()" after it produced "initTable[K, V]]()",
            # a real Nim syntax error. See emit_nim.py regression:
            # R-NIM-6.
            return "init" + nim_type + "()"
        if nim_type.startswith("HashSet["):
            return "init" + nim_type + "()"
        return "default(" + nim_type + ")"

    def type_to_nim_ffi(self, dt: str) -> str:
        """Like type_to_nim(), but for `import from C`/`import from C++`
        signatures specifically, where the real ABI is what a raw C
        function actually passes/returns -- not what a native Dictum
        value normally maps to.

        `text` -> Nim `string` everywhere else in this emitter, because
        a native Dictum string is Nim-GC-managed there. But a real C
        function returning `const char*` (e.g. sqlite3_libversion)
        returns a raw pointer, not a Nim string object -- assigning
        that raw pointer into a `string`-typed proc's return slot has
        Nim's GC try to read a managed-string header out of memory
        that was never one, which segfaults on the very first call.
        The correct Nim FFI type for a raw C string is `cstring`.
        Confirmed with a real, live `sqlite3_libversion()` call through
        `-lsqlite3`. See emit_nim.py regression: R-NIM-10.
        """
        if dt.strip() == "text":
            return "cstring"
        return self.type_to_nim(dt)

    def expr_to_nim(self, node) -> str:
        if node is None:
            return "/*nil*/"
        if isinstance(node, Literal):
            v = node.value
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, str):
                return _nim_string_literal(v)
            if isinstance(v, list):
                elems = []
                for x in v:
                    if isinstance(x, Node):
                        s = self.expr_to_nim(x)
                        elems.append(s if s is not None else "/*nil-elem*/")
                    elif isinstance(x, bool):
                        elems.append("true" if x else "false")
                    elif isinstance(x, str):
                        elems.append(_nim_string_literal(x))
                    else:
                        elems.append(str(x))
                return "@[" + ", ".join(elems) + "]"
            return str(v)
        if isinstance(node, Identifier):
            return node.name
        if isinstance(node, FieldAccess):
            return f"{node.obj}.{node.field}"
        if isinstance(node, IndexAccess):
            idx = self.expr_to_nim(node.index)
            return f"{node.collection}[{idx}]"
        if isinstance(node, MapGet):
            key = self.expr_to_nim(node.key)
            return f"{node.name}[{key}]"
        if isinstance(node, Contains):
            val = self.expr_to_nim(node.value)
            return f"{node.name}.contains({val})"
        if isinstance(node, BinaryOp):
            left = self.expr_to_nim(node.left)
            right = self.expr_to_nim(node.right)
            if right in ('"empty"', "'empty'"):
                right = "nil"
            op = _BIN_OP_MAP.get(node.op, node.op)
            return f"({left} {op} {right})"
        if isinstance(node, UnaryOp):
            # "the count of X" / "the length of X" parse to
            # UnaryOp(op='count'|'length', operand=X) -- NOT a FuncCall
            # (see parser.py's `_one` helper). The old special-case
            # below checked `isinstance(node, FuncCall)`, which this
            # node type never is, so it silently fell through to the
            # generic prefix-op path and emitted the mangled
            # `(countnums)` instead of `len(nums)`. Handle both
            # function-style unary ops as real Nim calls here instead
            # of as a prefix operator. See emit_nim.py regression:
            # R-NIM-5.
            if node.op in ("count", "length"):
                operand = self.expr_to_nim(node.operand)
                return f"len({operand})"
            op = _UNARY_OP_MAP.get(node.op, node.op)
            if op is None:
                op = node.op
            operand = self.expr_to_nim(node.operand)
            return f"({op}{operand})"
        if isinstance(node, FuncCall):
            # Kept for safety in case some other call path still
            # constructs a literal FuncCall named "count" -- the real
            # parse path is the UnaryOp branch above (R-NIM-5).
            if node.name in ("count", "the count"):
                if node.args:
                    arg = self.expr_to_nim(node.args[0])
                    return f"len({arg})"
            args = []
            for a in node.args:
                s = self.expr_to_nim(a)
                args.append(s if s is not None else "/*nil-arg*/")
            return f"{node.name}({', '.join(args)})"
        if isinstance(node, NewExpr):
            args = []
            for a in node.args:
                s = self.expr_to_nim(a)
                args.append(s if s is not None else "/*nil-arg*/")
            args_str = ", ".join(args)
            if args_str:
                return f"new({node.type_name})({args_str})"
            return f"new({node.type_name})"
        if isinstance(node, Transmute):
            expr = self.expr_to_nim(node.expr)
            target = self.type_to_nim(node.type)
            return f"cast[{target}]({expr})"
        return f"/* unknown expr: {type(node).__name__} */"

    def emit_node(self, node: Node) -> None:
        if isinstance(node, Program):
            for stmt in node.body:
                if isinstance(stmt, Use):
                    if stmt.path in ("Text", "Console", "Json", "Http",
                                     "File", "Path", "Directory", "CSV",
                                     "Math", "Net", "Thread", "Mutex",
                                     "Timer", "Process", "Signal"):
                        self._imports.add("std/" + stmt.path.lower())
                    elif stmt.path == "Math":
                        self._imports.add("std/math")
            for mod in sorted(self._imports):
                self.emit(f"import {mod}")
            if self._imports:
                self.emit("")
            for stmt in node.body:
                self.emit_node(stmt)
            return

        if isinstance(node, Module):
            prev = self.current_module
            self.current_module = node.name
            for stmt in node.body:
                self.emit_node(stmt)
            self.current_module = prev
            return

        if isinstance(node, Possibilities):
            self.emit(f"type {node.name}* = enum")
            self.indent += 1
            for v in node.variants:
                self.emit(v + ",")
            self.indent -= 1
            self.emit("")
            return

        if isinstance(node, Shape):
            self.shapes[node.name] = {f: t for f, t in node.fields}
            has_methods = bool(node.methods or node.constructors or node.destructor)
            if has_methods:
                self.emit(f"type {node.name}* = ref object")
            else:
                self.emit(f"type {node.name}* = object")
            self.indent += 1
            for fname, ftype in node.fields:
                ft = self.type_to_nim(ftype)
                self.emit(f"{fname}*: {ft}")
            self.indent -= 1
            self.emit("")
            for meth in node.methods:
                params = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in meth.params)
                ret = self.type_to_nim(meth.ret_type) if meth.ret_type else "void"
                self.emit(f"proc {meth.name}*(self: {node.name}")
                if params:
                    self.emit(f"{node.name}.{meth.name}*({params}): {ret} =")
                else:
                    self.emit(f"): {ret} =")
                self.indent += 1
                for stmt in meth.body:
                    self.emit_node(stmt)
                self.indent -= 1
                self.emit("")
            for ctor in node.constructors:
                params = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in ctor.params)
                self.emit(f"proc new{node.name}*({params}): {node.name} =")
                self.indent += 1
                self.emit(f"result = {node.name}()")
                for stmt in ctor.body:
                    self.emit_node(stmt)
                self.indent -= 1
                self.emit("")
            if node.destructor:
                self.emit(f"proc `=destroy`*(self: var {node.name}) =")
                self.indent += 1
                for stmt in node.destructor.body:
                    self.emit_node(stmt)
                self.indent -= 1
                self.emit("")
            return

        if isinstance(node, VarDecl):
            nt = self.type_to_nim(node.type)
            self.declared_vars[node.name] = nt
            if node.value is None:
                zv = self._zero_value(nt)
                self.emit(f"var {node.name}: {nt} = {zv}")
            else:
                val = self.expr_to_nim(node.value)
                self.emit(f"var {node.name}: {nt} = {val}")
            return

        if isinstance(node, AddToList):
            val = self.expr_to_nim(node.value)
            # Nim's seq[T] uses .add(), but HashSet[T] has no .add() --
            # it's .incl() (element insertion into a set). `add to X`
            # is the same Dictum statement for both growable lists and
            # sets, so the emitter must branch on X's declared Nim
            # type rather than assuming .add() always applies.
            # See emit_nim.py regression: R-NIM-7.
            declared = self.declared_vars.get(node.name, "")
            method = "incl" if declared.startswith("HashSet[") else "add"
            self.emit(f"{node.name}.{method}({val})")
            return

        if isinstance(node, MapPut):
            key = self.expr_to_nim(node.key)
            val = self.expr_to_nim(node.value)
            self.emit(f"{node.name}[{key}] = {val}")
            return

        if isinstance(node, Assignment):
            target = node.target
            if "." in target:
                parts = target.split(".", 1)
                base = parts[0]
                if base in self.declared_vars and self.declared_vars[base].startswith("ptr "):
                    target = f"{base}[]" + target[len(base):]
            val = self.expr_to_nim(node.value)
            base_name = target.split("[")[0].split(".")[0]
            # `call SOME_FFI_FN giving x` (an Assignment under the hood)
            # where x is declared `text` (Nim `string`) but the callee
            # is a real `import from C`/`import from C++` function
            # returning `text` compiles to Nim `cstring`
            # (type_to_nim_ffi(), R-NIM-10) -- and Nim does not
            # implicitly convert cstring -> string at an assignment
            # site (`type mismatch: got 'cstring' but expected
            # 'string'`), only in a couple of narrower contexts. `$`
            # is the real, correct Nim conversion. Confirmed with a
            # live `call sqlite3_libversion giving ver` through
            # -lsqlite3. See emit_nim.py regression: R-NIM-11.
            if (isinstance(node.value, FuncCall)
                    and node.value.name in self.ffi_string_returns
                    and self.declared_vars.get(base_name) == "string"):
                val = f"$({val})"
            if base_name not in self.declared_vars and "[" not in target and "." not in target:
                inferred = self._infer_type(node.value) or "int32"
                self.declared_vars[base_name] = inferred
                self.emit(f"var {target}: {inferred} = {val}")
            else:
                self.emit(f"{target} = {val}")
            return

        if isinstance(node, Action):
            self.actions.add(node.name)
            self.declared_vars[node.name] = node.ret_type
            params = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in node.params)
            ret = self.type_to_nim(node.ret_type) if node.ret_type else "void"
            if node.template_params:
                tparams = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in node.template_params)
                self.emit(f"proc {node.name}*[{tparams}]({params}): {ret} =")
            else:
                self.emit(f"proc {node.name}*({params}): {ret} =")
            self.indent += 1
            for stmt in node.body:
                self.emit_node(stmt)
            self.indent -= 1
            self.emit("")
            return

        if isinstance(node, If):
            cond = self.expr_to_nim(node.cond)
            self.emit(f"if {cond}:")
            self.indent += 1
            for stmt in node.then_body:
                self.emit_node(stmt)
            self.indent -= 1
            if node.else_body:
                self.emit("else:")
                self.indent += 1
                for stmt in node.else_body:
                    self.emit_node(stmt)
                self.indent -= 1
            return

        if isinstance(node, While):
            cond = self.expr_to_nim(node.cond)
            self.emit(f"while {cond}:")
            self.indent += 1
            for stmt in node.body:
                self.emit_node(stmt)
            self.indent -= 1
            return

        if isinstance(node, ForEach):
            self.emit(f"for {node.item} in {node.collection}:")
            self.indent += 1
            for stmt in node.body:
                self.emit_node(stmt)
            self.indent -= 1
            return

        if isinstance(node, Repeat):
            # `repeat N times using i` declares `i` as `whole number`
            # (int32) everywhere else in the emitted program. Nim's own
            # `0 ..< N` range literal defaults to Nim's native `int`
            # (64-bit), so the loop variable silently becomes `int` and
            # any later `i`-involving expression against an `int32`
            # (e.g. `result * i`) fails to compile with a type
            # mismatch. Anchor the range to int32 explicitly so the
            # loop variable's type matches every other `whole number`.
            # See emit_nim.py regression: R-NIM-3.
            count = self.expr_to_nim(node.count)
            counter = node.counter or "_i"
            self.emit(f"for {counter} in 0'i32 ..< int32({count}):")
            self.indent += 1
            for stmt in node.body:
                self.emit_node(stmt)
            self.indent -= 1
            return

        if isinstance(node, Break):
            self.emit("break")
            return

        if isinstance(node, Attempt):
            if node.call:
                call_str = self.expr_to_nim(node.call)
                if node.result_name:
                    self.emit(f"var {node.result_name} = {call_str}")
                else:
                    self.emit(call_str)
            self.emit("try:")
            self.indent += 1
            for stmt in node.success_body:
                self.emit_node(stmt)
            self.indent -= 1
            if node.failure_body:
                self.emit("except:")
                self.indent += 1
                if node.failure_name:
                    self.emit(f"var {node.failure_name} = getCurrentExceptionMsg()")
                for stmt in node.failure_body:
                    self.emit_node(stmt)
                self.indent -= 1
            return

        if isinstance(node, Return):
            if isinstance(node.value, Literal) and node.value.value == 0 and type(node.value.value) is int:
                self.emit("return")
            else:
                val = self.expr_to_nim(node.value)
                self.emit(f"return {val}")
            return

        if isinstance(node, Assert):
            cond = self.expr_to_nim(node.cond)
            self.emit(f"assert({cond})")
            return

        if isinstance(node, Print):
            # `print the text ... and ...` mixes string literals with
            # values of any type (numbers, bools, etc). Nim's `&` only
            # concatenates strings, so every non-string-literal part
            # must be run through Nim's `$` stringify operator. `$` on
            # an already-string value is the identity, so wrapping
            # every non-literal part is always safe even without full
            # static type inference. See emit_nim.py regression: R-NIM-2.
            parts = []
            for p in node.parts:
                s = self.expr_to_nim(p)
                if s is None:
                    s = "/*nil-print*/"
                elif not (isinstance(p, Literal) and isinstance(p.value, str)):
                    s = f"$({s})"
                parts.append(s)
            self.emit("echo " + " & ".join(parts))
            return

        if isinstance(node, FuncCall):
            args = []
            for a in node.args:
                s = self.expr_to_nim(a)
                args.append(s if s is not None else "/*nil-arg*/")
            self.emit(f"{node.name}({', '.join(args)})")
            return

        if isinstance(node, ImportC):
            nim_params = []
            if node.params:
                # Each entry in node.params is a TYPE, not "<type> <name>".
                # Dictum's `import from C the action f takes whole number
                # and text ...` names no parameters at all -- exactly like
                # emit_c.py, which generates its own a0/a1 argument names.
                # The previous rsplit(' ', 1) here assumed a "<type> <name>"
                # shape and got BOTH cases wrong:
                #   * `whole number` -> type "whole", name "number" (emits
                #     an invalid Nim type; `whole` does not exist)
                #   * `text`         -> len(parts) == 1, so the parameter
                #     was silently DROPPED, giving the Nim proc the wrong
                #     arity versus the real C symbol -- a silent ABI
                #     mismatch, not a compile error.
                # Found by libmanifest.py verifying sdl2/raylib across all
                # three targets: both passed on c and cpp, both failed only
                # on nim.
                for i, p in enumerate(node.params):
                    nim_type = self.type_to_nim_ffi(p.strip())
                    nim_params.append(f"a{i}: {nim_type}")
            params_str = ", ".join(nim_params)
            ret = self.type_to_nim_ffi(node.ret_type) if node.ret_type else "void"
            name = node.alias or node.action_name
            # Dictum's `import from C` syntax never carries a real
            # header filename (see parser.py's parse_import_c -- there
            # is no header field on the ImportC node at all), only the
            # real C symbol name. This used to guess a header as
            # f"{action_name}.h" (e.g. "sqlite3_libversion.h"), which
            # doesn't exist and fails Nim's own compile with a real
            # "No such file or directory" from the underlying gcc
            # pass. The C backend has never needed a header for this
            # either -- it just forward-declares its own `extern`
            # prototype and lets the linker resolve the real symbol
            # (see ImportC in emit_c.py). Do the same thing here: a
            # bare `{.importc, cdecl.}` with no `header:` makes Nim
            # emit its own matching C prototype instead of trying to
            # #include a header that was never given to it. The actual
            # library gets linked in via `--link LIBNAME` /
            # `--passL:-lLIBNAME` (dictumc_cli.py), same as the C/C++
            # backends' `-l` flags -- Dictum has never auto-discovered
            # system library link flags for any backend. See
            # emit_nim.py regression: R-NIM-9.
            self.emit(f'proc {name}*({params_str}): {ret} {{.importc: "{node.action_name}", cdecl.}}')
            if node.ret_type and node.ret_type.strip() == "text":
                self.ffi_string_returns.add(name)
                self.ffi_string_returns.add(node.action_name)
            return

        if isinstance(node, ImportCpp):
            nim_params = []
            if node.params:
                for p in node.params:
                    parts = p.strip().rsplit(' ', 1)
                    if len(parts) == 2:
                        nim_type = self.type_to_nim_ffi(parts[0])
                        nim_params.append(f"{parts[1]}: {nim_type}")
            params_str = ", ".join(nim_params)
            ret = self.type_to_nim_ffi(node.ret_type) if node.ret_type else "void"
            name = node.alias or node.action_name
            self.emit(f'proc {name}*({params_str}): {ret} {{.importcpp: "{node.action_name}".}}')
            if node.ret_type and node.ret_type.strip() == "text":
                self.ffi_string_returns.add(name)
                self.ffi_string_returns.add(node.action_name)
            return

        if isinstance(node, ImportDict):
            mod_name = node.module_name.lower()
            self.emit(f"import {mod_name}")
            return

        if isinstance(node, HandleTypeDecl):
            self.emit(f"type {node.name}* = distinct pointer")
            return

        if isinstance(node, Use):
            # Emit a real Nim `import` for a module defined in a SIBLING
            # project file. This used to `return` unconditionally, silently
            # dropping every `use` -- which meant a multi-file Nim build had
            # no way to reference another module at all, the core reason
            # project_builder.py only ever offered c/cpp.
            #
            # Stdlib `use Text` / `use File` and same-file modules are still
            # dropped on purpose: the former are provided by Dictum's own
            # runtime rather than a Nim module, and the latter are already
            # in this same translation unit.
            if node.path in getattr(self, '_project_modules', ()) \
                    and node.path not in getattr(self, 'local_modules', ()):
                self.emit(f"import {node.path.lower()}")
            return

        if isinstance(node, UnsafeBlock):
            self.emit('{.emit: """')
            for stmt in node.body:
                if isinstance(stmt, UnsafeToken):
                    self._emit_unsafe_token(stmt)
                else:
                    self.emit(f"    /* {type(stmt).__name__} in unsafe block */")
            self.emit('""" .}')
            return

        if isinstance(node, VerifyToken):
            self.emit(f"# [VERIFY:{node.key}]")
            return

        if isinstance(node, ExternFn):
            params = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in node.params)
            ret = self.type_to_nim(node.ret_type) if node.ret_type else "void"
            name = node.name
            self.emit(f"proc {name}*({params}): {ret} {{.importc.}}")
            return

        if isinstance(node, Bind):
            params = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in node.params)
            ret = self.type_to_nim(node.ret_type) if node.ret_type else "void"
            name = node.alias or node.name
            self.emit(f'proc {name}*({params}): {ret} {{.importc: "{node.name}".}}')
            return

        if isinstance(node, LambdaExpr):
            params = ", ".join(f"{n}: {self.type_to_nim(t)}" for n, t in node.params)
            ret = self.type_to_nim(node.ret_type) if node.ret_type else "void"
            self.emit(f"proc ({params}): {ret} =")
            self.indent += 1
            for stmt in node.body:
                self.emit_node(stmt)
            self.indent -= 1
            return

        self.emit(f"# TODO: emit_node for {type(node).__name__}")

    def _emit_unsafe_token(self, node: UnsafeToken) -> None:
        n = node.name
        p = node.params
        def pa(i, default=""):
            return p[i] if i < len(p) else default
        if n == "ATOMIC_LOAD":
            self.emit(f"__atomic_load({pa(0)}, &{pa(2)}, {pa(1, 'seq_cst')})")
        elif n == "ATOMIC_STORE":
            self.emit(f"__atomic_store({pa(0)}, &{pa(2)}, {pa(1, 'seq_cst')})")
        elif n == "ATOMIC_ADD":
            self.emit(f"{pa(2)} = __atomic_fetch_add({pa(0)}, {pa(1, '1')}, __ATOMIC_SEQ_CST)")
        elif n == "BARRIER_RELEASE":
            self.emit("__atomic_thread_fence(__ATOMIC_RELEASE)")
        elif n == "BARRIER_ACQUIRE":
            self.emit("__atomic_thread_fence(__ATOMIC_ACQUIRE)")
        else:
            self.emit(f"/* UNSAFE: {n} */")

    def _infer_type(self, node: Node) -> Optional[str]:
        if isinstance(node, Literal):
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, int):
                return "int32"
            if isinstance(node.value, float):
                return "float64"
            if isinstance(node.value, str):
                return "string"
        if isinstance(node, Identifier):
            return self.declared_vars.get(node.name)
        if isinstance(node, BinaryOp):
            return self._infer_type(node.left)
        return None

    def get_output(self) -> str:
        # `Table[...]`/`HashSet[...]` types are only ever produced by
        # type_to_nim() while emitting a VarDecl body, well after the
        # single import-emission pass at the top of Program already
        # ran (it only looks at explicit `use` statements) -- so a
        # program with `map of ... to ...` or `set of ...` but no
        # matching `use` statement compiled with an undeclared
        # `Table`/`HashSet` identifier. Patch in the required stdlib
        # imports here as a final pass over the fully emitted source,
        # since by now every VarDecl this program contains has already
        # been through type_to_nim(). See emit_nim.py regression:
        # R-NIM-8.
        needed = []
        body_text = "\n".join(self.output)
        if "Table[" in body_text and "import std/tables" not in body_text:
            needed.append("import std/tables")
        if "HashSet[" in body_text and "import std/sets" not in body_text:
            needed.append("import std/sets")
        if needed:
            insert_at = 0
            for i, line in enumerate(self.output):
                if line.startswith("import "):
                    insert_at = i + 1
                else:
                    break
            for offset, imp in enumerate(needed):
                self.output.insert(insert_at + offset, imp)
            if insert_at == 0 and self.output and self.output[len(needed)].strip() != "":
                self.output.insert(len(needed), "")
        return "\n".join(self.output)
