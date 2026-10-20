import posixpath
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from re import Match
from typing import NamedTuple

from agy_workspace import DECODE_ERRORS, TEXT_ENCODING, GrepHit

MAX_CONTEXT_NAMES = 30
MAX_SITES_PER_NAME = 8
MAX_CALL_SITES = 80
MAX_SITE_LINE_CHARS = 160
MAX_CALL_SITES_BYTES = 12_000
MAX_FILE_LIST_BYTES = 40_000
MIN_NAME_LENGTH = 3
NO_SITES_PREFIX = "No call sites in unchanged files: "
DIFF_HEADER = "diff --git "
RENAME_FROM = "rename from "
RENAME_TO = "rename to "
OLD_IMAGE = "--- "
NEW_IMAGE = "+++ "
NO_FILE = "/dev/null"
OLD_PREFIX = "a/"
NEW_PREFIX = "b/"
PATH_SEPARATOR = " b/"
HEADER_OVERHEAD = len(OLD_PREFIX) + len(PATH_SEPARATOR)
ADDED = "+"
REMOVED = "-"
CHANGED_MARKERS = (ADDED, REMOVED)
QUOTE = '"'
OCTAL_DIGITS = 3
OCTAL_BASE = 8
QUOTED_PATH_PATTERN = r'"(?:[^"\\]|\\.)*"'
QUOTED_PAIR = re.compile(rf"^({QUOTED_PATH_PATTERN}) ({QUOTED_PATH_PATTERN})$")
ESCAPE = re.compile(rb"\\([0-7]{3}|.)", re.DOTALL)
SIMPLE_ESCAPES = {
    b"a": b"\a",
    b"b": b"\b",
    b"f": b"\f",
    b"n": b"\n",
    b"r": b"\r",
    b"t": b"\t",
    b"v": b"\v",
}
NO_NEWLINE_MARKER = "\\"
CONTINUATION_STARTS = ("{", ")", "]")
NAME_SEPARATOR = "::"
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MODIFIERS = (
    r"(?:(?:export|default|async|pub(?:\([^)]*\))?|static|public|private"
    r"|protected|abstract|final|extern|unsafe|override|virtual|inline)\s+)*"
)
KEYWORD_DEFINITION = re.compile(
    rf"^\s*{MODIFIERS}"
    r"(?:def|class|function|func|fn|struct|interface|enum|trait|type)\b"
    r"\s*\*?\s*(?:\([^)]*\)\s*)?([A-Za-z_][\w$]*)"
)
ASSIGNED_FUNCTION = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::[^=]+)?=\s*(?:async\s+)?(?:function\b|\(|<)"
)
COLUMN_ZERO_FUNCTION = re.compile(
    r"^[A-Za-z_][\w:<>,~*&\s]*?[\s*&]((?:\w+::)*~?\w+)\s*\("
    r"(?:[^;{}]*|[^;{}]*\)(?:\s+(?:const|noexcept))*\s*(?:\{.*)?)$"
)
INDENTED_METHOD = re.compile(
    r"^\s+(?:[\w<>\[\],:.*&?\s]+\s)?([A-Za-z_$][\w$]*)\s*(?:<[^()]*>)?"
    r"\s*\([^;]*\)\s*"
    r"(?:(?:const|override|final|noexcept)\s*|throws\s+[\w.,\s]+?\s*)*"
    r"(?::\s*[^{;]+)?\{\s*$"
)
DEFINITION_PATTERNS = (
    KEYWORD_DEFINITION,
    ASSIGNED_FUNCTION,
    COLUMN_ZERO_FUNCTION,
    INDENTED_METHOD,
)
IGNORED_NAMES = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "else",
        "sizeof",
        "elif",
        "with",
        "class",
        "struct",
        "enum",
        "import",
        "from",
        "include",
        "define",
        "assert",
        "function",
        "new",
        "delete",
        "typeof",
    }
)


class Hunk(NamedTuple):
    """The lines of one diff hunk and where it starts in the new file."""

    new_start: int
    lines: tuple[str, ...]


@dataclass(slots=True)
class FileDiff:
    """The paths and hunks of one file of a unified diff."""

    old_path: str | None
    new_path: str | None
    hunks: list[Hunk] = field(default_factory=list)


