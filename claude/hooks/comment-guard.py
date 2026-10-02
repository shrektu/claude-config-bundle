#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit|NotebookEdit) hook: an edit may not add a comment to a code file."""
import ast
import bisect
import io
import json
import re
import sys
import tokenize
import warnings
from collections import Counter
from dataclasses import dataclass
from enum import Enum

sys.dont_write_bytecode = True
from code_files import SHEBANG, Language, first_line, language_of, suffix_of

NOTEBOOK_SUFFIX = "ipynb"
PYTHON_SUFFIX = "py"
PYTHON_KERNEL = "python"
CODE_CELL = "code"
CELL_INDEX = re.compile(r"^cell-(\d+)$")
SCAN_FLAG = "--scan"
RAW_FLAG = "--raw"
MAX_REPORTED = 3
MAX_SHOWN_CHARS = 60
RUST_INNER_ATTRIBUTE = "#!["
COOKIE_LINES = (1, 2)
CODING_COOKIE = re.compile(r"^#.*?coding[:=][ \t]*[-\w.]+")

REASON_HEAD = "comment-guard: no comments in code. Added: "
REASON_TAIL = (" Allowed: tool directives (type: ignore, noqa, eslint-disable, @ts-expect-error, go:build, …), "
               "a one-line docstring or doc comment; pass descriptions as parameters (description=…).")

DIRECTIVES = tuple(re.compile(pattern) for pattern in (
    r"type:", r"noqa\b", r"pragma:", r"fmt:", r"pylint:", r"mypy:", r"pyright:", r"ruff:", r"isort:",
    r"eslint-disable", r"eslint-enable\b", r"@ts-(ignore|expect-error|nocheck|check)\b", r"prettier-ignore\b",
    r"biome-ignore\b", r"(istanbul|c8|v8) ignore\b", r"@(vitest|jest)-environment\b", r"@vite-ignore\b",
    r"webpack(ChunkName|Mode|Prefetch|Preload|Include|Exclude|Exports|Ignore|FetchPriority):",r"<reference\b.*/>", r"go:\w", r"\+build\b", r"nolint\b", r"NOLINT",
    r"clang-format (off|on)\b", r"IWYU pragma:", r"shellcheck ", r"frozen_string_literal:", r"encoding:",
    r"rubocop:", r"swiftlint:",
))

JS_SUFFIXES = frozenset({"js", "jsx", "ts", "tsx", "mjs", "cjs", "vue", "svelte"})
MARKUP_SUFFIXES = frozenset({"vue", "svelte"})
C_RAW_SUFFIXES = frozenset({"c", "h", "cc", "cpp", "cxx", "hpp", "hh", "ino", "m", "mm"})
TEXT_BLOCK_SUFFIXES = frozenset({"java", "kt", "kts", "swift", "scala", "cs", "dart"})
MULTILINE_STRING_SUFFIXES = frozenset({"rs", "php"})
RUBY_SUFFIXES = frozenset({"rb", "ex", "exs"})
RUBY_SHEBANG_MARKS = ("ruby", "elixir")
LUA_SUFFIX = "lua"
PHP_SUFFIX = "php"
CSHARP_SUFFIX = "cs"
GO_SUFFIX = "go"
RUST_SUFFIX = "rs"
DART_SUFFIX = "dart"

