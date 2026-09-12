#!/usr/bin/env python3
"""PreToolUse(Bash) hook: denies bare test/lint/build/typecheck commands, pointing at ~/.claude/bin/verify."""
import json
import re
import shlex
import sys

OPERATORS = {";", ";;", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"}
PUNCTUATION = set("();|&")
MULTI_CHAR = {"&&", "||", ";;", "|&"}
WORD_END = set(" \t\n;|&()<>")
REDIRECT_OP = re.compile(r"(\d*)(&>>|&>|>>|>&|<&|>\||<<<|>|<)")
HEREDOC_FD = re.compile(r"\d+<<(?!<)")
PLACEHOLDER = "__subst__"
NEWLINE_MARK = ""
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
KEYWORDS = {"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "case", "esac", "!", "function"}

VERIFY_NAME = "verify"
VERIFY_PATH_SUFFIX = "/bin/verify"
DISPLAY_FILTERS = {"tail", "head"}

RECURSE_SHELLS = {"bash", "sh", "zsh"}
COMBINED_C_OPT_RE = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "nice", "ionice", "time", "nohup",
            "timeout", "stdbuf", "unbuffer", "xargs", "npx", "bunx"}
WRAPPER_VALUE_OPTS = {
    "env": {"-u", "-C", "-S", "--unset", "--chdir", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "ionice": {"-c", "-n", "-p", "--class", "--classdata", "--pid"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U", "--user", "--group", "--host",
             "--prompt", "--role", "--type", "--other-user", "--close-from"},
    "xargs": {"-n", "-L", "-P", "-s", "-a", "-d", "-E", "-I", "--max-args", "--max-procs",
              "--max-chars", "--arg-file", "--delimiter"},
}
WRAPPER_OPTIONAL_VALUE_OPTS = {"xargs": {"-i", "-e", "-l", "--replace", "--eof", "--max-lines"}}
WRAPPER_VALUE_ARGS = {"timeout": 1}
MULTI_WORD_WRAPPERS = {
    ("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("pdm", "run"), ("hatch", "run"),
    ("pnpm", "exec"), ("pnpm", "dlx"), ("yarn", "dlx"),
}
PY_MODULE_RUNNERS = {"python", "python3"}
INSPECT_WORDS = {"which", "type"}

STANDALONE_EXCEPTION_FLAGS = {
    "--version", "-V", "--help", "-h", "--collect-only", "--list-tests",
    "--dry-run", "--showconfig",
}
MAKE_EXTRA_EXCEPTION_FLAGS = {"-n", "--just-print"}

NPM_SCRIPT_RE = re.compile(r"^(test\S*|lint\S*|build\S*|e2e\S*|typecheck|check\S*|ci)$")
MAKE_TARGET_RE = re.compile(r"^(all|test\S*|lint\S*|build\S*|check\S*|e2e|benchmark|typecheck|ci)$")
NPM_VALUE_OPTS = {"-C", "--prefix", "--filter", "-w", "--workspace", "--dir"}
MAKE_VALUE_OPTS = {"-C", "-f", "-I", "-o", "-W"}


def _first(args):
    return args[0] if args else None


def _always(args):
    return True


def _strip_npm_options(args):
    i, n = 0, len(args)
    while i < n and args[i].startswith("-"):
        opt = args[i]
        i += 1
        if opt in NPM_VALUE_OPTS and i < n:
            i += 1
    return args[i:]


def _npm_strict(args):
    args = _strip_npm_options(args)
    first = _first(args)
    if first == "test":
        return True
    return first == "run" and len(args) > 1 and bool(NPM_SCRIPT_RE.match(args[1]))


def _npm_bare(args):
    args = _strip_npm_options(args)
    first = _first(args)
    if first == "test":
        return True
    if first == "run":
        return len(args) > 1 and bool(NPM_SCRIPT_RE.match(args[1]))
    return bool(first) and bool(NPM_SCRIPT_RE.match(first))


def _make(args):
    positional, i, n = [], 0, len(args)
    while i < n:
        a = args[i]
        if a in MAKE_VALUE_OPTS:
            i += 2
            continue
        if not a.startswith("-"):
            positional.append(a)
        i += 1
    if not positional:
        return True
    return any(MAKE_TARGET_RE.match(p) for p in positional)


def _ruff(args):
    first = _first(args)
    if first == "check":
        return True
    return first == "format" and "--check" in args


def _prettier(args):
    return "--check" in args


def _playwright(args):
    return _first(args) == "test"


def _cargo(args):
    return _first(args) in {"test", "build", "clippy", "check", "bench"}


def _go(args):
    return _first(args) in {"test", "build", "vet"}


def _cmake(args):
    return "--build" in args


def _pio(args):
    return _first(args) in {"run", "test"}


def _west(args):
    return _first(args) in {"build", "test"}


def _idf(args):
    return _first(args) in {"build", "flash"}


def _docker(args):
    first = _first(args)
    if first == "build":
        return True
    return first == "compose" and "build" in args[1:]


def _docker_compose(args):
    return "build" in args


def _alembic(args):
    return _first(args) in {"upgrade", "downgrade", "revision"}


RUNNER_TABLE = {
    "pytest": _always, "vitest": _always, "jest": _always, "mocha": _always, "ava": _always,
    "tox": _always, "nox": _always, "mypy": _always, "pyright": _always, "eslint": _always, "tsc": _always,
    "playwright": _playwright, "ruff": _ruff, "prettier": _prettier,
    "cargo": _cargo, "go": _go, "mvn": _always, "mvnw": _always, "gradle": _always, "gradlew": _always,
    "ninja": _always, "cmake": _cmake, "pio": _pio, "platformio": _pio, "west": _west, "idf.py": _idf,
    "make": _make, "npm": _npm_strict, "pnpm": _npm_bare, "yarn": _npm_bare, "bun": _npm_bare,
    "docker": _docker, "docker-compose": _docker_compose, "alembic": _alembic,
}


def is_verify_word(token):
    return basename(token) == VERIFY_NAME or token.endswith(VERIFY_PATH_SUFFIX)


def top_level_pipes(command):
    positions, quote, depth, i, n = [], "", 0, 0, len(command)
    while i < n:
        char = command[i]
        if char == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            i += 1
            continue
        if char in "'\"":
            quote = char
        elif command.startswith("$(", i):
            depth += 1
            i += 2
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "`":
            j = command.find("`", i + 1)
            i = n if j < 0 else j + 1
            continue
        elif char == "|" and depth == 0:
            if command.startswith("||", i) or command.startswith("|&", i):
                i += 2
                continue
            positions.append(i)
        i += 1
    return positions


def without_display_tail(command):
    """The verify log keeps the full output, so a trailing `| tail`/`| head` is dropped from the suggestion."""
    pipes = top_level_pipes(command)
    if not pipes:
        return command
    last = pipes[-1]
    tokens = tokenize(command[last + 1:])
    if not tokens or basename(tokens[0]) not in DISPLAY_FILTERS:
        return command
    if OPERATORS & set(tokens[1:]):
        return command
    head = command[:last].rstrip()
    return head or command


def deny(full_command, segment_tokens):
    segment_text = shlex.join(segment_tokens)
    suggested = without_display_tail(full_command)
    quoted = "'" + suggested.replace("'", "'\\''") + "'"
    reason = (
        f"verify-guard: `{segment_text}` prints long output. "
        f"Run it as: ~/.claude/bin/verify -- {quoted} — the full log stays on disk, "
        "only PASS/FAIL and the error section enter the context."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def matching_paren(text, start):
    depth, j, n = 1, start, len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = text.find("'", j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if not depth:
                return j
        j += 1
    return n


def substitutions_in(text):
    found, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
        elif text.startswith("$(", i):
            j = matching_paren(text, i + 2)
            found.append(text[i + 2:j])
            i = j + 1
        elif c == "`":
            j = i + 1
            while j < n and text[j] != "`":
                j += 2 if text[j] == "\\" else 1
            found.append(text[i + 1:j].replace("\\`", "`"))
            i = j + 1
        else:
            i += 1
    return found


class Scanner:
    """Quote-aware splitter: strips comments/redirects/heredocs, keeps quotes, masks substitutions."""

    def __init__(self, text):
        self.t = text
        self.n = len(text)
        self.i = 0
        self.out = []
        self.inner = []
        self.heredocs = []

    def at_word_start(self):
        return self.i == 0 or self.t[self.i - 1] in WORD_END

    def run(self):
        t = self.t
        while self.i < self.n:
            c = t[self.i]
            if c == "\\":
                self.out.append(t[self.i:self.i + 2])
                self.i += 2
            elif c == "'":
                j = t.find("'", self.i + 1)
                j = self.n if j < 0 else j
                self.out.append(t[self.i:j + 1].replace("\n", NEWLINE_MARK))
                self.i = j + 1
            elif c == '"':
                self.double_quoted()
            elif c == "`":
                self.backtick()
            elif t.startswith("$(", self.i):
                self.paren_subst(self.i + 2)
            elif c in "<>" and t.startswith("(", self.i + 1):
                self.paren_subst(self.i + 2)
            elif t.startswith("<<", self.i) and not t.startswith("<<<", self.i):
                self.heredoc_operator()
            elif c.isdigit() and self.at_word_start() and HEREDOC_FD.match(t, self.i):
                self.i = HEREDOC_FD.match(t, self.i).end() - 2
                self.heredoc_operator()
            elif (c in "<>&" or (c.isdigit() and self.at_word_start())) and self.redirect():
                pass
            elif c == "#" and self.at_word_start():
                j = t.find("\n", self.i)
                self.i = self.n if j < 0 else j
            elif c == "\n":
                self.out.append("\n")
                self.i += 1
                if self.heredocs:
                    self.consume_heredocs()
            else:
                self.out.append(c)
                self.i += 1
        return self

    def double_quoted(self):
        t = self.t
        self.out.append('"')
        self.i += 1
        while self.i < self.n:
            c = t[self.i]
            if c == "\\":
                self.out.append(t[self.i:self.i + 2])
                self.i += 2
            elif c == '"':
                self.out.append('"')
                self.i += 1
                return
            elif c == "`":
                self.backtick()
            elif t.startswith("$(", self.i):
                self.paren_subst(self.i + 2)
            else:
                self.out.append(NEWLINE_MARK if c == "\n" else c)
                self.i += 1

    def backtick(self):
        t = self.t
        j = self.i + 1
        while j < self.n and t[j] != "`":
            j += 2 if t[j] == "\\" else 1
        self.inner.append(t[self.i + 1:j].replace("\\`", "`"))
        self.out.append(PLACEHOLDER)
        self.i = min(j + 1, self.n)

    def paren_subst(self, start):
        j = matching_paren(self.t, start)
        self.inner.append(self.t[start:j])
        self.out.append(PLACEHOLDER)
        self.i = min(j + 1, self.n)

    def read_word(self):
        t = self.t
        start = self.i
        while self.i < self.n and t[self.i] not in WORD_END:
            c = t[self.i]
            if c == "\\":
                self.i += 2
            elif c in "'\"`":
                k = t.find(c, self.i + 1)
                self.i = self.n if k < 0 else k + 1
            elif t.startswith("$(", self.i):
                self.i = matching_paren(t, self.i + 2) + 1
            else:
                self.i += 1
        return t[start:self.i]

    def redirect(self):
        m = REDIRECT_OP.match(self.t, self.i)
        if not m:
            return False
        self.i = m.end()
        while self.i < self.n and self.t[self.i] in " \t":
            self.i += 1
        target = self.read_word()
        self.inner.extend(Scanner(target).run().inner)
        self.out.append(" ")
        return True

    def heredoc_operator(self):
        t = self.t
        self.i += 2
        strip_tabs = self.i < self.n and t[self.i] == "-"
        if strip_tabs:
            self.i += 1
        while self.i < self.n and t[self.i] in " \t":
            self.i += 1
        raw = self.read_word()
        literal = any(ch in raw for ch in "'\"\\")
        delimiter = raw.strip("'\"").replace("\\", "")
        self.heredocs.append((delimiter, literal, strip_tabs))
        self.out.append(" ")

    def consume_heredocs(self):
        t = self.t
        for delimiter, literal, strip_tabs in self.heredocs:
            body = []
            while self.i < self.n:
                j = t.find("\n", self.i)
                j = self.n if j < 0 else j
                line = t[self.i:j]
                self.i = min(j + 1, self.n)
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
                body.append(line)
            if not literal and body:
                self.inner.extend(substitutions_in("\n".join(body)))
        self.heredocs = []


def tokenize(line):
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars="();|&")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        tokens = [t for t in re.split(r"([ \t]+|&&|\|\||[;|()&])", line) if t and not t.isspace()]
    split = []
    for tok in tokens:
        if len(tok) > 1 and tok not in MULTI_CHAR and set(tok) <= PUNCTUATION:
            split.extend(tok)
        else:
            split.append(tok)
    return split


def segments(tokens):
    current = []
    for tok in tokens:
        if tok in OPERATORS:
            if current:
                yield current
            current = []
        else:
            current.append(tok)
    if current:
        yield current


def basename(tok):
    return tok.rsplit("/", 1)[-1]


def top_level_segments(command):
    scanner = Scanner(command.replace(NEWLINE_MARK, "\n")).run()
    text = "".join(scanner.out).replace("\\\n", " ")
    for line in text.split("\n"):
        for seg in segments(tokenize(line)):
            yield seg


def strip_leading(tokens):
    i, n = 0, len(tokens)
    while i < n and (tokens[i] in KEYWORDS or ENV_ASSIGNMENT.match(tokens[i])):
        i += 1
    return tokens[i:]


def find_dash_c(args):
    for idx, a in enumerate(args):
        if COMBINED_C_OPT_RE.match(a):
            return idx
    return None


def is_inspection_only(tokens):
    if not tokens:
        return False
    w = basename(tokens[0])
    if w in INSPECT_WORDS:
        return True
    return w == "command" and any(t in ("-v", "-V") for t in tokens[1:])


def strip_wrappers(tokens):
    i, n = 0, len(tokens)
    while i < n:
        word = basename(tokens[i])
        if i + 1 < n and (word, basename(tokens[i + 1])) in MULTI_WORD_WRAPPERS:
            i += 2
            continue
        if word in PY_MODULE_RUNNERS and i + 1 < n and tokens[i + 1] == "-m" and i + 2 < n:
            i += 2
            break
        if word in WRAPPERS:
            value_opts = WRAPPER_VALUE_OPTS.get(word, ())
            optional_opts = WRAPPER_OPTIONAL_VALUE_OPTS.get(word, ())
            i += 1
            while i < n and tokens[i].startswith("-") and tokens[i] != "-":
                option = tokens[i]
                i += 1
                if "=" in option or option in optional_opts:
                    continue
                if option in value_opts and i < n:
                    i += 1
            extra = WRAPPER_VALUE_ARGS.get(word, 0)
            while extra > 0 and i < n and not tokens[i].startswith("-"):
                i += 1
                extra -= 1
            continue
        break
    return tokens[i:]


def has_exception(tokens, word):
    if any(t in STANDALONE_EXCEPTION_FLAGS for t in tokens):
        return True
    return word == "make" and any(t in MAKE_EXTRA_EXCEPTION_FLAGS for t in tokens)


def check_segment(tokens, depth):
    body = strip_leading(tokens)
    if not body or is_inspection_only(body):
        return None
    effective = strip_wrappers(body)
    if not effective:
        return None
    word = basename(effective[0])
    if is_verify_word(effective[0]):
        return None
    args = effective[1:]
    if depth == 0 and word in RECURSE_SHELLS:
        idx = find_dash_c(args)
        if idx is not None and idx + 1 < len(args):
            for inner_seg in top_level_segments(args[idx + 1]):
                res = check_segment(inner_seg, depth + 1)
                if res is not None:
                    return res
        return None
    fn = RUNNER_TABLE.get(word)
    if not fn or not fn(args):
        return None
    if has_exception(tokens, word):
        return None
    return tokens


def scan_command(command):
    for seg in top_level_segments(command):
        result = check_segment(seg, 0)
        if result is not None:
            return result
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") not in (None, "Bash"):
            return
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return
        offending = scan_command(command)
        if offending is not None:
            deny(command, offending)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
