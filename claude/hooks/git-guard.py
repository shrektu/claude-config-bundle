#!/usr/bin/env python3
"""PreToolUse(Bash) hook: denies git commands that discard or overwrite work."""
import json
import re
import shlex
import sys

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
VALUE_SHORT_OPTS = {"checkout": "bB", "switch": "cC", "restore": "s", "clean": "e", "push": "o", "stash": "m"}
STASH_READ_ONLY = {"list", "show", "create"}
PLACEHOLDER = "__subst__"
NEWLINE_MARK = ""
WORD_END = set(" \t\n;|&()<>")
REDIRECT_OP = re.compile(r"(\d*)(&>>|&>|>>|>&|<&|>\||<<<|>|<)")
HEREDOC_FD = re.compile(r"\d+<<(?!<)")
MAX_DEPTH = 12
HINT = " If a revert or cleanup is really needed, STOP and report it to the orchestrator/user instead."


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"git-guard: {reason}{HINT}",
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
    """$(...) and `...` bodies in text whose quotes are literal (expandable heredoc bodies)."""
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
    """Splits a bash command into its outer text (quotes kept, comments/redirects/heredocs removed,
    substitutions replaced by a placeholder) and the inner commands of every substitution."""

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


def git_calls(command, depth=0):
    if depth > MAX_DEPTH:
        return
    scanner = Scanner(command.replace(NEWLINE_MARK, "\n")).run()
    for line in "".join(scanner.out).replace("\\\n", " ").split("\n"):
        for seg in segments(tokenize(line)):
            yield from analyze(seg, depth)
    for inner in scanner.inner:
        yield from git_calls(inner, depth + 1)


def analyze(tokens, depth):
    i = 0
    while i < len(tokens) and (tokens[i] in KEYWORDS or ENV_ASSIGNMENT.match(tokens[i])):
        i += 1
    if i >= len(tokens):
        return
    prog = basename(tokens[i])
    if prog in WRAPPERS:
        for k in range(i + 1, len(tokens)):
            if basename(tokens[k]) in SHELLS | {"git", "eval"} and not tokens[k].startswith("-"):
                yield from analyze(tokens[k:], depth)
                return
        return
    if prog in SHELLS:
        seen_c, k = False, i + 1
        while k < len(tokens):
            tok = tokens[k]
            if tok in SHELL_OPTS_WITH_ARG:
                k += 2
                continue
            if tok == "--":
                k += 1
                if seen_c and k < len(tokens):
                    yield from git_calls(tokens[k], depth + 1)
                return
            if tok[:1] in "-+" and len(tok) > 1:
                if not tok.startswith("--"):
                    seen_c = seen_c or "c" in tok[1:]
                    k += 2 if any(ch in "oO" for ch in tok[1:]) else 1
                else:
                    k += 1
                continue
            if seen_c:
                yield from git_calls(tok, depth + 1)
            return
        return
    if prog == "eval":
        yield from git_calls(" ".join(tokens[i + 1:]), depth + 1)
        return
    if prog != "git":
        return
    j = i + 1
    while j < len(tokens) and tokens[j].startswith("-"):
        j += 2 if tokens[j] in GIT_GLOBAL_OPTS_WITH_ARG else 1
    if j < len(tokens):
        yield tokens[j], tokens[j + 1:]


def parse(sub, args):
    events, positional, skip = [], [], False
    value_opts = VALUE_SHORT_OPTS.get(sub, "")
    for idx, arg in enumerate(args):
        if skip:
            skip = False
            continue
        if arg == "--":
            positional.extend(args[idx + 1:])
            break
        if arg.startswith("--") and len(arg) > 2:
            events.append(arg.split("=", 1)[0])
        elif arg.startswith("-") and len(arg) > 1:
            cluster = arg[1:]
            for pos, ch in enumerate(cluster):
                events.append("-" + ch)
                if ch in value_opts:
                    skip = pos == len(cluster) - 1
                    break
        else:
            positional.append(arg)
    return events, positional


def toggled(events, on, off):
    state = False
    for ev in events:
        if ev in on:
            state = True
        elif ev in off:
            state = False
    return state


def verdict(sub, args):
    events, positional = parse(sub, args)
    if sub == "checkout":
        if "-B" in events:
            return "`git checkout -B` resets an existing branch."
        if "-b" in events or "--orphan" in events:
            return None
        return "`git checkout` overwrites working-tree files; use `git switch <branch>` or `git switch -c <new>`."
    if sub == "switch":
        if "-C" in events or "--force-create" in events:
            return "`git switch -C/--force-create` resets an existing branch; use `-c`."
        if toggled(events, {"-f", "--force", "--discard-changes"}, {"--no-force", "--no-discard-changes"}):
            return "`git switch --force/--discard-changes` throws away local changes."
        return None
    if sub == "restore":
        staged = toggled(events, {"-S", "--staged"}, {"--no-staged"})
        worktree = toggled(events, {"-W", "--worktree"}, {"--no-worktree"})
        if staged and not worktree:
            return None
        return "`git restore` overwrites working-tree files."
    if sub == "stash":
        if positional and positional[0] in STASH_READ_ONLY:
            return None
        return "`git stash` removes uncommitted work from the tree."
    if sub == "reset":
        modes = [ev for ev in events if ev in {"--hard", "--merge", "--keep", "--soft", "--mixed"}]
        if modes and modes[-1] in {"--hard", "--merge", "--keep"}:
            return "`git reset --hard/--merge/--keep` destroys uncommitted work."
        return None
    if sub == "clean":
        if toggled(events, {"-n", "--dry-run"}, {"--no-dry-run"}):
            return None
        return "`git clean` deletes untracked files."
    if sub == "push":
        if toggled(events, {"-f", "--force"}, {"--no-force"}):
            return "`git push --force` disables every safety check, including `--force-with-lease`; use `--force-with-lease` alone."
        return None
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
        for sub, args in git_calls(command):
            reason = verdict(sub, args)
            if reason:
                deny(reason)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
