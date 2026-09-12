#!/usr/bin/env python3
"""PreToolUse(Read) hook: denies whole-file reads of large files, offering an outline instead."""
import json
import os
import re
import sys

MAX_BYTES = int(os.environ.get("READ_GUARD_MAX_BYTES", 16000))
SNIFF_BYTES = 8192
MAX_SCAN_BYTES = 2_000_000
MAX_OUTLINE_LINES = 40
FALLBACK_LINES = 15
TRUNCATE_LEN = 100
REASON_BUDGET = 4000
BINARY_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "pdf", "ipynb"}

INSTRUCTION = (
    "Read it in slices with offset/limit (≤ 250 lines each) or grep for the symbol you need; "
    "do not read the whole file."
)

DEFINITION_RE = re.compile(
    r"^( {0,4}(def|class)\s+\w+"
    r"|(export\s+)?(function|class|interface|type|const)\s+\w+"
    r"|(pub\s+)?(fn|impl|struct|enum|trait)\b"
    r"|(func|type)\s+\w+"
    r"|[A-Za-z_][\w:<>*& ]+\("
    r"|[ \t]*#{1,6}\s"
    r"|[A-Za-z_][\w-]*:"
    r"|\[)"
)


def truncate(line):
    line = line.rstrip("\n")
    return line if len(line) <= TRUNCATE_LEN else line[:TRUNCATE_LEN]


def build_outline(lines):
    matches = [(n, line) for n, line in enumerate(lines, start=1) if DEFINITION_RE.match(line)]
    if matches:
        shown = matches[:MAX_OUTLINE_LINES]
        outline = [f"{n}: {truncate(line)}" for n, line in shown]
        if len(matches) > MAX_OUTLINE_LINES:
            outline.append(f"... {len(matches) - MAX_OUTLINE_LINES} more")
        return outline
    return [f"{i}: {truncate(line)}" for i, line in enumerate(lines[:FALLBACK_LINES], start=1)]


def deny(path, line_count, approx_tokens, outline, truncated):
    count_desc = f"≥ {line_count} lines" if truncated else f"{line_count} lines"
    header = (
        f"read-guard: {path} is {count_desc} (~{approx_tokens} tokens), too large for a whole-file read. "
        f"{INSTRUCTION}\nOutline:\n"
    )
    lines = list(outline)
    reason = header + "\n".join(lines)
    while len(reason) > REASON_BUDGET and lines:
        lines.pop()
        reason = header + "\n".join(lines)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") not in (None, "Read"):
            return
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        if "offset" in tool_input or "limit" in tool_input:
            return
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            return
        if not os.path.isfile(file_path):
            return
        base = os.path.basename(file_path)
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if ext in BINARY_EXTENSIONS:
            return
        size = os.path.getsize(file_path)
        if size <= MAX_BYTES:
            return
        with open(file_path, "rb") as f:
            head = f.read(SNIFF_BYTES)
        if b"\x00" in head:
            return
        truncated = size > MAX_SCAN_BYTES
        with open(file_path, "rb") as f:
            raw = f.read(MAX_SCAN_BYTES) if truncated else f.read()
        content = raw.decode("utf-8", errors="replace")
        lines = content.splitlines()
        deny(file_path, len(lines), size // 4, build_outline(lines), truncated)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