class CallSites(NamedTuple):
    """The caller lines found for the changed names."""

    lines: list[str]
    without_sites: list[str]

    def all_lines(self) -> list[str]:
        """Return the section lines, the names without callers last."""
        if not self.without_sites:
            return self.lines
        missing = NO_SITES_PREFIX + ", ".join(self.without_sites)
        return [*self.lines, missing]


def decode_escape(match: re.Match[bytes]) -> bytes:
    """Decode one backslash escape of a C-quoted path."""
    token = match[1]
    if len(token) == OCTAL_DIGITS:
        return bytes([int(token, OCTAL_BASE)])
    return SIMPLE_ESCAPES.get(token, token)


def unquote_path(text: str) -> str:
    """Decode a path that git C-quoted, leave other paths alone."""
    if len(text) < len(QUOTE) * 2 or not (
        text.startswith(QUOTE) and text.endswith(QUOTE)
    ):
        return text
    raw = text[1:-1].encode(TEXT_ENCODING)
    decoded = ESCAPE.sub(decode_escape, raw)
    return decoded.decode(TEXT_ENCODING, DECODE_ERRORS)


def header_paths(line: str) -> tuple[str, str]:
    """Return the old and new path of a diff --git line."""
    rest = line.removeprefix(DIFF_HEADER)
    if quoted := QUOTED_PAIR.match(rest):
        old, new = (unquote_path(quoted[index]) for index in (1, 2))
        return old.removeprefix(OLD_PREFIX), new.removeprefix(NEW_PREFIX)
    length, remainder = divmod(len(rest) - HEADER_OVERHEAD, 2)
    if not remainder and rest[2 : 2 + length] == rest[-length:]:
        return rest[2 : 2 + length], rest[-length:]
    old, _, new = rest.partition(PATH_SEPARATOR)
    return old.removeprefix(OLD_PREFIX), new


def image_path(line: str, prefix: str) -> str | None:
    """Return the path of a --- or +++ line, None for /dev/null."""
    path = line[len(OLD_IMAGE) :].split("\t", maxsplit=1)[0]
    return None if path == NO_FILE else unquote_path(path).removeprefix(prefix)


def read_hunk(
    lines: Sequence[str], start: int, header: Match[str]
) -> tuple[Hunk, int]:
    """Read the body of a hunk and return it with the next line index."""
    old_left = 1 if header[1] is None else int(header[1])
    new_left = 1 if header[3] is None else int(header[3])
    body: list[str] = []
    index = start
    while index < len(lines) and (old_left > 0 or new_left > 0):
        line = lines[index]
        index += 1
        marker = line[:1]
        if marker == NO_NEWLINE_MARKER:
            continue
        body.append(line)
        if marker != ADDED:
            old_left -= 1
        if marker != REMOVED:
            new_left -= 1
    return Hunk(int(header[2]), tuple(body)), index


def apply_header_line(current: FileDiff, line: str) -> None:
    """Update the paths of a file from a header line of its diff."""
    if line.startswith(RENAME_FROM):
        current.old_path = unquote_path(line.removeprefix(RENAME_FROM))
    elif line.startswith(RENAME_TO):
        current.new_path = unquote_path(line.removeprefix(RENAME_TO))
    elif line.startswith(OLD_IMAGE):
        current.old_path = image_path(line, OLD_PREFIX)
    elif line.startswith(NEW_IMAGE):
        current.new_path = image_path(line, NEW_PREFIX)


def parse_diff(diff: str) -> list[FileDiff]:
    """Split a unified diff into its files and hunks."""
    files: list[FileDiff] = []
    lines = diff.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith(DIFF_HEADER):
            files.append(FileDiff(*header_paths(line)))
        elif files and (header := HUNK_HEADER.match(line)):
            hunk, index = read_hunk(lines, index, header)
            files[-1].hunks.append(hunk)
        elif files:
            apply_header_line(files[-1], line)
    return files


def changed_paths(diff: str) -> frozenset[str]:
    """Return every old and new path a diff touches."""
    return frozenset(
        path
        for file in parse_diff(diff)
        for path in (file.old_path, file.new_path)
        if path is not None
    )


def usable_name(name: str) -> str | None:
    """Return the last segment of a name when it is worth searching."""
    segment = name.rsplit(NAME_SEPARATOR, 1)[-1]
    dunder = segment.startswith("__") and segment.endswith("__")
    if len(segment) < MIN_NAME_LENGTH or dunder or segment in IGNORED_NAMES:
        return None
    return segment


