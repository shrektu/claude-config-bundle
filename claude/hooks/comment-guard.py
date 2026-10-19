#!/usr/bin/env python3
import ast
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import NoReturn

JsonObject = dict[str, object]

HASH_EXTS = (".py", ".pyi", ".sh", ".bash", ".zsh", ".rb")
SLASH_EXTS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".cs",
    ".cpp",
    ".hpp",
    ".cc",
    ".hh",
)
DASH_EXTS = (".sql", ".lua")
STYLE_EXTS = (".css", ".scss")
LINE_MARKERS: dict[str, tuple[str, ...]] = {
    **dict.fromkeys(HASH_EXTS, ("#",)),
    **dict.fromkeys(SLASH_EXTS, ("//",)),
    **dict.fromkeys(DASH_EXTS, ("--",)),
    **dict.fromkeys(STYLE_EXTS, ()),
}
BLOCK_LANGS = frozenset((*SLASH_EXTS, ".sql", *STYLE_EXTS))
QUOTES = ("'", '"', "`")
BLOCK_OPEN = "/*"
BLOCK_CLOSE = "*/"
HEREDOC_START = re.compile(
    r"\b(?:cat|tee)\b[^\n|;&]*?(?:>>?\s*|\s)"
    r"(?P<path>[^\s>|;&]+\.[A-Za-z0-9]+)"
    r"[^\n]*?<<-?\s*(?P<q>['\"]?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=q)",
)

DIRECTIVE = re.compile(
    r"(noqa|type:\s*ignore|pragma|eslint-disable|eslint-enable|"
    r"ts-expect-error|ts-ignore|@ts-|SPDX|"
    r"prettier-ignore|biome-ignore|clang-format|istanbul ignore|c8 ignore|"
    r"v8 ignore|coverage:|"
    r"mypy:|ruff:|flake8:|pylint:|shellcheck|coding[:=]|-\*-|#!|deno-lint|"
    r"golangci|nolint|"
    r"#\s*(include|define|ifdef|ifndef|endif|pragma|else|elif|undef|error|"
    r"warning))",
    re.IGNORECASE,
)

REASON = (
    "generated code carries no comments (zero, not 'few') — this edit adds "
    "{n}:\n{samples}\n"
    "A comment is a signal that the code does not say what it means. Fix "
    "the code instead: rename the variable or function to the sentence you "
    "were about to write, extract the block into a named function, or "
    "replace the magic literal with a named constant. A section banner is a "
    "function that wants to exist; a narrating line is a name that is "
    "missing; a commented-out block is deleted code.\n"
    "Tool directives (noqa, type: ignore, eslint-disable, SPDX, shebangs) "
    "are not comments and pass. "
    "Docstrings are governed by the docstring rule.\n"
    "If a line genuinely cannot be expressed in code (hardware quirk, "
    "protocol constraint), that is a decision for the orchestrator, not the "
    "implementer: report it instead of writing it. "
    "Escape hatch: CLAUDE_COMMENT_GUARD=off."
)
DOCSTRING_REASON = (
    "docstring rule — this edit adds {n} violation(s):\n{samples}\n"
    "No module docstrings. A class or function docstring is one line and "
    "one sentence, at most {limit} characters, as short as possible, "
    "stating what it does — arguments, returns and raises are not listed.\n"
    "Escape hatch: CLAUDE_COMMENT_GUARD=off."
)
SHELL_NOTE = (
    "\nThis file is being written from the shell; the rule is about the "
    "code that lands in the file, not the tool that puts it there."
)
MODULE_VIOLATION = "module docstring — delete it"
TOO_MANY_LINES = "docstring spans several lines — make it one line"
TOO_MANY_SENTENCES = "docstring has more than one sentence — keep one"
TOO_LONG = "docstring is {length} characters — at most {limit}"
DOCSTRING_EXT = ".py"
RUFF_CONFIG_FILES = ("ruff.toml", ".ruff.toml")
PYPROJECT = "pyproject.toml"
SELECT_KEYS = ("select", "extend-select")
IGNORE_KEYS = ("ignore", "extend-ignore")
MODULE_DOCSTRING_SELECTORS = frozenset(("ALL", "D", "D1", "D10", "D100"))
MODULE_DOCSTRING_IGNORES = frozenset(("D", "D1", "D10", "D100"))
MAX_DOCSTRING_LENGTH = 72
SENTENCE_END = re.compile(r"(?<!e\.g)(?<!i\.e)[.!?]\s+\S", re.IGNORECASE)
DEFINITION_NODES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
OFF_VALUES = {"off", "0", "false", "no"}
ESCAPE_VARIABLE = "CLAUDE_COMMENT_GUARD"
GUARDED_TOOLS = ("Edit", "Write", "NotebookEdit", "Bash")
WRITE_TOOL = "Write"
BASH_TOOL = "Bash"
MAX_SAMPLES = 4
SAMPLE_LEN = 90
PARSE_FAILURES = (SyntaxError, ValueError)
READ_FAILURES = (OSError, UnicodeDecodeError)
HOOK_FAILURES = (
    ValueError,
    OSError,
    TypeError,
    AttributeError,
    KeyError,
    RecursionError,
)


