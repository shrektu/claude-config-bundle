#!/usr/bin/env python3
"""PreToolUse(Agent|Task) hook: an implementer may only be spawned with a complete delegation prompt."""
import json
import re
import sys
from typing import Callable, NamedTuple

IMPLEMENTER_TYPES = ("implementer", "implementer-hard", "implementer-opus")
ACCEPTANCE_MARKERS = ("acceptance_criteria", "acceptance criteria")
VERIFY_MARKER = "verify --"
GIT_SAFETY_MARKER = "Never revert or discard changes you did not make"
REPO_BOUNDARY_MARKERS = ("may not touch", "only touch", "must not touch", "do not modify anything under")
ABSOLUTE_PATH_RE = re.compile(r"(^|[\s`'\"(\[=])/[A-Za-z0-9_./-]+")

GIT_SAFETY_LINE = (GIT_SAFETY_MARKER + " (checkout/restore/stash/reset/clean are blocked by a hook); "
                   "if you think a revert is needed, stop and report.")
SUBAGENT_KEYS = ("subagent_type", "agent_type")


class Requirement(NamedTuple):
    hint: str
    present: Callable


def _has_any(text, markers):
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


REQUIREMENTS = (
    Requirement("an `acceptance_criteria:` section saying what must be true when the task is done",
                lambda text: _has_any(text, ACCEPTANCE_MARKERS)),
    Requirement("the test command to run as `~/.claude/bin/verify -- <command>` (the prompt must contain "
                "`verify --`)",
                lambda text: VERIFY_MARKER in text.lower()),
    Requirement("at least one absolute path, so the agent does not guess where the code lives",
                lambda text: bool(ABSOLUTE_PATH_RE.search(text))),
    Requirement(f'the git-safety line: "{GIT_SAFETY_LINE}"',
                lambda text: GIT_SAFETY_MARKER.lower() in text.lower()),
    Requirement('the repo boundary, e.g. "Repos: you may only touch <paths>; you may not touch <paths>"',
                lambda text: _has_any(text, REPO_BOUNDARY_MARKERS)),
)

BARE_MODEL_REASON = ("a bare `model` without `subagent_type` loses the agent contract and its reasoning effort. "
                     "Spawn implementer / implementer-hard / implementer-opus instead (see the `delegate` skill).")


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
        if agent not in IMPLEMENTER_TYPES:
            return
        prompt = tool_input.get("prompt")
        if not isinstance(prompt, str):
            return
        missing = [req.hint for req in REQUIREMENTS if not req.present(prompt)]
        if missing:
            items = "".join(f"\n  - {hint}" for hint in missing)
            deny(f"the prompt for `{agent}` is missing:{items}\nAdd them (the `delegate` skill has the "
                 f"template) and spawn it again.")
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
