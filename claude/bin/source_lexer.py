from __future__ import annotations

import ast
import bisect
import re
import warnings
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath

TEST_DIRS = frozenset({"tests", "test", "__tests__"})
TEST_NAME = re.compile(r"test_.*\.py|.*_test\.\w+|.*\.(?:test|spec)\.\w+")
UPPER_NAME = re.compile(r"[A-Z][A-Z0-9_]*$|k[A-Z]\w*$")
PYTHON_SUFFIX = ".py"
NATIVE_SUFFIXES = frozenset({".c", ".h", ".cpp", ".hpp", ".cc"})
SCRIPT_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx"})
OPERATOR_PUNCTS = frozenset("=+-*/%&|^<>?:,.!~(")
CONTINUING_PUNCTS = frozenset(".?:+*/|&<>=,%^")
REGEX_KEYWORDS = frozenset(
    {
        "return",
        "typeof",
        "case",
        "do",
        "else",
        "in",
        "of",
        "void",
        "delete",
        "throw",
        "new",
        "instanceof",
        "yield",
        "await",
    }
)
CONST_KEYWORDS = frozenset({"const", "constexpr", "constinit"})
RAW_PREFIXES = frozenset({"R", "LR", "uR", "UR", "u8R"})
RAW_OPEN = re.compile(r'"([^()\\\s]{0,16})\(')
NUMBER = re.compile(
    r"0[xX][0-9a-fA-F](?:'?[0-9a-fA-F_])*(?:\.[0-9a-fA-F_']*)?"
    r"(?:[pP][+-]?\d+)?[uUlLfFnNzZ]*"
    r"|0[bB][01](?:'?[01_])*[uUlLnNzZ]*"
    r"|(?:\d(?:'?[\d_])*\.?(?:\d(?:'?[\d_])*)?|\.\d(?:'?[\d_])*)"
    r"(?:[eE][+-]?\d+)?[uUlLfFnNzZ]*"
)
IDENT = re.compile(r"[^\W\d][\w$]*|\$[\w$]*")
DIRECTIVE = re.compile(r"[ \t]*([A-Za-z_]+)")
REGEX_LITERAL = re.compile(
    r"/(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+/[a-z]*"
)
QUOTED = {
    '"': re.compile(r'"(?:\\.|[^"\\\n])*"?', re.DOTALL),
    "'": re.compile(r"'(?:\\.|[^'\\\n])*'?", re.DOTALL),
}


class StaticLanguage(Enum):
    """The language families the static check understands."""

    PYTHON = "python"
    NATIVE = "native"
    SCRIPT = "script"


class TokenKind(Enum):
    """The token classes the tokenizer distinguishes."""

    NUMBER = "number"
    IDENT = "ident"
    PUNCT = "punct"
    COMMENT = "comment"
    STRING = "string"


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token with its position and preprocessor group."""

    kind: TokenKind
    text: str
    line: int
    column: int
    offset: int
    end: int
    directive: str
    group: int


def parse_python(text: str) -> ast.Module | None:
    """Parse Python source, None when it does not parse."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            return None


def static_is_test(path: str) -> bool:
    """Tell whether a path is a test file."""
    pure = PurePosixPath(path)
    if TEST_DIRS & set(pure.parts[:-1]):
        return True
    return TEST_NAME.fullmatch(pure.name) is not None


def static_language(path: str) -> StaticLanguage | None:
    """Return the language family of a path, None when unsupported."""
    suffix = PurePosixPath(path).suffix
    if suffix == PYTHON_SUFFIX:
        return StaticLanguage.PYTHON
    if suffix in NATIVE_SUFFIXES:
        return StaticLanguage.NATIVE
    if suffix in SCRIPT_SUFFIXES:
        return StaticLanguage.SCRIPT
    return None


