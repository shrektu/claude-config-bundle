#!/usr/bin/env python3
"""PreToolUse(Agent|Task) hook: developer and codex-runner may only be spawned against a complete plan file."""
import json
import os
import re
import sys
from collections.abc import Iterator
from typing import Callable, NamedTuple

DEVELOPER = "developer"
CODEX_RUNNER = "codex-runner"
REVIEW_MODES = ("plan", "code")
ACCEPTANCE_HEADING_RE = re.compile(r"(?i)^##[ \t]+acceptance_criteria[ \t]*$")
TEST_PLAN_HEADING_RE = re.compile(r"(?i)^##[ \t]+test_plan[ \t]*$")
COMMANDS_HEADING_RE = re.compile(r"(?i)^##[ \t]+commands[ \t]*$")
QUALITY_LINE_RE = re.compile(r"^[ \t\-*]*Quality:.*quality-gate")
SECTION_END_RE = re.compile(r"^#{1,2}[ \t]")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")
VERIFY_MARKER = "verify --"
REPO_BOUNDARY_MARKERS = ("may not touch", "only touch", "must not touch", "do not modify anything under")
ABSOLUTE_PATH_RE = re.compile(r"(^|[\s`'\"(\[=])/[A-Za-z0-9_./-]+")
PLAN_FILE_RE = re.compile(r"(?m)^[ \t\-*]*plan_file:[ \t]*(.*?)[ \t]*$")
MODE_RE = re.compile(r"(?m)^[ \t\-*]*mode:[ \t]*(.*?)[ \t]*$")
PROJECT_PATH_RE = re.compile(r"(?m)^[ \t\-*]*project_path:[ \t]*(.*?)[ \t]*$")
EMPTY_EXEMPT_RE = re.compile(r"(?m)^[ \t\-*]*tdd_exempt:[ \t]*$")
VALUE_QUOTES = "`'\""
MAX_PLAN_BYTES = 1000000
SUBAGENT_KEYS = ("subagent_type", "agent_type")


class Requirement(NamedTuple):
    hint: str
    present: Callable


def unfenced_lines(text: str) -> Iterator[str]:
    fenced = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield line


def section_lines(plan: str, heading_re: re.Pattern[str]) -> Iterator[str]:
    inside = False
    for line in unfenced_lines(plan):
        if inside and SECTION_END_RE.match(line):
            inside = False
        if heading_re.match(line):
            inside = True
        elif inside:
            yield line


def has_filled_section(plan: str, heading_re: re.Pattern[str]) -> bool:
    return any(line.strip() for line in section_lines(plan, heading_re))


def has_quality_gate_line(plan: str) -> bool:
    return any(QUALITY_LINE_RE.match(line) for line in section_lines(plan, COMMANDS_HEADING_RE))


def _has_any(text, markers):
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


PLAN_REQUIREMENTS = (
    Requirement("a filled `## acceptance_criteria` section in the plan file (outside code fences), saying what "
                "must be true when the task is done",
                lambda plan: has_filled_section(plan, ACCEPTANCE_HEADING_RE)),
    Requirement("a filled `## test_plan` section in the plan file (outside code fences), listing the tests to "
                "write red first",
                lambda plan: has_filled_section(plan, TEST_PLAN_HEADING_RE)),
    Requirement("a `Quality:` line in the plan's `## commands` section that runs `quality-gate` through "
                "verify (outside code fences)",
                has_quality_gate_line),
)
REQUIREMENTS = (
    Requirement("the test commands as `~/.claude/bin/verify -- <command>` (the plan or prompt must contain "
                "`verify --`)",
                lambda text: VERIFY_MARKER in text.lower()),
    Requirement("at least one absolute path, so the agent does not guess where the code lives",
                lambda text: bool(ABSOLUTE_PATH_RE.search(text))),
    Requirement('the repo boundary, e.g. "You may only touch <paths>; you may not touch <paths>"',
                lambda text: _has_any(text, REPO_BOUNDARY_MARKERS)),
)

PLAN_FILE_HINT = "a `plan_file: <absolute path to an existing plan file>` line"
PROJECT_PATH_HINT = "a `project_path: <absolute path to an existing project directory>` line"
BARE_MODEL_REASON = ("a bare `model` without `subagent_type` loses the agent contract and its reasoning effort. "
                     f"Spawn `{DEVELOPER}` instead (see the `delegate` skill).")


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"delegation-guard: {reason}",
        }
    }))
    sys.exit(0)


def subagent_type(tool_input):
    for key in SUBAGENT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def field(pattern, prompt):
    match = pattern.search(prompt)
    return match.group(1).strip(VALUE_QUOTES) if match else ""


def plan_path(prompt):
    path = field(PLAN_FILE_RE, prompt)
    return path if os.path.isabs(path) and os.path.isfile(path) else None


def read_plan(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read(MAX_PLAN_BYTES)


def deny_missing(agent, missing):
    items = "".join(f"\n  - {hint}" for hint in missing)
    deny(f"the prompt for `{agent}` is missing:{items}\nAdd them (the `delegate` skill has the template) and "
         f"spawn it again.")


def check_developer(prompt):
    path = plan_path(prompt)
    if path is None:
        deny_missing(DEVELOPER, [PLAN_FILE_HINT])
    plan = read_plan(path)
    missing = [req.hint for req in PLAN_REQUIREMENTS if not req.present(plan)]
    missing += [req.hint for req in REQUIREMENTS if not req.present(prompt + "\n" + plan)]
    if EMPTY_EXEMPT_RE.search(prompt):
        missing.append("a reason after `tdd_exempt:` (or drop the line)")
    if missing:
        deny_missing(DEVELOPER, missing)


def check_codex_runner(prompt):
    missing = []
    if field(MODE_RE, prompt) not in REVIEW_MODES:
        missing.append(f"a `mode: {'|'.join(REVIEW_MODES)}` line")
    if plan_path(prompt) is None:
        missing.append(PLAN_FILE_HINT)
    project = field(PROJECT_PATH_RE, prompt)
    if not (os.path.isabs(project) and os.path.isdir(project)):
        missing.append(PROJECT_PATH_HINT)
    if missing:
        deny_missing(CODEX_RUNNER, missing)


CHECKS = {DEVELOPER: check_developer, CODEX_RUNNER: check_codex_runner}


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") not in (None, "Agent", "Task"):
            return
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        agent = subagent_type(tool_input)
        model = tool_input.get("model")
        if agent is None:
            if isinstance(model, str) and model.strip():
                deny(BARE_MODEL_REASON)
            return
        check = CHECKS.get(agent)
        prompt = tool_input.get("prompt")
        if check is None or not isinstance(prompt, str):
            return
        check(prompt)
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
