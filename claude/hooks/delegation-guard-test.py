#!/usr/bin/env python3
"""Regression matrix for delegation-guard.py (the sibling file by default; pass another path as argv[1])."""

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
hook = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "delegation-guard.py")
AGENT = "implementer"
STRONG_AGENT = "implementer-strong"
PROSE_FINDINGS_LINE = "rules: disputed gate findings go into the report\n"
REUSE_LINE = "reuse: src/lexer.py:10 `tokenize`.\n"
GIT_SAFETY = (
    "Never revert or discard changes you did not make "
    "(checkout/restore/stash/reset/clean are blocked by a hook); "
    "if you think a revert is needed, stop and report."
)
REPOS_LINE = (
    "Repos: you may only touch /home/user/project; "
    "you may not touch anything else.\n"
)
FULL = (
    "task: fix the parser.\n"
    "plan: single module.\n"
    "class: M\n"
    "acceptance_criteria: the matrix passes.\n"
    "paths: /home/user/project/src/parser.py\n"
    "tdd_phases: acceptance test, implementation, unit, "
    "edge cases, refactor.\n"
    + REUSE_LINE
    + "test_command: ~/.claude/bin/verify -- 'pytest -q'\n"
    + GIT_SAFETY
    + "\n"
    + REPOS_LINE
)
FIX_ROUND = (
    "findings: the retry loop never terminates; "
    "the parser drops the last token.\n"
    "acceptance_criteria: both findings have a "
    "red-without-the-fix regression test.\n"
    "paths: /home/user/project/src/parser.py\n"
    "test_command: ~/.claude/bin/verify -- 'pytest -q'\n"
    + GIT_SAFETY
    + "\n"
    + REPOS_LINE
)


def without(marker: str, replacement: str = "") -> str:
    return FULL.replace(marker, replacement)


deny = [
    {"subagent_type": AGENT, "prompt": "just fix the bug please"},
    {
        "subagent_type": AGENT,
        "prompt": without("acceptance_criteria: the matrix passes.\n"),
    },
    {"subagent_type": AGENT, "prompt": without("verify -- ", "run ")},
    {
        "subagent_type": AGENT,
        "prompt": without("/home/user/project/src/parser.py", "src/parser.py")
        .replace("/home/user/project;", "the repo;")
        .replace("~/.claude/bin/verify", "verify"),
    },
    {
        "subagent_type": AGENT,
        "prompt": without(
            "you may only touch /home/user/project; you may not "
            "touch anything else.",
            "work carefully",
        ),
    },
    {
        "subagent_type": AGENT,
        "prompt": without(
            "tdd_phases: acceptance test, implementation, unit, "
            "edge cases, refactor.\n"
        ),
    },
    {"subagent_type": AGENT, "prompt": without("class: M\n")},
    {"subagent_type": AGENT, "prompt": FIX_ROUND.replace("findings", "notes")},
    {"subagent_type": AGENT, "prompt": without(GIT_SAFETY + "\n")},
    {
        "subagent_type": AGENT,
        "prompt": FIX_ROUND.replace(GIT_SAFETY, "do not revert things"),
    },
    {"subagent_type": AGENT, "prompt": ""},
    {
        "subagent_type": AGENT,
        "prompt": "acceptance criteria: done. verify -- pytest. /abs/path ok.",
    },
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace("acceptance", "accept").replace(
            "Repos:", "notes:"
        ),
    },
    {"model": "sonnet", "prompt": "do it without naming an agent"},
    {"model": "opus", "prompt": FULL},
    {"subagent_type": AGENT, "prompt": without(REUSE_LINE)},
    {
        "subagent_type": AGENT,
        "prompt": without(REUSE_LINE, PROSE_FINDINGS_LINE),
    },
]
allow = [
    {"subagent_type": STRONG_AGENT, "prompt": "just fix the bug please"},
    {
        "subagent_type": STRONG_AGENT,
        "prompt": without("acceptance_criteria: the matrix passes.\n"),
    },
    {"subagent_type": STRONG_AGENT, "prompt": without(GIT_SAFETY + "\n")},
    {"subagent_type": STRONG_AGENT, "prompt": without(REUSE_LINE)},
    {"subagent_type": AGENT, "prompt": FULL},
    {"subagent_type": AGENT, "prompt": FIX_ROUND},
    {"subagent_type": STRONG_AGENT, "prompt": FULL},
    {"subagent_type": STRONG_AGENT, "prompt": FIX_ROUND},
    {"agent_type": STRONG_AGENT, "prompt": FULL},
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace("acceptance_criteria", "Acceptance Criteria"),
    },
    {"subagent_type": AGENT, "prompt": FULL.replace("class: M", "class\nXL")},
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace("tdd_phases", "TDD phases"),
    },
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace("you may only touch", "you must not touch"),
    },
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace(
            "you may only touch",
            "do not modify anything under other paths than",
        ),
    },
    {"subagent_type": AGENT, "prompt": FULL, "model": "opus"},
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace(
            "paths: /home/user/project/src/parser.py",
            "paths=(/home/user/project/src/parser.py)",
        ),
    },
    {
        "subagent_type": AGENT,
        "prompt": FULL.replace(
            "paths: /home/user/project/src/parser.py",
            "see [/home/user/project/src/parser.py]",
        ),
    },
    {"agent_type": AGENT, "prompt": FULL},
    {"subagent_type": AGENT, "prompt": FULL.replace("reuse:", "Reuse")},
    {
        "subagent_type": "Explore",
        "prompt": "look around the repo",
        "model": "haiku",
    },
    {"subagent_type": "Plan", "prompt": "design it", "model": "opus"},
    {
        "subagent_type": "general-purpose",
        "prompt": "find the config",
        "model": "sonnet",
    },
    {"subagent_type": "codex-runner", "prompt": "review it"},
    {"subagent_type": "Plan", "prompt": "design it"},
    {"subagent_type": "claude", "prompt": "do it"},
    {"subagent_type": "writer", "prompt": "draft it"},
    {"subagent_type": "claude-code-guide", "prompt": "how do hooks work"},
    {"subagent_type": AGENT, "prompt": 42},
    {"subagent_type": AGENT},
    {"prompt": "no subagent type and no model at all"},
]
garbage = [
    "",
    "not json",
    "null",
    "[]",
    "5",
    '{"tool_name":"Agent"}',
    '{"tool_name":"Agent","tool_input":null}',
    '{"tool_name":"Bash","tool_input":{"subagent_type":"implementer","prompt":"nope"}}',
    '{"tool_name":"Agent","tool_input":{"subagent_type":42,"prompt":"nope"}}',
    '{"tool_name":"Agent","tool_input":[1,2,3]}',
]