def deny(reason: str) -> NoReturn:
    """Print the PreToolUse deny decision and exit."""
    decision = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"comment-guard: {reason}",
        },
    }
    sys.stdout.write(json.dumps(decision) + "\n")
    sys.exit(0)


def comment_index(
    line: str,
    markers: tuple[str, ...],
    *,
    block: bool,
) -> int:
    """Return where a comment starts on the line, or -1."""
    i = 0
    quote = None
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in QUOTES:
            quote = ch
            i += 1
            continue
        if any(line.startswith(marker, i) for marker in markers):
            return i
        if block and line.startswith(BLOCK_OPEN, i):
            return i
        i += 1
    return -1


def is_added_comment(
    stripped: str,
    comment: str,
    old_lines: set[str],
) -> bool:
    """Tell whether a comment line is new and not a tool directive."""
    if stripped in old_lines or comment in old_lines:
        return False
    return DIRECTIVE.search(stripped) is None


def added_comments(new_text: str, old_text: str, ext: str) -> list[str]:
    """Return the comments new_text adds compared with old_text."""
    markers = LINE_MARKERS.get(ext, ())
    block = ext in BLOCK_LANGS
    if not markers and not block:
        return []
    old_lines = {line.strip() for line in old_text.splitlines()}
    found: list[str] = []
    in_block = False
    for raw in new_text.splitlines():
        stripped = raw.strip()
        if in_block:
            comment = stripped
            in_block = BLOCK_CLOSE not in stripped
        elif stripped:
            index = comment_index(raw, markers, block=block)
            if index < 0:
                continue
            comment = raw[index:].strip()
            in_block = (
                block
                and comment.startswith(BLOCK_OPEN)
                and BLOCK_CLOSE not in comment
            )
        else:
            continue
        if is_added_comment(stripped, comment, old_lines):
            found.append(comment)
    return found


def heredoc_writes(command: str) -> list[tuple[str, str]]:
    """Return (path, body) of every cat or tee heredoc writing a file."""
    writes = []
    lines = command.splitlines()
    index = 0
    while index < len(lines):
        match = HEREDOC_START.search(lines[index])
        index += 1
        if not match:
            continue
        delim = match.group("delim")
        body = []
        while index < len(lines) and lines[index].strip() != delim:
            body.append(lines[index])
            index += 1
        index += 1
        writes.append((match.group("path"), "\n".join(body)))
    return writes


