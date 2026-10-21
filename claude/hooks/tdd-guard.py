#!/usr/bin/env python3
"""PreToolUse(Edit|Write|NotebookEdit|Bash) hook: the first production edit needs a red test.

A change to production code in a repository under the projects root is denied until this session has
an earlier verify run for that worktree which the ledger classified as red. Test files, non-code
files, repositories with no detectable test harness and every path outside the projects root pass
untouched. Internal failures — a malformed payload, an unreadable transcript, a corrupt ledger line,
a payload without a scratchpad directory — pass as well: only missing evidence denies."""
import dataclasses
import datetime
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import sys
import time
from collections.abc import Callable

PROJECTS_ROOT_ENV = "CLAUDE_TDD_PROJECTS_ROOT"
DEFAULT_PROJECTS_ROOT = "__HOME__/projects"
LOG_DIR_ENV = "CLAUDE_VERIFY_LOG_DIR"
DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), ".cache", "claude-verify")
LEDGER_NAME = "ledger.jsonl"
SESSIONS_DIR = "sessions"
LEDGER_TAIL_LINES = 2000
RED_OUTCOME = "red"
GIT_MARKER = ".git"
EDIT_TOOL = "Edit"
EDIT_TOOLS = (EDIT_TOOL, "Write", "NotebookEdit")
AGENT_ID_KEY = "agent_id"
SMALL_EDIT_MAX_LINES = 5
BASH_TOOL = "Bash"
PATH_KEYS = ("file_path", "notebook_path")
STATE_PREFIX = "tdd-guard-"
STATE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")
STATE_ID_MAX = 120
FALLBACK_STATE_DIR = "/tmp"
NO_AGENT = "no-agent"
NO_SESSION = "no-session"
SECONDS_PER_HOUR = 3600
MARKER_RETENTION_HOURS = 24
MARKER_RETENTION_SECONDS = MARKER_RETENTION_HOURS * SECONDS_PER_HOUR
EXCEPTION_TOKEN = "TDD-EXCEPTION:"
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
MARKER_READ_LIMIT = 64 * 1024
CONFIG_READ_LIMIT = 512 * 1024
PATCH_READ_LIMIT = 4 * 1024 * 1024
TRANSCRIPT_LINE_LIMIT = 2_000_000
GO_WALK_BUDGET = 4000
GO_TEST_SUFFIX = "_test.go"
SKIPPED_DIRS = {".git", "node_modules", "vendor", "target", "dist", "build", ".venv", "__pycache__"}
UNEXPANDED_MARKERS = ("$", "`")
SEGMENT_BREAKS = ";&|\n()"
QUOTES = "'\""
WORD_BREAKS = set(" \t;|&<>()")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_KEYWORDS = {"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "case", "esac",
                  "!", "function", "{", "}"}
WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "doas", "nice", "ionice", "time", "nohup",
            "timeout", "stdbuf", "unbuffer", "chronic"}
HEREDOC_HEADER = re.compile(r"<<-?\s*(?P<q>['\"]?)(?P<delim>[A-Za-z_][A-Za-z0-9_]*)(?P=q)")
REDIRECT_OPERATOR = re.compile(r"^\d*(?:>>?|<<?|>&|&>)$")
REDIRECT_ATTACHED = re.compile(r"^\d*(?:>>?|<<?)\S+$")
SHORT_OPTION_WITH_VALUE = re.compile(r"^-[A-Za-z]*[eEfF]$")
SHORT_INPLACE = re.compile(r"^-[A-Za-z]*i")
PYTHON_COMMAND = re.compile(r"^python[0-9.]*$")
PYTHON_OPEN_WRITE = re.compile(
    r"open\(\s*(?P<q>['\"])(?P<path>[^'\"]+)(?P=q)\s*,\s*(?P<mq>['\"])(?P<mode>[rwaxbt+]+)(?P=mq)")
