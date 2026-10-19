#!/usr/bin/env python3
"""Standards gate: run lint-strict before a commit and before a stop.

PreToolUse on Bash denies a ``git commit`` whose recorded changes carry
norm violations; SubagentStop sends an implementer back to work while
lint-strict still reports violations, at most ``MAX_BLOCKS`` times.
"""

import contextlib
import functools
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

LINT_BIN_ENV = "LINT_STRICT_BIN"
DEFAULT_LINT_BIN = "~/.claude/bin/lint-strict"
LINT_TIMEOUT_ENV = "LINT_STRICT_TIMEOUT"
DEFAULT_LINT_TIMEOUT = 420.0
GIT_TIMEOUT = 10
EXIT_PASS = 0
EXIT_VIOLATIONS = 1
EXIT_BLOCK = 2
MAX_BLOCKS = 3
MAX_REPORT_LINES = 60
MAX_SHELL_DEPTH = 3
MAX_LINE_BYTES = 2_000_000
STATE_ID_LIMIT = 120
STATE_PREFIX = "standards-gate-"
UNKNOWN_ID = "unknown"
ENCODING = "utf-8"
DECODE_ERRORS = "replace"

REPO_FLAG = "--repo"
STAGED_FLAG = "--staged"
TRACKED_FLAG = "--tracked"
PATHS_FLAG = "--paths"

IMPLEMENTER = "implementer"
BASH_TOOL = "Bash"
EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
PATH_KEYS = ("file_path", "notebook_path")
TOOL_USE_TYPE = "tool_use"
VERIFY_NAME = "verify"

KEY_EVENT = "hook_event_name"
KEY_TOOL_NAME = "tool_name"
KEY_TOOL_INPUT = "tool_input"
KEY_COMMAND = "command"
KEY_CWD = "cwd"
KEY_AGENT_TYPE = "agent_type"
KEY_AGENT_ID = "agent_id"
KEY_SESSION_ID = "session_id"
KEY_AGENT_TRANSCRIPT = "agent_transcript_path"
KEY_TRANSCRIPT = "transcript_path"
KEY_SCRATCHPAD = "scratchpad_dir"
KEY_MESSAGE = "message"
KEY_CONTENT = "content"
KEY_TYPE = "type"
KEY_NAME = "name"
KEY_INPUT = "input"
KEY_HOOK_OUTPUT = "hookSpecificOutput"
KEY_HOOK_EVENT = "hookEventName"
KEY_DECISION = "permissionDecision"
KEY_DECISION_REASON = "permissionDecisionReason"
KEY_SYSTEM_MESSAGE = "systemMessage"
DENY = "deny"

COMMIT_WORD = "commit"
ADD_WORD = "add"
ADD_WHOLE_TREE_PATHS = frozenset({".", ":/"})
ADD_LONG_VALUE_OPTIONS = frozenset({"--chmod", "--pathspec-from-file"})
GIT_WORD = "git"
CD_WORD = "cd"
DASH = "-"
LONG_PREFIX = "--"
END_OF_OPTIONS = "--"
EQUALS = "="
NEWLINE = "\n"
TAB = "\t"
SPACE = " "
BACKSLASH = "\\"
SINGLE_QUOTE = "'"
QUOTES = "'\""
BLANKS = " \t"
HEREDOC_OPERATOR = "<<"
HERESTRING_OPERATOR = "<<<"
HEREDOC_WORD_STOPS = " \t\n;&|()<>"
QUOTE_REMOVAL = str.maketrans("", "", "'\"\\")
SEGMENT_BREAKS = ";&|\n()"
OPTION_SIGNS = "-+"

