"""Shell command parsing shared by the hooks: does a Bash command run ~/.claude/bin/verify."""
import os
import re
import shlex

VERIFY_NAME = "verify"
VERIFY_PATH_SUFFIX = "/bin/verify"
MAX_SHELL_DEPTH = 3
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
KEYWORDS = {"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "case", "esac", "!", "function"}
WRAPPERS = {"env", "command", "builtin", "exec", "sudo", "doas", "nice", "ionice", "time", "nohup",
            "timeout", "stdbuf", "unbuffer", "xargs", "chronic"}
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
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
SHELL_OPTS_WITH_ARG = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
SEGMENT_BREAKS = ";&|\n()"


def split_segments(command):
    parts, current, quote, i, n = [], [], "", 0, len(command)
    while i < n:
        char = command[i]
        if char == "\\" and quote != "'":
            current.append(command[i:i + 2])
            i += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            current.append(char)
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char in SEGMENT_BREAKS:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    parts.append("".join(current))
    return [p for p in parts if p.strip()]


def tokens_of(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def is_verify_word(word):
    return word == VERIFY_NAME or word.endswith(VERIFY_PATH_SUFFIX)


def strip_prefix(tokens):
    i, moved = 0, True
    while moved and i < len(tokens):
        moved = False
        while i < len(tokens) and (tokens[i] in KEYWORDS or ENV_ASSIGNMENT.match(tokens[i])):
            i, moved = i + 1, True
        if i < len(tokens) and os.path.basename(tokens[i]) in WRAPPERS:
            i, moved = skip_wrapper(tokens, i), True
    return tokens[i:]


def skip_wrapper(tokens, i):
    word = os.path.basename(tokens[i])
    value_opts = WRAPPER_VALUE_OPTS.get(word, ())
    optional_opts = WRAPPER_OPTIONAL_VALUE_OPTS.get(word, ())
    i += 1
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] != "-":
        option = tokens[i]
        i += 1
        if "=" in option or option in optional_opts:
            continue
        if option in value_opts and i < len(tokens):
            i += 1
    extra = WRAPPER_VALUE_ARGS.get(word, 0)
    while extra > 0 and i < len(tokens) and not tokens[i].startswith("-"):
        i, extra = i + 1, extra - 1
    return i


def shell_runs_verify(tokens, depth):
    seen_c, k = False, 1
    while k < len(tokens):
        tok = tokens[k]
        if tok in SHELL_OPTS_WITH_ARG:
            k += 2
            continue
        if tok == "--":
            k += 1
            return seen_c and k < len(tokens) and runs_verify(tokens[k], depth + 1)
        if tok[:1] in "-+" and len(tok) > 1:
            if not tok.startswith("--"):
                seen_c = seen_c or "c" in tok[1:]
                k += 2 if any(ch in "oO" for ch in tok[1:]) else 1
            else:
                k += 1
            continue
        return seen_c and runs_verify(tok, depth + 1)
    return False


def segment_runs_verify(text, depth=0):
    tokens = strip_prefix(tokens_of(text))
    if not tokens:
        return False
    if is_verify_word(tokens[0]) or is_verify_word(os.path.basename(tokens[0])):
        return True
    if os.path.basename(tokens[0]) in SHELLS and depth < MAX_SHELL_DEPTH:
        return shell_runs_verify(tokens, depth)
    return False


def runs_verify(command, depth=0):
    if depth > MAX_SHELL_DEPTH:
        return False
    return any(segment_runs_verify(segment, depth) for segment in split_segments(command))