WRITING_MODES = ("w", "a", "x")
PATCH_STRIP_DEFAULT = 0
PATCH_PREFIXES = ("a/", "b/")
PATCH_TARGET_MARKER = "+++ "
PATCH_NULL_TARGET = "/dev/null"
NPM_PLACEHOLDER = "no test specified"
TS_CONFIG_PREFIXES = ("vitest.config", "jest.config", "playwright.config")
CMAKE_TEST_MARKERS = ("enable_testing()", "add_test(")
MAKEFILE_TEST_TARGET = re.compile(r"^(test|check):", re.M)
TWISTER_FILES = ("testcase.yaml", "testcase.yml")
HARNESS_LOOKASIDE_DIR = "tests"

REASON = (
    "tdd-guard: no red test run recorded for {repo} in this session, so this is the first production "
    "edit without a failing test.\n"
    "Write the test first and watch it fail:\n"
    "  ~/.claude/bin/verify --repo {repo} -- '<the test command>'\n"
    "The run has to end red — a recognised runner reporting a non-zero failure count. A run that "
    "errors out (import error, collection error, typo in the command, a non-runner printing FAILED) "
    "proves nothing and does not unlock the edit.\n"
    "The log path that verify prints is the evidence the review asks for; quote it in your report.\n"
    "Only the first production edit per repository is gated — once the red run is recorded the rest "
    "of the cycle runs unblocked. Test files, non-code files and repositories without a test harness "
    "are never gated."
)


@dataclasses.dataclass(slots=True, frozen=True)
class Language:
    """One gated language: which files are its code, which of them are tests, how its harness looks."""

    name: str
    extensions: tuple[str, ...]
    test_dirs: tuple[str, ...]
    test_globs: tuple[str, ...]
    marker_in: Callable[[str], bool]


@dataclasses.dataclass(slots=True, frozen=True)
class Segment:
    """One shell segment with the directory its relative paths resolve against."""

    text: str
    tokens: tuple[str, ...]
    base_dir: str


@dataclasses.dataclass(slots=True, frozen=True)
class UnlockMarker:
    """The unlock state left after a red run: whose session, for which worktree, and when."""

    session_id: str
    repo: str
    created_at: datetime.datetime | None


@dataclasses.dataclass(slots=True, frozen=True)
class LedgerEntry:
    """The fields of a ledger line this hook decides on."""

    outcome: str
    repo: str
    session_id: str
    ts: datetime.datetime | None


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def read_text(path, limit):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def projects_root():
    override = os.environ.get(PROJECTS_ROOT_ENV)
    if override and os.path.isdir(override):
        return os.path.realpath(override)
    return os.path.realpath(DEFAULT_PROJECTS_ROOT)


def log_dir():
    return os.environ.get(LOG_DIR_ENV) or DEFAULT_LOG_DIR


def is_under(path, root):
    return path == root or path.startswith(root + os.sep)


def ancestors(start, root):
    current = start
    while True:
        yield current
        if current == root or current == os.path.dirname(current):
            return
        current = os.path.dirname(current)


def python_marker(directory):
    project = os.path.join(directory, "pyproject.toml")
    if os.path.isfile(project) and "pytest" in read_text(project, CONFIG_READ_LIMIT):
        return True
    if os.path.isfile(os.path.join(directory, "pytest.ini")):
        return True
    for name in ("tox.ini", "setup.cfg"):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and "[tool:pytest]" in read_text(candidate, CONFIG_READ_LIMIT):
            return True
    return False


def package_json_tests(path):
    try:
        data = json.loads(read_text(path, CONFIG_READ_LIMIT))
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        script = scripts.get("test")
        if isinstance(script, str) and script.strip() and NPM_PLACEHOLDER not in script:
            return True
    return isinstance(data.get("jest"), dict)


def typescript_marker(directory):
    manifest = os.path.join(directory, "package.json")
    if os.path.isfile(manifest) and package_json_tests(manifest):
        return True
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    return any(name.startswith(TS_CONFIG_PREFIXES) for name in names)


