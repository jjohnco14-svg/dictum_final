from __future__ import annotations

"""
Dictum Lexer — tokenises Dictum source text.
Extracted from transpiler.py v3.3 and kept API-identical.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Any


class TokenType(Enum):
    WORD    = auto()
    NUMBER  = auto()
    STRING  = auto()
    NEWLINE = auto()
    INDENT  = auto()
    DEDENT  = auto()
    EOF     = auto()


@dataclass
class Token:
    type: TokenType
    value: Any
    line: int = 0


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.indent_stack = [0]
        self.tokens: List[Token] = []

    def peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        if idx >= len(self.source):
            return '\0'
        return self.source[idx]

    def advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line += 1
        return ch

    def skip_spaces(self) -> None:
        while self.peek() in ' \t\r':
            self.advance()

    _STRING_ESCAPES = {
        'n': '\n', 't': '\t', 'r': '\r', '0': '\0',
        '"': '"', "'": "'", '\\': '\\',
    }

    def read_string(self) -> Token:
        quote = self.advance()
        start_line = self.line
        buf = []
        while self.peek() not in ('\0', '\n'):
            ch = self.advance()
            if ch == quote:
                return Token(TokenType.STRING, ''.join(buf), start_line)
            if ch == '\\':
                # FIX: this used to just discard the backslash and keep
                # whatever character followed it literally — so `\"`
                # became a bare `"` with no record that it had been
                # escaped, `\n` became the letter 'n' (not a newline),
                # and `\\` became a single `\`. That's silently wrong for
                # any string with an escape in it, and specifically
                # breaks embedding JSON literals in Dictum source (e.g.
                # `"{\"name\":\"Jeff\"}"`), which need `\"` to survive as
                # an actual quote character the C emitter can re-escape.
                nxt = self.advance()
                ch = self._STRING_ESCAPES.get(nxt, nxt)
            buf.append(ch)
        raise SyntaxError(f"Unterminated string at line {start_line}")

    def read_number(self) -> Token:
        start_line = self.line
        buf = []
        while self.peek().isdigit() or self.peek() == '.':
            buf.append(self.advance())
        val = ''.join(buf)
        if '.' in val:
            return Token(TokenType.NUMBER, float(val), start_line)
        return Token(TokenType.NUMBER, int(val), start_line)

    def read_word(self) -> Token:
        start_line = self.line
        buf = []
        while self.peek().isalnum() or self.peek() == '_':
            buf.append(self.advance())
        return Token(TokenType.WORD, ''.join(buf), start_line)

    def tokenize(self) -> List[Token]:
        while True:
            self.skip_spaces()
            ch = self.peek()
            if ch == '\0':
                break
            if ch in ('"', "'"):
                self.tokens.append(self.read_string())
                continue
            if ch.isdigit():
                self.tokens.append(self.read_number())
                continue
            if ch.isalpha() or ch == '_':
                self.tokens.append(self.read_word())
                continue
            if ch == '#':
                if self.peek(1) == '[':
                    self.tokens.append(Token(TokenType.WORD, '#', self.line))
                    self.advance()
                    continue
                else:
                    while self.peek() not in ('\0', '\n'):
                        self.advance()
                    continue
            if ch == '\n':
                self.advance()
                self.tokens.append(Token(TokenType.NEWLINE, None, self.line))
                indent = 0
                while self.peek() in ' \t':
                    if self.advance() == '\t':
                        indent += 4
                    else:
                        indent += 1
                if self.peek() in ('\n', '#', '\0'):
                    continue
                if indent > self.indent_stack[-1]:
                    self.indent_stack.append(indent)
                    self.tokens.append(Token(TokenType.INDENT, None, self.line))
                elif indent < self.indent_stack[-1]:
                    while indent < self.indent_stack[-1]:
                        self.indent_stack.pop()
                        self.tokens.append(Token(TokenType.DEDENT, None, self.line))
                    if indent != self.indent_stack[-1]:
                        raise SyntaxError(f"Invalid dedent at line {self.line}")
                continue
            # Single-char punctuation
            _SINGLE = {'.', '*', '&', '(', ')', '[', ']', ',', ';', '+', '-', '%', '@'}
            if ch in _SINGLE:
                self.tokens.append(Token(TokenType.WORD, ch, self.line))
                self.advance()
                continue
            # Skip unknown characters (e.g. ':', '=', '/')
            self.advance()

        while len(self.indent_stack) > 1:
            self.indent_stack.pop()
            self.tokens.append(Token(TokenType.DEDENT, None, self.line))
        self.tokens.append(Token(TokenType.EOF, None, self.line))
        return self.tokens
"""
Dictum AST Nodes — shared dataclasses for all compiler phases.
Extracted from monolith transpiler.py v3.3.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any, Dict


@dataclass
class Node:
    line: int = field(default=0, kw_only=True)


@dataclass
class Program(Node):
    name: str = ''
    body: List[Node] = field(default_factory=list)
    export: bool = False


@dataclass
class Module(Node):
    name: str = ''
    body: List[Node] = field(default_factory=list)
    export: bool = False


@dataclass
class Shape(Node):
    name: str = ''
    fields: List[Tuple[str, str]] = field(default_factory=list)
    is_packed: bool = False
    parent: Optional[str] = None
    methods: List['Method'] = field(default_factory=list)
    constructors: List['Constructor'] = field(default_factory=list)
    destructor: Optional['Destructor'] = None
    access_map: Dict[str, str] = field(default_factory=dict)
    export: bool = False


@dataclass
class Method(Node):
    name: str = ''
    params: List[Tuple[str, str]] = field(default_factory=list)
    ret_type: str = ''
    body: List[Node] = field(default_factory=list)
    access: str = 'public'
    is_virtual: bool = False
    is_override: bool = False


@dataclass
class Constructor(Node):
    params: List[Tuple[str, str]] = field(default_factory=list)
    body: List[Node] = field(default_factory=list)
    access: str = 'public'


@dataclass
class Destructor(Node):
    body: List[Node] = field(default_factory=list)
    access: str = 'public'
    is_virtual: bool = False


@dataclass
class VarDecl(Node):
    name: str = ''
    type: str = ''
    value: Optional[Node] = None
    export: bool = False


@dataclass
class Assignment(Node):
    target: str = ''
    value: Node = field(default_factory=lambda: Literal(0))


@dataclass
class Action(Node):
    name: str = ''
    params: List[Tuple[str, str]] = field(default_factory=list)
    ret_type: str = ''
    body: List[Node] = field(default_factory=list)
    template_params: List[Tuple[str, str]] = field(default_factory=list)
    export: bool = False


@dataclass
class FuncCall(Node):
    name: str = ''
    args: List[Node] = field(default_factory=list)


@dataclass
class Return(Node):
    value: Node = field(default_factory=lambda: Literal(0))


@dataclass
class If(Node):
    cond: Node = field(default_factory=lambda: Literal(True))
    then_body: List[Node] = field(default_factory=list)
    else_body: List[Node] = field(default_factory=list)


@dataclass
class While(Node):
    cond: Node = field(default_factory=lambda: Literal(True))
    body: List[Node] = field(default_factory=list)


@dataclass
class ForEach(Node):
    item: str = ''
    collection: str = ''
    body: List[Node] = field(default_factory=list)


@dataclass
class Repeat(Node):
    count: Node = field(default_factory=lambda: Literal(0))
    counter: str = ''
    body: List[Node] = field(default_factory=list)


@dataclass
class Break(Node):
    """`stop repeating` — exits the nearest enclosing loop (while/for/
    repeat). Lowers to a plain C/C++ `break;`."""
    pass


@dataclass
class Attempt(Node):
    call: Optional['FuncCall'] = None
    result_name: str = ''
    success_body: List[Node] = field(default_factory=list)
    failure_name: str = ''
    failure_body: List[Node] = field(default_factory=list)


@dataclass
class Literal(Node):
    value: Any = None


@dataclass
class Identifier(Node):
    name: str = ''


@dataclass
class BinaryOp(Node):
    op: str = ''
    left: Node = field(default_factory=lambda: Literal(0))
    right: Node = field(default_factory=lambda: Literal(0))


@dataclass
class UnaryOp(Node):
    op: str = ''
    operand: Node = field(default_factory=lambda: Literal(0))


@dataclass
class FieldAccess(Node):
    obj: str = ''
    field: str = ''


@dataclass
class IndexAccess(Node):
    collection: str = ''
    index: Node = field(default_factory=lambda: Literal(0))


@dataclass
class Assert(Node):
    cond: Node = field(default_factory=lambda: Literal(True))


@dataclass
class Print(Node):
    parts: List[Node] = field(default_factory=list)


@dataclass
class ImportC(Node):
    action_name: str = ''
    params: List[str] = field(default_factory=list)
    ret_type: str = ''
    alias: str = ''


@dataclass
class ImportCpp(Node):
    item_type: str = ''
    item_name: str = ''
    params: List[str] = field(default_factory=list)
    ret_type: str = ''
    alias: str = ''


@dataclass
class ImportDict(Node):
    """MISSING-08: import MyModule from "mymodule.dict"
    Resolved by the Transpiler at run-time: transpile the .dict file,
    emit #include "mymodule.h", and return the .c/.h pair for the module.
    """
    module_name: str = ''   # e.g. "MyModule"
    file_path:   str = ''   # e.g. "mymodule.dict"
    alias:       str = ''   # optional alias, defaults to module_name


@dataclass
class UnsafeBlock(Node):
    body: List[Node] = field(default_factory=list)


@dataclass
class ExternFn(Node):
    name: str = ''
    params: List[Tuple[str, str]] = field(default_factory=list)
    ret_type: str = ''
    syscall_name: Optional[str] = None


@dataclass
class Transmute(Node):
    expr: Node = field(default_factory=lambda: Literal(0))
    type: str = ''


@dataclass
class Use(Node):
    path: str = ''
    is_system: bool = False


@dataclass
class HandleTypeDecl(Node):
    """`define handle Name` — declares Name as a distinct nominal handle
    type. Two handle types with different names are never interchangeable,
    even though both compile down to an opaque pointer in C. This catches
    e.g. passing a Stmt where a Db is expected at compile time instead of
    letting it through as silent void*-to-void* aliasing."""
    name: str = ''


