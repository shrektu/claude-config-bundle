#!/usr/bin/env python3
"""Regression matrix for delegation-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, os, subprocess, sys, time

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "delegation-guard.py")
GIT_SAFETY = ("Never revert or discard changes you did not make (checkout/restore/stash/reset/clean are "
              "blocked by a hook); if you think a revert is needed, stop and report.")
FULL = ("task: fix the parser.\n"
        "architecture: single module.\n"
        "acceptance_criteria: the matrix passes.\n"
        "paths: /home/user/project/src/parser.py\n"
        "test_command: ~/.claude/bin/verify -- 'pytest -q'\n"
        + GIT_SAFETY + "\n"
        "Repos: you may only touch /home/user/project; you may not touch anything else.\n")


def without(marker, replacement=""):
    return FULL.replace(marker, replacement)


deny = [
    {"subagent_type": "implementer", "prompt": "just fix the bug please"},
    {"subagent_type": "implementer-hard", "prompt": "just fix the bug please"},
    {"subagent_type": "implementer-opus", "prompt": "just fix the bug please"},
    {"subagent_type": "implementer", "prompt": without("acceptance_criteria: the matrix passes.\n")},
    {"subagent_type": "implementer", "prompt": without("verify -- ", "run ")},
    {"subagent_type": "implementer", "prompt": without("/home/user/project/src/parser.py", "src/parser.py")
                                                .replace("/home/user/project;", "the project;")
                                                .replace("~/.claude/bin/verify", "verify")},
    {"subagent_type": "implementer", "prompt": without(GIT_SAFETY + "\n")},
    {"subagent_type": "implementer", "prompt": without("you may only touch /home/user/project; you may not "
                                                       "touch anything else.\n")},
    {"subagent_type": "implementer-hard", "prompt": without("acceptance_criteria", "goals")
                                                    .replace(GIT_SAFETY, "do not revert things")},
    {"subagent_type": "implementer-opus", "prompt": ""},
    {"subagent_type": "commander-opus", "prompt": "just fix the bug please"},
    {"subagent_type": "commander-opus", "prompt": without("acceptance_criteria: the matrix passes.\n")},
    {"subagent_type": "implementer", "prompt": "acceptance criteria: done. verify -- pytest. /abs/path ok."},
    {"subagent_type": "implementer", "prompt": FULL.replace("acceptance", "accept")
                                                   .replace("verify --", "verify")},
    {"model": "claude-sonnet-5", "prompt": FULL},
    {"model": "opus", "prompt": "anything"},
    {"model": "haiku", "description": "quick fix"},
]
allow = [
    {"subagent_type": "implementer", "prompt": FULL},
    {"subagent_type": "implementer-hard", "prompt": FULL},
    {"subagent_type": "implementer-opus", "prompt": FULL},
    {"subagent_type": "commander-opus", "prompt": FULL},
    {"subagent_type": "implementer", "prompt": FULL.replace("acceptance_criteria", "Acceptance Criteria")},
    {"subagent_type": "implementer", "prompt": FULL.replace("you may only touch", "you must not touch")},
    {"subagent_type": "implementer", "prompt": FULL.replace("you may only touch", "do not modify anything "
                                                            "under")},
    {"subagent_type": "implementer", "prompt": FULL, "model": "sonnet"},
    {"subagent_type": "implementer", "prompt": FULL.replace("paths: /home/user/project/src/parser.py",
                                                            "paths: `/home/user/project/src/parser.py`")},
    {"subagent_type": "implementer", "prompt": FULL.replace("paths: /home/user/project/src/parser.py",
                                                            'paths: "/home/user/project/src/parser.py"')},
    {"subagent_type": "implementer", "prompt": FULL.replace("paths: /home/user/project/src/parser.py",
                                                            "paths=(/home/user/project/src/parser.py)")},
    {"subagent_type": "implementer", "prompt": FULL.replace("paths: /home/user/project/src/parser.py",
                                                            "see [/home/user/project/src/parser.py]")},
    {"agent_type": "implementer", "prompt": FULL},
    {"subagent_type": "Explore", "prompt": "look around the repo"},
    {"subagent_type": "Plan", "prompt": "design it"},
    {"subagent_type": "codex-runner", "prompt": "review the diff"},
    {"subagent_type": "general-purpose", "prompt": "find the config"},
    {"subagent_type": "claude-code-guide", "prompt": "how do hooks work"},
    {"subagent_type": "implementer", "prompt": 42},
    {"subagent_type": "implementer"},
    {"prompt": "no subagent type and no model at all"},
]
garbage = [
    "", "not json", "null", "[]", "5",
    '{"tool_name":"Agent"}',
    '{"tool_name":"Agent","tool_input":null}',
    '{"tool_name":"Bash","tool_input":{"subagent_type":"implementer","prompt":"nope"}}',
    '{"tool_name":"Agent","tool_input":{"subagent_type":42,"prompt":"nope"}}',
    '{"tool_name":"Agent","tool_input":[1,2,3]}',
]


def run(tool_input, tool_name="Agent"):
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    done = subprocess.run(["python3", hook], input=payload, capture_output=True, text=True, timeout=10)
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
        print(f"DENY MISS  {str(case)[:110]!r} -> rc={rc} {out[:120]} {err[-160:]}")
for case in allow:
    t0 = time.time()
    rc, out, err = run(case)
    slowest = max(slowest, time.time() - t0)
    ok = rc == 0 and out == "" and not err
    bad += not ok
    if not ok:
        print(f"ALLOW FP   {str(case)[:110]!r} -> rc={rc} {out[:200]} {err[-160:]}")
for raw in garbage:
    done = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=10)
    ok = done.returncode == 0 and not done.stderr and done.stdout == ""
    bad += not ok
    if not ok:
        print(f"garbage {raw[:60]!r} -> rc={done.returncode} out={done.stdout[:60]!r} err={done.stderr[-160:]!r}")

rc, out, err = run({"subagent_type": "implementer", "prompt": "fix it"})
needles = ["acceptance_criteria", "verify --", "absolute path", "Never revert or discard changes you did not make",
           "may not touch", "delegate"]
missing = [n for n in needles if n not in out]
bad += bool(missing)
if missing:
    print(f"SPOT FAIL missing={missing} -> {out[:400]}")

rc, out, err = run({"model": "sonnet", "prompt": "do it"})
spot2 = '"deny"' in out and "implementer-opus" in out
bad += not spot2
if not spot2:
    print(f"SPOT2 FAIL -> {out[:300]}")

rc, out, err = run({"subagent_type": "implementer", "prompt": FULL}, tool_name="Task")
spot3 = rc == 0 and out == ""
bad += not spot3
if not spot3:
    print(f"SPOT3 FAIL -> {out[:200]}")

total = len(deny) + len(allow) + len(garbage) + 3
print(f"hook: {hook}\ndeny cases: {len(deny)}, allow cases: {len(allow)}, garbage: {len(garbage)}, "
      f"spot checks: 3, slowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}")
print(("FAIL " if bad else "PASS ") + f"{total - bad}/{total}")
sys.exit(1 if bad else 0)
