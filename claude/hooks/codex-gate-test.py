#!/usr/bin/env python3
"""Regression matrix for codex-gate.py (the sibling file by default; pass another path as argv[1])."""
import json, subprocess, os, sys
from typing import Any

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex-gate.py")
CODEX = "mcp__codex-worker__codex_review_changes"
CODEX_IMPLEMENT = "mcp__codex-worker__codex_implement"
STRONG = "implementer-strong"
PROJECTS = "__HOME__/.claude/projects"
SESSION = "90942b38-0519-4808-bbac-296fd5fe5513"
MAIN = f"{PROJECTS}/-home-sebastian-projects-cloud/{SESSION}.jsonl"
SUB = f"{PROJECTS}/-home-sebastian-projects-cloud/{SESSION}/subagents/agent-a4f3eb035e316a448.jsonl"
NESTED_SUB = f"{PROJECTS}/-home-sebastian-projects-cloud/{SESSION}/subagents/deeper/agent-a56a8c6f73036aa05.jsonl"
# CLAUDE_CODE_PROJECT_DIR_NAME=subagents puts a MAIN transcript under a directory called "subagents".
SPOOFED = f"{PROJECTS}/subagents/{SESSION}.jsonl"
AGENT_ID = "a41b0d4bd296103f3"


def run(
    payload: dict[str, Any], env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    proc = subprocess.run([sys.executable, hook], input=json.dumps(payload), capture_output=True,
                          text=True, env={**os.environ, **(env or {})})
    return proc.returncode, proc.stdout, proc.stderr


def denies(out: str) -> bool:
    """A deny is only valid if it is the exact contract the other hooks in this directory use."""
    try:
        block = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return False
    return (block.get("hookEventName") == "PreToolUse"
            and block.get("permissionDecision") == "deny"
            and "codex-runner" in block.get("permissionDecisionReason", ""))


deny = [
    ({"tool_name": CODEX, "transcript_path": MAIN}, "main session by transcript path"),
    ({"tool_name": CODEX, "transcript_path": MAIN, "agent_type": "claude"}, "a commanding session must use the relay"),
    ({"tool_name": CODEX, "transcript_path": SUB, "agent_type": "general-purpose"}, "another agent must use the relay"),
    ({"tool_name": CODEX, "agent_type": "Explore"}, "agent_type wins over a missing path"),
    ({"tool_name": "mcp__codex-worker__anything_else", "transcript_path": MAIN}, "whole server is gated"),
    ({"tool_name": CODEX, "transcript_path": MAIN, "subagent_type": "Explore"}, "subagent_type key is read too"),
    ({"tool_name": CODEX, "transcript_path": MAIN, "agent_type": "codex-runner"},
     "`claude --agent codex-runner` on a main session is not a spawned runner"),
    ({"tool_name": CODEX, "transcript_path": MAIN, "agent_type": "codex-runner", "agent_id": ""},
     "an empty agent id does not back the agent name"),
    ({"tool_name": CODEX, "transcript_path": SPOOFED},
     "a main transcript under a project dir named subagents is still a main session"),
    ({"tool_name": CODEX, "transcript_path": SPOOFED, "agent_type": "codex-runner"},
     "the spoofed path does not rescue an unbacked runner name"),
    ({"tool_name": CODEX, "transcript_path": f"{PROJECTS}/proj/{SESSION}/subagents/{SESSION}.jsonl"},
     "a subagents directory without an agent- transcript is not a subagent"),
    ({"tool_name": CODEX, "transcript_path": f"{PROJECTS}/proj/{SESSION}/agent-a4f3eb035e316a448.jsonl"},
     "an agent- file outside a subagents directory is not a subagent"),
    (
        {"tool_name": CODEX_IMPLEMENT, "transcript_path": MAIN},
        "main session cannot call codex_implement",
    ),
    (
        {
            "tool_name": CODEX_IMPLEMENT,
            "transcript_path": SUB,
            "agent_type": "implementer",
        },
        "the plain implementer is not a relay",
    ),
    (
        {
            "tool_name": CODEX_IMPLEMENT,
            "transcript_path": MAIN,
            "agent_type": STRONG,
        },
        "`claude --agent implementer-strong` is not a spawned relay",
    ),
    (
        {
            "tool_name": CODEX_IMPLEMENT,
            "transcript_path": MAIN,
            "agent_type": STRONG,
            "agent_id": "",
        },
        "an empty agent id does not back the implementer-strong name",
    ),
    (
        {
            "tool_name": CODEX,
            "transcript_path": SUB,
            "agent_type": "implementer-strong-impostor",
        },
        "a name that only starts with a relay name is not a relay",
    ),
]
PLAN_GATE = "plan-gate-runner"
deny.append(
    (
        {"tool_name": CODEX, "transcript_path": MAIN, "agent_type": PLAN_GATE},
        "`claude --agent plan-gate-runner` on a main session is no runner",
    )
)
deny.extend(
    [
        (
            {
                "tool_name": CODEX_IMPLEMENT,
                "transcript_path": SUB,
                "agent_type": STRONG,
            },
            "the removed escalation agent on its own transcript",
        ),
        (
            {
                "tool_name": CODEX_IMPLEMENT,
                "transcript_path": MAIN,
                "agent_type": STRONG,
                "agent_id": AGENT_ID,
            },
            "a spawned agent of the removed name is no relay",
        ),
        (
            {"tool_name": CODEX_IMPLEMENT, "transcript_path": SUB},
            "subagent transcript without an agent type",
        ),
        (
            {"tool_name": CODEX_IMPLEMENT, "agent_type": "codex-runner"},
            "a relay agent may not implement",
        ),
        (
            {
                "tool_name": CODEX_IMPLEMENT,
                "transcript_path": SUB,
                "agent_type": "codex-runner",
                "agent_id": AGENT_ID,
            },
            "a spawned relay may not implement",
        ),
        ({"tool_name": CODEX_IMPLEMENT}, "no session evidence at all"),
        (
            {"tool_name": CODEX, "transcript_path": SUB, "agent_type": STRONG},
            "the removed agent is no review relay either",
        ),
    ]
)
allow = [
    ({"tool_name": CODEX, "transcript_path": SUB, "agent_type": "codex-runner"}, "runner on its own transcript"),
    ({"tool_name": CODEX, "transcript_path": NESTED_SUB}, "a nested subagent transcript still counts"),
    ({"tool_name": CODEX, "agent_transcript_path": SUB, "transcript_path": MAIN, "agent_type": "codex-runner"},
     "runner reporting the parent transcript beside its own"),
    ({"tool_name": CODEX, "transcript_path": MAIN, "agent_type": "codex-runner", "agent_id": AGENT_ID},
     "spawned runner identified by agent id"),
    ({"tool_name": CODEX, "agent_type": "codex-runner"}, "runner without any path, fail open"),
    ({"tool_name": CODEX, "transcript_path": SUB}, "unnamed subagent, fail open"),
    ({"tool_name": CODEX}, "no session evidence at all, fail open"),
    ({"tool_name": "Bash", "tool_input": {"command": "ls"}, "transcript_path": MAIN}, "other tools untouched"),
    ({"tool_name": "Agent", "transcript_path": MAIN}, "agent spawns untouched"),
]
allow.append(
    (
        {"tool_name": CODEX, "transcript_path": SUB, "agent_type": PLAN_GATE},
        "plan-gate-runner on its own subagent transcript",
    )
)
garbage = ["", "null", "[]", "{", '{"tool_name": 42}', '{"tool_name": null}', '{"tool_name": "' + CODEX + '", "transcript_path": 7}']

bad = 0
for payload, label in deny:
    rc, out, err = run(payload)
    if not (rc == 0 and denies(out) and err == ""):
        bad += 1
        print(f"DENY FAIL ({label}): rc={rc} out={out[:200]!r} err={err[:120]!r}")
for payload, label in allow:
    rc, out, err = run(payload)
    if not (rc == 0 and out.strip() == "" and err == ""):
        bad += 1
        print(f"ALLOW FAIL ({label}): rc={rc} out={out[:200]!r} err={err[:120]!r}")
for raw in garbage:
    proc = subprocess.run([sys.executable, hook], input=raw, capture_output=True, text=True)
    if not (proc.returncode == 0 and proc.stdout.strip() == "" and proc.stderr == ""):
        bad += 1
        print(f"GARBAGE FAIL {raw!r}: rc={proc.returncode} out={proc.stdout[:150]!r} err={proc.stderr[:120]!r}")

rc, out, err = run({"tool_name": CODEX, "transcript_path": MAIN}, env={"CLAUDE_CODEX_GATE": "off"})
if not (rc == 0 and out.strip() == "" and err == ""):
    bad += 1
    print(f"ESCAPE HATCH FAIL: rc={rc} out={out[:200]!r} err={err[:120]!r}")

for implement_payload in (
    {"tool_name": CODEX_IMPLEMENT, "transcript_path": MAIN},
    {"tool_name": CODEX_IMPLEMENT, "transcript_path": SUB},
    {"tool_name": CODEX_IMPLEMENT},
):
    rc, out, err = run(implement_payload, env={"CLAUDE_CODEX_GATE": "off"})
    if not (rc == 0 and denies(out) and err == ""):
        bad += 1
        print(
            f"IMPLEMENT UNDER ESCAPE HATCH FAIL: {implement_payload} "
            f"out={out[:200]!r}"
        )

rc, out, err = run({"tool_name": CODEX, "transcript_path": MAIN})
reason = ""
if out.strip():
    reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
needles = ["gpt-6.1-sol medium", "plan-gate-runner", "Gemini Flash"]
missing = [needle for needle in needles if needle not in reason]
stale = [
    word
    for word in ("gpt-6-astra", STRONG, "Argon", "gpt-6.1-sol high,")
    if word in reason
]
if missing or stale:
    bad += 1
    print(f"MESSAGE FAIL: missing={missing} stale={stale} {reason[:300]!r}")

rc, out, err = run({"tool_name": CODEX_IMPLEMENT, "transcript_path": MAIN})
implement_reason = ""
if out.strip():
    implement_reason = json.loads(out)["hookSpecificOutput"][
        "permissionDecisionReason"
    ]
if (
    "escalation was removed" not in implement_reason
    or STRONG in implement_reason
):
    bad += 1
    print(f"IMPLEMENT MESSAGE FAIL: {implement_reason[:300]!r}")

total = len(deny) + len(allow) + len(garbage) + 6
print(
    f"hook: {hook}\ndeny cases: {len(deny)}, allow cases: {len(allow)}, "
    f"garbage: {len(garbage)}, escape hatch: 1, implement escape hatch: 3, "
    f"message: 2"
)
print(f"{'FAIL' if bad else 'PASS'} {total - bad}/{total}")
sys.exit(1 if bad else 0)