@dataclass
class Bind(Node):
    name: str = ''
    params: List[Tuple[str, str]] = field(default_factory=list)
    ret_type: str = ''
    alias: str = ''


@dataclass
class NewExpr(Node):
    type_name: str = ''
    args: List[Node] = field(default_factory=list)


@dataclass
class LambdaExpr(Node):
    params: List[Tuple[str, str]] = field(default_factory=list)
    ret_type: str = ''
    body: List[Node] = field(default_factory=list)


# Possibilities (enum) — not a dataclass in original, kept as simple class
class Possibilities:
    def __init__(self, name: str, variants: List[str], line: int = 0):
        self.name = name
        self.variants = variants
        self.line = line


# ── Special token AST node (merge architecture L3) ───────────────────────────
# Represents [TOKEN_NAME: param1 : param2 : ... : result_var] inside unsafe blocks.
# The parser builds these; emit_c.py expands them to verified C intrinsics.

@dataclass
class UnsafeToken(Node):
    """A special pre-verified token inside an unsafe block.

    Examples:
        [ATOMIC_CAS_64: ptr : expected : desired : ok]
        [BARRIER_RELEASE]
        [SIMD_LOAD_F32: ptr : reg]
        [HP_PROTECT: hp_record : node_ptr]
    """
    name:   str             = ''   # e.g. 'ATOMIC_CAS_64'
    params: List[str]       = field(default_factory=list)  # positional params
    # Convenience accessors (set by parser from params by position)
    result: str             = ''   # last param if it's a result variable


@dataclass  
class VerifyToken(Node):
    """[VERIFY:CATEGORY_ID] — L2 plan verification marker.

    Emitted as a C comment: /* [VERIFY:OPERATION_3] */
    The review engine checks these match the [PLAN:...] items.
    """
    key: str = ''   # e.g. 'OPERATION_3'
"""
type_registry.py -- single source of truth for Dictum's primitive type
vocabulary.

WHY THIS EXISTS
----------------
Before this module, the same type vocabulary was independently duplicated
across five files with no mechanism keeping them in sync:
  - parser.py       _TERMINAL_TYPES, _PRIMITIVE_SUFFIXES
  - emit_c.py        self.types  (Dictum name -> C type)
  - emit_cpp.py       self.types  (Dictum name -> C++ type)
  - validator.py     PRIMITIVE_TYPES, NUMERIC_TYPES
  - grammar.py       TYPE_WORDS

This was a confirmed, live source of bugs, not a theoretical risk:
  - `u8`/`u64` were parseable and emittable but missing from the
    validator's own type sets -- any program using them failed validation.
  - `f32` had to be added by hand in all five places to work end-to-end.
  - `bytes` (plural) was accepted by the parser AND listed in grammar.py's
    TYPE_WORDS, but had no entry in the validator's PRIMITIVE_TYPES and no
    C/C++ mapping in either emitter at all -- `keep x as bytes` parsed
    successfully and then failed validation with "Unknown type 'bytes'",
    a contradiction between two files that should never have been able to
    disagree.

Every one of those was the same root cause: five independent lists, no
shared definition. This module is that shared definition. Adding a new
primitive type now means adding ONE entry here; every consumer picks it up
automatically.

WHAT THIS DOES NOT COVER
-------------------------
Recursive/compound type FORMS (`list of <T>`, `unique handle to <T>`,
`raw pointer to <T>`, `const ref <T>`, `handle to bytes`) are parsed by
dedicated control-flow branches in parser.py's parse_type(), not simple
table lookups -- they genuinely need to recurse into an inner type, which
a flat word table can't express. This module only centralizes the leaf
vocabulary (the primitives) and the building-block WORDS those compound
forms consume (exported via WRAPPER_WORDS, so grammar.py's GBNF-facing
TYPE_WORDS can still include them without parser.py's actual parsing logic
needing to change at all).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class PrimitiveType:
    name: str                      # canonical Dictum name, e.g. "whole number"
    words: Tuple[str, ...]         # word tokens that spell it, e.g. ("whole", "number")
    c_type: str
    cpp_type: Optional[str] = None  # None -> same as c_type
    numeric: bool = False
    terminal: bool = False          # True if usable as a single bare word
                                     # (-> parser._TERMINAL_TYPES)
    var_valid: bool = True          # False if only valid as a return type
                                     # (e.g. `nothing` -- void isn't a
                                     # value a variable can hold)

    @property
    def cpp(self) -> str:
        return self.cpp_type if self.cpp_type is not None else self.c_type


# The canonical list. This is the ONE place to add/change a primitive type.
PRIMITIVES: List[PrimitiveType] = [
    PrimitiveType("whole number",       ("whole", "number"),      "int32_t",      numeric=True),
    PrimitiveType("count",              ("count",),               "size_t",       numeric=True, terminal=True),
    PrimitiveType("fractional number",  ("fractional", "number"), "double",       numeric=True),
    PrimitiveType("decimal number",     ("decimal", "number"),    "double",       numeric=True),
    PrimitiveType("decimal",            ("decimal",),             "double",       numeric=True, terminal=True),
    PrimitiveType("truth value",        ("truth", "value"),       "bool"),
    PrimitiveType("bool",               ("bool",),                "bool",         terminal=True),
    PrimitiveType("byte",               ("byte",),                "uint8_t",      numeric=True, terminal=True),
    # FIX: `bytes` (plural) was parseable (parser._TERMINAL_TYPES) and
    # listed in grammar.py's TYPE_WORDS, but had no validator entry and no
    # C/C++ mapping anywhere -- "Unknown type 'bytes'" on every use despite
    # looking, from the parser's side, exactly as valid as `byte`. Given a
    # real, distinct meaning here: a raw byte pointer (distinct from the
    # opaque `handle to bytes` below).
    PrimitiveType("bytes",              ("bytes",),               "uint8_t*",     terminal=True),
    PrimitiveType("text",               ("text",),                "dictum_text",  cpp_type="const char*", terminal=True),
    PrimitiveType("handle to bytes",    ("handle", "to", "bytes"), "void*"),
    PrimitiveType("opaque pointer",     ("opaque", "pointer"),    "void*"),
    PrimitiveType("nothing",            ("nothing",),             "void",         terminal=True, var_valid=False),
    PrimitiveType("u8",  ("u8",),  "uint8_t",  numeric=True, terminal=True),
    PrimitiveType("u16", ("u16",), "uint16_t", numeric=True, terminal=True),
    PrimitiveType("u32", ("u32",), "uint32_t", numeric=True, terminal=True),
    PrimitiveType("u64", ("u64",), "uint64_t", numeric=True, terminal=True),
    PrimitiveType("i16", ("i16",), "int16_t",  numeric=True, terminal=True),
    PrimitiveType("i32", ("i32",), "int32_t",  numeric=True, terminal=True),
    PrimitiveType("i64", ("i64",), "int64_t",  numeric=True, terminal=True),
    PrimitiveType("f32", ("f32",), "float",    numeric=True, terminal=True),
    PrimitiveType("f64", ("f64",), "double",   numeric=True, terminal=True),
    PrimitiveType("result", ("result",), "void*", terminal=True),
]

BY_NAME: Dict[str, PrimitiveType] = {p.name: p for p in PRIMITIVES}

# Building-block words consumed by RECURSIVE type forms that parser.py
# hand-parses (list of <T>, unique/shared/weak/raw handle/pointer to <T>,
# const ref <T>, ref <T>, move <T>). These aren't primitives themselves --
# they're grammatical scaffolding -- but grammar.py's GBNF-facing
# TYPE_WORDS needs them too, so they're exported alongside the primitives
# rather than living as yet another independent hand-typed list.
WRAPPER_WORDS: Set[str] = {
    'list', 'array', 'of',
    'unique', 'shared', 'weak', 'raw', 'handle', 'pointer', 'to',
    'const', 'ref', 'move',
}


def all_type_words() -> Set[str]:
    """Every individual word token across every primitive, plus the
    recursive-form building-block words. For grammar.py's TYPE_WORDS /
    keeping the static .gbnf files' type-word rule in sync."""
    words: Set[str] = set()
    for p in PRIMITIVES:
        words.update(p.words)
    words.update(WRAPPER_WORDS)
    return words


def terminal_type_words() -> Set[str]:
    """Single bare-word complete types. For parser._TERMINAL_TYPES."""
    return {p.name for p in PRIMITIVES if p.terminal}


def primitive_suffixes() -> Dict[str, List[str]]:
    """Multi-word compound types expressible as a simple
    {first_word: [remaining_words]} lookup (`whole` -> `number`, `opaque`
    -> `pointer`, etc). For parser._PRIMITIVE_SUFFIXES. Excludes compounds
    with hand-coded control flow elsewhere (`handle to bytes` has its own
    branch in parse_type() because `handle` alone is also a distinct,
    valid nominal-handle-reference form -- it can't be a flat suffix
    lookup without breaking that other meaning)."""
    out: Dict[str, List[str]] = {}
    for p in PRIMITIVES:
        if len(p.words) > 1 and not p.terminal and p.words[0] != 'handle':
            out.setdefault(p.words[0], []).extend(p.words[1:])
    return out


def c_type_map() -> Dict[str, str]:
    """Dictum name -> C type. For emit_c.py's self.types."""
    return {p.name: p.c_type for p in PRIMITIVES}


def cpp_type_map() -> Dict[str, str]:
    """Dictum name -> C++ type. For emit_cpp.py's self.types."""
    return {p.name: p.cpp for p in PRIMITIVES}


def primitive_type_names() -> Set[str]:
    """All valid canonical primitive type names. For validator.py's
    PRIMITIVE_TYPES."""
    return set(BY_NAME.keys())


def numeric_type_names() -> Set[str]:
    """Primitive type names valid in arithmetic/comparison contexts. For
    validator.py's NUMERIC_TYPES."""
    return {p.name for p in PRIMITIVES if p.numeric}


def non_variable_type_names() -> Set[str]:
    """Primitive type names that are valid types in general (e.g. as an
    action return type) but not valid as a `keep <name> as <type>`
    variable declaration's type. For validator.py's VarDecl check."""
    return {p.name for p in PRIMITIVES if not p.var_valid}
