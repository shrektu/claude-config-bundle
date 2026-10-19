from __future__ import annotations

import ast
import dataclasses
import io
import itertools
import re
import tokenize
from dataclasses import dataclass, field
from enum import StrEnum

from source_lexer import (
    StaticLanguage,
    Token,
    TokenKind,
    const_exclusions,
    define_exclusions,
    enum_exclusions,
)

REPEAT_LINES = 3
COMPARISON_QUIET = frozenset({-1, 0, 1})
OBVIOUS_VALUES = frozenset({-1, 0, 1, 2, 10})
SCALE_VALUES = frozenset(
    {24, 60, 100, 1000, 3600, 86400, 1_000_000, 1_000_000_000}
)
QUIET_VALUES = OBVIOUS_VALUES | SCALE_VALUES
ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
PY_CONSTANT = re.compile(r"[A-Z][A-Z0-9_]*$")
DUNDER_NAME = re.compile(r"__\w+__$")
INTEGER_SUFFIX = re.compile(r"[ulzn]+$")
FLOAT_SUFFIX = re.compile(r"f$")
OCTAL_BASE = 8
DECIMAL_BASE = 10
RADIX_PREFIXES = {"0x": 16, "0b": 2, "0o": 8}
MAX_OPERATOR_LENGTH = 3
OPERATORS = frozenset(
    {
        "<<=",
        ">>=",
        "===",
        "!==",
        "==",
        "!=",
        "<=",
        ">=",
        "<<",
        ">>",
        "&&",
        "||",
        "&=",
        "|=",
        "^=",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "++",
        "--",
        "->",
        "=>",
        "??",
        "?.",
        "::",
        "**",
    }
)
COMPARISONS = frozenset({"==", "!=", "===", "!==", "<", "<=", ">", ">="})
BITWISE = frozenset(
    {"&", "|", "^", "~", "<<", ">>", "&=", "|=", "^=", "<<=", ">>="}
)
OPERAND_STARTS = frozenset(
    {"(", ",", "[", "{", "}", ";", "?", ":", "=", "=>", "&&", "||"}
)
OPERAND_ENDS = frozenset({")", "]", "}", ";", ",", ":", "?", "&&", "||"})
OPENERS = frozenset({"(", "[", "{"})
CLOSERS = frozenset({")", "]", "}"})
NON_CALLEES = frozenset(
    {
        "if",
        "while",
        "for",
        "switch",
        "return",
        "catch",
        "case",
        "throw",
        "else",
        "in",
        "of",
    }
)
TEMPLATE_PUNCTS = frozenset({",", "::", "*", "&", "-", "."})
BITWISE_PY = (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)
SCALING_PY = (ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
SCALING = frozenset({"*", "/", "%"})
FUNCTION_MARKERS = frozenset({"=>", "{", "function"})
DELAY_CALLEES = frozenset(
    {
        "sleep",
        "usleep",
        "msleep",
        "nanosleep",
        "delay",
        "delay_ms",
        "delay_us",
        "delayMicroseconds",
        "k_sleep",
        "k_msleep",
        "k_usleep",
        "k_busy_wait",
        "vTaskDelay",
        "HAL_Delay",
        "osDelay",
        "sleep_ms",
        "sleep_us",
        "sleep_for",
        "sleep_until",
        "wait_ms",
        "wait_us",
        "setTimeout",
        "setInterval",
    }
)
NON_CODE_PY_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
)


class MagicRule(StrEnum):
    """The magic-number rules."""

    COMPARISON = "MAG001"
    REPEATED = "MAG002"
    DELAY = "MAG003"


@dataclass(frozen=True, slots=True)
class MagicHit:
    """A magic-number finding on one line."""

    line: int
    rule: MagicRule
    values: tuple[str, ...]
    column: int = field(default=0, compare=False)


@dataclass(frozen=True, slots=True)
class Occurrence:
    """A numeric literal outside every exempt context."""

    line: int
    text: str
    key: int | float
    comparison: bool
    column: int
    delay: bool = False


@dataclass(frozen=True, slots=True)
class Stream:
    """Operator-merged code tokens with their enclosing brackets."""

    tokens: list[Token]
    openers: list[int | None]