def module_has_test_file(directory):
    budget = GO_WALK_BUDGET
    for current, subdirectories, files in os.walk(directory):
        subdirectories[:] = [name for name in subdirectories if name not in SKIPPED_DIRS]
        if any(name.endswith(GO_TEST_SUFFIX) for name in files):
            return True
        budget -= 1
        if budget <= 0:
            return False
    return False


def go_marker(directory):
    return os.path.isfile(os.path.join(directory, "go.mod")) and module_has_test_file(directory)


def rust_marker(directory):
    return os.path.isfile(os.path.join(directory, "Cargo.toml"))


def c_marker(directory):
    lists = os.path.join(directory, "CMakeLists.txt")
    if os.path.isfile(lists):
        text = read_text(lists, CONFIG_READ_LIMIT)
        if any(marker in text for marker in CMAKE_TEST_MARKERS):
            return True
    if any(os.path.isfile(os.path.join(directory, name)) for name in TWISTER_FILES):
        return True
    makefile = os.path.join(directory, "Makefile")
    return os.path.isfile(makefile) and bool(
        MAKEFILE_TEST_TARGET.search(read_text(makefile, CONFIG_READ_LIMIT)))


LANGUAGES = (
    Language("python", (".py",), ("tests",), ("test_*.py", "*_test.py"), python_marker),
    Language("typescript", (".ts", ".tsx", ".js", ".jsx"), ("tests", "__tests__"),
             ("*.test.*", "*.spec.*"), typescript_marker),
    Language("go", (".go",), (), ("*_test.go",), go_marker),
    Language("rust", (".rs",), ("tests", "benches"), (), rust_marker),
    Language("c", (".c", ".h"), ("tests",), ("test_*.c", "*_test.c"), c_marker),
)


def has_harness(language, path, root):
    """Markers on the way up to the worktree root, plus the one bounded lookaside in <root>/tests."""
    if any(language.marker_in(directory) for directory in ancestors(os.path.dirname(path), root)):
        return True
    return language.marker_in(os.path.join(root, HARNESS_LOOKASIDE_DIR))


def language_for(path):
    extension = os.path.splitext(path)[1].lower()
    for language in LANGUAGES:
        if extension in language.extensions:
            return language
    return None


def worktree_root(path):
    for directory in ancestors(os.path.dirname(path), os.sep):
        if os.path.exists(os.path.join(directory, GIT_MARKER)):
            return directory
    return None


def is_test_path(path, root, language):
    relative = os.path.relpath(path, root)
    parts = relative.split(os.sep)
    if any(part in language.test_dirs for part in parts[:-1]):
        return True
    return any(fnmatch.fnmatch(parts[-1], pattern) for pattern in language.test_globs)


def gated_repo(path):
    real = os.path.realpath(path)
    if not is_under(real, projects_root()):
        return None
    language = language_for(real)
    if language is None:
        return None
    root = worktree_root(real)
    if root is None:
        return None
    if is_test_path(real, root, language):
        return None
    if not has_harness(language, real, root):
        return None
    return root


def split_segments(command):
    parts, current, quote, index = [], [], "", 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            current.append(command[index:index + 2])
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            current.append(char)
        elif char in QUOTES:
            quote = char
            current.append(char)
        elif char in SEGMENT_BREAKS:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [part for part in parts if part.strip()]


def strip_heredoc_bodies(command):
    lines = command.splitlines()
    kept, index = [], 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        match = HEREDOC_HEADER.search(line)
        index += 1
        if not match:
            continue
        delimiter = match.group("delim")
        while index < len(lines) and lines[index].strip() != delimiter:
            index += 1
        index += 1
    return "\n".join(kept)