"""
Dictum Parser — builds the AST from a token stream.
Extracted from transpiler.py v3.3.

Phase 1 fixes applied:
  BUG-02: `set X to <expr>` now parsed as Assignment.
  BUG-03: `is less than or equal to` / `is greater than or equal to` now work.
  BUG-08: `keep N as list of whole number with room for 10` no longer crashes.
  MISSING-04: `otherwise:` / `else:` plain else branch fully supported.
  MISSING-09: `truth value` -> bool; `true`/`false` literals consistent.

Grammar integration:
  Parser accepts an optional DictumGrammar instance.  When provided, every
  token fed to the parser is also fed to the grammar state machine, enabling
  grammar-constrained parsing without a separate pre-pass.
"""

from typing import List, Optional, TYPE_CHECKING


if TYPE_CHECKING:
    from .grammar import DictumGrammar


class Parser:
    def __init__(self, tokens: List[Token], grammar: Optional['DictumGrammar'] = None):
        self.tokens = tokens
        self.pos = 0
        self.in_at_index = False
        # Optional grammar state machine for constrained parsing
        self._grammar = grammar

    # ------------------------------------------------------------------
    # Token navigation
    # ------------------------------------------------------------------
    def cur(self) -> Token:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return self.tokens[-1]

    def advance(self) -> Token:
        tok = self.cur()
        self.pos += 1
        # Feed grammar if attached
        if self._grammar is not None:
            ttype = tok.type.name if tok.type != TokenType.WORD else "WORD"
            self._grammar.feed_token(str(tok.value), ttype, strict=False)
        return tok

    def match_word(self, *words: str) -> bool:
        tok = self.cur()
        if tok.type == TokenType.WORD and tok.value in words:
            self.pos += 1
            if self._grammar is not None:
                self._grammar.feed_token(tok.value, "WORD", strict=False)
            return True
        return False

    def expect_word(self, *words: str) -> Token:
        tok = self.advance()
        if tok.type != TokenType.WORD:
            raise SyntaxError(f"Expected word, got {tok.type.name} at line {tok.line}")
        if words and tok.value not in words:
            raise SyntaxError(f"Expected {words}, got '{tok.value}' at line {tok.line}")
        return tok

    def consume_newlines(self) -> None:
        while self.cur().type in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT):
            self.advance()

    # ------------------------------------------------------------------
    # Top-level
    # ------------------------------------------------------------------
    def parse(self) -> List[Node]:
        nodes = []
        while self.cur().type != TokenType.EOF:
            self.consume_newlines()
            if self.cur().type == TokenType.EOF:
                break
            nodes.append(self.parse_top_level())
            self.consume_newlines()
        return nodes

    def parse_top_level(self) -> Node:
        self.consume_newlines()
        tok = self.cur()
        if tok.type != TokenType.WORD:
            raise SyntaxError(f"Expected top-level keyword, got {tok.type.name} at line {tok.line}")
        is_export = False
        if tok.value == 'export':
            is_export = True
            self.advance()
            tok = self.cur()
        if tok.value == 'program':
            node = self.parse_program(); node.export = is_export; return node
        elif tok.value == 'module':
            node = self.parse_module(); node.export = is_export; return node
        elif tok.value == 'shape':
            node = self.parse_shape(); node.export = is_export; return node
        elif tok.value == 'action':
            node = self.parse_action(); node.export = is_export; return node
        elif tok.value == 'use':
            return self.parse_use()
        elif tok.value == 'bind':
            return self.parse_bind()
        elif tok.value == 'import':
            return self.parse_import()
        elif tok.value == 'extern':
            return self.parse_extern()
        elif tok.value == 'define':
            return self.parse_define()
        elif tok.value == '#':
            attr = self.parse_attribute()
            if attr == 'packed':
                self.consume_newlines()
                if self.cur().type == TokenType.WORD and self.cur().value == 'shape':
                    return self.parse_shape(is_packed=True)
            raise SyntaxError(f"Unknown attribute #{attr} at line {tok.line}")
        elif tok.value == '[':
            # Bracket tokens (e.g. a legacy [VERIFY: ...] marker, or any
            # other [TOKEN: ...] form) are meaningless as a top-level
            # declaration — they carry no structural information the
            # compiler needs — but a model has no way to know that only
            # parse_statement() (inside a block/action body) previously
            # accepted them, not parse_top_level(). Rather than hard-
            # failing with "Unknown top-level '['" for a token that is
            # harmless to just skip, consume it and continue to the next
            # real top-level declaration.
            #
            # FIX: this used to recurse into parse_top_level() once per
            # stray bracket token instead of looping. A single stray
            # token, or a short run, was fine either way — but a long
            # run of consecutive bracket tokens (this project has
            # observed 4096-token generations that were almost entirely
            # repeated bracket tokens under runaway repetition) would
            # consume one Python stack frame per token and eventually
            # hit RecursionError (default limit 1000) on exactly the
            # input this defensive path exists to tolerate. Loop
            # internally over consecutive '[' tokens instead — this
            # function still always returns a single real declaration,
            # just via a bounded loop rather than unbounded recursion.
            while self.cur().type == TokenType.WORD and self.cur().value == '[':
                self._parse_bracket_token()
                self.consume_newlines()
            return self.parse_top_level()
        else:
            raise SyntaxError(f"Unknown top-level '{tok.value}' at line {tok.line}")

    def parse_program(self) -> Program:
        line = self.advance().line
        name = self.expect_word().value
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'program':
                self.advance()
        return Program(name=name, body=body, line=line)

    def parse_module(self) -> Module:
        line = self.advance().line
        name = self.expect_word().value
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'module':
                self.advance()
        return Module(name=name, body=body, line=line)

    # ------------------------------------------------------------------
    # Block
    # ------------------------------------------------------------------
    def parse_block(self) -> List[Node]:
        statements = []
        # Pre-INDENT: consume any directives or annotations at statement level
        while self.cur().type == TokenType.WORD and self.cur().value in ('#', '@', 'polyglot'):
            stmt = self.parse_statement()
            statements.append(stmt)
            while self.cur().type == TokenType.NEWLINE:
                self.advance()

        if self.cur().type == TokenType.INDENT:
            self.advance()
        else:
            if self.cur().type == TokenType.NEWLINE:
                self.advance()
            if self.cur().type == TokenType.INDENT:
                self.advance()
        _BLOCK_TERM_WORDS = {'end', 'otherwise', 'on'}
        while self.cur().type not in (TokenType.DEDENT, TokenType.EOF):
            while self.cur().type == TokenType.NEWLINE:
                self.advance()
            if self.cur().type in (TokenType.DEDENT, TokenType.EOF):
                break
            if self.cur().type == TokenType.WORD and self.cur().value in _BLOCK_TERM_WORDS:
                break
            statements.append(self.parse_statement())
            while self.cur().type == TokenType.NEWLINE:
                self.advance()
        if self.cur().type == TokenType.DEDENT:
            self.advance()
        return statements

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------
    def parse_statement(self) -> Node:
        tok = self.cur()
        if tok.type in (TokenType.NUMBER, TokenType.STRING):
            return self.parse_expression()
        if tok.type == TokenType.WORD and tok.value == '[':
            # [VERIFY:CATEGORY_ID] / [TOKEN_NAME: p1 : p2 : ...] bracket
            # tokens can legitimately appear anywhere in generated Dictum,
            # not only inside `unsafe:` blocks — SKILL_BUILD.md instructs
            # the model to emit [VERIFY: ...] before each plan item, with
            # no restriction to unsafe contexts. Previously only
            # parse_unsafe_body() routed to _parse_bracket_token(); the
            # general statement dispatch had no case for '[' at all and
            # fell through to expression parsing, which doesn't recognize
            # '[' either — the bracket and its contents were silently
            # consumed as a sequence of meaningless bare-word statements.
            node = self._parse_bracket_token()
            if node is not None:
                return node
            # _parse_bracket_token() returning None means it couldn't
            # parse a recognized bracket form — fall through to a clear
            # error rather than silently treating '[' as a bare word.
            raise SyntaxError(f"Unrecognized bracket token at line {tok.line}")
        if tok.type != TokenType.WORD:
            raise SyntaxError(f"Expected statement, got {tok.type.name} at line {tok.line}")

        word = tok.value
        if word == 'export':        return self.parse_export_statement()
        elif word == 'keep':        return self.parse_keep()
        elif word == 'put':         return self.parse_put()
        # BUG-02 FIX: `set X to <expr>` is a valid assignment form
        elif word == 'set':         return self.parse_set()
        elif word == 'if':          return self.parse_if()
        elif word == 'while':       return self.parse_while()
        elif word == 'for':         return self.parse_for()
        elif word == 'repeat':      return self.parse_repeat()
        elif word == 'attempt':     return self.parse_attempt()
        elif word == 'return':      return self.parse_return()
        elif word == 'produce':     return self.parse_produce()
        elif word == 'assert':      return self.parse_assert()
        elif word == 'print':       return self.parse_print()
        elif word == 'call':        return self.parse_call()
        elif word == 'run':         return self.parse_run()
        elif word == 'shape':       return self.parse_shape()
        elif word == 'action':      return self.parse_action()
        elif word == 'defer':       return self.parse_defer()
        elif word == 'release':     return self.parse_release()
        elif word == 'use':         return self.parse_use()
        elif word == 'bind':        return self.parse_bind()
        elif word == 'import':      return self.parse_import()
        elif word == 'extern':      return self.parse_extern()
        elif word == 'define':      return self.parse_define()
        elif word == 'unsafe':      return self.parse_unsafe()
        elif word == 'stop':        return self.parse_stop()
        elif word == '#':
            attr = self.parse_attribute()
            if attr == 'packed':
                self.consume_newlines()
                if self.cur().type == TokenType.WORD and self.cur().value == 'shape':
                    return self.parse_shape(is_packed=True)
            raise SyntaxError(f"Unknown attribute #{attr} at line {tok.line}")
        elif word == 'possibilities': return self.parse_possibilities()
        elif word == 'end':
            raise SyntaxError(f"Unexpected 'end' at line {tok.line}")
        else:
            return self.parse_expression()

    # ------------------------------------------------------------------
    # BUG-02 FIX: set X to <expr>
    # ------------------------------------------------------------------
    def parse_set(self) -> Assignment:
        """Parse `set <target> to <expr>` → Assignment node."""
        line = self.advance().line      # consume 'set'
        target = self.parse_lvalue()
        self.expect_word('to')
        value = self.parse_expression()
        return Assignment(target=target, value=value, line=line)

    # ------------------------------------------------------------------
    # Attribute
    # ------------------------------------------------------------------
    def parse_attribute(self) -> str:
        self.expect_word('#')
        self.expect_word('[')
        name = self.expect_word().value
        self.expect_word(']')
        return name

    # ------------------------------------------------------------------
    # keep (variable declaration)
    # BUG-08 FIX: `list of <type>` parsed before scanning for `for`
    # ------------------------------------------------------------------
    def parse_keep(self) -> VarDecl:
        line = self.advance().line
        name = self.expect_word().value
        self.expect_word('as')
        type_ = self.parse_type()
        value = None
        if self.match_word('with'):
            if self.match_word('value'):
                value = self.parse_expression()
            elif self.match_word('values'):
                values = []
                while not self._is_end_of_statement():
                    values.append(self.parse_expression())
                    if not self.match_word('and'):
                        if (self.cur().type == TokenType.WORD and
                                self.cur().value == ','):
                            self.advance()
                        else:
                            break
                value = Literal(values)
            elif self.match_word('all'):
                self.expect_word('values')
                val = self.parse_expression()
                value = UnaryOp(op='all_values', operand=val)
            elif self.match_word('room'):
                self.expect_word('for')
                val = self.parse_expression()
                value = UnaryOp(op='room_for', operand=val)
            elif self.match_word('no'):
                self.expect_word('value')
                value = None
            else:
                raise SyntaxError(f"Unknown 'with' clause at line {line}")
        return VarDecl(name=name, type=type_, value=value, line=line)

    # ------------------------------------------------------------------
    # Type parser
    # BUG-08 FIX: treats `list` and `array` as type-word continuators so
    #             `list of whole number` doesn't fall through to parse_for.
    # MISSING-09 FIX: multi-word primitives handled explicitly.
    # ------------------------------------------------------------------
    # Standalone multi-word primitive types (keyword → trailing words)
    # SOURCE OF TRUTH: derived from type_registry.py, not hand-maintained
    # here -- see that module's docstring for why (the same vocabulary
    # used to be independently duplicated across 5 files with no sync
    # mechanism, which caused several real bugs: u8/u64 missing from the
    # validator, f32 needing manual addition in 6 places, `bytes` being
    # parseable here but invalid everywhere else).
    # (primitive_suffixes, terminal_type_words defined earlier in this same file)
    _PRIMITIVE_SUFFIXES = primitive_suffixes()
    # Terminal single words
    _TERMINAL_TYPES = terminal_type_words()
    # Words that always end a type
    _TYPE_STOP = {
        'with', 'produces', 'takes', 'as', 'into', 'from', 'using',
        'or', 'is', 'then', 'end', 'if', 'otherwise', 'on',
        'by', 'in', 'repeat', 'times', 'giving', 'alone',
        'holds', 'holding', 'modulo', 'plus', 'minus', 'greater', 'less',
        'equal', 'not', 'least', 'most', 'true', 'false', 'success',
        'failure', 'empty', 'newline', 'room', 'value', 'values',
        'no', 'all', 'item', ',', '@', '(', ')',
    }

    def parse_type(self) -> str:
        """Recursive descent type parser. Returns a type string."""
        if self.cur().type != TokenType.WORD:
            return ''
        word = self.cur().value
        if word in self._TYPE_STOP:
            return ''

        # ── action type ──────────────────────────────────────────────
        if word == 'action':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'taking':
                self.advance()
                param_parts = []
                while True:
                    pname = self.expect_word().value
                    self.expect_word('as')
                    ptype = self.parse_type()
                    param_parts.append(f"{pname} as {ptype}")
                    if not self.match_word('and'):
                        break
                self.expect_word('produces')
                ret = self.parse_type()
                return f"action taking {' and '.join(param_parts)} produces {ret}"
            return 'action'

        # ── list / array of <inner> ───────────────────────────────────
        if word in ('list', 'array'):
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'of':
                self.advance()
                inner = self.parse_type()
                return f"{word} of {inner}"
            return word

        # ── smart-pointer wrapper types (C++) ─────────────────────────
        #    unique/shared/weak/raw handle to <inner>
        #    unique/shared/weak/raw pointer [to <inner>]   (bare pointer form)
        if word in ('unique', 'shared', 'weak', 'raw'):
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'handle':
                self.advance()
                if self.cur().type == TokenType.WORD and self.cur().value == 'to':
                    self.advance()
                inner = self.parse_type()
                return f"{word} handle to {inner}"
            if self.cur().type == TokenType.WORD and self.cur().value == 'pointer':
                self.advance()
                if self.cur().type == TokenType.WORD and self.cur().value == 'to':
                    self.advance()
                    inner = self.parse_type()
                    return f"{word} pointer to {inner}"
                # bare `raw pointer` / `unique pointer` with no explicit
                # inner type — do not swallow the following token as an
                # inner type; it belongs to the caller (e.g. a param name).
                return f"{word} pointer"
            return word

        # ── reference types (C++) ────────────────────────────────────
        if word == 'const':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'ref':
                self.advance()
                inner = self.parse_type()
                return f"const ref {inner}"
            inner = self.parse_type()
            return f"const {inner}"

        if word == 'ref':
            self.advance()
            inner = self.parse_type()
            return f"ref {inner}"

        if word == 'move':
            self.advance()
            inner = self.parse_type()
            return f"move {inner}"

        # ── handle to bytes / nominal handle type ──────────────────────
        if word == 'handle':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'to':
                self.advance()
                if self.cur().type == TokenType.WORD and self.cur().value == 'bytes':
                    self.advance()
                    return 'handle to bytes'
                return 'handle to'
            # `handle Db` — nominal handle type reference (must match a
            # prior `define handle Db`). Distinguished from generic
            # `handle` by a following capitalized identifier.
            if (self.cur().type == TokenType.WORD
                    and self.cur().value not in self._TYPE_STOP
                    and self.cur().value[:1].isupper()):
                name = self.advance().value
                return name
            return 'handle'

        # ── raw pointer (*) ──────────────────────────────────────────
        if word == '*':
            self.advance()
            inner = self.parse_type()
            return f"*{inner}"

        # ── primitive two-word types ──────────────────────────────────
        if word in self._PRIMITIVE_SUFFIXES:
            self.advance()
            suffix = self._PRIMITIVE_SUFFIXES[word]
            collected = [word]
            for s in suffix:
                if self.cur().type == TokenType.WORD and self.cur().value == s:
                    collected.append(self.advance().value)
            result = ' '.join(collected)
            # Optional list/array suffix: `whole number list`
            if self.cur().type == TokenType.WORD and self.cur().value in ('list', 'array'):
                result += ' ' + self.advance().value
            return result

        # ── terminal single-word types ────────────────────────────────
        if word in self._TERMINAL_TYPES:
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value in ('list', 'array'):
                return word + ' ' + self.advance().value
            return word

        # ── user-defined type (identifier) ───────────────────────────
        self.advance()
        result = word
        # Namespaced: Shapes.Point
        while self.cur().type == TokenType.WORD and self.cur().value == '.':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value not in self._TYPE_STOP:
                result += '.' + self.advance().value
        # Optional list/array suffix
        if self.cur().type == TokenType.WORD and self.cur().value in ('list', 'array'):
            result += ' ' + self.advance().value
        return result

    def _is_end_of_statement(self) -> bool:
        tok = self.cur()
        if tok.type in (TokenType.NEWLINE, TokenType.DEDENT, TokenType.EOF):
            return True
        if tok.type == TokenType.WORD and tok.value in ('end', 'otherwise', 'on', 'if', 'then'):
            return True
        return False

    # ------------------------------------------------------------------
    # put ... into
    # ------------------------------------------------------------------
    def parse_put(self) -> Assignment:
        line = self.advance().line
        value = self.parse_expression()
        self.expect_word('into')
        target = self.parse_lvalue()
        return Assignment(target=target, value=value, line=line)

    def parse_lvalue(self) -> str:
        if self.cur().type == TokenType.WORD:
            if self.cur().value == 'item':
                self.advance()
                old = self.in_at_index; self.in_at_index = True
                idx_expr = self.parse_expression()
                self.in_at_index = old
                self.expect_word('of')
                coll = self.expect_word().value
                return f"{coll}[{self._expr_to_str(idx_expr)}]"
            name = self.advance().value
            if self.match_word('at'):
                old = self.in_at_index; self.in_at_index = True
                idx_expr = self.parse_expression()
                self.in_at_index = old
                self.expect_word('of')
                coll = self.expect_word().value
                return f"{coll}[{self._expr_to_str(idx_expr)}]"
            if self.match_word('of'):
                obj = self.expect_word().value
                return f"{obj}.{name}"
            if self.match_word('.'):
                field = self.expect_word().value
                result = f"{name}.{field}"
                while self.match_word('.'):
                    result += '.' + self.expect_word().value
                return result
            return name
        raise SyntaxError(f"Expected lvalue at line {self.cur().line}")

    def _expr_to_str(self, node: Node) -> str:
        if isinstance(node, Literal):    return str(node.value)
        if isinstance(node, Identifier): return node.name
        if isinstance(node, BinaryOp):
            return f"({self._expr_to_str(node.left)} {node.op} {self._expr_to_str(node.right)})"
        if isinstance(node, UnaryOp):
            return f"({node.op}{self._expr_to_str(node.operand)})"
        if isinstance(node, FieldAccess): return f"{node.obj}.{node.field}"
        if isinstance(node, IndexAccess):
            return f"{node.collection}[{self._expr_to_str(node.index)}]"
        if isinstance(node, FuncCall):
            args = ", ".join(self._expr_to_str(a) for a in node.args)
            return f"{node.name}({args})"
        return str(node)

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------
    def parse_expression(self) -> Node:
        return self.parse_comparison()

    def parse_comparison(self) -> Node:
        left = self.parse_additive()
        while True:
            if self.match_word('is'):
                if self.match_word('equal'):
                    self.expect_word('to')
                    right = self.parse_additive()
                    left = BinaryOp(op='==', left=left, right=right)
                elif self.match_word('not'):
                    self.expect_word('equal')
                    self.expect_word('to')
                    right = self.parse_additive()
                    left = BinaryOp(op='!=', left=left, right=right)
                elif self.match_word('greater'):
                    self.expect_word('than')
                    # BUG-03 FIX: `is greater than or equal to`
                    if (self.cur().type == TokenType.WORD and
                            self.cur().value == 'or'):
                        self.advance()              # 'or'
                        self.expect_word('equal')
                        self.expect_word('to')
                        right = self.parse_additive()
                        left = BinaryOp(op='>=', left=left, right=right)
                    else:
                        right = self.parse_additive()
                        left = BinaryOp(op='>', left=left, right=right)
                elif self.match_word('less'):
                    self.expect_word('than')
                    # BUG-03 FIX: `is less than or equal to`
                    if (self.cur().type == TokenType.WORD and
                            self.cur().value == 'or'):
                        self.advance()              # 'or'
                        self.expect_word('equal')
                        self.expect_word('to')
                        right = self.parse_additive()
                        left = BinaryOp(op='<=', left=left, right=right)
                    else:
                        right = self.parse_additive()
                        left = BinaryOp(op='<', left=left, right=right)
                elif self.match_word('at'):
                    if self.match_word('least'):
                        right = self.parse_additive()
                        left = BinaryOp(op='>=', left=left, right=right)
                    elif self.match_word('most'):
                        right = self.parse_additive()
                        left = BinaryOp(op='<=', left=left, right=right)
                    else:
                        raise SyntaxError(f"Unknown comparison after 'at' at line {self.cur().line}")
                elif self.match_word('empty'):
                    left = BinaryOp(op='==', left=left, right=Literal(value='empty'))
                elif self.match_word('true'):
                    # `is true` → == true
                    left = BinaryOp(op='==', left=left, right=Literal(value=True))
                elif self.match_word('false'):
                    # `is false` → == false
                    left = BinaryOp(op='==', left=left, right=Literal(value=False))
                elif self.match_word('nothing'):
                    # `is nothing` → == NULL
                    left = BinaryOp(op='==', left=left, right=Literal(value=None))
                else:
                    raise SyntaxError(f"Unknown comparison at line {self.cur().line}")
            else:
                break
        return left

    def parse_additive(self) -> Node:
        if self.cur().type == TokenType.WORD and self.cur().value == 'the':
            save = self.pos
            self.advance()
            _PREFIX_OPS = {
                'sum', 'difference', 'product', 'quotient', 'remainder',
                'count', 'length', 'bitwise', 'left', 'right', 'tanh',
                'square', 'power', 'exponential', 'sine', 'cosine'
            }
            if self.cur().type == TokenType.WORD and self.cur().value in _PREFIX_OPS:
                self.pos = save
                return self.parse_prefix_expression()
            self.pos = save
        left = self.parse_multiplicative()
        # FIX: 'plus' / 'minus' as infix operators (e.g. `x plus y`,
        # `total minus 1`) were reserved by the tokenizer (_TYPE_STOP) and
        # advertised as valid by the grammar (GrammarState.EXPRESSION,
        # EXPR_CONTINUATORS) but never actually implemented here — this
        # method previously fell straight through to parse_multiplicative
        # with no loop for these two words at all, unlike modulo/times/
        # divided which DO have a correct loop one level down. The effect:
        # `x plus y` parsed as the single expression `x`, silently dropping
        # `plus y`, which then surfaced as two orphaned bare-identifier
        # statements at the statement level (the same failure shape as the
        # unrelated `display "..."` bug found elsewhere this session — an
        # unrecognized/unimplemented token sequence silently producing no
        # error rather than a clear failure).
        while True:
            if self.match_word('plus'):
                right = self.parse_multiplicative()
                left = BinaryOp(op='+', left=left, right=right)
            elif self.match_word('minus'):
                right = self.parse_multiplicative()
                left = BinaryOp(op='-', left=left, right=right)
            else:
                break
        return left

    def parse_multiplicative(self) -> Node:
        left = self.parse_unary()
        while True:
            if self.match_word('modulo'):
                right = self.parse_unary()
                left = BinaryOp(op='%', left=left, right=right)
            elif self.match_word('times'):
                right = self.parse_unary()
                left = BinaryOp(op='*', left=left, right=right)
            elif self.match_word('divided'):
                self.expect_word('by')
                right = self.parse_unary()
                left = BinaryOp(op='/', left=left, right=right)
            else:
                break
        return left

    def parse_unary(self) -> Node:
        tok = self.cur()
        if tok.type == TokenType.WORD and tok.value == 'the':
            return self.parse_prefix_expression()
        if tok.type == TokenType.WORD and tok.value == '*':
            self.advance()
            return UnaryOp(op='deref', operand=self.parse_unary(), line=tok.line)
        if tok.type == TokenType.WORD and tok.value == '&':
            self.advance()
            return UnaryOp(op='addrof', operand=self.parse_unary(), line=tok.line)
        if tok.type == TokenType.WORD and tok.value == '-':
            # FIX: unary minus / negative literals (`-1.0`, `-x`) were
            # entirely unparseable — see comment on parse_unary's '-' case.
            self.advance()
            return UnaryOp(op='neg', operand=self.parse_unary(), line=tok.line)
        if tok.type == TokenType.WORD and tok.value == 'transmute':
            self.advance()
            expr = self.parse_expression()
            self.expect_word('as')
            type_ = self.parse_type()
            return Transmute(expr=expr, type=type_, line=tok.line)
        return self.parse_primary()

    def parse_prefix_expression(self) -> Node:
        line = self.expect_word('the').line
        nxt = self.expect_word().value
        def _two(op):
            self.expect_word('of')
            a = self.parse_expression()
            self.expect_word('and')
            b = self.parse_expression()
            return BinaryOp(op=op, left=a, right=b, line=line)
        def _one(op):
            self.expect_word('of')
            a = self.parse_expression()
            return UnaryOp(op=op, operand=a, line=line)

        if nxt == 'sum':         return _two('+')
        elif nxt == 'difference':return _two('-')
        elif nxt == 'product':   return _two('*')
        elif nxt == 'quotient':  return _two('/')
        elif nxt == 'remainder':
            self.expect_word('of')
            a = self.parse_expression()
            # FIX: LANGUAGE_REFERENCE.md documents "the remainder of a and
            # b" (both in its Arithmetic table and the find_first_even
            # worked example) -- consistent with every sibling operator
            # (sum/difference/product/quotient all use "and"). The parser
            # previously hardcoded "by" only, rejecting the doc's own
            # worked example. Accept either.
            if not self.match_word('and'):
                self.expect_word('by')
            b = self.parse_expression()
            return BinaryOp(op='%', left=a, right=b, line=line)
        elif nxt == 'bitwise':
            op_word = self.expect_word().value
            self.expect_word('of')
            a = self.parse_expression()
            if op_word == 'not':
                return UnaryOp(op='~', operand=a, line=line)
            self.expect_word('and')
            b = self.parse_expression()
            if op_word == 'and': return BinaryOp(op='&', left=a, right=b, line=line)
            if op_word == 'or':  return BinaryOp(op='|', left=a, right=b, line=line)
            if op_word == 'xor': return BinaryOp(op='^', left=a, right=b, line=line)
            raise SyntaxError(f"Unknown bitwise op {op_word}")
        elif nxt == 'left':
            self.expect_word('shift'); self.expect_word('of')
            a = self.parse_expression(); self.expect_word('by')
            b = self.parse_expression()
            return BinaryOp(op='<<', left=a, right=b, line=line)
        elif nxt == 'right':
            self.expect_word('shift'); self.expect_word('of')
            a = self.parse_expression(); self.expect_word('by')
            b = self.parse_expression()
            return BinaryOp(op='>>', left=a, right=b, line=line)
        elif nxt == 'count':     return _one('count')
        elif nxt == 'length':    return _one('length')
        elif nxt == 'tanh':      return _one('tanh')
        elif nxt == 'square':
            self.expect_word('root'); self.expect_word('of')
            return UnaryOp(op='sqrt', operand=self.parse_expression(), line=line)
        elif nxt == 'power':     return _two('pow')
        elif nxt == 'exponential': return _one('exp')
        elif nxt == 'sine':      return _one('sin')
        elif nxt == 'cosine':    return _one('cos')
        elif nxt == 'value':
            # `the value <expr>` — transparent wrapper. Documented and used
            # pervasively (LANGUAGE_REFERENCE.md's own canonical examples:
            # `put the value 42 into count`, `put the value p.x into q.x`,
            # etc.). Previously unhandled here, so this extremely common
            # documented idiom raised "Unknown 'the' expression: value" on
            # every single use — a hard compile failure on some of the
            # simplest possible Dictum programs.
            return self.parse_expression()
        raise SyntaxError(f"Unknown 'the' expression: {nxt} at line {line}")

    def parse_primary(self) -> Node:
        tok = self.cur()
        if tok.type == TokenType.NUMBER:
            return Literal(value=self.advance().value, line=tok.line)
        if tok.type == TokenType.STRING:
            return Literal(value=self.advance().value, line=tok.line)
        if tok.type == TokenType.WORD:
            word = tok.value
            # MISSING-09: bool literals consistent
            if word in ('true', 'false'):
                self.advance()
                return Literal(value=(word == 'true'), line=tok.line)
            if word == 'nothing':
                self.advance()
                return Literal(value=None, line=tok.line)
            if word == 'empty':
                self.advance()
                return Literal(value='empty', line=tok.line)
            if word == 'newline':
                self.advance()
                return Literal(value='\n', line=tok.line)
            if word == 'new':
                return self.parse_new_expr()
            if word == 'action':
                return self.parse_lambda()
            if word == 'item':
                self.advance()
                old = self.in_at_index; self.in_at_index = True
                idx = self.parse_expression()
                self.in_at_index = old
                self.expect_word('of')
                coll = self.expect_word().value
                return IndexAccess(collection=coll, index=idx, line=tok.line)
            self.advance()
            if self.match_word('at'):
                old = self.in_at_index; self.in_at_index = True
                idx = self.parse_expression()
                self.in_at_index = old
                # Optional 'of collection' — if present, it's another array
                if self.cur().type == TokenType.WORD and self.cur().value == 'of':
                    self.advance()
                    coll = self.expect_word().value
                    return IndexAccess(collection=coll, index=idx, line=tok.line)
                # Otherwise 'Name at N' means Name[N]
                return IndexAccess(collection=word, index=idx, line=tok.line)
            elif not self.in_at_index and self.match_word('of'):
                obj = self.expect_word().value
                return FieldAccess(obj=obj, field=word, line=tok.line)
            else:
                if self.match_word('with'):
                    args = []
                    while not self._is_end_of_statement() and not (
                        self.cur().type == TokenType.WORD and
                        self.cur().value in ('giving', 'and', 'into', 'from', 'as')
                    ):
                        args.append(self.parse_expression())
                        if not self.match_word('and'):
                            break
                    return FuncCall(name=word, args=args, line=tok.line)
                if self.match_word('.'):
                    field = self.expect_word().value
                    fa = FieldAccess(obj=word, field=field, line=tok.line)
                    while self.match_word('.'):
                        subfield = self.expect_word().value
                        fa = FieldAccess(obj=f"{fa.obj}.{fa.field}", field=subfield, line=tok.line)
                    return fa
                return Identifier(name=word, line=tok.line)
        raise SyntaxError(f"Unexpected token {tok.type.name} at line {tok.line}")

    def parse_new_expr(self) -> NewExpr:
        line = self.advance().line
        type_name = self.parse_type()
        while self.match_word('.'):
            type_name += '.' + self.expect_word().value
        args = []
        if self.match_word('with'):
            while not self._is_end_of_statement():
                args.append(self.parse_expression())
                if not self.match_word('and'):
                    break
        return NewExpr(type_name=type_name, args=args, line=line)

    def parse_lambda(self) -> LambdaExpr:
        line = self.advance().line
        self.expect_word('taking')
        params = []
        while not (self.cur().type == TokenType.WORD and self.cur().value == 'produces'):
            pname = self.expect_word().value
            self.expect_word('as')
            ptype = self.parse_type()
            params.append((pname, ptype))
            if not self.match_word('and'):
                break
        self.expect_word('produces')
        ret_type = self.parse_type()
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'action':
                self.advance()
        return LambdaExpr(params=params, ret_type=ret_type, body=body, line=line)

    # ------------------------------------------------------------------
    # Control flow
    # MISSING-04 FIX: `otherwise:` plain else branch
    # ------------------------------------------------------------------
    def parse_if(self) -> If:
        line = self.advance().line
        cond = self.parse_expression()
        self.expect_word('then')
        self.consume_newlines()
        then_body = self.parse_block()
        else_body = []
        self.consume_newlines()
        if self.match_word('otherwise'):
            # BUG FIX (nested-if-in-otherwise): only strip NEWLINE here,
            # not INDENT/DEDENT. consume_newlines() ate the INDENT token
            # too, which made a nested fresh `if` statement (otherwise\n
            # INDENT if...) look identical to a chained `otherwise if`
            # (otherwise if... on the same line, no INDENT) to the check
            # below -- causing a real `if` nested inside a plain
            # `otherwise` block to be mis-parsed as this if's own elif
            # clause, silently stealing tokens meant for the enclosing
            # block and desyncing the parser (manifesting as a spurious
            # "Unknown top-level 'if'" error much later in the file).
            while self.cur().type == TokenType.NEWLINE:
                self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'if':
                self.advance()   # consume 'if' - then parse the if body inline (not via parse_if which would re-consume 'if')
                elif_cond = self.parse_expression()
                self.expect_word('then')
                self.consume_newlines()
                elif_then = self.parse_block()
                elif_else: List[Node] = []
                self.consume_newlines()
                if self.cur().type == TokenType.WORD and self.cur().value == 'otherwise':
                    self.advance()
                    # Same fix as above: only strip NEWLINE, not INDENT,
                    # so a nested fresh `if` here isn't mistaken for a
                    # further chained `otherwise if`.
                    while self.cur().type == TokenType.NEWLINE:
                        self.advance()
                    if self.cur().type == TokenType.WORD and self.cur().value == 'if':
                        self.advance()
                        elif_else = [self.parse_if()]
                    else:
                        elif_else = self.parse_block()
                if self.cur().type == TokenType.WORD and self.cur().value == 'end':
                    self.advance()
                    if self.cur().type == TokenType.WORD and self.cur().value == 'if':
                        self.advance()
                else_body = [If(cond=elif_cond, then_body=elif_then, else_body=elif_else, line=line)]
            else:
                # Plain `otherwise` / `else` block
                else_body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'if':
                self.advance()
        return If(cond=cond, then_body=then_body, else_body=else_body, line=line)

    def parse_while(self) -> While:
        line = self.advance().line
        cond = self.parse_expression()
        self.expect_word('repeat')
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value in ('while', 'repeat'):
                self.advance()
        return While(cond=cond, body=body, line=line)

    def parse_for(self) -> ForEach:
        line = self.advance().line
        self.expect_word('each')
        item = self.expect_word().value
        self.expect_word('in')
        collection = self.expect_word().value
        self.expect_word('repeat')
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value in ('for', 'repeat'):
                self.advance()
        return ForEach(item=item, collection=collection, body=body, line=line)

    def parse_repeat(self) -> Repeat:
        line = self.advance().line
        count = self.parse_primary()
        self.expect_word('times')
        self.expect_word('using')
        counter = self.expect_word().value
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'repeat':
                self.advance()
        return Repeat(count=count, counter=counter, body=body, line=line)

    # ------------------------------------------------------------------
    # attempt
    # ------------------------------------------------------------------
    def parse_attempt(self) -> Attempt:
        line = self.advance().line
        self.consume_newlines()
        call = None
        result_name = ''
        if self.cur().type == TokenType.WORD and self.cur().value == 'call':
            expr = self.parse_call()
            if isinstance(expr, Assignment) and isinstance(expr.value, FuncCall):
                call = expr.value
                result_name = expr.target
            elif isinstance(expr, FuncCall):
                call = expr
            else:
                raise SyntaxError(f"Attempt requires a function call at line {line}")
        elif self.cur().type not in (TokenType.NEWLINE, TokenType.INDENT, TokenType.DEDENT) and \
                self.cur().value not in frozenset({'if','return','print','on','for','keep','put',
                                                    'action','possibilities','module','export',
                                                    'shape','assert','end','while','call',
                                                    'import','repeat','produce'}):
            expr = self.parse_expression()
            if isinstance(expr, FuncCall):
                call = expr
                if self.match_word('giving'):
                    result_name = self.expect_word().value
        self.consume_newlines()
        success_body: list = []
        failure_name = ''
        failure_body: list = []
        if call is None or self.cur().type == TokenType.INDENT:
            success_body = self._parse_attempt_body(stop_at={'on', 'end'})
        while not (self.cur().type == TokenType.WORD and self.cur().value == 'end'):
            self.consume_newlines()
            if self.cur().type in (TokenType.EOF, TokenType.DEDENT):
                break
            if self.match_word('on'):
                if self.match_word('success'):
                    self.consume_newlines()
                    success_body = success_body + self._parse_attempt_body(stop_at={'on', 'end'})
                elif self.match_word('failure'):
                    if self.match_word('with'):
                        # `on failure with <name>:`
                        failure_name = self.expect_word().value
                    elif (self.cur().type == TokenType.WORD and
                          self.cur().value not in ('end', 'on', 'attempt')):
                        # `on failure <name>:` — name without 'with' keyword
                        failure_name = self.cur().value
                        self.advance()
                    self.consume_newlines()
                    failure_body = self._parse_attempt_body(stop_at={'end'})
                else:
                    break
            else:
                break
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'attempt':
                self.advance()
        return Attempt(call=call, result_name=result_name,
                       success_body=success_body, failure_name=failure_name,
                       failure_body=failure_body, line=line)

    def _parse_attempt_body(self, stop_at: set) -> list:
        statements = []
        if self.cur().type == TokenType.INDENT:
            self.advance()
        while self.cur().type not in (TokenType.DEDENT, TokenType.EOF):
            self.consume_newlines()
            if self.cur().type in (TokenType.DEDENT, TokenType.EOF):
                break
            if self.cur().type == TokenType.WORD and self.cur().value in stop_at:
                break
            if self.cur().type == TokenType.WORD and self.cur().value == 'end':
                break
            statements.append(self.parse_statement())
            self.consume_newlines()
        if self.cur().type == TokenType.DEDENT:
            self.advance()
        return statements

    # ------------------------------------------------------------------
    # Produce / return
    # BUG-09 FIX: emit clean return without /* success */ noise
    # ------------------------------------------------------------------
    def parse_return(self) -> Return:
        line = self.advance().line
        val = self.parse_expression()
        return Return(value=val, line=line)

    def parse_produce(self) -> Return:
        line = self.advance().line
        if self.match_word('failure'):
            self.expect_word('with')
            self.expect_word('text')
            msg = self.parse_expression()
            return Return(value=FuncCall(name='failure', args=[msg], line=line), line=line)
        if self.match_word('success'):
            self.expect_word('with')
            val = self.parse_expression()
            # Store as a tagged Return so emitter can handle cleanly
            return Return(value=FuncCall(name='__produce_success', args=[val], line=line), line=line)
        val = self.parse_expression()
        return Return(value=val, line=line)

    def parse_assert(self) -> Assert:
        line = self.advance().line
        return Assert(cond=self.parse_expression(), line=line)

    def parse_print(self) -> Print:
        line = self.advance().line
        self.expect_word('the')
        self.expect_word('text')
        parts = []
        while not self._is_end_of_statement():
            parts.append(self.parse_expression())
            if not self.match_word('and'):
                break
        return Print(parts=parts, line=line)

    # ------------------------------------------------------------------
    # call
    # ------------------------------------------------------------------
    def parse_call(self) -> Node:
        line = self.advance().line
        name = self.expect_word().value
        obj = None
        # Handle Module.fn style call names
        if self.match_word('.'):
            method = self.expect_word().value
            name = f"{name}.{method}"
        elif self.match_word('of'):
            obj = self.expect_word().value
        args = []
        if self.match_word('with'):
            while not self._is_end_of_statement():
                args.append(self.parse_expression())
                if not self.match_word('and') and not self.match_word(','):
                    break
        if obj:
            call = FuncCall(name=f"{obj}->{name}", args=args, line=line)
        else:
            call = FuncCall(name=name, args=args, line=line)
        if self.match_word('giving'):
            result_name = self.expect_word().value
            return Assignment(target=result_name, value=call, line=line)
        return call

    def parse_run(self) -> FuncCall:
        line = self.advance().line
        name = self.expect_word().value
        args = []
        if self.match_word('with'):
            while not self._is_end_of_statement():
                args.append(self.parse_expression())
                if not self.match_word('and'):
                    break
        return FuncCall(name=name, args=args, line=line)

    # ------------------------------------------------------------------
    # Shape / possibilities
    # ------------------------------------------------------------------
    def parse_shape(self, is_packed: bool = False) -> Shape:
        line = self.advance().line
        name = self.expect_word().value
        parent = None
        if self.match_word('is') and self.match_word('a'):
            parent = self.expect_word().value
        elif self.match_word('extends'):
            parent = self.expect_word().value
        self.expect_word('holds')
        self.consume_newlines()
        fields, methods, constructors, destructor = [], [], [], None
        access_map = {}
        current_access = 'public'
        if self.cur().type == TokenType.INDENT:
            self.advance()
        while not (self.cur().type == TokenType.WORD and self.cur().value == 'end'):
            self.consume_newlines()
            if self.cur().type in (TokenType.DEDENT, TokenType.EOF):
                break
            if self.cur().type == TokenType.WORD and self.cur().value == 'end':
                break
            if self.cur().type == TokenType.WORD and self.cur().value in ('public', 'private', 'protected'):
                current_access = self.advance().value
                continue
            if self.cur().type == TokenType.WORD and self.cur().value == 'method':
                m = self.parse_method(access=current_access)
                methods.append(m); access_map[m.name] = current_access
                if self.cur().type == TokenType.WORD and self.cur().value == 'end': break
            elif self.cur().type == TokenType.WORD and self.cur().value == 'constructor':
                c = self.parse_constructor(access=current_access)
                constructors.append(c)
                if self.cur().type == TokenType.WORD and self.cur().value == 'end': break
            elif self.cur().type == TokenType.WORD and self.cur().value == 'destructor':
                d = self.parse_destructor(access=current_access)
                destructor = d
                if self.cur().type == TokenType.WORD and self.cur().value == 'end': break
            else:
                fname = self.expect_word().value
                self.expect_word('as')
                ftype = self.parse_type()
                fields.append((fname, ftype))
                access_map[fname] = current_access
                self.consume_newlines()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'shape':
                self.advance()
        if self.cur().type == TokenType.DEDENT:
            self.advance()
        return Shape(name=name, fields=fields, is_packed=is_packed, parent=parent,
                     methods=methods, constructors=constructors, destructor=destructor,
                     access_map=access_map, line=line)

    def parse_possibilities(self) -> Possibilities:
        line = self.advance().line
        name = self.expect_word().value
        self.consume_newlines()
        variants = []
        if self.cur().type == TokenType.INDENT:
            self.advance()
        while not (self.cur().type == TokenType.WORD and self.cur().value == 'end'):
            self.consume_newlines()
            if self.cur().type in (TokenType.DEDENT, TokenType.EOF): break
            if self.cur().type == TokenType.WORD and self.cur().value == 'end': break
            variants.append(self.expect_word().value)
            self.consume_newlines()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'possibilities':
                self.advance()
        if self.cur().type == TokenType.DEDENT:
            self.advance()
        return Possibilities(name, variants, line)

    # ------------------------------------------------------------------
    # Method / constructor / destructor
    # ------------------------------------------------------------------
    def _parse_params(self) -> list:
        params = []
        if self.match_word('takes'):
            if self.cur().type in (TokenType.INDENT, TokenType.NEWLINE):
                self.consume_newlines()
                if self.cur().type == TokenType.INDENT:
                    self.advance()
            # BUGFIX: `takes nothing` is the explicit zero-params marker
            # (same convention already honored by parse_import_c/
            # parse_import_cpp), not a param whose name happens to be
            # "nothing". Without this check the loop below would try to
            # parse 'nothing' as a param name and then `expect_word('as')`
            # against whatever follows it (usually 'produces'), which is
            # exactly the "plan calls for 'as', but the generated code has
            # 'produces'" failure -- and it fires on ANY hand-written
            # `takes nothing` action/method, not just AI-generated code.
            if self.cur().type == TokenType.WORD and self.cur().value == 'nothing':
                self.advance()
            else:
                while not (self.cur().type == TokenType.WORD and
                           self.cur().value in ('produces', 'end')):
                    self.consume_newlines()
                    if self.cur().type in (TokenType.DEDENT, TokenType.EOF): break
                    if self.cur().type == TokenType.WORD and self.cur().value in ('produces','end'): break
                    pname = self.expect_word().value
                    self.expect_word('as')
                    ptype = self.parse_type()
                    params.append((pname, ptype))
                    self.consume_newlines()
                    self.match_word('and') or self.match_word(',')
            if self.cur().type == TokenType.DEDENT:
                self.advance()
        return params

    def parse_method(self, access: str = 'public') -> Method:
        line = self.advance().line
        name = self.expect_word().value
        params = self._parse_params()
        self.expect_word('produces')
        ret_type = self.parse_type()
        self.consume_newlines()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            save = self.pos; self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'method':
                self.advance()
                return Method(name=name, params=params, ret_type=ret_type,
                              body=[], access=access, line=line)
            self.pos = save
            return Method(name=name, params=params, ret_type=ret_type,
                          body=[], access=access, line=line)
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            save = self.pos; self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'method':
                self.advance()
            else:
                self.pos = save
        return Method(name=name, params=params, ret_type=ret_type,
                      body=body, access=access, line=line)

    def parse_constructor(self, access: str = 'public') -> Constructor:
        line = self.advance().line
        params = self._parse_params()
        self.expect_word('produces')
        self.parse_type()   # consume return type (always 'nothing')
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'constructor':
                self.advance()
        return Constructor(params=params, body=body, access=access, line=line)

    def parse_destructor(self, access: str = 'public') -> Destructor:
        line = self.advance().line
        self.expect_word('produces')
        self.parse_type()
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'destructor':
                self.advance()
        return Destructor(body=body, access=access, line=line)

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------
    def parse_action(self) -> Action:
        line = self.advance().line
        name = self.expect_word().value
        template_params = []
        params = []
        if self.match_word('takes'):
            if self.cur().type in (TokenType.INDENT, TokenType.NEWLINE):
                self.consume_newlines()
                if self.cur().type == TokenType.INDENT: self.advance()
            # BUGFIX: `takes nothing` is the explicit zero-params marker
            # (mirrors the same fix in _parse_params / parse_import_c /
            # parse_import_cpp) -- without it, 'nothing' gets consumed as
            # a param NAME below and the following `expect_word('as')`
            # then fails against 'produces', which is the exact "plan
            # calls for 'as', but the generated code has 'produces'"
            # class of failure (and breaks hand-written `takes nothing`
            # actions too, not just AI-generated ones).
            if self.cur().type == TokenType.WORD and self.cur().value == 'nothing':
                self.advance()
            else:
                while not (self.cur().type == TokenType.WORD and
                           self.cur().value in ('produces', 'end')):
                    self.consume_newlines()
                    if self.cur().type in (TokenType.DEDENT, TokenType.EOF): break
                    if self.cur().type == TokenType.WORD and self.cur().value in ('produces','end'): break
                    pname = self.expect_word().value
                    self.expect_word('as')
                    if self.match_word('any'):
                        constraint = self.parse_type()
                        params.append((pname, constraint))
                        if constraint not in [t[0] for t in template_params]:
                            template_params.append((constraint, constraint))
                    else:
                        ptype = self.parse_type()
                        params.append((pname, ptype))
                    self.consume_newlines()
                    self.match_word('and') or self.match_word(',')
            if self.cur().type == TokenType.DEDENT: self.advance()
        self.expect_word('produces')
        ret_type = self.parse_type()
        self.consume_newlines()
        body = self.parse_block()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'action':
                self.advance()
        return Action(name=name, params=params, ret_type=ret_type, body=body,
                      template_params=template_params, line=line)

    # ------------------------------------------------------------------
    # extern / unsafe / defer / release / use / bind / import
    # ------------------------------------------------------------------
    def parse_extern(self) -> ExternFn:
        line = self.advance().line
        self.expect_word('fn')
        name = self.expect_word().value
        params = []; ret_type = 'nothing'; syscall_name = None
        if self.match_word('takes'):
            while True:
                self.consume_newlines()
                if self.cur().type in (TokenType.DEDENT, TokenType.EOF): break
                if self.cur().type == TokenType.WORD and self.cur().value == 'produces': break
                pname = self.expect_word().value
                self.expect_word('as')
                ptype = self.parse_type()
                params.append((pname, ptype))
                self.consume_newlines()
                if not self.match_word('and') and not self.match_word(','): break
        self.consume_newlines()
        if self.cur().type == TokenType.WORD and self.cur().value == 'produces':
            self.advance(); ret_type = self.parse_type()
        self.consume_newlines()
        if self.match_word('@'):
            self.expect_word('syscall')
            if self.match_word('('): pass
            syscall_tok = self.cur()
            if syscall_tok.type == TokenType.STRING:
                self.advance(); syscall_name = syscall_tok.value
            else:
                raise SyntaxError(f"Expected string after @syscall at line {syscall_tok.line}")
            if self.match_word(')'): pass
            self.consume_newlines()
        return ExternFn(name=name, params=params, ret_type=ret_type,
                        syscall_name=syscall_name, line=line)

    def parse_unsafe(self) -> UnsafeBlock:
        line = self.advance().line   # consume 'unsafe'
        self.consume_newlines()
        body = self.parse_unsafe_body()
        if self.cur().type == TokenType.WORD and self.cur().value == 'end':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == 'unsafe':
                self.advance()
        return UnsafeBlock(body=body, line=line)

    def parse_unsafe_body(self):
        """Parse body of unsafe: block.
        Recognises:
          [TOKEN_NAME: p1 : p2 : result]  -> UnsafeToken
          [VERIFY:CATEGORY_ID]             -> VerifyToken
        Everything else falls through to parse_statement().
        """
        stmts = []
        while True:
            self.consume_newlines()
            cur = self.cur()
            if cur.type in (TokenType.DEDENT, TokenType.EOF):
                break
            if cur.type == TokenType.WORD and cur.value == 'end':
                break
            if cur.type == TokenType.WORD and cur.value == '[':
                node = self._parse_bracket_token()
                if node is not None:
                    stmts.append(node)
                continue
            try:
                stmt = self.parse_statement()
                if stmt is not None:
                    stmts.append(stmt)
            except Exception:
                while self.cur().type not in (TokenType.NEWLINE, TokenType.DEDENT, TokenType.EOF):
                    self.advance()
        return stmts

    def _parse_bracket_token(self):
        """Parse [TOKEN_NAME: p1 : p2 : ...] or [VERIFY:KEY].
        The lexer emits '[', ']' as WORD tokens and drops ':' silently,
        so we just collect WORD tokens between '[' and ']'.
        """
        line = self.advance().line  # consume '['
        params = []
        while True:
            cur = self.cur()
            if cur.type == TokenType.EOF:
                break
            if cur.type == TokenType.WORD and cur.value == ']':
                self.advance()
                break
            if cur.type == TokenType.NUMBER:
                # Numeric literals (e.g. sizes, alignments) inside [TOKEN: ...]
                params.append(str(cur.value))
            elif cur.type == TokenType.WORD and cur.value not in ('[', ':'):
                params.append(cur.value)
            self.advance()
        if not params:
            return None
        token_name = params[0].upper()
        token_params = params[1:]
        # [VERIFY:CATEGORY_ID]
        if token_name == 'VERIFY' and len(token_params) == 1:
            return VerifyToken(key=token_params[0], line=line)
        # All other special tokens
        result = token_params[-1] if token_params else ''
        return UnsafeToken(name=token_name, params=token_params, result=result, line=line)

    def parse_defer(self) -> FuncCall:
        line = self.advance().line
        self.expect_word('release')
        name = self.expect_word().value
        return FuncCall(name='__defer_release', args=[Identifier(name=name)], line=line)

    def parse_release(self) -> FuncCall:
        line = self.advance().line
        if self.match_word('the'):
            field = self.expect_word().value
            self.expect_word('of')
            obj = self.expect_word().value
            return FuncCall(name='release', args=[FieldAccess(obj=obj, field=field)], line=line)
        name = self.expect_word().value
        return FuncCall(name='release', args=[Identifier(name=name)], line=line)

    def parse_use(self) -> Use:
        line = self.advance().line
        tok = self.cur()
        if tok.type == TokenType.STRING:
            raw = self.advance().value
            is_system = raw.startswith('<') and raw.endswith('>')
            path = raw.strip('<>"\'')
        else:
            path = self.expect_word().value
            is_system = False
        return Use(path=path, is_system=is_system, line=line)

    def parse_bind(self) -> Bind:
        line = self.advance().line
        name = self.expect_word().value
        params = []
        if self.match_word('takes'):
            while not (self.cur().type == TokenType.WORD and self.cur().value == 'produces'):
                self.consume_newlines()
                if self.cur().type in (TokenType.DEDENT, TokenType.EOF): break
                pname = self.expect_word().value
                self.expect_word('as')
                ptype = self.parse_type()
                params.append((pname, ptype))
                self.consume_newlines()
                if not self.match_word('and') and not self.match_word(','): break
        self.expect_word('produces')
        ret_type = self.parse_type()
        self.expect_word('as')
        alias_parts = [self.expect_word().value]
        _TOP = {'end','program','module','shape','action','use','bind','import','extern','export'}
        while self.cur().type == TokenType.WORD and self.cur().value not in _TOP:
            alias_parts.append(self.advance().value)
        return Bind(name=name, params=params, ret_type=ret_type,
                    alias=' '.join(alias_parts), line=line)

    def parse_import(self) -> Node:
        line = self.advance().line   # consume 'import'

        # Peek: is the next token a module name (WORD) followed by 'from' and a string?
        # Grammar: `import MyModule from "mymodule.dict"`
        # vs:      `import from C the action ...`
        # We distinguish by checking if cur() is a WORD that isn't 'from'.
        if (self.cur().type == TokenType.WORD and self.cur().value != 'from'):
            candidate_name = self.cur().value
            # Peek further: if next is 'from' and after that a string → .dict import
            if (self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].type == TokenType.WORD
                    and self.tokens[self.pos + 1].value == 'from'
                    and self.pos + 2 < len(self.tokens)
                    and self.tokens[self.pos + 2].type == TokenType.STRING):
                self.advance()            # consume module_name
                self.expect_word('from')  # consume 'from'
                file_path = self.advance().value  # consume the string path
                alias = candidate_name
                return ImportDict(module_name=candidate_name, file_path=file_path,
                                  alias=alias, line=line)

        # Legacy C / C++ import: `import from C ...`
        self.expect_word('from')
        if self.cur().type == TokenType.WORD and self.cur().value == 'C':
            self.advance()
            if self.cur().type == TokenType.WORD and self.cur().value == '+':
                self.advance()
                if self.cur().type == TokenType.WORD and self.cur().value == '+':
                    self.advance()
                    return self.parse_import_cpp(line)
                else:
                    self.pos -= 1
            return self.parse_import_c(line)

        # Bare string path: `import from "file.dict"` (module name inferred)
        if self.cur().type == TokenType.STRING:
            import os
            file_path = self.advance().value
            module_name = os.path.splitext(os.path.basename(file_path))[0].capitalize()
            return ImportDict(module_name=module_name, file_path=file_path,
                              alias=module_name, line=line)

        raise SyntaxError(f"Expected 'from C', 'from C++', or 'MyModule from \"file.dict\"' at line {line}")

    def parse_import_c(self, line: int) -> ImportC:
        self.expect_word('the'); self.expect_word('action')
        action_name = self.expect_word().value
        self.expect_word('takes')
        params = []
        while not (self.cur().type == TokenType.WORD and self.cur().value == 'produces'):
            if self.cur().type in (TokenType.NEWLINE, TokenType.EOF): break
            ptype = self.parse_type()
            if ptype != 'nothing':
                # FIX: `takes nothing` means zero parameters -- `nothing`
                # is the explicit "no args" marker, not a real param type,
                # and must not be counted as one.
                params.append(ptype)
            if not self.match_word('and'): break
        self.match_word('produces')
        ret_type = self.parse_type()
        self.expect_word('as')
        alias_parts = [self.expect_word().value]
        _TOP = {'end','program','module','shape','action','use','bind','import','extern','export'}
        while self.cur().type == TokenType.WORD and self.cur().value not in _TOP:
            alias_parts.append(self.advance().value)
        return ImportC(action_name=action_name, params=params, ret_type=ret_type,
                       alias=' '.join(alias_parts), line=line)

    def parse_import_cpp(self, line: int) -> ImportCpp:
        self.expect_word('the')
        item_type = self.expect_word().value
        item_name = self.expect_word().value
        params = []; ret_type = 'nothing'
        if item_type == 'action':
            self.expect_word('takes')
            while not (self.cur().type == TokenType.WORD and self.cur().value == 'produces'):
                if self.cur().type in (TokenType.NEWLINE, TokenType.EOF): break
                ptype = self.parse_type()
                if ptype != 'nothing':
                    params.append(ptype)
                if not self.match_word('and') and not self.match_word(','): break
            if self.cur().type == TokenType.WORD and self.cur().value == 'produces':
                self.advance(); ret_type = self.parse_type()
        elif item_type == 'container':
            if self.match_word('of'):
                rest_parts = []
                while not (self.cur().type == TokenType.WORD and self.cur().value == 'as'):
                    if self.cur().type in (TokenType.NEWLINE, TokenType.EOF): break
                    rest_parts.append(self.advance().value)
                item_name = item_name + ' of ' + ' '.join(rest_parts)
        self.expect_word('as')
        alias_parts = [self.expect_word().value]
        _TOP = {'end','program','module','shape','action','use','bind','import','extern','export'}
        while self.cur().type == TokenType.WORD and self.cur().value not in _TOP:
            alias_parts.append(self.advance().value)
        return ImportCpp(item_type=item_type, item_name=item_name, params=params,
                         ret_type=ret_type, alias=' '.join(alias_parts), line=line)

    def parse_define(self) -> HandleTypeDecl:
        """`define handle Name` — declares Name as a distinct nominal
        handle type (e.g. `define handle Db`, `define handle Stmt`)."""
        line = self.advance().line   # consume 'define'
        self.expect_word('handle')
        name_tok = self.expect_word()
        return HandleTypeDecl(name=name_tok.value, line=line)

    def parse_stop(self) -> Break:
        """`stop repeating` — breaks out of the nearest enclosing loop."""
        line = self.advance().line   # consume 'stop'
        self.expect_word('repeating')
        return Break(line=line)

    def parse_export_statement(self) -> Node:
        line = self.advance().line
        tok = self.cur()
        if tok.type != TokenType.WORD:
            raise SyntaxError(f"Expected keyword after 'export' at line {tok.line}")
        if tok.value == 'keep':
            node = self.parse_keep(); node.export = True; return node
        elif tok.value == 'action':
            node = self.parse_action(); node.export = True; return node
        elif tok.value == 'shape':
            node = self.parse_shape(); node.export = True; return node
        raise SyntaxError(f"Cannot export '{tok.value}' at line {tok.line}")


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