def literal_key(text: str) -> int | float | None:
    """Return the exact value of a numeric literal, None if unknown."""
    cleaned = text.replace("'", "").replace("_", "").lower()
    try:
        radix = RADIX_PREFIXES.get(cleaned[:2])
        if radix is not None:
            return int(INTEGER_SUFFIX.sub("", cleaned[2:]), radix)
        digits = INTEGER_SUFFIX.sub("", cleaned)
        if digits.isdigit():
            return int(
                digits, OCTAL_BASE if digits[0] == "0" else DECIMAL_BASE
            )
        return float(FLOAT_SUFFIX.sub("", digits))
    except ValueError:
        return None


def target_names(target: ast.expr) -> list[str] | None:
    """Return the plain names an assignment target binds, else None."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple):
        names = [target_names(element) for element in target.elts]
        if any(item is None for item in names):
            return None
        return [name for item in names for name in item or []]
    return None


def is_constant_name(name: str) -> bool:
    """Tell whether a name is UPPER_CASE or a dunder."""
    return bool(PY_CONSTANT.fullmatch(name) or DUNDER_NAME.fullmatch(name))


def is_enum_class(node: ast.ClassDef) -> bool:
    """Tell whether a class derives from an Enum base by name."""
    for base in node.bases:
        name = (
            base.attr
            if isinstance(base, ast.Attribute)
            else getattr(base, "id", "")
        )
        if name in ENUM_BASES or name.endswith("Enum"):
            return True
    return False


def assignment_value(statement: ast.stmt, *, in_enum: bool) -> ast.expr | None:
    """Return the value of a constant or enum member definition."""
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AnnAssign):
        targets = [statement.target]
    else:
        return None
    names = [target_names(target) for target in targets]
    if any(item is None for item in names):
        return None
    flat = [name for item in names for name in item or []]
    if in_enum or all(is_constant_name(name) for name in flat):
        return statement.value
    return None


def subtree_ids(node: ast.AST | None) -> set[int]:
    """Return the ids of a node and everything below it."""
    if node is None:
        return set()
    return {id(child) for child in ast.walk(node)}


def definition_ids(node: ast.AST) -> set[int]:
    """Return the ids inside constant and enum member definitions."""
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        return subtree_ids(assignment_value(node, in_enum=False))
    if isinstance(node, ast.ClassDef) and is_enum_class(node):
        values = [assignment_value(s, in_enum=True) for s in node.body]
        return set().union(*(subtree_ids(value) for value in values))
    return set()


def call_argument_ids(node: ast.AST) -> set[int]:
    """Return the ids of whole call arguments."""
    if not isinstance(node, ast.Call):
        return set()
    values = [*node.args, *(keyword.value for keyword in node.keywords)]
    return {id(value) for value in values}


def bitwise_operand_ids(node: ast.AST) -> set[int]:
    """Return the ids of operands of bitwise and shift operators."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, BITWISE_PY):
        return {id(node.left), id(node.right)}
    if isinstance(node, ast.AugAssign) and isinstance(node.op, BITWISE_PY):
        return {id(node.value)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
        return {id(node.operand)}
    return set()


def exempt_python_ids(
    tree: ast.Module, *, include_calls: bool = True
) -> set[int]:
    """Return the ids of every node in an exempt context."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        exempt |= definition_ids(node)
        if include_calls:
            exempt |= call_argument_ids(node)
        exempt |= bitwise_operand_ids(node)
        if isinstance(node, ast.Subscript):
            exempt |= subtree_ids(node.slice)
    return exempt


def delay_argument_ids(node: ast.AST) -> set[int]:
    """Return the ids below the arguments of a delay call."""
    if not isinstance(node, ast.Call):
        return set()
    callee = node.func
    name = callee.attr if isinstance(callee, ast.Attribute) else ""
    if isinstance(callee, ast.Name):
        name = callee.id
    if name not in DELAY_CALLEES:
        return set()
    values = [*node.args, *(keyword.value for keyword in node.keywords)]
    return set().union(
        *(
            subtree_ids(value)
            for value in values
            if not isinstance(value, ast.Lambda)
        )
    )


def scaled_operand_ids(node: ast.AST) -> set[int]:
    """Return the ids of scale constants next to a scaling operator."""
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, SCALING_PY):
        return set()
    return {
        id(operand)
        for operand in (node.left, node.right)
        if python_number(operand) in SCALE_VALUES
    }


def python_delay_ids(tree: ast.Module) -> set[int]:
    """Return the ids of nodes that are delay literals to judge."""
    delayed: set[int] = set()
    scaled: set[int] = set()
    for node in ast.walk(tree):
        delayed |= delay_argument_ids(node)
        scaled |= scaled_operand_ids(node)
    return delayed - scaled - exempt_python_ids(tree, include_calls=False)


def python_number(node: ast.expr) -> int | float | None:
    """Return the value of an int or float constant, else None."""
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
        return None
    if isinstance(node.value, (int, float)):
        return node.value
    return None


def python_literals(tree: ast.Module) -> list[tuple[ast.expr, int | float]]:
    """Return the number literals, a negated one as a single node."""
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.expr)]
    negated = {
        id(node.operand): node
        for node in nodes
        if isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and python_number(node.operand) is not None
    }
    literals: list[tuple[ast.expr, int | float]] = []
    for node in nodes:
        value = python_number(node)
        if value is None:
            continue
        unary = negated.get(id(node))
        if unary is None:
            literals.append((node, value))
        else:
            literals.append((unary, -value))
    return literals


def character_column(lines: list[str], line: int, byte_offset: int) -> int:
    """Return the 1-based character column of a UTF-8 byte offset."""
    prefix = lines[line - 1].encode()[:byte_offset]
    return len(prefix.decode(errors="ignore")) + 1


def reported(
    node_id: int, value: float, delayed: set[int], exempt: set[int]
) -> bool:
    """Tell whether a literal is outside every exempt context."""
    if node_id in delayed:
        return value != 0
    return node_id not in exempt


def python_occurrences(tree: ast.Module, text: str) -> list[Occurrence]:
    """Return the number literals outside every exempt context."""
    exempt = exempt_python_ids(tree)
    delayed = python_delay_ids(tree)
    lines = text.split("\n")
    return [
        Occurrence(
            node.lineno,
            str(value),
            value,
            comparison=False,
            column=character_column(lines, node.lineno, node.col_offset),
            delay=id(node) in delayed,
        )
        for node, value in python_literals(tree)
        if reported(id(node), value, delayed, exempt)
    ]


def explained_from(
    comment_lines: set[int], code_lines: set[int]
) -> frozenset[int]:
    """Return the comment lines and the line below a comment-only line."""
    standalone = comment_lines - code_lines
    return frozenset(comment_lines | {line + 1 for line in standalone})


def python_explained_lines(text: str) -> frozenset[int]:
    """Return the lines a comment explains in Python source."""
    comment_lines: set[int] = set()
    code_lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comment_lines.add(token.start[0])
            elif token.type not in NON_CODE_PY_TOKENS:
                code_lines.add(token.start[0])
    except (tokenize.TokenError, SyntaxError):
        return frozenset()
    return explained_from(comment_lines, code_lines)


def token_explained_lines(tokens: list[Token]) -> frozenset[int]:
    """Return the lines a comment explains in C-family or script tokens."""
    comment_lines: set[int] = set()
    code_lines: set[int] = set()
    for token in tokens:
        if token.kind is TokenKind.COMMENT:
            comment_lines.update(
                range(token.line, token.line + token.text.count("\n") + 1)
            )
        else:
            code_lines.add(token.line)
    return explained_from(comment_lines, code_lines)


def unexplained(
    hits: list[MagicHit], explained: frozenset[int]
) -> list[MagicHit]:
    """Drop the hits on lines a comment explains."""
    return [hit for hit in hits if hit.line not in explained]


def python_magic_hits(
    tree: ast.Module, changed: frozenset[int], text: str
) -> list[MagicHit]:
    """Return the delay and repeated-number hits of a Python module."""
    occurrences = python_occurrences(tree, text)
    hits = unexplained(
        delay_hits(occurrences, changed), python_explained_lines(text)
    )
    hits += repeated_hits(occurrences, changed)
    return sorted(hits, key=lambda hit: (hit.line, hit.rule))


def repeated_hits(
    occurrences: list[Occurrence], changed: frozenset[int]
) -> list[MagicHit]:
    """Return one hit per changed line holding a repeated value."""
    counted = [item for item in occurrences if not item.delay]
    lines: dict[int | float, set[int]] = {}
    for item in counted:
        if item.key not in QUIET_VALUES:
            lines.setdefault(item.key, set()).add(item.line)
    grouped: dict[int, dict[int | float, Occurrence]] = {}
    for item in counted:
        if len(lines.get(item.key, ())) >= REPEAT_LINES and (
            item.line in changed
        ):
            grouped.setdefault(item.line, {}).setdefault(item.key, item)
    return [
        MagicHit(
            line,
            MagicRule.REPEATED,
            tuple(item.text for item in found.values()),
            min(item.column for item in found.values()),
        )
        for line, found in sorted(grouped.items())
    ]


def line_hits(
    found: list[Occurrence], rule: MagicRule, changed: frozenset[int]
) -> list[MagicHit]:
    """Return one hit of the rule per changed line of the occurrences."""
    grouped: dict[int, list[Occurrence]] = {}
    for item in found:
        if item.line in changed:
            grouped.setdefault(item.line, []).append(item)
    return [
        MagicHit(
            line,
            rule,
            tuple(item.text for item in items),
            min(item.column for item in items),
        )
        for line, items in sorted(grouped.items())
    ]


def comparison_hits(
    occurrences: list[Occurrence], changed: frozenset[int]
) -> list[MagicHit]:
    """Return one hit per changed line with a magic comparison."""
    found = [
        item
        for item in occurrences
        if item.comparison
        and not item.delay
        and item.key not in COMPARISON_QUIET
    ]
    return line_hits(found, MagicRule.COMPARISON, changed)


def delay_hits(
    occurrences: list[Occurrence], changed: frozenset[int]
) -> list[MagicHit]:
    """Return one hit per changed line with a magic delay."""
    found = [item for item in occurrences if item.delay]
    return line_hits(found, MagicRule.DELAY, changed)


def operator_length(code: list[Token], index: int) -> int:
    """Return how many tokens form the operator starting at index."""
    for length in range(MAX_OPERATOR_LENGTH, 1, -1):
        window = code[index : index + length]
        if len(window) < length:
            continue
        pairs = itertools.pairwise(window)
        adjacent = all(a.end == b.offset for a, b in pairs)
        punctuation = all(t.kind is TokenKind.PUNCT for t in window)
        if (
            adjacent
            and punctuation
            and "".join(t.text for t in window) in OPERATORS
        ):
            return length
    return 1


def merge_operators(code: list[Token]) -> list[Token]:
    """Join adjacent punctuation characters into operator tokens."""
    merged: list[Token] = []
    index = 0
    while index < len(code):
        token = code[index]
        length = operator_length(code, index)
        if length > 1:
            window = code[index : index + length]
            token = dataclasses.replace(
                token,
                text="".join(t.text for t in window),
                end=window[-1].end,
            )
        merged.append(token)
        index += length
    return merged


def enclosing_openers(tokens: list[Token]) -> list[int | None]:
    """Return, per token, the innermost bracket opener around it."""
    stack: list[int] = []
    result: list[int | None] = []
    for index, token in enumerate(tokens):
        if token.kind is TokenKind.PUNCT and token.text in CLOSERS and stack:
            stack.pop()
        result.append(stack[-1] if stack else None)
        if token.kind is TokenKind.PUNCT and token.text in OPENERS:
            stack.append(index)
    return result


def text_at(tokens: list[Token], index: int) -> str:
    """Return the text of a token, empty outside the stream."""
    if 0 <= index < len(tokens):
        return tokens[index].text
    return ""


def is_value_end(tokens: list[Token], index: int) -> bool:
    """Tell whether the token at index can end an operand."""
    if not 0 <= index < len(tokens):
        return False
    token = tokens[index]
    if token.kind is TokenKind.IDENT:
        return token.text not in NON_CALLEES
    if token.kind in (TokenKind.NUMBER, TokenKind.STRING):
        return True
    return token.text in {")", "]"}


def is_call_paren(tokens: list[Token], index: int) -> bool:
    """Tell whether the ( at index opens a call argument list."""
    if text_at(tokens, index) != "(" or index == 0:
        return False
    previous = tokens[index - 1]
    if previous.text == ">":
        return previous.end == tokens[index].offset
    if previous.kind is TokenKind.IDENT:
        return previous.text not in NON_CALLEES
    return previous.text in {")", "]"}


def is_unary_minus(tokens: list[Token], index: int) -> bool:
    """Tell whether a minus sign directly precedes the literal."""
    return text_at(tokens, index - 1) == "-" and not is_value_end(
        tokens, index - 2
    )


def operand_span(tokens: list[Token], index: int) -> tuple[int, int]:
    """Return the token range of a literal with its sign and parens."""
    start, end = index, index + 1
    if is_unary_minus(tokens, index):
        start -= 1
    while (
        text_at(tokens, start - 1) == "("
        and text_at(tokens, end) == ")"
        and not is_call_paren(tokens, start - 1)
    ):
        start -= 1
        end += 1
    return start, end


def is_call_argument(stream: Stream, start: int, end: int) -> bool:
    """Tell whether the span is a whole call argument."""
    tokens = stream.tokens
    if text_at(tokens, start - 1) not in {"(", ","}:
        return False
    if text_at(tokens, end) not in {",", ")"}:
        return False
    opener = stream.openers[start]
    return opener is not None and is_call_paren(tokens, opener)


def is_subscript_member(stream: Stream, index: int) -> bool:
    """Tell whether the token sits inside an index or array size."""
    opener = stream.openers[index]
    while opener is not None:
        if text_at(stream.tokens, opener) == "[" and is_value_end(
            stream.tokens, opener - 1
        ):
            return True
        opener = stream.openers[opener]
    return False


def argument_bounds(tokens: list[Token], opener: int, index: int) -> range:
    """Return the token range of the argument holding the index."""
    start, depth = opener + 1, 0
    for position in range(opener + 1, len(tokens)):
        text = tokens[position].text
        if tokens[position].kind is not TokenKind.PUNCT:
            continue
        if text in OPENERS:
            depth += 1
        elif text in CLOSERS and depth == 0:
            return range(start, position)
        elif text in CLOSERS:
            depth -= 1
        elif text == "," and depth == 0:
            if position > index:
                return range(start, position)
            start = position + 1
    return range(start, len(tokens))


def is_function_argument(tokens: list[Token], bounds: range) -> bool:
    """Tell whether an argument is a callback or holds a block."""
    return any(
        tokens[position].text in FUNCTION_MARKERS for position in bounds
    )


def in_delay_call(stream: Stream, index: int) -> bool:
    """Tell whether the token sits inside a delay argument."""
    opener = stream.openers[index]
    while opener is not None:
        if (
            is_call_paren(stream.tokens, opener)
            and stream.tokens[opener - 1].text in DELAY_CALLEES
            and not is_function_argument(
                stream.tokens, argument_bounds(stream.tokens, opener, index)
            )
        ):
            return True
        opener = stream.openers[opener]
    return False


def is_scaled(tokens: list[Token], start: int, end: int, key: float) -> bool:
    """Tell whether a scale constant sits next to a scaling operator."""
    return key in SCALE_VALUES and (
        text_at(tokens, start - 1) in SCALING
        or text_at(tokens, end) in SCALING
    )


def is_bitwise_operand(tokens: list[Token], start: int, end: int) -> bool:
    """Tell whether the span is next to a bitwise or shift operator."""
    before, after = text_at(tokens, start - 1), text_at(tokens, end)
    return before in BITWISE or after in BITWISE


def starts_operand(tokens: list[Token], start: int) -> bool:
    """Tell whether an operand begins at the token index."""
    before = text_at(tokens, start - 1)
    return (
        start == 0
        or before in OPERAND_STARTS
        or before in COMPARISONS
        or before == "return"
    )


def ends_operand(tokens: list[Token], end: int) -> bool:
    """Tell whether an operand ends before the token index."""
    after = text_at(tokens, end)
    return end >= len(tokens) or after in OPERAND_ENDS or after in COMPARISONS


def closes_jsx_tag(tokens: list[Token], end: int) -> bool:
    """Tell whether a closing tag starts at the token index."""
    return text_at(tokens, end) == "<" and text_at(tokens, end + 1) == "/"


def is_comparison_operand(tokens: list[Token], start: int, end: int) -> bool:
    """Tell whether the span is a whole operand of a comparison."""
    if closes_jsx_tag(tokens, end):
        return False
    right = text_at(tokens, start - 1) in COMPARISONS and ends_operand(
        tokens, end
    )
    left = text_at(tokens, end) in COMPARISONS and starts_operand(
        tokens, start
    )
    return right or left


def template_member(token: Token) -> bool:
    """Tell whether a token can appear in a template argument list."""
    if token.kind in (TokenKind.IDENT, TokenKind.NUMBER):
        return True
    return token.kind is TokenKind.PUNCT and token.text in TEMPLATE_PUNCTS


def template_end(tokens: list[Token], start: int) -> int | None:
    """Return the index after the template list opened at start."""
    depth = 0
    for index in range(start, len(tokens)):
        text = tokens[index].text
        if text == "<":
            depth += 1
        elif text == ">":
            depth -= 1
        elif text == ">>":
            depth -= 2
        elif not template_member(tokens[index]):
            return None
        if depth <= 0:
            return index + 1
    return None


def opens_template(tokens: list[Token], index: int) -> bool:
    """Tell whether the token at index may open a template list."""
    return (
        tokens[index].kind is TokenKind.PUNCT
        and tokens[index].text == "<"
        and index > 0
        and tokens[index - 1].kind is TokenKind.IDENT
    )


def template_numbers(tokens: list[Token]) -> set[int]:
    """Return the indices of numbers inside template argument lists."""
    marked: set[int] = set()
    for index in range(len(tokens)):
        end = (
            template_end(tokens, index)
            if opens_template(tokens, index)
            else None
        )
        if end is not None:
            marked.update(
                n
                for n in range(index, end)
                if tokens[n].kind is TokenKind.NUMBER
            )
    return marked


def excluded_offsets(code: list[Token], language: StaticLanguage) -> set[int]:
    """Return the offsets of tokens inside constant definitions."""
    indices = (
        define_exclusions(code)
        | enum_exclusions(code)
        | const_exclusions(code, language)
    )
    return {code[index].offset for index in indices}


def token_occurrence(stream: Stream, index: int) -> Occurrence | None:
    """Return the literal at index, None when its context is exempt."""
    tokens = stream.tokens
    key = literal_key(tokens[index].text)
    start, end = operand_span(tokens, index)
    if (
        key is None
        or is_subscript_member(stream, index)
        or is_bitwise_operand(tokens, start, end)
    ):
        return None
    delay = in_delay_call(stream, index)
    if delay and (key == 0 or is_scaled(tokens, start, end, key)):
        return None
    if not delay and is_call_argument(stream, start, end):
        return None
    negative = is_unary_minus(tokens, index)
    return Occurrence(
        tokens[index].line,
        ("-" if negative else "") + tokens[index].text,
        -key if negative else key,
        comparison=is_comparison_operand(tokens, start, end),
        column=tokens[index].column,
        delay=delay,
    )


def token_occurrences(
    code: list[Token], language: StaticLanguage
) -> list[Occurrence]:
    """Return the number literals outside every exempt context."""
    excluded = excluded_offsets(code, language)
    tokens = merge_operators(code)
    stream = Stream(tokens, enclosing_openers(tokens))
    templated = template_numbers(tokens)
    found = [
        token_occurrence(stream, index)
        for index, token in enumerate(tokens)
        if token.kind is TokenKind.NUMBER
        and not token.directive
        and token.offset not in excluded
        and index not in templated
    ]
    return [item for item in found if item is not None]


def token_magic_hits(
    tokens: list[Token],
    language: StaticLanguage,
    changed: frozenset[int],
) -> list[MagicHit]:
    """Return the magic-number hits of C-family or script tokens."""
    code = [token for token in tokens if token.kind is not TokenKind.COMMENT]
    occurrences = token_occurrences(code, language)
    hits = unexplained(
        comparison_hits(occurrences, changed)
        + delay_hits(occurrences, changed),
        token_explained_lines(tokens),
    )
    hits += repeated_hits(occurrences, changed)
    return sorted(hits, key=lambda hit: (hit.line, hit.rule))
