#!/usr/bin/env python3
"""PreToolUse(Bash) hook: a command may not write a code file inside a git work tree."""
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True
from code_files import language_of  # noqa: E402
from shell_words import (  # noqa: E402
    ENV_ASSIGNMENT,
    MAX_SHELL_DEPTH,
    SHELLS,
    parse_segment,
    split_heredocs,
    split_segments,
    strip_prefix,
)

BASH_TOOL = "Bash"
GIT_MARKER = ".git"
VARIABLE_MARKER = "$"
VARIABLE = re.compile(r"\$\{(\w+)\}|\$(\w+)")
HOME_VARIABLE = "HOME"
PWD_VARIABLE = "PWD"
DIRECTORY_SCAN_CAP = 2000
CHANGE_DIR = "cd"
TEE = "tee"
IN_PLACE_EDITORS = frozenset({"sed", "gsed", "perl"})
IN_PLACE_FLAG = re.compile(r"^-[nEpalswr]*i")
LONG_IN_PLACE_FLAG = "--in-place"
TRANSFER_COMMANDS = frozenset({"cp", "mv", "install", "rsync"})
MIN_TRANSFER_OPERANDS = 2
MIN_CD_WORDS = 2
TARGET_DIR_FLAGS = frozenset({"-t", "--target-directory"})
TARGET_DIR_PREFIX = "--target-directory="
VALUE_FLAGS = frozenset({"-m", "-o", "-g", "-S", "--mode", "--owner", "--group"})
INTERPRETER = re.compile(r"^(python[0-9.]*|node|nodejs)$")
SCRIPT_FLAGS = frozenset({"-c", "-e", "--eval", "-p"})
SHELL_COMMAND_FLAG = "-c"
HEREDOC_MARK = "<<"
WRITE_CALL = re.compile(r"write_text|write_bytes|writeFile|appendFile|\bopen\([^\n]*?[\"'][wa][bt+]*[\"']")
STRING_LITERAL = re.compile(r"[\"']([^\"'\n]+)[\"']")
REASON = (
    "bash-write-guard: `{how}` writes {path}, a code file inside a git work tree — write code with "
    "Edit/Write — the Edit/Write hooks (tdd-guard, comment-guard, lint-guard) never see Bash writes."
)


@dataclass(frozen=True, slots=True)
class Offense:
    how: str
    path: Path


@dataclass(slots=True)
class Scope:
    cwd: Path
    variables: dict[str, str]


def new_scope(cwd):
    return Scope(cwd, {HOME_VARIABLE: str(Path.home()), PWD_VARIABLE: str(cwd)})


def expand(raw, scope):
    def value_of(match):
        return scope.variables.get(match.group(1) or match.group(2), match.group(0))

    return VARIABLE.sub(value_of, raw)


def record_assignments(words, scope):
    for word in words:
        if not ENV_ASSIGNMENT.match(word):
            return
        name, _, value = word.partition("=")
        scope.variables[name] = expand(value, scope)


def resolve(raw, cwd):
    return (cwd / Path(raw).expanduser()).resolve()


def holds_code(directory):
    seen = 0
    for _, _, names in directory.walk():
        for name in names:
            seen += 1
            if seen > DIRECTORY_SCAN_CAP or is_code(Path(name)):
                return True
    return False


def work_tree_of(path):
    return next((directory for directory in (path, *path.parents) if (directory / GIT_MARKER).exists()), None)


def change_dir(words, scope):
    target = expand(words[1], scope) if len(words) >= MIN_CD_WORDS else VARIABLE_MARKER
    if VARIABLE_MARKER not in target:
        scope.cwd = resolve(target, scope.cwd)
        scope.variables[PWD_VARIABLE] = str(scope.cwd)


def is_code(path):
    return language_of(str(path), "") is not None


def code_write(raw, scope, how):
    expanded = expand(raw, scope)
    if VARIABLE_MARKER in expanded:
        unresolved = Path(expanded)
        if is_code(unresolved) and work_tree_of(scope.cwd) is not None:
            return Offense(how, unresolved)
        return None
    path = resolve(expanded, scope.cwd)
    if is_code(path) and work_tree_of(path) is not None:
        return Offense(how, path)
    return None


def first_offense(offenses):
    return next((offense for offense in offenses if offense is not None), None)