class Scanner:
    """Tokenize C-family and script source, keeping code and comments."""

    def __init__(self, text: str, language: StaticLanguage) -> None:
        """Prepare a scanner over the text."""
        self.text = text
        self.language = language
        self.pos = 0
        self.tokens: list[Token] = []
        self.last_code: Token | None = None
        self.directive = ""
        self.group = 0
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", text)]

    def emit(self, kind: TokenKind, start: int, end: int) -> None:
        """Append a token and move past it."""
        line = bisect.bisect_right(self.line_starts, start)
        token = Token(
            kind,
            self.text[start:end],
            line,
            start - self.line_starts[line - 1] + 1,
            start,
            end,
            self.directive,
            self.group if self.directive else 0,
        )
        self.tokens.append(token)
        if kind is not TokenKind.COMMENT:
            self.last_code = token
        self.pos = end

    def scan(self, *, nested: bool) -> None:
        """Scan tokens until the end, or the closing brace when nested."""
        depth = 0
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\n":
                self.directive = ""
                self.pos += 1
            elif char.isspace():
                self.pos += 1
            elif self.text.startswith("\\\n", self.pos):
                self.pos += 2
            elif nested and char == "}" and depth == 0:
                self.pos += 1
                return
            else:
                depth += self.scan_token(char)

    def scan_token(self, char: str) -> int:
        """Scan one token, returning the brace depth change."""
        text, pos = self.text, self.pos
        following = text[pos + 1 : pos + 2]
        if text.startswith("//", pos):
            self.scan_line_comment()
        elif text.startswith("/*", pos):
            self.scan_block_comment()
        elif char in QUOTED:
            self.scan_quoted(char)
        elif char == "`" and self.language is StaticLanguage.SCRIPT:
            self.scan_template()
        elif char.isdigit() or (char == "." and following.isdigit()):
            self.scan_number()
        elif ident := IDENT.match(text, pos):
            self.scan_identifier(ident)
        elif char == "#" and self.at_directive():
            self.scan_directive()
        elif char == "/" and self.regex_allowed():
            self.scan_regex()
        else:
            self.emit(TokenKind.PUNCT, pos, pos + 1)
            return {"{": 1, "}": -1}.get(char, 0)
        return 0

    def scan_line_comment(self) -> None:
        """Scan a // comment up to the end of the line."""
        end = self.text.find("\n", self.pos)
        self.emit(
            TokenKind.COMMENT, self.pos, len(self.text) if end < 0 else end
        )

    def scan_block_comment(self) -> None:
        """Scan a /* */ comment, possibly spanning lines."""
        end = self.text.find("*/", self.pos + 2)
        stop = len(self.text) if end < 0 else end + 2
        self.emit(TokenKind.COMMENT, self.pos, stop)

    def scan_quoted(self, quote: str) -> None:
        """Scan a string or character literal."""
        match = QUOTED[quote].match(self.text, self.pos)
        end = match.end() if match else self.pos + 1
        self.emit(TokenKind.STRING, self.pos, end)

    def scan_template(self) -> None:
        """Scan a template literal, scanning its interpolations as code."""
        start = self.pos
        self.emit(TokenKind.STRING, start, start + 1)
        while self.pos < len(self.text):
            if self.text.startswith("${", self.pos):
                self.pos += 2
                self.scan(nested=True)
            elif self.text[self.pos] == "\\":
                self.pos += 2
            elif self.text[self.pos] == "`":
                self.pos += 1
                return
            else:
                self.pos += 1

    def scan_number(self) -> None:
        """Scan a numeric literal."""
        match = NUMBER.match(self.text, self.pos)
        end = match.end() if match else self.pos + 1
        self.emit(TokenKind.NUMBER, self.pos, end)

    def scan_identifier(self, match: re.Match[str]) -> None:
        """Scan an identifier, or a C++ raw string it prefixes."""
        raw_start = match.end()
        is_raw = (
            self.language is StaticLanguage.NATIVE
            and match.group() in RAW_PREFIXES
            and self.text.startswith('"', raw_start)
        )
        if is_raw and self.scan_raw_string(raw_start):
            return
        self.emit(TokenKind.IDENT, self.pos, raw_start)

    def scan_raw_string(self, quote_at: int) -> bool:
        """Scan a C++ raw string literal, False when it is malformed."""
        opening = RAW_OPEN.match(self.text, quote_at)
        if opening is None:
            return False
        closing = f'){opening.group(1)}"'
        found = self.text.find(closing, opening.end())
        end = len(self.text) if found < 0 else found + len(closing)
        self.emit(TokenKind.STRING, self.pos, end)
        return True

    def at_directive(self) -> bool:
        """Tell whether a # starts a preprocessor directive."""
        if self.language is not StaticLanguage.NATIVE:
            return False
        line_start = self.text.rfind("\n", 0, self.pos) + 1
        return not self.text[line_start : self.pos].strip()

    def scan_directive(self) -> None:
        """Start a preprocessor directive group at a # sign."""
        match = DIRECTIVE.match(self.text, self.pos + 1)
        self.group += 1
        self.directive = match.group(1) if match else "?"
        self.pos = match.end() if match else self.pos + 1

    def regex_allowed(self) -> bool:
        """Tell whether a / here starts a regular expression literal."""
        if self.language is not StaticLanguage.SCRIPT:
            return False
        last = self.last_code
        if last is None:
            return True
        if last.kind is TokenKind.PUNCT:
            return last.text not in ")]}"
        return last.kind is TokenKind.IDENT and last.text in REGEX_KEYWORDS

    def scan_regex(self) -> None:
        """Scan a regular expression literal."""
        match = REGEX_LITERAL.match(self.text, self.pos)
        if match is None:
            self.emit(TokenKind.PUNCT, self.pos, self.pos + 1)
            return
        self.emit(TokenKind.STRING, self.pos, match.end())