def sample_block(found: list[str]) -> str:
    """Format the first MAX_SAMPLES findings and count the rest."""
    shown = "".join(f"  {line[:SAMPLE_LEN]}\n" for line in found[:MAX_SAMPLES])
    if len(found) > MAX_SAMPLES:
        shown += f"  … and {len(found) - MAX_SAMPLES} more\n"
    return shown.rstrip()


def report(found: list[str], extra: str = "") -> NoReturn:
    """Deny the edit because it adds comments."""
    reason = REASON.format(n=len(found), samples=sample_block(found))
    deny(reason + extra)


def report_docstrings(found: list[str], extra: str = "") -> NoReturn:
    """Deny the edit because it breaks the docstring rule."""
    reason = DOCSTRING_REASON.format(
        n=len(found),
        samples=sample_block(found),
        limit=MAX_DOCSTRING_LENGTH,
    )
    deny(reason + extra)


def parse_source(text: str) -> ast.Module | None:
    """Parse Python source, or return None when it is invalid."""
    try:
        return ast.parse(text)
    except PARSE_FAILURES:
        return None


def definition_docstrings(tree: ast.Module) -> list[tuple[int, str, str]]:
    """Return (line, name, docstring) of each documented definition."""
    return [
        (node.body[0].lineno, node.name, docstring)
        for node in ast.walk(tree)
        if isinstance(node, DEFINITION_NODES)
        and (docstring := ast.get_docstring(node, clean=True)) is not None
    ]


def docstring_shape_problem(docstring: str) -> str | None:
    """Return why a docstring breaks the shape rule, or None."""
    if "\n" in docstring:
        return TOO_MANY_LINES
    if SENTENCE_END.search(docstring):
        return TOO_MANY_SENTENCES
    if len(docstring) > MAX_DOCSTRING_LENGTH:
        return TOO_LONG.format(
            length=len(docstring),
            limit=MAX_DOCSTRING_LENGTH,
        )
    return None


def added_docstring_violations(
    new_text: str,
    old_text: str,
    *,
    module_docstrings_required: bool = False,
) -> list[str]:
    """Return the docstring-rule violations new_text adds."""
    new_tree = parse_source(new_text)
    if new_tree is None:
        return []
    old_tree = parse_source(old_text) or ast.Module(body=[], type_ignores=[])
    found = []
    new_module = ast.get_docstring(new_tree, clean=True)
    old_module = ast.get_docstring(old_tree, clean=True)
    module_added = new_module is not None and new_module != old_module
    if module_added and not module_docstrings_required:
        found.append(MODULE_VIOLATION)
    carried = {doc for _, _, doc in definition_docstrings(old_tree)}
    for line, name, docstring in definition_docstrings(new_tree):
        if docstring in carried:
            continue
        problem = docstring_shape_problem(docstring)
        if problem:
            found.append(f"line {line} `{name}`: {problem}")
    return found


def read_toml(path: Path) -> dict[str, object]:
    """Return the parsed TOML file, or an empty table when unusable."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}


def ruff_table_of(directory: Path) -> dict[str, object] | None:
    """Return the ruff table of the directory's own config, if any."""
    for name in RUFF_CONFIG_FILES:
        if (directory / name).is_file():
            return read_toml(directory / name)
    tools = read_toml(directory / PYPROJECT).get("tool")
    table = tools.get("ruff") if isinstance(tools, dict) else None
    return table if isinstance(table, dict) else None


def listed_rules(table: dict[str, object], keys: tuple[str, ...]) -> set[str]:
    """Return the rules a ruff table lists under keys, also under lint."""
    lint = table.get("lint")
    tables = [table, lint] if isinstance(lint, dict) else [table]
    listed = [scope.get(key) for scope in tables for key in keys]
    return {
        str(rule)
        for rules in listed
        if isinstance(rules, list)
        for rule in rules
    }


