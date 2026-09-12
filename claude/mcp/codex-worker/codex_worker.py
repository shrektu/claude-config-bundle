#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codex-worker")

REVIEW_TIMEOUT_SECONDS = 5100

MODE_PLAN = "plan"
MODE_CODE = "code"
MODE_FINAL_AUDIT = "final-audit"

MODE_FOCUS = {
    MODE_PLAN: """Review mode: PLAN REVIEW — you are reviewing a plan, not finished code.
Look for: contradictions between the steps, dependencies the plan missed, a rollout order that leaves
the system broken in between, data and protocol risks (migrations, on-wire compatibility, irreversible
steps, backfills), and acceptance criteria that are missing, unmeasurable or not actually checkable.
Read the current code wherever the plan makes a claim about it. Do not redesign the solution — report
what would bite if the plan were executed exactly as written.""",
    MODE_CODE: """Review mode: CODE REVIEW — the change has just been implemented.
Look for: correctness defects, regressions in existing behaviour and in callers, contract mismatches
(signatures, data shapes, protocol, error paths, invariants), missing or vacuous tests (tests that
cannot fail, silently skipped tests, a bug fix with no reproducing test), and idioms that are
deprecated or wrong for the versions pinned in this repo — the repo facts arrive in the extra context
below; trust them over your own recollection of the library.""",
    MODE_FINAL_AUDIT: """Review mode: FINAL AUDIT — this change was already reviewed more than once and
the findings were fixed. Your only question is: WHAT DID THE EARLIER REVIEWS MISS. Do not restate
findings that were already handled, and do not redesign the solution unless a defect makes the current
design unworkable.""",
}

OUTPUT_FORMAT = """Final response format, in exactly this order:

BLOCKER
IMPORTANT
OPTIONAL
  For every entry: a one-sentence statement of the defect; file:line; the conditions that trigger it;
  the effect when it triggers; reproduced yes/no. BLOCKER = must be fixed before this lands.
  IMPORTANT = fix now unless it is a deliberate trade-off. OPTIONAL = worth knowing, not required.
  Leave a bucket empty instead of padding it.

Checked and clean
  What you actually verified and found correct, so the coverage is known.

Could not verify
  What you could not check and why (missing environment, unavailable data, too little context).
  This is NOT the same as clean — never fold it into "checked and clean".

PASS
  Print PASS on its own line as the last line when there is no BLOCKER and no IMPORTANT finding."""


def resolve_project_path(project_path: Optional[str]) -> str:
    if project_path:
        return str(Path(project_path).expanduser().resolve())

    for key in ("CLAUDE_PROJECT_DIR", "PWD"):
        value = os.environ.get(key)
        if value and Path(value).exists():
            return str(Path(value).resolve())

    return str(Path.cwd().resolve())


@mcp.tool()
def codex_review_changes(
    what_changed: str,
    review_focus: str,
    project_path: Optional[str] = None,
    acceptance_criteria: str = "",
    extra_context: str = "",
    mode: str = MODE_CODE,
    model: str = "gpt-6-astra",
    reasoning_effort: str = "high",
    service_tier: str = "default",
) -> str:
    """
    Run Codex CLI as an independent SECOND REVIEWER (read-only).

    Claude is the architect, implementer-of-record and first reviewer.
    Codex reviews the resulting plan or code adversarially and reports findings.
    It must not edit, commit or otherwise modify anything.
    Codex never implements; the former codex_execute_task tool was removed.

    mode: "plan" (review a plan before implementation), "code" (default, review the diff)
    or "final-audit" (what did the earlier reviews miss).
    """

    if mode not in MODE_FOCUS:
        allowed = ", ".join(MODE_FOCUS)
        return f"ERROR: unknown mode {mode!r}. Allowed modes: {allowed}."

    root = resolve_project_path(project_path)
    codex_bin = os.environ.get("CODEX_BIN", "codex")

    prompt = f"""
You are Codex acting as an INDEPENDENT SECOND REVIEWER.

Role split:
- Claude designed this change, an implementer agent wrote it, and Claude has already
  reviewed it once.
- You are an adversarial reviewer. Your value is finding what Claude missed.
- You are READ-ONLY: do not edit, create or delete files. Do not commit, branch, push,
  or run any command that mutates the repository or the environment.
- Read the actual code. Do NOT trust any claim in the description below — verify it.
- Where you can, REPRODUCE a defect (a throwaway script in /tmp is fine) rather than
  asserting it. A reproduced finding is worth ten speculative ones.
- Report only defects that would actually bite: wrong behaviour, security or tenancy
  holes, data corruption, broken invariants, violated project conventions, untestable
  or silently-skipped tests, missing coverage of a stated requirement.
- Style preferences are not defects. Do not restate what the code does.
- If a design decision looks wrong but was deliberate, say so and argue against it on
  the merits instead of filing it as a bug.

{MODE_FOCUS[mode]}

Project root:
{root}

What was changed (Claude's account — verify it, do not assume it is true):
{what_changed}

What to focus the review on:
{review_focus}

Acceptance criteria the change is supposed to meet:
{acceptance_criteria or "[none given — infer from the task]"}

Extra context:
{extra_context}

{OUTPUT_FORMAT}
""".strip()

    # NOTE: `codex exec` has no --ask-for-approval flag (codex-cli 0.144.3); passing it
    # makes the CLI exit with a usage error. exec is non-interactive by definition.
    codex_args = [
        codex_bin,
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
    ]
    codex_args += ["-c", f'service_tier="{service_tier}"']
    codex_args += ["-C", root, "-"]

    try:
        result = subprocess.run(
            codex_args,
            input=prompt,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=REVIEW_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return "ERROR: Codex CLI not found. Set CODEX_BIN to the absolute path from `command -v codex`."
    except subprocess.TimeoutExpired:
        return f"ERROR: Codex review timed out after {REVIEW_TIMEOUT_SECONDS} seconds."

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        return f"""ERROR: Codex review exited with code {result.returncode}.

STDOUT:
{stdout[-12000:]}

STDERR:
{stderr[-12000:]}
"""

    return f"""Codex review completed (mode={mode}, model={model}, reasoning_effort={reasoning_effort}, service_tier={service_tier}, sandbox=read-only).

Findings:
{stdout[-20000:]}

STDERR:
{stderr[-4000:]}
"""


if __name__ == "__main__":
    mcp.run()