REGEX_KEYWORDS = frozenset({"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                            "instanceof", "yield", "await"})
WORD = re.compile(r"[^\W\d][\w$]*|\$[\w$]*")
NUMBER = re.compile(r"\d[\w.]*")
REGEX_FLAGS = re.compile(r"[A-Za-z]*")
CPP_RAW = re.compile(r"(?:u8|[uUL])?R\"([^()\\\s]{0,16})\(")
RUST_RAW = re.compile(r"b?r(#*)\"")
RUST_CHAR = re.compile(r"b?'(\\u\{[0-9a-fA-F]{1,6}\}|\\.|[^\\'\n])'")
DART_RAW = re.compile(r"r('''|\"\"\"|'|\")")
QUOTE_RUN = re.compile(r"\"{3,}")
SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>(.*?)</\1\s*>", re.DOTALL | re.IGNORECASE)
SCRIPT_TAG = "script"
MARKUP_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
CSS_QUOTES = "'\""
SH_HEREDOC = re.compile(r"<<(?!<)[-~]?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
RUBY_HEREDOC = re.compile(r"<<[-~](['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
LUA_LONG_OPEN = re.compile(r"\[(=*)\[")
SH_COMMENT_AFTER = " \t\n;"
WHITESPACE = " \t\r\n\f\v"
CLOSERS = ")]}"
PYTHON_TRIPLES = ('"""', "'''")
DOC_LINE_MARKERS = ("///", "//!")
NOT_DOC_LINE = "////"
DOC_BLOCK_MARKER = "/**"
RUST_INNER_DOC_MARKER = "/*!"
EMPTY_BLOCK = "/**/"
BLOCK_CLOSE = "*/"
CLOSING_MARKERS = ("-->", BLOCK_CLOSE, "]]")
COMMENT_MARKERS = ("<!--", "-->", "--[[", "]]", "/*", BLOCK_CLOSE, "//", "--", "#")
DOC_KEY = "doc:"
DOCSTRING_KEY = "docstring:"


class Tool(Enum):
    EDIT = "Edit"
    WRITE = "Write"
    MULTI_EDIT = "MultiEdit"
    NOTEBOOK_EDIT = "NotebookEdit"


class CellEdit(Enum):
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


class Style(Enum):
    LINE = "line"
    BLOCK = "block"
    DOC_LINE = "doc_line"
    DOC_BLOCK = "doc_block"
    DOCSTRING = "docstring"


class HashMode(Enum):
    SH = "sh"
    RUBY = "ruby"
    PYTHON = "python"


class Prev(Enum):
    NONE = "none"
    OPERAND = "operand"
    KEYWORD = "keyword"
    PUNCT = "punct"
    CLOSER = "closer"


@dataclass(frozen=True, slots=True)
class Comment:
    line: int
    end_line: int
    text: str
    style: Style


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    text: str
    key: str


@dataclass(frozen=True, slots=True)
class Change:
    language: Language
    suffix: str | None
    before: str
    after: str


class Lines:
    def __init__(self, text):
        self.starts = [index for index, char in enumerate(text) if char == "\n"]

    def of(self, position):
        return bisect.bisect_left(self.starts, position) + 1


def line_end(text, start, end):
    found = text.find("\n", start, end)
    return end if found < 0 else found


def skip_quoted(text, start, end, quote, escapes=True, multiline=False):
    index = start + 1
    while index < end:
        char = text[index]
        if escapes and char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n" and not multiline:
            return index
        index += 1
    return end


def skip_until(text, start, end, closer):
    found = text.find(closer, start, end)
    return end if found < 0 else found + len(closer)


class Collector:
    def __init__(self, text):
        self.text = text
        self.lines = Lines(text)
        self.comments = []

    def add(self, start, stop, style):
        self.comments.append(Comment(self.lines.of(start), self.lines.of(max(start, stop - 1)),
                                     self.text[start:stop], style))


class CLikeLexer(Collector):
    def __init__(self, text, suffix):
        super().__init__(text)
        self.suffix = suffix
        self.js = suffix in JS_SUFFIXES

    def run(self):
        text, start = self.text, 0
        if text.startswith(SHEBANG) and not text.startswith(RUST_INNER_ATTRIBUTE):
            start = line_end(text, 0, len(text))
        if self.suffix in MARKUP_SUFFIXES:
            self.markup(start)
        else:
            self.scan(start, len(text))
        return self.comments

    def markup(self, start):
        position = start
        for match in SCRIPT_OR_STYLE.finditer(self.text, start):
            self.markup_comments(position, match.start(2))
            if match.group(1).lower() == SCRIPT_TAG:
                self.scan(match.start(2), match.end(2))
            else:
                self.css(match.start(2), match.end(2))
            position = match.end(2)
        self.markup_comments(position, len(self.text))

    def css(self, index, end):
        text = self.text
        while index < end:
            if text.startswith("/*", index):
                index = self.block_comment(index, end)
            elif text[index] in CSS_QUOTES:
                index = skip_quoted(text, index, end, text[index])
            else:
                index += 1

    def markup_comments(self, start, end):
        for match in MARKUP_COMMENT.finditer(self.text, start, end):
            self.add(match.start(), match.end(), Style.BLOCK)

    def line_comment(self, index, end):
        stop = line_end(self.text, index, end)
        body = self.text[index:stop]
        doc = body.startswith(DOC_LINE_MARKERS) and not body.startswith(NOT_DOC_LINE)
        self.add(index, stop, Style.DOC_LINE if doc else Style.LINE)
        return stop

    def block_comment(self, index, end):
        stop = skip_until(self.text, index + 2, end, BLOCK_CLOSE)
        body = self.text[index:stop]
        markers = (DOC_BLOCK_MARKER, RUST_INNER_DOC_MARKER) if self.suffix == RUST_SUFFIX else (DOC_BLOCK_MARKER,)
        doc = body.startswith(markers) and not body.startswith(EMPTY_BLOCK)
        self.add(index, stop, Style.DOC_BLOCK if doc else Style.BLOCK)
        return stop

    def scan(self, index, end, until_brace=False):
        text = self.text
        depth = 0
        prev = Prev.NONE
        while index < end:
            char = text[index]
            following = text[index + 1] if index + 1 < end else ""
            if char in WHITESPACE:
                index += 1
                continue
            if char == "/" and following == "/":
                index = self.line_comment(index, end)
                continue
            if char == "/" and following == "*":
                index = self.block_comment(index, end)
                continue
            if char == "#" and self.suffix == PHP_SUFFIX and following != "[":
                stop = line_end(text, index, end)
                self.add(index, stop, Style.LINE)
                index = stop
                continue
            if until_brace and char == "{":
                depth += 1
            elif until_brace and char == "}":
                if depth == 0:
                    return index + 1
                depth -= 1
            literal_end = self.literal(index, end, prev)
            if literal_end is not None:
                index = literal_end
                prev = Prev.OPERAND
                continue
            word = WORD.match(text, index) or NUMBER.match(text, index)
            if word:
                prev = Prev.KEYWORD if word.group(0) in REGEX_KEYWORDS else Prev.OPERAND
                index = word.end()
                continue
            prev = Prev.CLOSER if char in CLOSERS else Prev.PUNCT
            index += 1
        return end

    def literal(self, index, end, prev):
        text, suffix, char = self.text, self.suffix, self.text[index]
        if suffix in C_RAW_SUFFIXES:
            raw = CPP_RAW.match(text, index)
            if raw:
                return skip_until(text, raw.end(), end, ")" + raw.group(1) + "\"")
        if suffix == RUST_SUFFIX:
            raw = RUST_RAW.match(text, index)
            if raw:
                return skip_until(text, raw.end(), end, "\"" + raw.group(1))
            if char in "b'":
                rust_char = RUST_CHAR.match(text, index)
                if rust_char:
                    return rust_char.end()
                if char == "'":
                    return None
        if suffix == DART_SUFFIX:
            raw = DART_RAW.match(text, index)
            if raw:
                quote = raw.group(1)
                if len(quote) > 1:
                    return skip_until(text, raw.end(), end, quote)
                return skip_quoted(text, raw.end() - 1, end, quote, escapes=False)
            if text.startswith("'''", index):
                return skip_until(text, index + 3, end, "'''")
        if suffix == CSHARP_SUFFIX:
            verbatim = next((len(prefix) for prefix in ("@\"", "$@\"", "@$\"") if text.startswith(prefix, index)), 0)
            if verbatim:
                return skip_quoted(text, index + verbatim - 1, end, "\"", escapes=False, multiline=True)
        if char == "\"":
            if suffix in TEXT_BLOCK_SUFFIXES:
                run = QUOTE_RUN.match(text, index)
                if run:
                    return skip_until(text, run.end(), end, run.group(0))
            return skip_quoted(text, index, end, char, multiline=suffix in MULTILINE_STRING_SUFFIXES)
        if char == "'":
            if suffix in C_RAW_SUFFIXES and index > 0 and text[index - 1].isdigit():
                return None
            return skip_quoted(text, index, end, char, multiline=suffix == PHP_SUFFIX)
        if char == "`":
            if self.js:
                return self.template(index + 1, end)
            return skip_quoted(text, index, end, char, escapes=False, multiline=suffix == GO_SUFFIX)
        if char == "/" and self.js and prev in (Prev.NONE, Prev.PUNCT, Prev.KEYWORD):
            return self.regex(index, end)
        return None

    def template(self, index, end):
        text = self.text
        while index < end:
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == "`":
                return index + 1
            if char == "$" and text.startswith("{", index + 1):
                index = self.scan(index + 2, end, until_brace=True)
                continue
            index += 1
        return end

    def regex(self, index, end):
        text = self.text
        position = index + 1
        in_class = False
        while position < end:
            char = text[position]
            if char == "\n":
                return None
            if char == "\\":
                position += 2
                continue
            if in_class:
                in_class = char != "]"
            elif char == "[":
                in_class = True
            elif char == "/":
                return REGEX_FLAGS.match(text, position + 1).end()
            position += 1
        return None


class HashLexer(Collector):
    def __init__(self, text, mode):
        super().__init__(text)
        self.mode = mode

    def run(self):
        text, mode = self.text, self.mode
        end = len(text)
        index = 0
        heredocs = []
        while index < end:
            char = text[index]
            if char == "\n":
                index += 1
                if heredocs:
                    index = self.skip_heredocs(index, heredocs)
                    heredocs = []
                continue
            if mode is HashMode.PYTHON and text.startswith(PYTHON_TRIPLES, index):
                index = skip_until(text, index + 3, end, text[index:index + 3])
                continue
            if char in "'\"":
                literal = mode is not HashMode.SH or char == "\""
                index = skip_quoted(text, index, end, char, escapes=literal, multiline=mode is not HashMode.PYTHON)
                continue
            if char == "\\":
                index += 2
                continue
            if mode is HashMode.RUBY and char == "?" and text.startswith("#", index + 1):
                index += 2
                continue
            if char == "<" and mode is not HashMode.PYTHON:
                heredoc = (SH_HEREDOC if mode is HashMode.SH else RUBY_HEREDOC).match(text, index)
                if heredoc and not (mode is HashMode.SH and index > 0 and text[index - 1] == "<"):
                    heredocs.append(heredoc.group(2))
                    index = heredoc.end()
                    continue
            if char == "#" and (mode is not HashMode.SH or index == 0 or text[index - 1] in SH_COMMENT_AFTER):
                stop = line_end(text, index, end)
                self.add(index, stop, Style.LINE)
                index = stop
                continue
            index += 1
        return self.comments

    def skip_heredocs(self, index, words):
        text = self.text
        for word in words:
            while index < len(text):
                stop = line_end(text, index, len(text))
                line = text[index:stop]
                index = stop + 1
                if line.strip() == word:
                    break
        return index


class DashLexer(Collector):
    def __init__(self, text, lua):
        super().__init__(text)
        self.lua = lua

    def run(self):
        text, lua = self.text, self.lua
        end = len(text)
        index = 0
        while index < end:
            char = text[index]
            if text.startswith("--", index):
                long_open = LUA_LONG_OPEN.match(text, index + 2) if lua else None
                if long_open:
                    stop = skip_until(text, long_open.end(), end, "]" + long_open.group(1) + "]")
                    self.add(index, stop, Style.BLOCK)
                else:
                    stop = line_end(text, index, end)
                    self.add(index, stop, Style.LINE)
                index = stop
                continue
            if not lua and text.startswith("/*", index):
                stop = skip_until(text, index + 2, end, BLOCK_CLOSE)
                self.add(index, stop, Style.BLOCK)
                index = stop
                continue
            if lua and char == "[":
                long_open = LUA_LONG_OPEN.match(text, index)
                if long_open:
                    index = skip_until(text, long_open.end(), end, "]" + long_open.group(1) + "]")
                    continue
            if char in "'\"":
                index = skip_quoted(text, index, end, char, escapes=lua, multiline=not lua)
                continue
            index += 1
        return self.comments


def python_comments(text):
    try:
        return [Comment(token.start[0], token.end[0], token.string, Style.LINE)
                for token in tokenize.generate_tokens(io.StringIO(text).readline) if token.type == tokenize.COMMENT]
    except (tokenize.TokenError, SyntaxError):
        return None


def parse_python(text):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def docstring_nodes(tree):
    owners = [tree] + [node for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    found = []
    for owner in owners:
        first = owner.body[0] if owner.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            found.append(first)
    return found


def docstring_finding(node):
    text = node.value.value
    return Finding(node.lineno, text, DOCSTRING_KEY + " ".join(text.split()))


def multi_line_docstrings(text):
    tree = parse_python(text)
    if tree is None:
        return []
    return [node for node in docstring_nodes(tree) if node.end_lineno > node.lineno]


def unseen_docstrings(before, after):
    if parse_python(before) is not None:
        return []
    return [docstring_finding(node) for node in multi_line_docstrings(after)
            if ast.get_source_segment(after, node) not in before]


def hash_mode(suffix, text):
    if suffix in RUBY_SUFFIXES:
        return HashMode.RUBY
    if suffix is None and any(mark in first_line(text) for mark in RUBY_SHEBANG_MARKS):
        return HashMode.RUBY
    return HashMode.SH


def raw_comments(text, language, suffix):
    match language:
        case Language.PYTHON:
            comments = python_comments(text)
            return HashLexer(text, HashMode.PYTHON).run() if comments is None else comments
        case Language.C_LIKE:
            return CLikeLexer(text, suffix).run()
        case Language.HASH:
            return HashLexer(text, hash_mode(suffix, text)).run()
        case Language.DASH:
            return DashLexer(text, suffix == LUA_SUFFIX).run()
    return []


def body_of(text):
    lines = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        for marker in COMMENT_MARKERS:
            if stripped.startswith(marker):
                stripped = stripped[len(marker):]
            if stripped.endswith(marker) and marker in CLOSING_MARKERS:
                stripped = stripped[:-len(marker)]
        lines.append(stripped.lstrip("/*!-# \t").strip())
    return " ".join(" ".join(lines).split())


def is_directive(comment):
    body = body_of(comment.text)
    return any(pattern.match(body) for pattern in DIRECTIVES)


def is_preamble(comment, language):
    if comment.line == 1 and comment.text.startswith(SHEBANG):
        return True
    return language is Language.PYTHON and comment.line in COOKIE_LINES and bool(CODING_COOKIE.match(comment.text))


def shown(text):
    line = " ".join(first_line(text.strip()).split())
    return line if len(line) <= MAX_SHOWN_CHARS else line[:MAX_SHOWN_CHARS - 1] + "…"


def findings(text, language, suffix, with_docstrings=True):
    comments = [comment for comment in raw_comments(text, language, suffix)
                if not is_directive(comment) and not is_preamble(comment, language)]
    result = []
    run = []

    def close_run():
        if len(run) > 1:
            result.append(Finding(run[0].line, run[0].text, DOC_KEY + " ".join(body_of(c.text) for c in run)))
        run.clear()

    for comment in comments:
        if comment.style is Style.DOC_LINE:
            if run and comment.line != run[-1].line + 1:
                close_run()
            run.append(comment)
            continue
        close_run()
        if comment.style is Style.DOC_BLOCK:
            if comment.end_line > comment.line:
                result.append(Finding(comment.line, comment.text, DOC_KEY + body_of(comment.text)))
            continue
        result.append(Finding(comment.line, comment.text, body_of(comment.text)))
    close_run()
    if language is Language.PYTHON and with_docstrings:
        result += [docstring_finding(node) for node in multi_line_docstrings(text)]
    return sorted(result, key=lambda finding: finding.line)


def added(before, after):
    budget = Counter(finding.key for finding in before)
    fresh = []
    for finding in after:
        if budget[finding.key] > 0:
            budget[finding.key] -= 1
        else:
            fresh.append(finding)
    return fresh


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def python_kernel(notebook):
    metadata = notebook.get("metadata")
    if not isinstance(metadata, dict):
        return True
    for section, key in (("kernelspec", "language"), ("language_info", "name")):
        value = metadata.get(section, {}).get(key) if isinstance(metadata.get(section), dict) else None
        if isinstance(value, str) and value.lower() != PYTHON_KERNEL:
            return False
    return True


def cell_source(cell):
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return source if isinstance(source, str) else ""


def notebook_code(text):
    if not text.strip():
        return ""
    try:
        notebook = json.loads(text)
    except ValueError:
        return None
    if not isinstance(notebook, dict) or not python_kernel(notebook):
        return None
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return ""
    return "\n".join(cell_source(cell) for cell in cells
                     if isinstance(cell, dict) and cell.get("cell_type") == CODE_CELL)


def find_cell(cells, cell_id):
    for cell in cells:
        if isinstance(cell, dict) and cell.get("id") == cell_id:
            return cell
    index = CELL_INDEX.match(cell_id) if isinstance(cell_id, str) else None
    if index and int(index.group(1)) < len(cells) and isinstance(cells[int(index.group(1))], dict):
        return cells[int(index.group(1))]
    return None


def notebook_change(data):
    path, new_source = data.get("notebook_path"), data.get("new_source")
    if not isinstance(path, str) or not isinstance(new_source, str):
        return None
    mode = data.get("edit_mode") or CellEdit.REPLACE.value
    if mode == CellEdit.DELETE.value:
        return None
    with open(path, encoding="utf-8") as handle:
        notebook = json.load(handle)
    if not isinstance(notebook, dict) or not python_kernel(notebook):
        return None
    cells = notebook.get("cells") if isinstance(notebook.get("cells"), list) else []
    cell = None if mode == CellEdit.INSERT.value else find_cell(cells, data.get("cell_id"))
    cell_type = data.get("cell_type") or (cell.get("cell_type") if cell else None) or CODE_CELL
    if cell_type != CODE_CELL:
        return None
    return Change(Language.PYTHON, PYTHON_SUFFIX, cell_source(cell) if cell else "", new_source)


def edited(before, data):
    old, new = data.get("old_string"), data.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str) or old not in before:
        return None
    return before.replace(old, new) if data.get("replace_all") is True else before.replace(old, new, 1)


def multi_edited(before, edits):
    if not isinstance(edits, list) or not edits:
        return None
    after = before
    for step in edits:
        after = edited(after, step) if isinstance(step, dict) else None
        if after is None:
            return None
    return after


def file_change(tool, data):
    path = data.get("file_path")
    if not isinstance(path, str) or not path:
        return None
    before = read_text(path)
    match tool:
        case Tool.WRITE:
            after = data.get("content")
        case Tool.EDIT:
            after = edited(before, data)
        case Tool.MULTI_EDIT:
            after = multi_edited(before, data.get("edits"))
        case _:
            after = None
    if not isinstance(after, str):
        return None
    suffix = suffix_of(path)
    if suffix == NOTEBOOK_SUFFIX:
        before, after = notebook_code(before) or "", notebook_code(after)
        if after is None:
            return None
    language = language_of(path, after) or language_of(path, before)
    if language is None:
        return None
    return Change(language, suffix, before, after)


def change_of(tool_name, data):
    tool = next((member for member in Tool if member.value == tool_name), None)
    if tool is None:
        return None
    if tool is Tool.NOTEBOOK_EDIT:
        return notebook_change(data)
    return file_change(tool, data)


def deny(violations):
    listed = "; ".join(f"L{finding.line}: {shown(finding.text)}" for finding in violations[:MAX_REPORTED])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON_HEAD + listed + "." + REASON_TAIL,
        }
    }))


