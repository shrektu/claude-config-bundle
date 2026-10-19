#!/usr/bin/env python3
"""PreToolUse(Agent|Task) hook: an implementer may only be spawned with a complete delegation prompt."""

import json
import re
import sys
from typing import Callable, NamedTuple

IMPLEMENTER_TYPES = ("implementer", "implementer-strong")
ACCEPTANCE_MARKERS = ("acceptance_criteria", "acceptance criteria")
VERIFY_MARKER = "verify --"
REPO_BOUNDARY_MARKERS = (
    "may not touch",
    "only touch",
    "must not touch",
    "do not modify anything under",
)
PHASE_MARKERS = ("tdd_phases", "tdd phases")
SEARCH_AGENT_TYPES = ("Explore", "general-purpose")
SEARCH_AGENT_MODEL = "sonnet"
GUARD_PREFIX = "delegation-guard: "
SEARCH_MODEL_REASON = GUARD_PREFIX + "search agent defaults to sonnet"
REUSE_LINE_RE = re.compile(r"^\s*reuse\b", re.IGNORECASE | re.MULTILINE)
FIX_ROUND_LINE_RE = re.compile(r"^\s*findings\b", re.IGNORECASE | re.MULTILINE)
GIT_SAFETY_MARKER = "Never revert or discard changes you did not make"
CLASS_MARKERS = (
    "class\ns",
    "class\nm",
    "class\nl",
    "class\nxl",
    "class: s",
    "class: m",
    "class: l",
    "class: xl",
    "class s",
    "class m",
    "class l",
    "class xl",
)
ABSOLUTE_PATH_RE = re.compile(r"(^|[\s`'\"(\[=])/[A-Za-z0-9_./-]+")

GIT_SAFETY_LINE = (
    GIT_SAFETY_MARKER
    + " (checkout/restore/stash/reset/clean are blocked by a hook); "
    "if you think a revert is needed, stop and report."
)
SUBAGENT_KEYS = ("subagent_type", "agent_type")


class Requirement(NamedTuple):
    hint: str
    present: Callable


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    """Tell whether the text contains any marker, ignoring case."""
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _is_fix_round(text: str) -> bool:
    """Tell whether the prompt has a findings section."""
    return bool(FIX_ROUND_LINE_RE.search(text))


def _is_new_task(text: str) -> bool:
    """Tell whether the prompt starts a task rather than a fix round."""
    return _has_any(text, PHASE_MARKERS) and not _is_fix_round(text)


def _reuse_requirement_met(text: str) -> bool:
    """Tell whether the prompt needs no reuse section or has one."""
    return not _is_new_task(text) or bool(REUSE_LINE_RE.search(text))


REQUIREMENTS = (
    Requirement(
        "an `acceptance_criteria:` section saying what must be true "
        "when the task is done",
        lambda text: _has_any(text, ACCEPTANCE_MARKERS),
    ),
    Requirement(
        "the test command to run as `~/.claude/bin/verify -- <command>` "
        "(the prompt must contain `verify --`)",
        lambda text: VERIFY_MARKER in text.lower(),
    ),
    Requirement(
        "at least one absolute path, so the implementer does not guess "
        "where the code lives",
        lambda text: bool(ABSOLUTE_PATH_RE.search(text)),
    ),
    Requirement(
        f'the git-safety line: "{GIT_SAFETY_LINE}"',
        lambda text: GIT_SAFETY_MARKER.lower() in text.lower(),
    ),
    Requirement(
        "the repo boundary, e.g. "
        '"Repos: you may only touch <paths>; you may not touch <paths>"',
        lambda text: _has_any(text, REPO_BOUNDARY_MARKERS),
    ),
    Requirement(
        "either a `tdd_phases` section (new task) or a `findings` list "
        "(fix round) — without them the implementer has no phase ladder "
        "to work",
        lambda text: _has_any(text, PHASE_MARKERS) or _is_fix_round(text),
    ),
    Requirement(
        "the task `class` (S, M, L or XL), which sets the TDD ladder "
        "the implementer works",
        lambda text: _has_any(text, CLASS_MARKERS) or _is_fix_round(text),
    ),
    Requirement(
        "a `reuse` section: the existing helpers, types, constants and "
        "components this milestone must use (file:line), or "
        "`none — searched: <terms>`",
        _reuse_requirement_met,
    ),
)

BARE_MODEL_REASON = (
    "a bare `model` without `subagent_type` loses the agent contract "
    "and its reasoning effort. Implementation goes to `implementer` "
    "(Sonnet 5.5, effort medium) instead — see the `delegate` skill."
)


def deny(reason: str) -> None:
    """Print a deny decision and exit."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": GUARD_PREFIX + reason,
                }
            }
        )
    )
    sys.exit(0)


def default_search_model(tool_input: dict[str, object]) -> None:
    """Print an allow decision that sets the search agent's model."""
    decision = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": SEARCH_MODEL_REASON,
        "updatedInput": {**tool_input, "model": SEARCH_AGENT_MODEL},
    }
    print(json.dumps({"hookSpecificOutput": decision}))


def subagent_type(tool_input):
    for key in SUBAGENT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") not in (
            None,
            "Agent",
            "Task",
        ):
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
        has_model = isinstance(model, str) and bool(model.strip())
        if agent in SEARCH_AGENT_TYPES and not has_model:
            default_search_model(tool_input)
            return
        if agent not in IMPLEMENTER_TYPES:
            return
        prompt = tool_input.get("prompt")
        if not isinstance(prompt, str):
            return
        missing = [req.hint for req in REQUIREMENTS if not req.present(prompt)]
        if missing:
            items = "".join(f"\n  - {hint}" for hint in missing)
            deny(
                f"the prompt for `{agent}` is missing:{items}\n"
                "Add them (the `delegate` skill has the template) "
                "and spawn it again."
            )
    except SystemExit:
        raise
    except Exception:
        return


if __name__ == "__main__":
    main()