def requires_module_docstrings(path: Path) -> bool:
    """Return whether the repo ruff config of the file requires D100."""
    for directory in path.resolve().parents:
        table = ruff_table_of(directory)
        if table is not None:
            return not MODULE_DOCSTRING_IGNORES.intersection(
                listed_rules(table, IGNORE_KEYS)
            ) and bool(
                MODULE_DOCSTRING_SELECTORS.intersection(
                    listed_rules(table, SELECT_KEYS)
                )
            )
        if (directory / ".git").exists():
            return False
    return False


def read_source(path: Path) -> str | None:
    """Return the text of the file, or None when it cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except READ_FAILURES:
        return None


def edited_text(tool_input: JsonObject, old_text: str) -> str | None:
    """Return the file text after the Edit applies, or None."""
    old_string = tool_input.get("old_string")
    new_string = tool_input.get("new_string")
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return None
    if not old_string:
        return None
    count = -1 if tool_input.get("replace_all") is True else 1
    return old_text.replace(old_string, new_string, count)


def docstring_violations_of_tool(
    tool: str,
    tool_input: JsonObject,
    path: Path,
) -> list[str]:
    """Return the docstring violations a Write or Edit adds."""
    on_disk = read_source(path)
    if tool == WRITE_TOOL:
        content = tool_input.get("content")
        if not isinstance(content, str):
            return []
        return added_docstring_violations(
            content,
            on_disk or "",
            module_docstrings_required=requires_module_docstrings(path),
        )
    if on_disk is None:
        return []
    new_text = edited_text(tool_input, on_disk)
    if new_text is None:
        return []
    return added_docstring_violations(
        new_text,
        on_disk,
        module_docstrings_required=requires_module_docstrings(path),
    )


def first_truthy(data: JsonObject, *keys: str) -> object:
    """Return the first truthy value among the keys, else an empty string."""
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return ""


def check_bash(tool_input: JsonObject) -> None:
    """Judge every code file the shell command writes through a heredoc."""
    command = tool_input.get("command")
    if not isinstance(command, str) or not command:
        return
    for target, body in heredoc_writes(command):
        ext = Path(target).suffix.lower()
        if ext not in LINE_MARKERS:
            continue
        found = added_comments(body, "", ext)
        if found:
            report(found, extra=SHELL_NOTE)
        if ext == DOCSTRING_EXT:
            on_disk = read_source(Path(target)) or ""
            violations = added_docstring_violations(
                body,
                on_disk,
                module_docstrings_required=requires_module_docstrings(
                    Path(target)
                ),
            )
            if violations:
                report_docstrings(violations, extra=SHELL_NOTE)


def check_file_edit(tool: str, tool_input: JsonObject) -> None:
    """Judge the comments and docstrings a file edit adds."""
    path = first_truthy(tool_input, "file_path", "notebook_path")
    if not isinstance(path, str):
        return
    ext = Path(path).suffix.lower()
    if ext not in LINE_MARKERS:
        return
    new_text = first_truthy(tool_input, "new_string", "content", "new_source")
    old_text = first_truthy(tool_input, "old_string", "old_source")
    if not isinstance(new_text, str) or not isinstance(old_text, str):
        return
    if not new_text:
        return
    found = added_comments(new_text, old_text, ext)
    if found:
        report(found)
    if ext == DOCSTRING_EXT:
        violations = docstring_violations_of_tool(tool, tool_input, Path(path))
        if violations:
            report_docstrings(violations)


def check(payload: object) -> None:
    """Judge a PreToolUse payload and deny it when it breaks a rule."""
    if not isinstance(payload, dict):
        return
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or tool not in GUARDED_TOOLS:
        return
    if os.environ.get(ESCAPE_VARIABLE, "").strip().lower() in OFF_VALUES:
        return
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    if tool == BASH_TOOL:
        check_bash(tool_input)
    else:
        check_file_edit(tool, tool_input)


def main() -> None:
    """Read the hook payload from stdin and judge it, failing open."""
    try:
        check(json.load(sys.stdin))
    except HOOK_FAILURES:
        return


if __name__ == "__main__":
    main()