def tokens_of(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def strip_redirections(tokens):
    cleaned, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if REDIRECT_OPERATOR.match(token):
            skip = True
            continue
        if REDIRECT_ATTACHED.match(token):
            continue
        cleaned.append(token)
    return cleaned


def strip_prefix(tokens):
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in SHELL_KEYWORDS or ENV_ASSIGNMENT.match(token):
            index += 1
            continue
        if os.path.basename(token) in WRAPPERS:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-") and tokens[index] != "-":
                index += 1
            continue
        break
    return tokens[index:]


def read_word(text, start):
    index = start
    while index < len(text) and text[index] in " \t":
        index += 1
    if index >= len(text):
        return "", index
    if text[index] in QUOTES:
        quote = text[index]
        index += 1
        word = []
        while index < len(text) and text[index] != quote:
            word.append(text[index])
            index += 1
        return "".join(word), index + 1
    word = []
    while index < len(text) and text[index] not in WORD_BREAKS:
        word.append(text[index])
        index += 1
    return "".join(word), index


def redirect_targets(text):
    targets, index, quote = [], 0, ""
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in QUOTES:
            quote = char
            index += 1
            continue
        if char == ">" and (index == 0 or text[index - 1] not in "0123456789&<>"):
            after = index + 1
            if after < len(text) and text[after] == ">":
                after += 1
            if after < len(text) and text[after] == "&":
                index = after + 1
                continue
            word, after = read_word(text, after)
            if word:
                targets.append(word)
            index = after
            continue
        index += 1
    return targets


def redirect_source(text):
    index, quote = 0, ""
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in QUOTES:
            quote = char
            index += 1
            continue
        if char == "<" and text[index + 1:index + 2] != "<" and text[index - 1:index] != "<":
            word, _ = read_word(text, index + 1)
            return word
        index += 1
    return ""


def positional_arguments(tokens, value_options):
    arguments, index = [], 1
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-") and token != "-":
            if token in value_options or SHORT_OPTION_WITH_VALUE.match(token):
                index += 2
                continue
            index += 1
            continue
        arguments.append(token)
        index += 1
    return arguments


def has_inplace_flag(tokens):
    return any(token in ("-i", "--in-place") or token.startswith("--in-place=")
               or (not token.startswith("--") and SHORT_INPLACE.match(token))
               for token in tokens[1:])


def has_script_option(tokens):
    return any(token in ("-e", "-f", "--expression", "--file")
               or token.startswith(("--expression=", "--file="))
               or SHORT_OPTION_WITH_VALUE.match(token)
               for token in tokens[1:])


def sed_targets(segment):
    if not has_inplace_flag(segment.tokens):
        return []
    arguments = positional_arguments(segment.tokens, {"-e", "-f", "--expression", "--file"})
    if not has_script_option(segment.tokens) and arguments:
        arguments = arguments[1:]
    return arguments


def perl_targets(segment):
    if not has_inplace_flag(segment.tokens):
        return []
    return positional_arguments(segment.tokens, {"-e", "-E"})


def tee_targets(segment):
    return positional_arguments(segment.tokens, set())


def copy_targets(segment):
    arguments = positional_arguments(
        segment.tokens, {"-t", "--target-directory", "-S", "--suffix", "-m", "--mode",
                         "-o", "--owner", "-g", "--group"})
    return arguments[-1:] if len(arguments) > 1 else []


def dd_targets(segment):
    return [token.split("=", 1)[1] for token in segment.tokens[1:] if token.startswith("of=")]


def truncate_targets(segment):
    return positional_arguments(segment.tokens, {"-s", "--size", "-r", "--reference"})


def strip_components(path, strip):
    parts = path.split("/")
    if strip:
        parts = parts[strip:]
    elif path.startswith(PATCH_PREFIXES):
        parts = parts[1:]
    return "/".join(parts)


def patch_strip_level(tokens):
    for index, token in enumerate(tokens):
        if token.startswith("-p") and token[2:].isdigit():
            return int(token[2:])
        if token == "-p" and index + 1 < len(tokens) and tokens[index + 1].isdigit():
            return int(tokens[index + 1])
        if token.startswith("--strip="):
            tail = token.split("=", 1)[1]
            if tail.isdigit():
                return int(tail)
    return PATCH_STRIP_DEFAULT


def patch_file_of(segment):
    tokens = segment.tokens
    for index, token in enumerate(tokens):
        if token in ("-i", "--input") and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--input="):
            return token.split("=", 1)[1]
    return redirect_source(segment.text)


def patch_targets(segment):
    source = patch_file_of(segment)
    if not source or not usable(source):
        return []
    text = read_text(absolute(source, segment.base_dir), PATCH_READ_LIMIT)
    strip = patch_strip_level(segment.tokens)
    targets = []
    for line in text.splitlines():
        if not line.startswith(PATCH_TARGET_MARKER):
            continue
        candidate = line[len(PATCH_TARGET_MARKER):].split("\t")[0].strip()
        if not candidate or candidate == PATCH_NULL_TARGET:
            continue
        targets.append(strip_components(candidate, strip))
    return targets


def python_targets(segment):
    tokens = segment.tokens
    for index, token in enumerate(tokens):
        if token == "-c" and index + 1 < len(tokens):
            return [match.group("path")
                    for match in PYTHON_OPEN_WRITE.finditer(tokens[index + 1])
                    if any(mode in match.group("mode") for mode in WRITING_MODES)]
    return []


COMMAND_TARGETS = {
    "sed": sed_targets,
    "perl": perl_targets,
    "tee": tee_targets,
    "cp": copy_targets,
    "mv": copy_targets,
    "install": copy_targets,
    "dd": dd_targets,
    "truncate": truncate_targets,
    "patch": patch_targets,
}


def segment_targets(text, base_dir):
    targets = list(redirect_targets(text))
    tokens = strip_prefix(strip_redirections(tokens_of(text)))
    if not tokens:
        return targets
    name = os.path.basename(tokens[0])
    segment = Segment(text=text, tokens=tuple(tokens), base_dir=base_dir)
    handler = COMMAND_TARGETS.get(name)
    if handler is not None:
        targets.extend(handler(segment))
    elif PYTHON_COMMAND.match(name):
        targets.extend(python_targets(segment))
    return targets


def leading_cd_path(command):
    segments = split_segments(command)
    if not segments:
        return ""
    tokens = tokens_of(segments[0])
    if len(tokens) != 2 or tokens[0] != "cd" or not usable(tokens[1]):
        return ""
    return tokens[1]


def bash_targets(command, cwd):
    body = strip_heredoc_bodies(command)
    prefix = leading_cd_path(command)
    base_dir = absolute(prefix, cwd) if prefix else cwd
    targets = []
    for segment in split_segments(body):
        targets.extend(segment_targets(segment, base_dir))
    return [absolute(target, base_dir) for target in targets if usable(target)]


def usable(path):
    return bool(path) and not any(marker in path for marker in UNEXPANDED_MARKERS)


def absolute(path, base_dir):
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(base_dir, expanded)


def edit_targets(tool_input, cwd):
    targets = []
    for key in PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and usable(value):
            targets.append(absolute(value, cwd))
    return targets


def user_text(entry):
    message = entry.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block["text"] for block in content
                 if isinstance(block, dict) and block.get("type") == "text"
                 and isinstance(block.get("text"), str)]
        return "\n".join(parts) if parts else None
    return None