def tokenize_source(text: str, language: StaticLanguage) -> list[Token]:
    """Split C-family or script source into tokens."""
    scanner = Scanner(text, language)
    scanner.scan(nested=False)
    return scanner.tokens


def group_end(code: list[Token], start: int) -> int:
    """Return the index after the last token of a directive group."""
    end = start
    while end < len(code) and code[end].group == code[start].group:
        end += 1
    return end


def define_exclusions(code: list[Token]) -> set[int]:
    """Return the indices of tokens in #define bodies."""
    excluded: set[int] = set()
    for index, token in enumerate(code):
        starts_define = token.directive == "define" and (
            index == 0 or code[index - 1].group != token.group
        )
        if starts_define:
            excluded.update(range(index + 1, group_end(code, index)))
    return excluded


def matching_brace(code: list[Token], open_index: int) -> int:
    """Return the index of the brace closing the one at open_index."""
    depth = 0
    for index in range(open_index, len(code)):
        if code[index].kind is not TokenKind.PUNCT:
            continue
        depth += {"{": 1, "}": -1}.get(code[index].text, 0)
        if depth == 0:
            return index
    return len(code)


def enum_body_start(code: list[Token], start: int) -> int | None:
    """Return the index of the brace opening an enum body."""
    for index in range(start + 1, len(code)):
        text = code[index].text
        if text == "{":
            return index
        if text in {";", "(", ")", "="}:
            return None
    return None


def enum_exclusions(code: list[Token]) -> set[int]:
    """Return the indices of tokens inside enum bodies."""
    excluded: set[int] = set()
    for index, token in enumerate(code):
        if token.kind is not TokenKind.IDENT or token.text != "enum":
            continue
        open_index = enum_body_start(code, index)
        if open_index is not None:
            excluded.update(
                range(open_index, matching_brace(code, open_index))
            )
    return excluded


def constant_assignment(
    code: list[Token], start: int, language: StaticLanguage
) -> tuple[Token | None, int] | None:
    """Find the name and = of a declaration after a const keyword."""
    depth = 0
    name: Token | None = None
    for index in range(start, len(code)):
        token = code[index]
        if token.kind is TokenKind.IDENT and depth == 0:
            if name is None or language is StaticLanguage.NATIVE:
                name = token
        elif token.kind is TokenKind.PUNCT:
            if token.text == "[":
                depth += 1
            elif token.text == "]":
                depth -= 1
            elif depth == 0 and token.text == "=":
                return name, index
            elif depth == 0 and token.text in {"(", ")", ";", "{", "}", ","}:
                return None
    return None


def continues_statement(previous: Token, token: Token) -> bool:
    """Tell whether a token on a new line continues the statement."""
    if previous.kind is TokenKind.PUNCT and previous.text in OPERATOR_PUNCTS:
        return True
    return token.kind is TokenKind.PUNCT and token.text in CONTINUING_PUNCTS


def initializer_end(
    code: list[Token], start: int, language: StaticLanguage
) -> int:
    """Return the index after the initializer that starts at start."""
    depth = 0
    for index in range(start, len(code)):
        token = code[index]
        if token.kind is TokenKind.PUNCT:
            if token.text in {"(", "[", "{"}:
                depth += 1
            elif token.text in {")", "]", "}"}:
                depth -= 1
                if depth < 0:
                    return index
            elif depth == 0 and token.text == ";":
                return index
        newline = index > start and token.line > code[index - 1].line
        if (
            language is StaticLanguage.SCRIPT
            and depth == 0
            and newline
            and not continues_statement(code[index - 1], token)
        ):
            return index
    return len(code)


def const_exclusions(code: list[Token], language: StaticLanguage) -> set[int]:
    """Return the indices of numbers in constant initializers."""
    excluded: set[int] = set()
    for index, token in enumerate(code):
        if token.kind is not TokenKind.IDENT or token.directive:
            continue
        if token.text not in CONST_KEYWORDS:
            continue
        found = constant_assignment(code, index + 1, language)
        if found is None or found[0] is None:
            continue
        if not UPPER_NAME.fullmatch(found[0].text):
            continue
        end = initializer_end(code, found[1] + 1, language)
        excluded.update(range(found[1] + 1, end))
    return excluded
