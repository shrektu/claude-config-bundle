#!/usr/bin/env python3
"""SubagentStop hook: an implementer may not stop with code edits that no verify run has covered."""
import json
import os
import re
import shlex
import sys

IMPLEMENTER_TYPES = ("implementer", "implementer-hard", "implementer-opus")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")
BASH_TOOL = "Bash"
DOC_SUFFIXES = (".md", ".txt", ".rst")
VERIFY_NAME = "verify"
VERIFY_PATH_SUFFIX = "/bin/verify"
VERIFY_RESULTS = ("VERIFY PASS", "VERIFY FAIL")
STATE_PREFIX = "subagent-verify-check-"
FALLBACK_STATE_DIR = "/tmp"
MAX_SHELL_DEPTH = 3
MAX_LINE_BYTES = 2000000
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
RESULT_TEXT_KEYS = ("stdout", "stderr", "output")
STATE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")

REASON = ("subagent-verify-check: you edited code after your last verify run (or never ran one). "
          "Run the test_command through ~/.claude/bin/verify -- <command>, then report its summary lines.")


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


def edited_path(data):
    for key in PATH_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def is_code_path(path):
    return isinstance(path, str) and bool(path) and not path.lower().endswith(DOC_SUFFIXES)


def result_text(block, entry):
    parts = []
    content = block.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    extra = entry.get("toolUseResult")
    if isinstance(extra, str):
        parts.append(extra)
    elif isinstance(extra, dict):
        parts.extend(extra[key] for key in RESULT_TEXT_KEYS if isinstance(extra.get(key), str))
    return "\n".join(parts)


def needs_verify(transcript):
    last_edit = -1
    verify_uses, results = [], {}
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            try:
                entry = json.loads(line[:MAX_LINE_BYTES])
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "tool_use":
                    name = block.get("name")
                    data = block.get("input")
                    if not isinstance(data, dict):
                        continue
                    if name in EDIT_TOOLS and is_code_path(edited_path(data)):
                        last_edit = index
                    elif name == BASH_TOOL and isinstance(data.get("command"), str) \
                            and runs_verify(data["command"]):
                        verify_uses.append((index, block.get("id")))
                elif kind == "tool_result":
                    use_id = block.get("tool_use_id")
                    if isinstance(use_id, str):
                        results[use_id] = result_text(block, entry)
    if last_edit < 0:
        return False
    for index, use_id in verify_uses:
        if index > last_edit and any(mark in results.get(use_id, "") for mark in VERIFY_RESULTS):
            return False
    return True


def state_file(payload):
    directory = payload.get("scratchpad_dir")
    if not isinstance(directory, str) or not os.path.isdir(directory):
        directory = FALLBACK_STATE_DIR
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        agent_id = str(payload.get("session_id", "unknown"))
    return os.path.join(directory, STATE_PREFIX + STATE_ID_RE.sub("_", agent_id)[:120])


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("stop_hook_active"):
            return 0
        agent_type = payload.get("agent_type")
        if agent_type is not None and agent_type not in IMPLEMENTER_TYPES:
            return 0
        transcript = payload.get("agent_transcript_path") or payload.get("transcript_path")
        if not isinstance(transcript, str) or not os.path.isfile(transcript):
            return 0
        if not needs_verify(transcript):
            return 0
        marker = state_file(payload)
        if os.path.exists(marker):
            return 0
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(transcript)
        except OSError:
            pass
        print(REASON, file=sys.stderr)
        return 2
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