def exception_granted(transcript):
    if not isinstance(transcript, str) or not transcript:
        return False
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line[:TRANSCRIPT_LINE_LIMIT])
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            text = user_text(entry)
            if text is None:
                continue
            return EXCEPTION_TOKEN in text
    return False


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def session_started_at(session_id):
    marker = os.path.join(log_dir(), SESSIONS_DIR, STATE_ID_RE.sub("_", session_id) + ".json")
    try:
        data = json.loads(read_text(marker, MARKER_READ_LIMIT))
    except ValueError:
        return EPOCH
    if not isinstance(data, dict):
        return EPOCH
    return parse_timestamp(data.get("started_at")) or EPOCH


def ledger_entries():
    path = os.path.join(log_dir(), LEDGER_NAME)
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-LEDGER_TAIL_LINES:]
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        entries.append(LedgerEntry(
            outcome=str(data.get("outcome") or ""),
            repo=str(data.get("repo") or ""),
            session_id=str(data.get("session_id") or ""),
            ts=parse_timestamp(data.get("ts"))))
    return entries


def red_run_recorded(repo, session_id, started_at, entries):
    for entry in entries:
        if entry.outcome != RED_OUTCOME or entry.session_id != session_id:
            continue
        if entry.ts is None or entry.ts < started_at:
            continue
        if os.path.realpath(entry.repo) == repo:
            return True
    return False