def run(
    tool_input: dict[str, object], tool_name: str = "Agent"
) -> tuple[int, str, str]:
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    done = subprocess.run(
        ["python3", hook],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return done.returncode, done.stdout.strip(), done.stderr.strip()


bad = 0
slowest = 0.0
for case in deny:
    t0 = time.time()
    rc, out, err = run(case)
    slowest = max(slowest, time.time() - t0)
    ok = rc == 0 and '"deny"' in out and not err
    bad += not ok
    if not ok:
        print(
            f"DENY MISS  {str(case)[-200:]!r} -> rc={rc} "
            f"{out[:120]} {err[-160:]}"
        )
for case in allow:
    t0 = time.time()
    rc, out, err = run(case)
    slowest = max(slowest, time.time() - t0)
    ok = rc == 0 and out == "" and not err
    bad += not ok
    if not ok:
        print(
            f"ALLOW FP   {str(case)[:110]!r} -> rc={rc} "
            f"{out[:200]} {err[-160:]}"
        )
for raw in garbage:
    done = subprocess.run(
        ["python3", hook],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    ok = done.returncode == 0 and not done.stderr and done.stdout == ""
    bad += not ok
    if not ok:
        print(
            f"garbage {raw[:60]!r} -> rc={done.returncode} "
            f"out={done.stdout[:60]!r} err={done.stderr[-160:]!r}"
        )

rc, out, err = run({"subagent_type": AGENT, "prompt": "fix it"})
needles = [
    "acceptance_criteria",
    "verify --",
    "absolute path",
    "Never revert or discard changes you did not make",
    "may not touch",
    "tdd_phases",
    "class",
    "delegate",
]
missing = [n for n in needles if n not in out]
bad += bool(missing)
if missing:
    print(f"SPOT FAIL missing={missing} -> {out[:400]}")

rc, out, err = run({"model": "sonnet", "prompt": "do it"})
spot2 = '"deny"' in out and AGENT in out
bad += not spot2
if not spot2:
    print(f"SPOT2 FAIL -> {out[:300]}")

rc, out, err = run({"subagent_type": AGENT, "prompt": FULL}, tool_name="Task")
spot3 = rc == 0 and out == ""
bad += not spot3
if not spot3:
    print(f"SPOT3 FAIL -> {out[:200]}")

rc, out, err = run({"subagent_type": STRONG_AGENT, "prompt": "fix it"})
spot4 = rc == 0 and out == ""
bad += not spot4
if not spot4:
    print(f"SPOT4 FAIL -> {out[:300]}")

SEARCH_AGENTS = ("Explore", "general-purpose")
for agent in SEARCH_AGENTS:
    original: dict[str, object] = {
        "subagent_type": agent,
        "prompt": "find it",
        "description": "look",
    }
    rc, out, err = run(original)
    try:
        decision = json.loads(out)["hookSpecificOutput"]
    except ValueError:
        decision = {}
    ok = (
        rc == 0
        and not err
        and decision.get("permissionDecision") == "allow"
        and decision.get("hookEventName") == "PreToolUse"
        and decision.get("permissionDecisionReason")
        == "delegation-guard: search agent defaults to sonnet"
        and decision.get("updatedInput") == {**original, "model": "sonnet"}
    )
    bad += not ok
    if not ok:
        print(
            f"SEARCH DEFAULT FAIL {agent} -> rc={rc} {out[:300]} {err[-160:]}"
        )

rc, out, err = run(
    {"subagent_type": AGENT, "prompt": FULL.replace("reuse", "notes")}
)
spot5 = '"deny"' in out and "`reuse`" in out and "searched: <terms>" in out
bad += not spot5
if not spot5:
    print(f"SPOT5 FAIL -> {out[:300]}")

rc, out, err = run(
    {
        "subagent_type": AGENT,
        "prompt": without("class: M\n", PROSE_FINDINGS_LINE),
    }
)
spot7 = '"deny"' in out and "the task `class`" in out
bad += not spot7
if not spot7:
    print(f"SPOT7 FAIL -> {out[:300]}")

rc, out, err = run({"subagent_type": "Explore", "prompt": "x", "model": "  "})
spot6 = '"updatedInput"' in out
bad += not spot6
if not spot6:
    print(f"SPOT6 FAIL -> {out[:300]}")

total = len(deny) + len(allow) + len(garbage) + 4 + len(SEARCH_AGENTS) + 3
print(
    f"hook: {hook}\ndeny cases: {len(deny)}, allow cases: {len(allow)}, "
    f"garbage: {len(garbage)}, spot checks: 7, "
    f"slowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}"
)
print(("FAIL " if bad else "PASS ") + f"{total - bad}/{total}")
sys.exit(1 if bad else 0)
