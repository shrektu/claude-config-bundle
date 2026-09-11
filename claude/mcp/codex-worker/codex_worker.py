#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codex-worker")

REVIEW_TIMEOUT_SECONDS = 5100


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
    model: str = "gpt-6-astra",
    reasoning_effort: str = "high",
    service_tier: str = "default",
) -> str:
    """
    Run Codex CLI as an independent SECOND REVIEWER (read-only).

    Claude is the architect, implementer-of-record and first reviewer.
    Codex reviews the resulting code adversarially and reports findings.
    It must not edit, commit or otherwise modify anything.
    Codex never implements; the former codex_execute_task tool was removed.
    """

    root = resolve_project_path(project_path)
    codex_bin = os.environ.get("CODEX_BIN", "codex")

    prompt = f"""
You are Codex acting as an INDEPENDENT SECOND REVIEWER.

Role split:
- Claude designed this change, a Sonnet agent implemented it, and Claude has already
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
- Do not report style nits, and do not restate what the code does.
- If a design decision looks wrong but was deliberate, say so and argue against it on
  the merits instead of filing it as a bug.

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

Final response format — a list of findings, most severe first. For each:
- Severity: High / Medium / Low
- One-sentence statement of the defect
- file:line anchors
- A concrete failure scenario (inputs/state -> wrong outcome), and whether you reproduced it
Then, one short paragraph: what you checked and found CLEAN, so Claude knows the coverage.
If nothing survives verification, say so plainly rather than padding the list.
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

    return f"""Codex review completed (model={model}, reasoning_effort={reasoning_effort}, service_tier={service_tier}, sandbox=read-only).

Findings:
{stdout[-20000:]}

STDERR:
{stderr[-4000:]}
"""


if __name__ == "__main__":
    mcp.run()