def state_directory(payload):
    directory = payload.get("scratchpad_dir")
    if not isinstance(directory, str) or not os.path.isdir(directory):
        return FALLBACK_STATE_DIR
    return directory


def state_id(value, missing):
    return STATE_ID_RE.sub("_", str(value or missing))[:STATE_ID_MAX]


def state_path(directory, payload, repo):
    agent = state_id(payload.get("agent_id"), NO_AGENT)
    session = state_id(payload.get("session_id"), NO_SESSION)
    digest = hashlib.sha1(repo.encode("utf-8")).hexdigest()
    return os.path.join(directory, f"{STATE_PREFIX}{agent}-{session}-{digest}")


def read_marker(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.loads(handle.read(MARKER_READ_LIMIT))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return UnlockMarker(session_id=str(data.get("session_id") or ""),
                        repo=str(data.get("repo") or ""),
                        created_at=parse_timestamp(data.get("created_at")))


def marker_accepted(path, session_id, repo, started_at):
    """A marker unlocks only its own session, its own worktree and only after this session began."""
    marker = read_marker(path)
    if marker is None or not marker.session_id or marker.session_id != session_id:
        return False
    if not marker.repo or os.path.realpath(marker.repo) != repo:
        return False
    return marker.created_at is not None and marker.created_at >= started_at


def forget_stale_markers(directory):
    cutoff = time.time() - MARKER_RETENTION_SECONDS
    with os.scandir(directory) as items:
        for item in items:
            if not item.name.startswith(STATE_PREFIX):
                continue
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    os.unlink(item.path)
            except OSError:
                pass


def remember_unlock(path, session_id, repo):
    content = {"session_id": session_id, "repo": repo,
               "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(content, handle)
    except OSError:
        pass
    try:
        forget_stale_markers(os.path.dirname(path))
    except OSError:
        pass


def is_small_main_session_edit(payload: dict[str, object]) -> bool:
    """Tell whether the main session makes an edit of a few lines."""
    if payload.get(AGENT_ID_KEY) or payload.get("tool_name") != EDIT_TOOL:
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("replace_all"):
        return False
    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        return False
    diff = difflib.ndiff(old.split("\n"), new.split("\n"))
    changes = [line[0] for line in diff]
    largest = max(changes.count("+"), changes.count("-"))
    return largest <= SMALL_EDIT_MAX_LINES


def guard(payload):
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if tool not in EDIT_TOOLS + (BASH_TOOL,) or not isinstance(tool_input, dict):
        return
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    if tool == BASH_TOOL:
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            return
        paths = bash_targets(command, cwd)
    else:
        paths = edit_targets(tool_input, cwd)
    repos = []
    for path in paths:
        repo = gated_repo(path)
        if repo is not None and repo not in repos:
            repos.append(repo)
    if not repos:
        return
    if is_small_main_session_edit(payload):
        return
    if exception_granted(payload.get("transcript_path")):
        return
    directory = state_directory(payload)
    session_id = str(payload.get("session_id") or "")
    started_at = session_started_at(session_id)
    entries = None
    for repo in repos:
        marker = state_path(directory, payload, repo)
        if marker_accepted(marker, session_id, repo, started_at):
            continue
        if entries is None:
            entries = ledger_entries()
        if red_run_recorded(repo, session_id, started_at, entries):
            remember_unlock(marker, session_id, repo)
            continue
        deny(REASON.format(repo=repo))


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        guard(payload)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
