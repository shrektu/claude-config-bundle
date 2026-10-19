#!/usr/bin/env python3
import json
import os
import re
import sys
from typing import NoReturn

TOOL_PREFIX = "mcp__codex-worker__"
RELAY_AGENTS = frozenset({"codex-runner", "plan-gate-runner"})
IMPLEMENT_TOOL = TOOL_PREFIX + "codex_implement"
AGENT_KEYS = ("agent_type", "subagent_type")
AGENT_ID_KEYS = ("agent_id",)
TRANSCRIPT_KEYS = ("agent_transcript_path", "transcript_path")
SUBAGENT_DIR = "subagents"
SUBAGENT_FILE_RE = re.compile(r"^agent-.+\.jsonl$")
OFF_VALUES = {"off", "0", "false", "no"}

REASON = (
    "Codex reviews run through the `codex-runner` agent (code gate) or the "
    "`plan-gate-runner` agent (plan gate: Gemini Flash first, Codex as "
    "fallback). Never a direct tool call: a direct call blocks "
    "you for 120s before the MCP tool moves itself to the background, "
    "and that time is lost every round.\n"
    "Spawn the matching runner instead, in the SAME tool batch as your own "
    "verify run, and hand it: "
    "diff_base (mode code — never paste the diff) or what_changed (mode plan), review_focus, "
    "acceptance_criteria, project_path (absolute), extra_context and `mode` "
    "(plan = critique of your plan, gpt-6.1-sol high | "
    "code = final review of the diff, "
    "gpt-6.1-sol medium, bugs only — always name it). "
    "Then work on your own review while it runs.\n"
    "Escape hatch when the runner itself is broken: CLAUDE_CODEX_GATE=off."
)

IMPLEMENT_REASON = (
    "codex_implement is disabled for every caller: the escalation was "
    "removed in workflow v2. There is one implementer, `implementer`; a "
    "blocked task stays blocked with its evidence. Codex only reviews, "
    "through the `codex-runner` agent."
)


def deny(reason: str) -> NoReturn:
    """Print a deny decision and exit."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"codex-gate: {reason}",
        }
    }))
    sys.exit(0)


def is_subagent_transcript(path):
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return bool(parts) and SUBAGENT_DIR in parts[:-1] and bool(SUBAGENT_FILE_RE.match(parts[-1]))


def first_str(payload, keys):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        tool = payload.get("tool_name")
        if not isinstance(tool, str) or not tool.startswith(TOOL_PREFIX):
            return
        if tool == IMPLEMENT_TOOL:
            deny(IMPLEMENT_REASON)
        if os.environ.get("CLAUDE_CODEX_GATE", "").strip().lower() in OFF_VALUES:
            return

        agent = first_str(payload, AGENT_KEYS)
        if agent is not None and agent not in RELAY_AGENTS:
            deny(REASON)

        transcripts = [payload.get(key) for key in TRANSCRIPT_KEYS]
        transcripts = [path for path in transcripts if isinstance(path, str) and path.strip()]
        if any(is_subagent_transcript(path) for path in transcripts):
            return
        if agent in RELAY_AGENTS and first_str(payload, AGENT_ID_KEYS):
            return
        if transcripts:
            deny(REASON)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
