#!/usr/bin/env python3
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

AGENT_ID_KEY = "agent_id"
TRANSCRIPT_KEY = "transcript_path"
SESSION_KEY = "session_id"
EVENT_KEY = "hook_event_name"
SUBAGENT_DIR = "subagents"
SUBAGENT_FILE_RE = re.compile(r"^agent-.+\.jsonl$")
TAIL_BYTES = 512 * 1024
DEFAULT_THRESHOLD = 500_000
DEFAULT_STEP = 50_000
DEFAULT_STATE_DIR = "~/.cache/claude-context-guard"
TOKENS_PER_K = 1000
STATE_READ_ERRORS = (OSError, ValueError)
HOOK_ERRORS = (OSError, ValueError, TypeError)
USAGE_KEYS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
ASSISTANT_TYPE = "assistant"
SYSTEM_TYPE = "system"
COMPACT_BOUNDARY_SUBTYPE = "compact_boundary"
USER_TEXT = (
    "Kontekst sesji: {k}k tokenów (próg {t}k). Przy najbliższym kamieniu "
    "milowym zrób /compact z fokusem — dalsze tury są coraz droższe i "
    "wolniejsze."
)
MODEL_TEXT = (
    "Context is {k}k tokens (threshold {t}k). At the next milestone "
    "(round reported, findings sent, commit made) make sure the progress "
    "log is current, then ask Sebastian to run /compact and propose the "
    "focus line; /compact is a user command you cannot run."
)


@dataclass(frozen=True, slots=True)
class Limits:
    """Warning threshold and re-warn step in tokens."""

    threshold: int
    step: int


def read_limits() -> Limits:
    """Read the threshold and step from the environment."""
    return Limits(
        int(os.environ.get("CONTEXT_GUARD_TOKENS", DEFAULT_THRESHOLD)),
        int(os.environ.get("CONTEXT_GUARD_STEP", DEFAULT_STEP)),
    )


def is_subagent_transcript(path: str) -> bool:
    """Tell whether the transcript path belongs to a subagent."""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return (
        bool(parts)
        and SUBAGENT_DIR in parts[:-1]
        and bool(SUBAGENT_FILE_RE.match(parts[-1]))
    )


def string_field(payload: dict[str, object], key: str) -> str | None:
    """Return the stripped non-empty string value of the key."""
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_entry(line: str) -> dict[str, object] | None:
    """Return the transcript line as a JSON object, if it is one."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def is_compact_boundary(entry: dict[str, object]) -> bool:
    """Tell whether the entry marks a /compact in the transcript."""
    return (
        entry.get("type") == SYSTEM_TYPE
        and entry.get("subtype") == COMPACT_BOUNDARY_SUBTYPE
    )


def usage_total(entry: dict[str, object]) -> int | None:
    """Return the context size of an assistant entry, if any."""
    if entry.get("type") != ASSISTANT_TYPE:
        return None
    message = entry.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    counts = (usage.get(key) for key in USAGE_KEYS)
    return sum(count for count in counts if isinstance(count, int))


def transcript_tail_lines(path: str) -> list[str]:
    """Return the complete lines within the last TAIL_BYTES bytes."""
    with Path(path).open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        start = max(0, size - TAIL_BYTES)
        handle.seek(start)
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if start > 0 else lines


def context_size(path: str) -> int | None:
    """Return the context size after the last compaction, if measured."""
    for line in reversed(transcript_tail_lines(path)):
        entry = parse_entry(line)
        if entry is None:
            continue
        if is_compact_boundary(entry):
            return None
        total = usage_total(entry)
        if total is not None:
            return total
    return None


def load_last_warned(state_file: Path) -> int | None:
    """Return the token count of the last warning, if recorded."""
    try:
        state = json.loads(state_file.read_text())
    except STATE_READ_ERRORS:
        return None
    if not isinstance(state, dict):
        return None
    value = state.get("last_warned")
    return value if isinstance(value, int) else None


def save_last_warned(state_file: Path, size: int | None) -> None:
    """Record the token count of the last warning, or clear it."""
    if size is None:
        state_file.unlink(missing_ok=True)
        return
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_warned": size}))


def warning_output(event: str, size: int, limits: Limits) -> str:
    """Build the hook JSON carrying both warning texts."""
    values = {
        "k": size // TOKENS_PER_K,
        "t": limits.threshold // TOKENS_PER_K,
    }
    return json.dumps(
        {
            "systemMessage": USER_TEXT.format(**values),
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": MODEL_TEXT.format(**values),
            },
        }
    )


def state_file_for(session_id: str) -> Path:
    """Return the state file path of a session."""
    directory = Path(
        os.environ.get("CONTEXT_GUARD_STATE_DIR", DEFAULT_STATE_DIR)
    ).expanduser()
    return directory / f"{Path(session_id).name}.json"


def is_main_session(payload: dict[str, object], transcript: str) -> bool:
    """Tell whether the payload comes from the main session."""
    if string_field(payload, AGENT_ID_KEY):
        return False
    return not is_subagent_transcript(transcript)


def due_warning(
    state_file: Path, size: int, limits: Limits, event: str
) -> str | None:
    """Return the warning JSON when this size is due, updating state."""
    if size < limits.threshold:
        save_last_warned(state_file, None)
        return None
    last_warned = load_last_warned(state_file)
    if last_warned is not None and size < last_warned + limits.step:
        return None
    save_last_warned(state_file, size)
    return warning_output(event, size, limits)


def evaluate(payload: dict[str, object]) -> str | None:
    """Return the warning JSON for a main-session payload, if due."""
    transcript = string_field(payload, TRANSCRIPT_KEY)
    session_id = string_field(payload, SESSION_KEY)
    event = string_field(payload, EVENT_KEY)
    if not (transcript and session_id and event):
        return None
    if not is_main_session(payload, transcript):
        return None
    size = context_size(transcript)
    if size is None:
        return None
    state_file = state_file_for(session_id)
    return due_warning(state_file, size, read_limits(), event)


def main() -> None:
    """Run the hook and fail open on any error."""
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        output = evaluate(payload)
    except HOOK_ERRORS:
        return
    if output:
        print(output)


if __name__ == "__main__":
    main()