GIT_CHDIR_OPTION = "-C"
GIT_VALUE_OPTIONS = frozenset(
    {"-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)
COMMIT_SHORT_VALUE_OPTIONS = frozenset("mFCct")
COMMIT_SHORT_ATTACHED_OPTIONS = frozenset("Su")
COMMIT_LONG_VALUE_OPTIONS = frozenset(
    {
        "--message",
        "--file",
        "--reuse-message",
        "--reedit-message",
        "--template",
        "--fixup",
        "--squash",
        "--author",
        "--date",
        "--cleanup",
        "--trailer",
        "--pathspec-from-file",
    }
)

REDIRECTION = re.compile(r"^\d*(?:<<<|<<|>>|<>|>\||<|>)&?(?P<target>.*)$")
REDIRECTION_TARGET = "target"
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
STATE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")
KEYWORDS = frozenset(
    {
        "if",
        "then",
        "elif",
        "else",
        "fi",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "!",
        "function",
    }
)
WRAPPERS = frozenset(
    {
        "env",
        "command",
        "builtin",
        "exec",
        "sudo",
        "doas",
        "nice",
        "ionice",
        "time",
        "nohup",
        "timeout",
        "stdbuf",
        "unbuffer",
        "xargs",
        "chronic",
    }
)
WRAPPER_VALUE_OPTS = {
    "env": frozenset({"-u", "-C", "-S", "--unset", "--chdir"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-k", "-s", "--kill-after", "--signal"}),
    "ionice": frozenset({"-c", "-n", "-p", "--class", "--classdata"}),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output"}),
    "sudo": frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t"}),
    "xargs": frozenset({"-n", "-L", "-P", "-s", "-a", "-d", "-E", "-I"}),
}
WRAPPER_OPTIONAL_VALUE_OPTS = {"xargs": frozenset({"-i", "-e", "-l"})}
WRAPPER_VALUE_ARGS = {"timeout": 1}
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
SHELL_OPTS_WITH_ARG = frozenset(
    {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
)
SHELL_COMMAND_FLAG = "c"
SHELL_OPTION_LETTERS = "oO"

FAIL_OPEN_ERRORS = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    IndexError,
    RecursionError,
    subprocess.SubprocessError,
)

FIX_INSTRUCTION = (
    "standards-gate: fix every violation on the changed lines, or argue a"
    " suppression in the review, then commit again."
)
INTERACTIVE_REASON = (
    "standards-gate: an interactive commit cannot be checked — stage the"
    " changes explicitly and commit again."
)
UNAVAILABLE_TEMPLATE = (
    "standards-gate: lint-strict unavailable ({reason}) — commit not checked"
)
NUDGE_INSTRUCTION = (
    "standards-gate: lint-strict found norm violations in the uncommitted"
    " changes of these repos. Fix every one in a file you created or"
    " changed; for a violation in a file you did not touch, do not edit"
    " it — list it in your report."
)
TIMEOUT_TEMPLATE = "timeout after {seconds}s"
EXIT_TEMPLATE = "exit {code}"


class HookEvent(StrEnum):
    """Hook events this gate acts on."""

    PRE_TOOL_USE = "PreToolUse"
    SUBAGENT_STOP = "SubagentStop"


class CommitScope(StrEnum):
    """Commit options that change which changes a commit records."""

    ALL = "all"
    ONLY = "only"
    INCLUDE = "include"
    INTERACTIVE = "interactive"
    PATHSPEC_FILE = "pathspec-file"


class AddScope(StrEnum):
    """Add options that change which changes ``git add`` stages."""

    WHOLE_TREE = "whole-tree"
    UPDATE = "update"


COMMIT_SHORT_SCOPES = {
    "a": CommitScope.ALL,
    "o": CommitScope.ONLY,
    "i": CommitScope.INCLUDE,
    "p": CommitScope.INTERACTIVE,
}
COMMIT_LONG_SCOPES = {
    "--all": CommitScope.ALL,
    "--only": CommitScope.ONLY,
    "--include": CommitScope.INCLUDE,
    "--interactive": CommitScope.INTERACTIVE,
    "--patch": CommitScope.INTERACTIVE,
    "--pathspec-from-file": CommitScope.PATHSPEC_FILE,
}
WHOLE_TREE_SCOPES = frozenset({CommitScope.ALL, CommitScope.PATHSPEC_FILE})
ADD_SHORT_SCOPES = {
    "A": AddScope.WHOLE_TREE,
    "p": AddScope.WHOLE_TREE,
    "i": AddScope.WHOLE_TREE,
    "e": AddScope.WHOLE_TREE,
    "u": AddScope.UPDATE,
}
ADD_LONG_SCOPES = {
    "--all": AddScope.WHOLE_TREE,
    "--no-ignore-removal": AddScope.WHOLE_TREE,
    "--patch": AddScope.WHOLE_TREE,
    "--interactive": AddScope.WHOLE_TREE,
    "--edit": AddScope.WHOLE_TREE,
    "--pathspec-from-file": AddScope.WHOLE_TREE,
    "--update": AddScope.UPDATE,
}


@dataclass(frozen=True, slots=True)
class HookPayload:
    """The fields of a hook's stdin JSON that this gate reads."""

    event: str
    tool_name: str
    command: str
    cwd: str
    agent_type: str | None
    agent_id: str
    session_id: str
    transcript: str
    scratchpad_dir: str

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> HookPayload:
        """Build the payload from the decoded stdin object."""
        tool_input = raw.get(KEY_TOOL_INPUT)
        command = (
            text_field(tool_input, KEY_COMMAND)
            if isinstance(tool_input, dict)
            else ""
        )
        agent_type = raw.get(KEY_AGENT_TYPE)
        transcript = text_field(raw, KEY_AGENT_TRANSCRIPT) or text_field(
            raw, KEY_TRANSCRIPT
        )
        return cls(
            event=text_field(raw, KEY_EVENT),
            tool_name=text_field(raw, KEY_TOOL_NAME),
            command=command,
            cwd=text_field(raw, KEY_CWD),
            agent_type=None if agent_type is None else str(agent_type),
            agent_id=text_field(raw, KEY_AGENT_ID),
            session_id=text_field(raw, KEY_SESSION_ID),
            transcript=transcript,
            scratchpad_dir=text_field(raw, KEY_SCRATCHPAD),
        )

    def working_dir(self) -> Path:
        """Return the resolved directory the tool call runs in."""
        return Path(self.cwd).resolve() if self.cwd else Path.cwd()


@dataclass(frozen=True, slots=True)
class Heredoc:
    """A pending heredoc whose body follows the next newline."""

    delimiter: str
    strip_tabs: bool


@dataclass(frozen=True, slots=True)
class Segment:
    """One simple command of a shell line and the directory it runs in."""

    tokens: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True, slots=True)
class GitCall:
    """A git invocation: its subcommand, arguments and target repo."""

    subcommand: str
    args: tuple[str, ...]
    repo: Path


@dataclass(frozen=True, slots=True)
class OptionGrammar:
    """Which options of a git subcommand set scopes or take values."""

    short_scopes: dict[str, StrEnum]
    long_scopes: dict[str, StrEnum]
    short_values: frozenset[str]
    short_attached: frozenset[str]
    long_values: frozenset[str]


@dataclass(slots=True)
class ParsedArgs:
    """Scope options and pathspecs parsed from git subcommand arguments."""

    scopes: set[StrEnum] = field(default_factory=set)
    paths: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LintRun:
    """One lint-strict invocation: the arguments after the binary."""

    args: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommitInvocation:
    """A detected commit: its repo and the lint runs covering its scope."""

    repo: Path
    runs: tuple[LintRun, ...]
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class Checker:
    """A checker binary and its timeout, each overridable through env."""

    binary_env: str
    default_binary: str
    timeout_env: str
    default_timeout: float


LINT_STRICT = Checker(
    LINT_BIN_ENV, DEFAULT_LINT_BIN, LINT_TIMEOUT_ENV, DEFAULT_LINT_TIMEOUT
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of one checker run; ``failure`` names why it could not."""

    exit_code: int | None
    output: str
    failure: str = ""

    @property
    def has_violations(self) -> bool:
        """Return whether the checker reported violations or findings."""
        return self.exit_code == EXIT_VIOLATIONS

    @property
    def unavailable(self) -> bool:
        """Return whether the checker could not give a verdict."""
        return self.exit_code not in {EXIT_PASS, EXIT_VIOLATIONS}


@dataclass(frozen=True, slots=True)
class ToolUse:
    """A tool call recorded in a transcript."""

    name: str
    data: dict[str, object]


@dataclass(slots=True)
class SegmentScanner:
    """Split a shell command into segments, dropping heredoc bodies."""

    text: str
    index: int = 0
    quote: str = ""
    current: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    heredocs: list[Heredoc] = field(default_factory=list)

    def segments(self) -> list[str]:
        """Return the non-blank segments of the whole command."""
        while self.index < len(self.text):
            self.step()
        self.flush()
        return [part for part in self.parts if part.strip()]

    def flush(self) -> None:
        """Close the segment collected so far."""
        self.parts.append("".join(self.current))
        self.current = []

    def step(self) -> None:
        """Consume the character (or escape pair) at the cursor."""
        char = self.text[self.index]
        if char == BACKSLASH and self.quote != SINGLE_QUOTE:
            self.current.append(self.text[self.index : self.index + 2])
            self.index += 2
            return
        if self.quote:
            self.quote = "" if char == self.quote else self.quote
            self.current.append(char)
        elif char in QUOTES:
            self.quote = char
            self.current.append(char)
        elif self.text.startswith(HERESTRING_OPERATOR, self.index):
            self.current.append(HERESTRING_OPERATOR)
            self.index += len(HERESTRING_OPERATOR)
            return
        elif self.at_heredoc():
            self.read_heredoc_operator()
            return
        elif char == NEWLINE and self.heredocs:
            self.flush()
            self.skip_heredoc_bodies()
            return
        elif char in SEGMENT_BREAKS:
            self.flush()
        else:
            self.current.append(char)
        self.index += 1

    def at_heredoc(self) -> bool:
        """Return whether a heredoc operator starts at the cursor."""
        return self.text.startswith(HEREDOC_OPERATOR, self.index)

    def read_heredoc_operator(self) -> None:
        """Consume ``<<[-] WORD`` and remember the heredoc it opens."""
        self.index += len(HEREDOC_OPERATOR)
        strip_tabs = self.text.startswith(DASH, self.index)
        self.index += int(strip_tabs)
        while self.index < len(self.text) and self.text[self.index] in BLANKS:
            self.index += 1
        start = self.index
        while (
            self.index < len(self.text)
            and self.text[self.index] not in HEREDOC_WORD_STOPS
        ):
            self.index += 1
        delimiter = self.text[start : self.index].translate(QUOTE_REMOVAL)
        if delimiter:
            self.heredocs.append(Heredoc(delimiter, strip_tabs=strip_tabs))
        self.current.append(SPACE)

    def skip_heredoc_bodies(self) -> None:
        """Skip every pending heredoc body after the current newline."""
        self.index += 1
        for heredoc in self.heredocs:
            self.index = heredoc_end(self.text, self.index, heredoc)
        self.heredocs.clear()


def text_field(raw: dict[str, object], key: str) -> str:
    """Return ``raw[key]`` when it is a string, else an empty string."""
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def heredoc_end(text: str, start: int, heredoc: Heredoc) -> int:
    """Return the index just past the delimiter line of a heredoc body."""
    position = start
    while position < len(text):
        newline = text.find(NEWLINE, position)
        stop = len(text) if newline < 0 else newline
        line = text[position:stop]
        if heredoc.strip_tabs:
            line = line.lstrip(TAB)
        position = stop + 1
        if line == heredoc.delimiter:
            return position
    return len(text)


def split_segments(command: str) -> list[str]:
    """Split a command at shell separators, ignoring quotes and heredocs."""
    return SegmentScanner(command).segments()


def tokens_of(text: str) -> list[str]:
    """Tokenize one segment; unparseable quoting yields no tokens."""
    try:
        return shlex.split(text)
    except ValueError:
        return []


def strip_redirections(tokens: list[str]) -> list[str]:
    """Drop redirection operators and their targets from the tokens."""
    kept, index = [], 0
    while index < len(tokens):
        match = REDIRECTION.match(tokens[index])
        index += 1
        if match is None:
            kept.append(tokens[index - 1])
        elif not match.group(REDIRECTION_TARGET):
            index += 1
    return kept


def strip_prefix(tokens: list[str]) -> list[str]:
    """Drop env assignments, shell keywords and wrapper commands."""
    index, moved = 0, True
    while moved and index < len(tokens):
        moved = False
        while index < len(tokens) and (
            tokens[index] in KEYWORDS or ENV_ASSIGNMENT.match(tokens[index])
        ):
            index, moved = index + 1, True
        if index < len(tokens) and Path(tokens[index]).name in WRAPPERS:
            index, moved = skip_wrapper(tokens, index), True
    return tokens[index:]


def skip_wrapper(tokens: list[str], index: int) -> int:
    """Return the index of the command a wrapper at ``index`` runs."""
    word = Path(tokens[index]).name
    value_opts = WRAPPER_VALUE_OPTS.get(word, frozenset())
    optional_opts = WRAPPER_OPTIONAL_VALUE_OPTS.get(word, frozenset())
    index += 1
    while (
        index < len(tokens)
        and tokens[index].startswith(DASH)
        and tokens[index] != DASH
    ):
        option = tokens[index]
        index += 1
        if EQUALS in option or option in optional_opts:
            continue
        if option in value_opts and index < len(tokens):
            index += 1
    extra = WRAPPER_VALUE_ARGS.get(word, 0)
    while extra > 0 and index < len(tokens):
        if tokens[index].startswith(DASH):
            break
        index, extra = index + 1, extra - 1
    return index


def shell_script(tokens: list[str]) -> str | None:
    """Return the ``-c`` script a shell invocation runs, if any."""
    seen_c, index = False, 1
    while index < len(tokens):
        token = tokens[index]
        if token in SHELL_OPTS_WITH_ARG:
            index += 2
            continue
        if token == END_OF_OPTIONS:
            index += 1
            has_script = seen_c and index < len(tokens)
            return tokens[index] if has_script else None
        if token[:1] in OPTION_SIGNS and len(token) > 1:
            letters = "" if token.startswith(LONG_PREFIX) else token[1:]
            seen_c = seen_c or SHELL_COMMAND_FLAG in letters
            takes_arg = any(ch in SHELL_OPTION_LETTERS for ch in letters)
            index += 2 if takes_arg else 1
            continue
        return token if seen_c else None
    return None


def resolve_path(base: Path, raw: str) -> Path:
    """Resolve ``raw`` (``~`` expanded) against ``base``."""
    return (base / Path(raw).expanduser()).resolve()


def change_dir(cwd: Path, args: list[str]) -> Path:
    """Return the directory a ``cd`` with ``args`` moves to."""
    targets = [arg for arg in args if not arg.startswith(DASH) or arg == DASH]
    if not targets:
        return Path.home()
    if targets[0] == DASH:
        return cwd
    return resolve_path(cwd, targets[0])


def walk_segments(
    command: str, cwd: Path, depth: int = 0
) -> Iterator[Segment]:
    """Yield every simple command with the directory it runs in."""
    for text in split_segments(command):
        tokens = strip_prefix(strip_redirections(tokens_of(text)))
        if not tokens:
            continue
        head = Path(tokens[0]).name
        if head == CD_WORD:
            cwd = change_dir(cwd, tokens[1:])
            continue
        script = None
        if head in SHELLS and depth < MAX_SHELL_DEPTH:
            script = shell_script(tokens)
        if script is not None:
            yield from walk_segments(script, cwd, depth + 1)
            continue
        yield Segment(tuple(tokens), cwd)


def parse_git(segment: Segment) -> GitCall | None:
    """Parse git global options; return the call or None if not git."""
    tokens = segment.tokens
    if Path(tokens[0]).name != GIT_WORD:
        return None
    repo, index = segment.cwd, 1
    while index < len(tokens) and tokens[index].startswith(DASH):
        option = tokens[index]
        has_value = index + 1 < len(tokens)
        if option == GIT_CHDIR_OPTION and has_value:
            repo = resolve_path(repo, tokens[index + 1])
            index += 2
        elif option in GIT_VALUE_OPTIONS:
            index += 2
        else:
            index += 1
    if index >= len(tokens):
        return None
    return GitCall(tokens[index], tokens[index + 1 :], repo)


def read_long_option(
    token: str, grammar: OptionGrammar, flags: ParsedArgs
) -> int:
    """Apply a long option; return how many values it consumes."""
    name, separator, _ = token.partition(EQUALS)
    scope = grammar.long_scopes.get(name)
    if scope is not None:
        flags.scopes.add(scope)
    return int(name in grammar.long_values and not separator)


def read_short_group(
    token: str, grammar: OptionGrammar, flags: ParsedArgs
) -> int:
    """Apply combined short options; return how many values they consume."""
    for position, letter in enumerate(token[1:], start=2):
        if letter in grammar.short_values:
            return int(not token[position:])
        if letter in grammar.short_attached:
            return 0
        scope = grammar.short_scopes.get(letter)
        if scope is not None:
            flags.scopes.add(scope)
    return 0


def parse_args(args: tuple[str, ...], grammar: OptionGrammar) -> ParsedArgs:
    """Parse subcommand arguments into scope flags and pathspecs."""
    flags = ParsedArgs()
    index, options_ended = 0, False
    while index < len(args):
        token = args[index]
        index += 1
        if options_ended or not token.startswith(DASH) or token == DASH:
            flags.paths.append(token)
        elif token == END_OF_OPTIONS:
            options_ended = True
        elif token.startswith(LONG_PREFIX):
            index += read_long_option(token, grammar, flags)
        else:
            index += read_short_group(token, grammar, flags)
    return flags


def plan_runs(repo: Path, flags: ParsedArgs) -> tuple[LintRun, ...]:
    """Map commit scope flags to the lint-strict runs that cover them."""
    base = (REPO_FLAG, str(repo))
    staged = LintRun((*base, STAGED_FLAG))
    if flags.scopes & WHOLE_TREE_SCOPES:
        return (LintRun((*base, TRACKED_FLAG)),)
    if not flags.paths:
        return (staged,)
    with_paths = LintRun((*base, TRACKED_FLAG, PATHS_FLAG, *flags.paths))
    if CommitScope.INCLUDE in flags.scopes:
        return (staged, with_paths)
    return (with_paths,)


COMMIT_GRAMMAR = OptionGrammar(
    short_scopes=COMMIT_SHORT_SCOPES,
    long_scopes=COMMIT_LONG_SCOPES,
    short_values=COMMIT_SHORT_VALUE_OPTIONS,
    short_attached=COMMIT_SHORT_ATTACHED_OPTIONS,
    long_values=COMMIT_LONG_VALUE_OPTIONS,
)
ADD_GRAMMAR = OptionGrammar(
    short_scopes=ADD_SHORT_SCOPES,
    long_scopes=ADD_LONG_SCOPES,
    short_values=frozenset(),
    short_attached=frozenset(),
    long_values=ADD_LONG_VALUE_OPTIONS,
)


def add_run(call: GitCall) -> LintRun:
    """Return the lint-strict run covering what a ``git add`` stages."""
    flags = parse_args(call.args, ADD_GRAMMAR)
    base = (REPO_FLAG, str(call.repo))
    whole_tree = AddScope.WHOLE_TREE in flags.scopes or not flags.paths
    if whole_tree or ADD_WHOLE_TREE_PATHS.intersection(flags.paths):
        if AddScope.UPDATE in flags.scopes and not flags.paths:
            return LintRun((*base, TRACKED_FLAG))
        return LintRun(base)
    if AddScope.UPDATE in flags.scopes:
        return LintRun((*base, TRACKED_FLAG, PATHS_FLAG, *flags.paths))
    return LintRun((*base, PATHS_FLAG, *flags.paths))


@functools.cache
def cached_git_root(directory: Path) -> Path | None:
    """Return ``git_root`` of ``directory``, computed once per directory."""
    return git_root(directory)


def same_repo(add_dir: Path, commit_dir: Path) -> bool:
    """Return whether an add may stage into the commit's repo.

    An unresolvable root counts as the same repo: covering too much is
    the safe side.
    """
    if add_dir == commit_dir:
        return True
    add_root = cached_git_root(add_dir)
    commit_root = cached_git_root(commit_dir)
    return add_root is None or commit_root is None or add_root == commit_root


def commit_invocation(
    call: GitCall, earlier_adds: list[GitCall]
) -> CommitInvocation:
    """Return the commit a git call runs, covering earlier adds too."""
    flags = parse_args(call.args, COMMIT_GRAMMAR)
    if CommitScope.INTERACTIVE in flags.scopes:
        return CommitInvocation(call.repo, (), interactive=True)
    added = tuple(
        add_run(add) for add in earlier_adds if same_repo(add.repo, call.repo)
    )
    runs = (*plan_runs(call.repo, flags), *added)
    return CommitInvocation(call.repo, tuple(dict.fromkeys(runs)))


def find_commits(command: str, cwd: Path) -> list[CommitInvocation]:
    """Return every commit a command line runs."""
    adds: list[GitCall] = []
    commits: list[CommitInvocation] = []
    for segment in walk_segments(command, cwd):
        call = parse_git(segment)
        if call is None:
            continue
        if call.subcommand == ADD_WORD:
            adds.append(call)
        elif call.subcommand == COMMIT_WORD:
            commits.append(commit_invocation(call, list(adds)))
    return commits


def checker_timeout(checker: Checker) -> float:
    """Return the checker's timeout, overridable through the env."""
    raw = os.environ.get(checker.timeout_env, checker.default_timeout)
    try:
        return float(raw)
    except ValueError:
        return checker.default_timeout


def run_check(checker: Checker, args: tuple[str, ...]) -> CheckResult:
    """Run the checker with ``args`` and classify the outcome."""
    binary = Path(os.environ.get(checker.binary_env, checker.default_binary))
    timeout = checker_timeout(checker)
    try:
        done = subprocess.run(
            [str(binary.expanduser()), *args],
            capture_output=True,
            text=True,
            errors=DECODE_ERRORS,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        reason = TIMEOUT_TEMPLATE.format(seconds=timeout)
        return CheckResult(None, "", reason)
    except OSError as error:
        return CheckResult(None, "", str(error))
    stderr_lines = done.stderr.strip().splitlines()
    reason = (
        stderr_lines[-1]
        if stderr_lines
        else EXIT_TEMPLATE.format(code=done.returncode)
    )
    return CheckResult(done.returncode, done.stdout, reason)


def emit(document: dict[str, object]) -> None:
    """Print a hook response document as JSON on stdout."""
    print(json.dumps(document))


def deny(reason: str) -> None:
    """Emit a PreToolUse deny decision with ``reason``."""
    emit(
        {
            KEY_HOOK_OUTPUT: {
                KEY_HOOK_EVENT: HookEvent.PRE_TOOL_USE.value,
                KEY_DECISION: DENY,
                KEY_DECISION_REASON: reason,
            }
        }
    )


def gate_commit(payload: HookPayload) -> None:
    """Deny a commit with norm violations."""
    if COMMIT_WORD not in payload.command:
        return
    commits = find_commits(payload.command, payload.working_dir())
    if any(commit.interactive for commit in commits):
        deny(INTERACTIVE_REASON)
        return
    runs = list(dict.fromkeys(run for c in commits for run in c.runs))
    lint_results = [run_check(LINT_STRICT, run.args) for run in runs]
    reports = [
        r.output.rstrip(NEWLINE) for r in lint_results if r.has_violations
    ]
    if reports:
        deny(NEWLINE.join([*reports, FIX_INSTRUCTION]))
        return
    failures = [r.failure for r in lint_results if r.unavailable]
    if failures:
        reason = UNAVAILABLE_TEMPLATE.format(reason="; ".join(failures))
        emit({KEY_SYSTEM_MESSAGE: reason})


def tool_uses(line: str) -> list[ToolUse]:
    """Return the tool calls recorded on one transcript line."""
    try:
        entry = json.loads(line[:MAX_LINE_BYTES])
    except ValueError:
        return []
    message = entry.get(KEY_MESSAGE) if isinstance(entry, dict) else None
    content = message.get(KEY_CONTENT) if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [
        ToolUse(block[KEY_NAME], block[KEY_INPUT])
        for block in content
        if is_tool_use(block)
    ]


def is_tool_use(block: object) -> bool:
    """Return whether a content block is a well-formed tool call."""
    return (
        isinstance(block, dict)
        and block.get(KEY_TYPE) == TOOL_USE_TYPE
        and isinstance(block.get(KEY_NAME), str)
        and isinstance(block.get(KEY_INPUT), dict)
    )


def edited_path(data: dict[str, object]) -> str:
    """Return the file path an edit tool call touched, or ''."""
    for key in PATH_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def is_verify_word(word: str) -> bool:
    """Return whether a command word runs the verify wrapper."""
    return Path(word).name == VERIFY_NAME


def repo_argument(tokens: tuple[str, ...]) -> str:
    """Return the ``--repo`` value of a verify invocation, or ''."""
    prefix = REPO_FLAG + EQUALS
    for index, token in enumerate(tokens[1:], start=1):
        if token == END_OF_OPTIONS:
            break
        if token == REPO_FLAG and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(prefix):
            return token.removeprefix(prefix)
    return ""


def verify_repos(command: str, cwd: Path) -> list[Path]:
    """Return the ``--repo`` directories of verify runs in a command."""
    if VERIFY_NAME not in command:
        return []
    found = []
    for segment in walk_segments(command, cwd):
        if not is_verify_word(segment.tokens[0]):
            continue
        repo = repo_argument(segment.tokens)
        if repo:
            found.append(resolve_path(segment.cwd, repo))
    return found


def tool_dirs(use: ToolUse, cwd: Path) -> list[Path]:
    """Return the directories a tool call points the lint at."""
    if use.name in EDIT_TOOLS:
        path = edited_path(use.data)
        return [resolve_path(cwd, path).parent] if path else []
    command = use.data.get(KEY_COMMAND)
    if use.name == BASH_TOOL and isinstance(command, str):
        return verify_repos(command, cwd)
    return []


def transcript_dirs(transcript: str, cwd: Path) -> list[Path]:
    """Return the directories the subagent edited or verified."""
    path = Path(transcript) if transcript else None
    if path is None or not path.is_file():
        return []
    found = []
    with path.open(encoding=ENCODING, errors=DECODE_ERRORS) as handle:
        for line in handle:
            for use in tool_uses(line):
                found.extend(tool_dirs(use, cwd))
    return found


def nearest_existing(path: Path) -> Path:
    """Return ``path`` or its closest ancestor that exists."""
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def git_root(directory: Path) -> Path | None:
    """Return the top level of the git work tree holding ``directory``."""
    try:
        done = subprocess.run(
            [GIT_WORD, "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = done.stdout.strip()
    return Path(top) if done.returncode == EXIT_PASS and top else None


def git_roots(directories: list[Path]) -> list[Path]:
    """Return the distinct git roots of ``directories`` in order."""
    roots = (git_root(nearest_existing(d)) for d in dict.fromkeys(directories))
    return list(dict.fromkeys(root for root in roots if root is not None))


def state_path(payload: HookPayload) -> Path:
    """Return the block-counter file for this agent."""
    directory = (
        Path(payload.scratchpad_dir) if payload.scratchpad_dir else None
    )
    if (
        directory is None
        or not directory.is_dir()
        or not os.access(directory, os.W_OK)
    ):
        directory = Path(tempfile.gettempdir())
    key = payload.agent_id or payload.session_id or UNKNOWN_ID
    safe_key = STATE_ID_RE.sub("_", key)[:STATE_ID_LIMIT]
    return directory / f"{STATE_PREFIX}{safe_key}"


def read_blocks(state: Path) -> int:
    """Return how many times this agent has been sent back already."""
    try:
        return int(state.read_text(encoding=ENCODING).strip())
    except (OSError, ValueError):
        return 0


def write_blocks(state: Path, blocks: int) -> None:
    """Persist the block counter, ignoring an unwritable state file."""
    with contextlib.suppress(OSError):
        state.write_text(str(blocks), encoding=ENCODING)


def capped(report: str) -> str:
    """Return the first ``MAX_REPORT_LINES`` lines of a report."""
    return NEWLINE.join(report.splitlines()[:MAX_REPORT_LINES])


def nudge_implementer(payload: HookPayload) -> int:
    """Send an implementer back while lint-strict reports violations."""
    if payload.agent_type is not None and payload.agent_type != IMPLEMENTER:
        return EXIT_PASS
    state = state_path(payload)
    blocks = read_blocks(state)
    if blocks >= MAX_BLOCKS:
        return EXIT_PASS
    cwd = payload.working_dir()
    directories = [*transcript_dirs(payload.transcript, cwd), cwd]
    results = [
        run_check(LINT_STRICT, (REPO_FLAG, str(root)))
        for root in git_roots(directories)
    ]
    reports = [capped(r.output) for r in results if r.has_violations]
    if not reports:
        return EXIT_PASS
    write_blocks(state, blocks + 1)
    print(NEWLINE.join([*reports, NUDGE_INSTRUCTION]), file=sys.stderr)
    return EXIT_BLOCK


def dispatch(payload: HookPayload) -> int:
    """Route a payload to the duty its hook event calls for."""
    match payload.event:
        case HookEvent.PRE_TOOL_USE if payload.tool_name == BASH_TOOL:
            gate_commit(payload)
            return EXIT_PASS
        case HookEvent.SUBAGENT_STOP:
            return nudge_implementer(payload)
        case _:
            return EXIT_PASS


def main() -> int:
    """Read the hook payload from stdin; fail open on any error."""
    try:
        raw = json.loads(sys.stdin.read())
        if not isinstance(raw, dict):
            return EXIT_PASS
        return dispatch(HookPayload.from_json(raw))
    except FAIL_OPEN_ERRORS:
        return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
