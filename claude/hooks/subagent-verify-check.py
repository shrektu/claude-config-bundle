#!/usr/bin/env python3
"""SubagentStop hook: a developer may not stop with code edits that no verify run has covered."""
import json
import os
import re
import sys

sys.dont_write_bytecode = True
from shell_words import runs_verify

GUARDED_TYPES = ("developer",)
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")
BASH_TOOL = "Bash"
DOC_SUFFIXES = (".md", ".txt", ".rst")
VERIFY_RESULTS = ("VERIFY PASS", "VERIFY FAIL")
STATE_PREFIX = "subagent-verify-check-"
FALLBACK_STATE_DIR = "/tmp"
MAX_LINE_BYTES = 2000000
RESULT_TEXT_KEYS = ("stdout", "stderr", "output")
STATE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")

REASON = ("subagent-verify-check: you edited code after your last verify run (or never ran one). "
          "Run the test_command through ~/.claude/bin/verify -- <command>, then report its summary lines.")


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
        if agent_type is not None and agent_type not in GUARDED_TYPES:
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
