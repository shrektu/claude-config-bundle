#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit|NotebookEdit) hook: a developer edits production code only after a red test run."""
import json
import os
import re
import sys
from enum import Enum

sys.dont_write_bytecode = True
from code_files import CODE_SUFFIXES
from shell_words import runs_verify

GUARDED_AGENT = "developer"
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
BASH_TOOL = "Bash"
PATH_KEYS = ("file_path", "notebook_path")
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs", "e2e", "testing"}
TEST_NAMES = tuple(re.compile(pattern) for pattern in (
    r"^test_.*\.py$",
    r"[_-]test\.py$",
    r"^conftest\.py$",
    r"\.(test|spec)\.[^.]+$",
    r"_test\.go$",
    r"Tests?\.(java|kt)$",
    r"Tests\.cs$",
    r"_spec\.rb$",
    r"^test_.*\.c$",
    r"_test\.(c|cc|cpp)$",
))
GIT_MARKER = ".git"
SHEBANG = "#!"
INLINE_TEST_MARKERS = ("#[test]", "#[cfg(test)]", "#[tokio::test]")
EXEMPT_LINE = re.compile(r"(?m)^[ \t]*tdd_exempt:[ \t]*\S")
VERIFY_FAIL_LINE = re.compile(r"(?m)^VERIFY FAIL exit=")
TRANSCRIPT_SUFFIX = ".jsonl"
SUBAGENTS_DIR = "subagents"
AGENT_FILE_PREFIX = "agent-"
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_LINE_BYTES = 2000000

REASON = ("tdd-guard: RED first. Write or extend the test from test_plan, run it through ~/.claude/bin/verify "
          "-- <command> and see VERIFY FAIL for the expected reason, then edit production code. Only the spawn "
          "prompt can exempt a task (`tdd_exempt: <reason>`).")


class FileKind(Enum):
    TEST = "test"
    SOURCE = "source"
    OTHER = "other"


def target_path(data):
    for key in PATH_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def new_content(tool, data):
    match tool:
        case "Edit":
            parts = [data.get("new_string")]
        case "Write":
            parts = [data.get("content")]
        case "MultiEdit":
            edits = data.get("edits")
            parts = [edit.get("new_string") for edit in edits if isinstance(edit, dict)] \
                if isinstance(edits, list) else []
        case "NotebookEdit":
            parts = [data.get("new_source")]
        case _:
            parts = []
    return "\n".join(part for part in parts if isinstance(part, str))


def starts_with_shebang(path, content):
    if content.startswith(SHEBANG):
        return True
    try:
        with open(path, "rb") as handle:
            return handle.read(len(SHEBANG)) == SHEBANG.encode()
    except OSError:
        return False


def repo_root(path, cwd):
    directory = os.path.dirname(path)
    while True:
        if os.path.lexists(os.path.join(directory, GIT_MARKER)):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    if isinstance(cwd, str) and os.path.isabs(cwd) and path.startswith(os.path.join(os.path.normpath(cwd), "")):
        return os.path.normpath(cwd)
    return None


def test_dir_segments(path, cwd):
    root = repo_root(path, cwd)
    scoped = os.path.relpath(path, root) if root else path
    return scoped.split(os.sep)[:-1]


def classify(path, content, cwd=None):
    if isinstance(cwd, str) and os.path.isabs(cwd) and not os.path.isabs(path):
        path = os.path.join(cwd, path)
    path = os.path.normpath(path.replace("\\", "/"))
    name = os.path.basename(path)
    if any(segment in TEST_DIRS for segment in test_dir_segments(path, cwd)) or any(p.search(name) for p in TEST_NAMES):
        return FileKind.TEST
    stem, dot, suffix = name.rpartition(".")
    if dot and stem:
        return FileKind.SOURCE if suffix.lower() in CODE_SUFFIXES else FileKind.OTHER
    return FileKind.SOURCE if starts_with_shebang(path, content) else FileKind.OTHER


def has_inline_test(content):
    return any(marker in content for marker in INLINE_TEST_MARKERS)


def is_test_edit(tool, data, cwd):
    path = target_path(data)
    content = new_content(tool, data)
    return has_inline_test(content) or (path is not None and classify(path, content, cwd) is FileKind.TEST)


def transcript_of(payload):
    explicit = payload.get("agent_transcript_path")
    if isinstance(explicit, str) and explicit:
        return explicit
    main = payload.get("transcript_path")
    agent_id = payload.get("agent_id")
    if not (isinstance(main, str) and main.endswith(TRANSCRIPT_SUFFIX)):
        return None
    if not (isinstance(agent_id, str) and AGENT_ID_RE.match(agent_id)):
        return None
    return os.path.join(main[:-len(TRANSCRIPT_SUFFIX)], SUBAGENTS_DIR,
                        f"{AGENT_FILE_PREFIX}{agent_id}{TRANSCRIPT_SUFFIX}")


def user_text(entry, content):
    if entry.get("isMeta"):
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in content
                     if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str))


def result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(item["text"] for item in content
                         if isinstance(item, dict) and isinstance(item.get("text"), str))
    return ""


def entries(transcript):
    with open(transcript, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line[:MAX_LINE_BYTES])
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def red_or_exempt(transcript, cwd):
    first_user = True
    test_seen = False
    test_edit_ids, verify_ids = set(), set()
    for entry in entries(transcript):
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if entry.get("type") == "user" and first_user:
            first_user = False
            if isinstance(content, (str, list)) and EXEMPT_LINE.search(user_text(entry, content)):
                return True
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                name, data = block.get("name"), block["input"]
                if name in EDIT_TOOLS and is_test_edit(name, data, cwd):
                    test_edit_ids.add(block.get("id"))
                elif name == BASH_TOOL and test_seen and isinstance(data.get("command"), str) \
                        and runs_verify(data["command"]):
                    verify_ids.add(block.get("id"))
            elif block.get("type") == "tool_result":
                use_id = block.get("tool_use_id")
                if use_id in test_edit_ids and not block.get("is_error"):
                    test_seen = True
                elif use_id in verify_ids and VERIFY_FAIL_LINE.search(result_text(block)):
                    return True
    return False


def deny():
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }))


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("agent_type") != GUARDED_AGENT:
            return
        tool = payload.get("tool_name")
        data = payload.get("tool_input")
        if tool not in EDIT_TOOLS or not isinstance(data, dict):
            return
        path = target_path(data)
        cwd = payload.get("cwd")
        if path is None or is_test_edit(tool, data, cwd):
            return
        if classify(path, new_content(tool, data), cwd) is not FileKind.SOURCE:
            return
        transcript = transcript_of(payload)
        if transcript is None or not os.path.isfile(transcript):
            return
        if not red_or_exempt(transcript, cwd):
            deny()
    except Exception:
        return


if __name__ == "__main__":
    main()