def definition_name(line: str) -> str | None:
    """Return the name a definition line defines, if it is one."""
    for pattern in DEFINITION_PATTERNS:
        match = pattern.match(line)
        if match and (name := usable_name(match[1])):
            return name
    return None


def indentation(line: str) -> int:
    """Return the number of leading blanks of a line."""
    return len(line) - len(line.lstrip(" \t"))


def enclosing_names(
    image: Sequence[str], start_line: int, indent: int
) -> Iterator[str]:
    """Yield the definitions above a line that enclose it."""
    limit = indent
    for text in reversed(image[: start_line - 1]):
        if limit == 0:
            return
        if not text.strip():
            continue
        depth = indentation(text)
        name = definition_name(text) if depth < limit else None
        if name:
            limit = depth
            yield name
        elif depth == 0 and not text.startswith(CONTINUATION_STARTS):
            return


def hunk_names(hunk: Hunk, image: Sequence[str]) -> Iterator[str]:
    """Yield the names defined or enclosing the changes of a hunk."""
    new_line = hunk.new_start
    scanned = False
    for line in hunk.lines:
        marker, content = line[:1], line[1:]
        if marker not in CHANGED_MARKERS:
            scanned = False
        else:
            if not scanned and content.strip():
                yield from enclosing_names(
                    image, new_line, indentation(content)
                )
                scanned = True
            if name := definition_name(content):
                yield name
        if marker != REMOVED:
            new_line += 1


def changed_names(
    diff: str, read_post_image: Callable[[str], str | None]
) -> list[str]:
    """Return the names a diff defines or changes, first seen first."""
    names: dict[str, None] = {}
    for file in parse_diff(diff):
        text = read_post_image(file.new_path) if file.new_path else None
        image = (text or "").splitlines()
        for hunk in file.hunks:
            names.update(dict.fromkeys(hunk_names(hunk, image)))
    return list(names)[:MAX_CONTEXT_NAMES]


def site_line(hit: GrepHit) -> str:
    """Format a call site, cutting only the text of the line."""
    text = hit.text.strip()[:MAX_SITE_LINE_CHARS]
    return f"  {hit.path}:{hit.line}: {text}"


def select_call_sites(
    names: Sequence[str],
    hits: Sequence[GrepHit],
    excluded_paths: frozenset[str],
) -> CallSites:
    """Pick the capped caller lines of each name in unchanged files."""
    remaining = MAX_CALL_SITES
    lines: list[str] = []
    without_sites: list[str] = []
    for name in names:
        sites = [
            hit
            for hit in hits
            if hit.name == name and hit.path not in excluded_paths
        ]
        if not sites:
            without_sites.append(name)
            continue
        chosen = sites[: min(MAX_SITES_PER_NAME, remaining)]
        if chosen:
            lines.append(f"{name}:")
            lines.extend(site_line(hit) for hit in chosen)
        remaining -= len(chosen)
    return CallSites(lines, without_sites)


def ordered_paths(paths: Sequence[str], changed: frozenset[str]) -> list[str]:
    """Sort paths, those next to changed files first."""
    changed_dirs = {posixpath.dirname(path) for path in changed}
    near = [path for path in paths if posixpath.dirname(path) in changed_dirs]
    far = [
        path for path in paths if posixpath.dirname(path) not in changed_dirs
    ]
    return [*sorted(near), *sorted(far)]


def byte_size(text: str) -> int:
    """Return the UTF-8 size of a text."""
    return len(text.encode(TEXT_ENCODING))


def fit_lines(
    header: str,
    lines: Sequence[str],
    budget_bytes: int,
    more_line: Callable[[int], str],
) -> str:
    """Join a header and lines within a byte budget, marking the cut."""
    used = byte_size(header)
    sizes = [byte_size(line) + 1 for line in lines]
    if lines and used + sum(sizes) <= budget_bytes:
        return "\n".join([header, *lines])
    kept = 0
    for count, size in enumerate(sizes, start=1):
        used += size
        if used > budget_bytes:
            break
        if used + byte_size(more_line(len(lines) - count)) + 1 <= budget_bytes:
            kept = count
    if not kept:
        return ""
    more = more_line(len(lines) - kept)
    return "\n".join([header, *lines[:kept], more])
