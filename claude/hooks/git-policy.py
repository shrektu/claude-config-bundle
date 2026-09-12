#!/usr/bin/env python3
"""PreToolUse(Bash) hook: git branch rule (only work branches may be moved) + commit message rule.
By design constructs that hide the cwd or the git word (scripts, eval, $GIT, `!` aliases, exotic heredoc or
case nesting) are not classified - git-guard carries the same class of blind spots."""
import json
import os
import re
import shlex
import subprocess
import sys
from typing import NamedTuple

OPERATORS = {";", ";;", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"}
KEYWORDS = {"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "case", "esac", "!", "function"}
PUNCTUATION = set("();|&")
MULTI_CHAR = {"&&", "||", ";;", "|&"}
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "doas", "nice", "ionice", "time", "nohup",
            "xargs", "timeout", "stdbuf", "chronic", "unbuffer", "watch"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
SHELL_OPTS_WITH_ARG = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
GIT_GLOBAL_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
SUBST_FORMAT = "__subst_%d__"
REDIRECT_FORMAT = "__redir_%d__"
PLACEHOLDER_RE = re.compile(r"__(?:subst|redir)_(\d+)__")
REDIRECT_TOKEN_RE = re.compile(r"^__redir_\d+__$")
NEWLINE_MARK = ""
WORD_END = set(" \t\n;|&()<>")
REDIRECT_OP = re.compile(r"(\d*)(&>>|&>|>>|>&|<&|>\||<<<|>|<)")
HEREDOC_FD = re.compile(r"\d+<<(?!<)")
MAX_DEPTH = 12
CD_OPTS = {"-L", "-P", "-e", "-@", "--"}
CASE_KEYWORD = "case"
ESAC_KEYWORD = "esac"

WORK_BRANCH_PREFIXES = ("feature/", "bugfix/", "hotfix/", "test/")
WORK_BRANCH_HINT = "feature/*, bugfix/*, hotfix/*, test/*"
REFS_HEADS = "refs/heads/"
GIT_TIMEOUT_S = 2
REBASE_STATE_DIRS = ("rebase-merge", "rebase-apply")

SHORT_VALUE_OPTS = {
    "commit": "mCcFt",
    "tag": "mFu",
    "branch": "u",
    "push": "o",
    "notes": "mF",
    "symbolic-ref": "m",
    "update-ref": "m",
}
LONG_VALUE_OPTS = {
    "commit": {"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--fixup", "--squash",
               "--trailer"},
    "tag": {"--message", "--file", "--local-user"},
    "branch": {"--set-upstream-to"},
    "notes": {"--message", "--file", "--reuse-message", "--reedit-message"},
    "symbolic-ref": {"-m"},
    "update-ref": {"-m"},
}

MUTATION_SUBS = frozenset({"commit", "merge", "rebase", "cherry-pick", "revert", "am", "reset", "push", "pull",
                           "tag", "branch", "update-ref", "symbolic-ref", "filter-branch", "filter-repo",
                           "replace", "notes"})
NEUTRAL_SUBS = frozenset({"status", "log", "diff", "show", "fetch", "remote", "config", "add", "rm", "mv",
                          "apply", "stash", "checkout", "switch", "restore", "clean", "clone", "init",
                          "worktree", "submodule", "bisect", "blame", "describe", "grep", "shortlog",
                          "reflog", "rev-parse", "rev-list", "ls-files", "ls-tree", "ls-remote", "cat-file",
                          "merge-base", "name-rev", "cherry", "range-diff", "format-patch", "send-email",
                          "request-pull", "bundle", "archive", "gc", "fsck", "prune", "maintenance",
                          "sparse-checkout", "check-ignore", "check-attr", "count-objects", "difftool",
                          "mergetool", "verify-commit", "verify-tag", "whatchanged", "annotate", "help",
                          "version", "hash-object", "for-each-ref", "update-index", "diff-tree", "gui"})
KNOWN_SUBCOMMANDS = MUTATION_SUBS | NEUTRAL_SUBS
ALIAS_PREFIX = "alias."
ALIAS_CONFIG_KEY = "alias.%s"
SHELL_ALIAS_MARK = "!"
MAX_ALIAS_DEPTH = 3

FORBIDDEN_TRAILERS = ("Co-Authored-By", "Generated with", "Claude-Session")
TRAILER_EVENTS = ("--trailer",)
COMMIT_DRY_RUN_EVENTS = {"--short", "--porcelain", "--long", "--null", "-z"}
EMOJI_RE = re.compile("[\u2600-\u27bf\U0001f300-\U0001faff]")
NON_BMP_MIN = 0x10000
SIGNOFF_EVENTS = {"-s", "--signoff"}
NO_SIGNOFF_EVENTS = {"--no-signoff"}
MESSAGE_EVENTS = {"-m", "--message"}
REUSE_EVENTS = {"-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message"}
NO_MESSAGE_CHECK_EVENTS = {"--fixup", "--squash"}
TAG_LIST_EVENTS = {"-l", "--list", "--contains", "--no-contains", "--points-at", "--merged", "--no-merged",
                   "--sort", "--format", "--column", "--no-column", "-n", "-v", "--verify"}
TAG_WRITE_EVENTS = {"-d", "--delete", "-a", "--annotate", "-s", "--sign", "-f", "--force", "-m", "--message",
                    "-F", "--file", "-e", "--edit", "--create-reflog"}
BRANCH_WRITE_EVENTS = {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f", "--force"}
NOTES_WRITE_SUBS = {"add", "append", "remove"}

HINT = " If this really has to land there, say so and let the user decide how (their own commit, a PR, a cherry-pick)."


class GitOpts(NamedTuple):
    directory: str
    git_dir: str
    work_tree: str


class GitCall(NamedTuple):
    sub: str
    args: tuple
    opts: GitOpts


class Parsed(NamedTuple):
    events: tuple
    positional: tuple
    values: tuple

    def has(self, *names):
        return any(ev in names for ev in self.events)

    def count(self, *names):
        return sum(1 for ev in self.events if ev in names)

    def values_of(self, *names):
        return [val for name, val in self.values if name in names]


class RepoState(NamedTuple):
    branch: str
    rebase_head: str
    directory: str


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"git-policy: {reason}",
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
    """Splits a bash command into outer text (quotes kept, redirects/heredocs removed) and substitution bodies."""

    def __init__(self, text):
        self.t = text
        self.n = len(text)
        self.i = 0
        self.out = []
        self.inner = []
        self.marks = set()
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

    def mark_for(self, body, template):
        self.inner.append(body)
        mark = template % (len(self.inner) - 1)
        self.marks.add(mark)
        return mark

    def emit(self, body, template):
        self.out.append(self.mark_for(body, template))

    def backtick(self):
        t = self.t
        j = self.i + 1
        while j < self.n and t[j] != "`":
            j += 2 if t[j] == "\\" else 1
        self.emit(t[self.i + 1:j].replace("\\`", "`"), SUBST_FORMAT)
        self.i = min(j + 1, self.n)

    def paren_subst(self, start):
        j = matching_paren(self.t, start)
        self.emit(self.t[start:j], SUBST_FORMAT)
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
        self.out.append(" ")
        for body in Scanner(target).run().inner:
            self.out.append(" ")
            self.emit(body, REDIRECT_FORMAT)
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
        self.out.append(" ")
        self.heredocs.append((delimiter, literal, strip_tabs, len(self.out) - 1))

    def consume_heredocs(self):
        t = self.t
        for delimiter, literal, strip_tabs, slot in self.heredocs:
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
                marks = [self.mark_for(found, REDIRECT_FORMAT)
                         for found in substitutions_in("\n".join(body))]
                if marks:
                    self.out[slot] = " " + " ".join(marks) + " "
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


def basename(tok):
    return tok.rsplit("/", 1)[-1]


def resolve(directory, value):
    if not value:
        return directory
    return os.path.normpath(value if os.path.isabs(value) else os.path.join(directory, value))


def cd_target(args, cwd):
    for arg in args:
        if arg in CD_OPTS or arg.startswith("-"):
            continue
        return resolve(cwd, arg)
    return cwd


def at_command_position(current):
    return all(tok in KEYWORDS for tok in current)


class Substitutions:
    """Only the placeholder strings the Scanner really emitted stand for a substitution."""

    def __init__(self, scanner):
        self.bodies = scanner.inner
        self.marks = scanner.marks
        self.consumed = set()

    def take(self, token):
        for found in PLACEHOLDER_RE.finditer(token):
            index = int(found.group(1))
            if found.group(0) not in self.marks or index in self.consumed or index >= len(self.bodies):
                continue
            self.consumed.add(index)
            if self.bodies[index]:
                yield self.bodies[index]

    def is_operator(self, token):
        return token in self.marks and bool(REDIRECT_TOKEN_RE.match(token))

    def unconsumed(self):
        return [body for index, body in enumerate(self.bodies) if index not in self.consumed and body]


class DirState:
    """Tracks the effective cwd; `( … )` runs in a subshell, so its `cd` does not reach the outer commands."""

    def __init__(self, cwd):
        self.cwd = cwd
        self.saved = []
        self.parens = 0
        self.cases = []

    def enter(self):
        self.saved.append(self.cwd)

    def leave(self):
        if self.saved:
            self.cwd = self.saved.pop()


def scan(command, cwd, depth=0):
    calls = []
    if depth > MAX_DEPTH:
        return calls
    scanner = Scanner(command.replace(NEWLINE_MARK, "\n")).run()
    state = DirState(cwd)
    substitutions = Substitutions(scanner)
    for line in "".join(scanner.out).replace("\\\n", " ").split("\n"):
        calls.extend(walk(tokenize(line), state, depth, substitutions))
    for body in substitutions.unconsumed():
        calls.extend(scan(body, state.cwd, depth + 1))
    return calls


def walk(tokens, state, depth, substitutions):
    calls, current = [], []

    def flush():
        if not current:
            return
        found, state.cwd = analyze(list(current), state.cwd, depth)
        calls.extend(found)
        current.clear()

    for tok in tokens:
        if tok == CASE_KEYWORD and at_command_position(current):
            state.cases.append(state.parens)
            current.append(tok)
            continue
        if tok == ESAC_KEYWORD and at_command_position(current):
            if state.cases:
                state.cases.pop()
            continue
        if tok == "(":
            flush()
            state.parens += 1
            state.enter()
            continue
        if tok == ")":
            flush()
            if state.cases and state.parens == state.cases[-1]:
                continue
            state.parens = max(0, state.parens - 1)
            state.leave()
            continue
        if tok in OPERATORS:
            flush()
            continue
        for body in substitutions.take(tok):
            calls.extend(scan(body, state.cwd, depth + 1))
        if substitutions.is_operator(tok):
            continue
        current.append(tok)
    flush()
    return calls


def analyze(tokens, cwd, depth, inline=None, alias_depth=0):
    inline = inline or {}
    i = 0
    while i < len(tokens) and (tokens[i] in KEYWORDS or ENV_ASSIGNMENT.match(tokens[i])):
        i += 1
    if i >= len(tokens):
        return [], cwd
    prog = basename(tokens[i])
    if prog == "cd":
        return [], cd_target(tokens[i + 1:], cwd)
    if prog in WRAPPERS:
        for k in range(i + 1, len(tokens)):
            if basename(tokens[k]) in SHELLS | {"git", "eval"} and not tokens[k].startswith("-"):
                found, _ = analyze(tokens[k:], cwd, depth, inline, alias_depth)
                return found, cwd
        return [], cwd
    if prog in SHELLS:
        return shell_calls(tokens, i, cwd, depth), cwd
    if prog == "eval":
        return scan(" ".join(tokens[i + 1:]), cwd, depth + 1), cwd
    if prog != "git":
        return [], cwd
    directory, git_dir, work_tree = cwd, "", ""
    aliases = dict(inline)
    j = i + 1
    while j < len(tokens) and tokens[j].startswith("-"):
        name, value, step = tokens[j], None, 1
        if name in GIT_GLOBAL_OPTS_WITH_ARG and j + 1 < len(tokens):
            value, step = tokens[j + 1], 2
        elif name[:2] in ("-C", "-c") and not name.startswith("--") and len(name) > 2:
            name, value = name[:2], name[2:]
        elif "=" in name:
            name, _, value = name.partition("=")
        if name == "-C" and value:
            directory = resolve(directory, value)
        elif name == "--work-tree" and value:
            work_tree = value
        elif name == "--git-dir" and value:
            git_dir = value
        elif name == "-c" and value and value.startswith(ALIAS_PREFIX):
            alias_name, _, expansion = value[len(ALIAS_PREFIX):].partition("=")
            if alias_name and expansion:
                aliases[alias_name] = expansion
        j += step
    if j >= len(tokens):
        return [], cwd
    opts = GitOpts(directory, git_dir, work_tree)
    sub = tokens[j]
    if sub not in KNOWN_SUBCOMMANDS:
        expansion = aliases.get(sub) or alias_expansion(opts, sub)
        if expansion:
            if expansion.lstrip().startswith(SHELL_ALIAS_MARK):
                return [], cwd
            words = tokenize(expansion)
            if words and alias_depth < MAX_ALIAS_DEPTH:
                expanded = [tokens[i], *tokens[i + 1:j], *words, *tokens[j + 1:]]
                found, _ = analyze(expanded, cwd, depth, aliases, alias_depth + 1)
                return found, cwd
    return [GitCall(sub, tuple(tokens[j + 1:]), opts)], cwd


_ALIAS_CACHE = {}


def alias_expansion(opts, name):
    key = (opts, name)
    if key not in _ALIAS_CACHE:
        _ALIAS_CACHE[key] = git_output(opts, "config", "--get", ALIAS_CONFIG_KEY % name)
    return _ALIAS_CACHE[key]


def shell_calls(tokens, i, cwd, depth):
    seen_c, k = False, i + 1
    while k < len(tokens):
        tok = tokens[k]
        if tok in SHELL_OPTS_WITH_ARG:
            k += 2
            continue
        if tok == "--":
            k += 1
            if seen_c and k < len(tokens):
                return scan(tokens[k], cwd, depth + 1)
            return []
        if tok[:1] in "-+" and len(tok) > 1:
            if not tok.startswith("--"):
                seen_c = seen_c or "c" in tok[1:]
                k += 2 if any(ch in "oO" for ch in tok[1:]) else 1
            else:
                k += 1
            continue
        if seen_c:
            return scan(tok, cwd, depth + 1)
        return []
    return []


def parse(sub, args):
    events, positional, values = [], [], []
    short_value = SHORT_VALUE_OPTS.get(sub, "")
    long_value = LONG_VALUE_OPTS.get(sub, frozenset())
    pending = None
    for idx, arg in enumerate(args):
        if pending is not None:
            values.append((pending, arg))
            pending = None
            continue
        if arg == "--":
            positional.extend(args[idx + 1:])
            break
        if arg.startswith("--") and len(arg) > 2:
            name, eq, val = arg.partition("=")
            events.append(name)
            if eq:
                values.append((name, val))
            elif name in long_value:
                pending = name
        elif arg.startswith("-") and len(arg) > 1:
            cluster = arg[1:]
            for pos, ch in enumerate(cluster):
                opt = "-" + ch
                events.append(opt)
                if ch in short_value:
                    rest = cluster[pos + 1:]
                    if rest:
                        values.append((opt, rest))
                    else:
                        pending = opt
                    break
        else:
            positional.append(arg)
    return Parsed(tuple(events), tuple(positional), tuple(values))


def toggled(events, on, off):
    state = False
    for ev in events:
        if ev in on:
            state = True
        elif ev in off:
            state = False
    return state


def commit_is_dry_run(parsed):
    if parsed.has(*COMMIT_DRY_RUN_EVENTS):
        return True
    return toggled(parsed.events, {"--dry-run"}, {"--no-dry-run"})


def mutates(sub, parsed):
    if sub not in MUTATION_SUBS:
        return None
    if sub == "commit":
        return None if commit_is_dry_run(parsed) else "creates a commit on"
    if sub == "merge":
        return "merges into"
    if sub == "rebase":
        return None if parsed.has("--show-current-patch") else "rewrites"
    if sub == "cherry-pick":
        return "adds commits to"
    if sub == "revert":
        return "adds a revert commit to"
    if sub == "am":
        return None if parsed.has("--show-current-patch") else "applies patches to"
    if sub == "reset":
        return "moves"
    if sub == "pull":
        if toggled(parsed.events, {"--dry-run"}, {"--no-dry-run"}):
            return None
        return "fast-forwards or merges into"
    if sub == "push":
        if toggled(parsed.events, {"-n", "--dry-run"}, {"--no-dry-run"}):
            return None
        return "publishes"
    if sub == "tag":
        if parsed.has(*TAG_LIST_EVENTS):
            return None
        if parsed.has(*TAG_WRITE_EVENTS) or parsed.positional:
            return "creates or deletes a tag in the repo of"
        return None
    if sub == "branch":
        return "deletes, renames or resets a branch in the repo of" if parsed.has(*BRANCH_WRITE_EVENTS) else None
    if sub == "update-ref":
        return "moves a ref in the repo of"
    if sub == "symbolic-ref":
        if parsed.has("-d", "--delete") or len(parsed.positional) > 1:
            return "repoints a symbolic ref in the repo of"
        return None
    if sub in ("filter-branch", "filter-repo"):
        return "rewrites the history of"
    if sub == "replace":
        if parsed.has("-l", "--list"):
            return None
        if parsed.has("-d", "--delete") or parsed.positional:
            return "replaces objects in the repo of"
        return None
    if sub == "notes":
        first = parsed.positional[0] if parsed.positional else None
        return "rewrites notes in the repo of" if first in NOTES_WRITE_SUBS else None
    return None


def is_work_branch(name):
    return bool(name) and name.startswith(WORK_BRANCH_PREFIXES)


def git_output(opts, *args):
    """Runs git with the same repository selection the inspected command uses."""
    command = ["git", "-C", opts.directory]
    if opts.git_dir:
        command.append(f"--git-dir={opts.git_dir}")
    if opts.work_tree:
        command.append(f"--work-tree={opts.work_tree}")
    try:
        done = subprocess.run((*command, *args), capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    except Exception:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def rebase_head_name(git_dir):
    for state in REBASE_STATE_DIRS:
        path = os.path.join(git_dir, state, "head-name")
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                name = handle.readline().strip()
        except OSError:
            continue
        if name:
            return name[len(REFS_HEADS):] if name.startswith(REFS_HEADS) else name
    return None


_STATE_CACHE = {}


def repo_state(opts):
    if opts in _STATE_CACHE:
        return _STATE_CACHE[opts]
    state = None
    if os.path.isdir(opts.directory):
        git_dir = git_output(opts, "rev-parse", "--git-dir")
        if git_dir:
            state = RepoState(git_output(opts, "symbolic-ref", "--short", "-q", "HEAD"),
                              rebase_head_name(resolve(opts.directory, git_dir)), opts.directory)
    _STATE_CACHE[opts] = state
    return state


def branch_verdict(call, action):
    state = repo_state(call.opts)
    if state is None:
        return None
    if state.rebase_head:
        if is_work_branch(state.rebase_head):
            return None
        return (f"a rebase of `{state.rebase_head}` is in progress in {call.opts.directory} and `git {call.sub}` "
                f"{action} it, but it is not a work branch ({WORK_BRANCH_HINT}). Abort that rebase or hand it "
                f"to the user.{HINT}")
    if state.branch is None:
        return (f"HEAD is detached in {call.opts.directory}, so `git {call.sub}` {action} no work branch "
                f"({WORK_BRANCH_HINT}). Create one first: `git switch -c feature/<topic>`.{HINT}")
    if is_work_branch(state.branch):
        return None
    return (f"`git {call.sub}` {action} `{state.branch}`, which is not a work branch ({WORK_BRANCH_HINT}). "
            f"Run it on a work branch instead: `git switch -c feature/<topic>`.{HINT}")


def has_emoji(text):
    return bool(EMOJI_RE.search(text)) or any(ord(ch) >= NON_BMP_MIN for ch in text)


def clean_message(message):
    first = message.replace(NEWLINE_MARK, "\n").split("\n", 1)[0]
    for trailer in FORBIDDEN_TRAILERS:
        cut = first.lower().find(trailer.lower())
        if cut >= 0:
            first = first[:cut]
    return "".join(ch for ch in first if not has_emoji(ch)).strip()


def suggest_commit(sub, args, message):
    keep, skip_next = [], False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in MESSAGE_EVENTS or arg in TRAILER_EVENTS:
            skip_next = True
            continue
        if arg in SIGNOFF_EVENTS or arg in NO_SIGNOFF_EVENTS:
            continue
        if arg.startswith(("--message=", "--trailer=")) or arg.startswith("-m") and len(arg) > 2:
            continue
        keep.append(arg)
    body = ["git", sub, *keep, "-s"]
    if message is not None:
        body += ["-m", clean_message(message) or "One sentence in imperative mood."]
    return shlex.join(body)


def commit_verdict(call, parsed):
    if parsed.has(*NO_MESSAGE_CHECK_EVENTS):
        return None
    if parsed.has("--amend") and parsed.has("--no-edit"):
        return None
    if commit_is_dry_run(parsed):
        return None
    messages = parsed.values_of(*MESSAGE_EVENTS)
    message_count = parsed.count(*MESSAGE_EVENTS)
    message = messages[0] if messages else None
    fix = suggest_commit(call.sub, call.args, message)
    for value in parsed.values_of(*TRAILER_EVENTS):
        for trailer in FORBIDDEN_TRAILERS:
            if trailer.lower() in value.lower():
                return (f"`{trailer}` is not allowed in a commit message; the only trailer is `Signed-off-by:` "
                        f"added by `-s`. Use: {fix}")
    if not message_count and not parsed.has(*REUSE_EVENTS):
        return None
    signed = toggled(parsed.events, SIGNOFF_EVENTS, NO_SIGNOFF_EVENTS)
    if not signed:
        return (f"every commit is signed off: `git commit` is missing `-s`/`--signoff`. Use: {fix}")
    if not message_count:
        return None
    if message_count > 1:
        return (f"the commit message is ONE sentence with no body: {message_count} `-m` options were given. "
                f"Use: {fix}")
    text = messages[0] if messages else ""
    if "\n" in text or NEWLINE_MARK in text:
        return f"the commit message is ONE sentence with no body, but this one contains a newline. Use: {fix}"
    for trailer in FORBIDDEN_TRAILERS:
        if trailer.lower() in text.lower():
            return (f"`{trailer}` is not allowed in a commit message; the only trailer is `Signed-off-by:` "
                    f"added by `-s`. Use: {fix}")
    if has_emoji(text):
        return f"commit messages carry no emoji. Use: {fix}"
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
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            cwd = os.getcwd()
        for call in scan(command, os.path.expanduser(cwd)):
            parsed = parse(call.sub, call.args)
            if call.sub == "commit":
                reason = commit_verdict(call, parsed)
                if reason:
                    deny(reason)
            action = mutates(call.sub, parsed)
            if action:
                reason = branch_verdict(call, action)
                if reason:
                    deny(reason)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