def options_and_operands(args):
    operands, target_dir, skip = [], None, False
    for index, arg in enumerate(args):
        if skip:
            skip = False
        elif arg in TARGET_DIR_FLAGS and index + 1 < len(args):
            target_dir, skip = args[index + 1], True
        elif arg.startswith(TARGET_DIR_PREFIX):
            target_dir = arg.removeprefix(TARGET_DIR_PREFIX)
        elif arg in VALUE_FLAGS:
            skip = True
        elif not arg.startswith("-"):
            operands.append(arg)
    return operands, target_dir


def unresolved_transfer(name, destination, sources, scope):
    tree = work_tree_of(scope.cwd)
    if tree is None:
        return None
    target = Path(destination)
    if is_code(target):
        return Offense(name, target)
    if not (destination.endswith("/") or not target.suffix):
        return None
    for source in (expand(operand, scope) for operand in sources):
        source_path = resolve(source, scope.cwd)
        if VARIABLE_MARKER in source or source_path.is_relative_to(tree):
            continue
        if is_code(source_path) or (source_path.is_dir() and holds_code(source_path)):
            return Offense(name, target)
    return None


def transfer_offense(name, args, scope):
    operands, target_dir = options_and_operands(args)
    if target_dir is None and len(operands) < MIN_TRANSFER_OPERANDS:
        return None
    destination = expand(target_dir if target_dir is not None else operands[-1], scope)
    sources = operands if target_dir is not None else operands[:-1]
    if VARIABLE_MARKER in destination:
        return unresolved_transfer(name, destination, sources, scope)
    dest_path = resolve(destination, scope.cwd)
    tree = work_tree_of(dest_path)
    if tree is None:
        return None
    into_directory = target_dir is not None or destination.endswith("/") or dest_path.is_dir()
    for source in (expand(operand, scope) for operand in sources):
        source_path = resolve(source, scope.cwd)
        if VARIABLE_MARKER in source or source_path.is_relative_to(tree):
            continue
        if source_path.is_dir():
            if holds_code(source_path):
                return Offense(name, dest_path)
            continue
        written = dest_path / Path(source).name if into_directory else dest_path
        if is_code(written):
            return Offense(name, written)
    return None


def script_text(args, segment, bodies):
    inline = next((args[index + 1] for index, arg in enumerate(args[:-1]) if arg in SCRIPT_FLAGS), "")
    return "\n".join([inline, *bodies]) if HEREDOC_MARK in segment else inline


def script_offense(name, text, scope):
    if not WRITE_CALL.search(text):
        return None
    return first_offense(code_write(literal, scope, name) for literal in STRING_LITERAL.findall(text))


def in_place_offense(name, args, scope):
    if not any(IN_PLACE_FLAG.match(arg) or arg.startswith(LONG_IN_PLACE_FLAG) for arg in args):
        return None
    return first_offense(code_write(arg, scope, f"{name} -i") for arg in args if not arg.startswith("-"))


def command_offense(words, segment, bodies, scope, depth):
    name, args = Path(words[0]).name, words[1:]
    if name == TEE:
        return first_offense(code_write(arg, scope, TEE) for arg in args if not arg.startswith("-"))
    if name in IN_PLACE_EDITORS:
        return in_place_offense(name, args, scope)
    if name in TRANSFER_COMMANDS:
        return transfer_offense(name, args, scope)
    if INTERPRETER.match(name):
        return script_offense(name, script_text(args, segment, bodies), scope)
    if name in SHELLS and depth < MAX_SHELL_DEPTH and SHELL_COMMAND_FLAG in args[:-1]:
        return scan(args[args.index(SHELL_COMMAND_FLAG) + 1], scope, depth + 1)
    return None


def scan(command, scope, depth=0):
    heredocs = split_heredocs(command)
    for segment in split_segments(heredocs.command):
        parsed = parse_segment(segment)
        record_assignments(parsed.words, scope)
        offense = first_offense(code_write(target, scope, ">") for target in parsed.targets)
        words = strip_prefix(parsed.words)
        if words and Path(words[0]).name == CHANGE_DIR:
            change_dir(words, scope)
        elif words and offense is None:
            offense = command_offense(words, segment, heredocs.bodies, scope, depth)
        if offense is not None:
            return offense
    return None


def deny(offense):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON.format(how=offense.how, path=offense.path),
        }
    }))


def hook():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") != BASH_TOOL:
            return
        data = payload.get("tool_input")
        command = data.get("command") if isinstance(data, dict) else None
        if not isinstance(command, str):
            return
        offense = scan(command, new_scope(Path(payload.get("cwd") or Path.cwd())))
        if offense is not None:
            deny(offense)
    except Exception:
        return


if __name__ == "__main__":
    hook()