def hook():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
            return
        change = change_of(payload.get("tool_name"), payload["tool_input"])
        if change is None:
            return
        with_docstrings = change.language is Language.PYTHON and all(
            parse_python(text) is not None for text in (change.before, change.after))
        violations = added(findings(change.before, change.language, change.suffix, with_docstrings),
                           findings(change.after, change.language, change.suffix, with_docstrings))
        if change.language is Language.PYTHON:
            violations = sorted(violations + unseen_docstrings(change.before, change.after),
                                key=lambda finding: finding.line)
        if violations:
            deny(violations)
    except Exception:
        return


def scan(arguments):
    raw = RAW_FLAG in arguments
    for path in (argument for argument in arguments if argument not in (SCAN_FLAG, RAW_FLAG)):
        text = read_text(path)
        suffix = suffix_of(path)
        if suffix == NOTEBOOK_SUFFIX:
            text = notebook_code(text)
            if text is None:
                continue
        language = language_of(path, text)
        if language is None:
            continue
        items = raw_comments(text, language, suffix) if raw else findings(text, language, suffix)
        for item in items:
            print(f"{path}:{item.line}: {' '.join(first_line(item.text.strip()).split())}")


def main():
    if SCAN_FLAG in sys.argv[1:]:
        scan(sys.argv[1:])
    else:
        hook()


if __name__ == "__main__":
    main()
