#!/usr/bin/env python3
import contextlib
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codex-worker")

REVIEW_TIMEOUT_SECONDS = 5100
SANDBOX_MODE = "read-only"
STDOUT_TAIL_LIMIT = 16000
STDERR_TAIL_LIMIT = 4000
FINDINGS_LIMIT = 20000
GIT_TIMEOUT_SECONDS = 30
NO_INDEX_DIFFERENCES_EXIT = 1
DEV_NULL = "/dev/null"
GIT_OUTPUT_ENCODING = "utf-8"
GIT_DECODE_ERRORS = "replace"
LAST_MESSAGE_ENCODING = "utf-8"
CODEX_BIN_ENV = "CODEX_BIN"
DEFAULT_CODEX_BIN = "codex"
END_OF_OPTIONS = "--end-of-options"
MISSING_CHANGE_ERROR = "ERROR: pass diff_base (preferred) or what_changed."

REVIEW_TASK = "review"
CODEX_NOT_FOUND_ERROR = (
    "ERROR: Codex CLI not found. "
    "Set CODEX_BIN to the absolute path from `command -v codex`."
)

MODE_PLAN = "plan"
MODE_CODE = "code"


class CodexProfile(NamedTuple):
    """Model and reasoning effort for one Codex run."""

    model: str
    reasoning_effort: str


IGNORE_USER_CONFIG_FLAG = "--ignore-user-config"
LOW_VERBOSITY_OVERRIDE = 'model_verbosity="low"'


MODE_PROFILES = {
    MODE_PLAN: CodexProfile(model="gpt-6.1-sol", reasoning_effort="high"),
    MODE_CODE: CodexProfile(model="gpt-6.1-sol", reasoning_effort="medium"),
}

MODE_FOCUS = {
    MODE_PLAN: """Review mode: PLAN CRITIQUE — you are reviewing a plan before a line of it is implemented.
Look for: contradictions between the steps, dependencies the plan missed, a rollout order that leaves
the system broken in between, data and protocol risks (migrations, on-wire compatibility, irreversible
steps, backfills), architecture that will not hold under the stated constraints, and acceptance criteria
that are missing, unmeasurable or not actually checkable. Read the current code wherever the plan makes
a claim about it.
ONLY POINT OUT PROBLEMS. Do not rewrite the plan, do not propose an alternative plan or architecture,
do not list replacement steps. For every finding name the plan step, what is wrong with it and what
breaks if it is executed as written — nothing more. Even when a design choice is unworkable, say why
it fails and stop there: choosing the fix is the orchestrator's job.""",
}

OUTPUT_FORMAT = """Final response format, in exactly this order:

BLOCKER
IMPORTANT
OPTIONAL
  For every entry: a one-sentence statement of the defect; file:line (or the plan step); the conditions
  that trigger it; the effect when it triggers; reproduced yes/no. BLOCKER = must be fixed before this
  lands. IMPORTANT = fix now unless it is a deliberate trade-off. OPTIONAL = worth knowing, not required.
  Leave a bucket empty instead of padding it.

Checked and clean
  What you actually verified and found correct, so the coverage is known.

Could not verify
  What you could not check and why (missing environment, unavailable data, too little context).
  This is NOT the same as clean — never fold it into "checked and clean".

PASS
  Print PASS on its own line as the last line when there is no BLOCKER and no IMPORTANT finding."""


def resolve_project_path(project_path: str | None) -> str:
    """Resolve the repo path from the argument or the environment."""
    if project_path:
        return str(Path(project_path).expanduser().resolve())

    for key in ("CLAUDE_PROJECT_DIR", "PWD"):
        value = os.environ.get(key)
        if value and Path(value).exists():
            return str(Path(value).resolve())

    return str(Path.cwd().resolve())


class DiffUnavailable(Exception):
    pass


def run_git(
    root: str,
    args: list[str],
    accepted_exit_codes: tuple[int, ...] = (0,),
) -> str:
    """Run git in the repo and return its stdout."""
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            check=False,
            encoding=GIT_OUTPUT_ENCODING,
            errors=GIT_DECODE_ERRORS,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise DiffUnavailable("git executable not found") from error
    except subprocess.TimeoutExpired as error:
        raise DiffUnavailable(f"git timed out after {GIT_TIMEOUT_SECONDS} seconds") from error

    if result.returncode not in accepted_exit_codes:
        raise DiffUnavailable((result.stderr or "").strip() or f"git exited with code {result.returncode}")
    return result.stdout


def list_untracked_files(root: str) -> list[str]:
    listing = run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    return sorted(name for name in listing.split("\0") if name)


def diff_untracked_file(root: str, name: str) -> str:
    return run_git(root, ["diff", "--no-color", "--no-index", "--", DEV_NULL, name],
                   accepted_exit_codes=(0, NO_INDEX_DIFFERENCES_EXIT))


def build_diff(root: str, base: str) -> str:
    tracked = run_git(root, ["diff", "--no-color", END_OF_OPTIONS, base])
    untracked = [diff_untracked_file(root, name) for name in list_untracked_files(root)]
    return "".join([tracked, *untracked])


def resolve_change_description(
    root: str, what_changed: str, diff_base: str | None
) -> str:
    """Return the change text to review, from the diff or the account."""
    if not diff_base:
        if not what_changed.strip():
            raise DiffUnavailable(MISSING_CHANGE_ERROR)
        return what_changed

    try:
        diff = build_diff(root, diff_base)
    except DiffUnavailable as error:
        raise DiffUnavailable(f"ERROR: cannot compute the diff against {diff_base!r}: {error}") from error

    if not diff.strip():
        raise DiffUnavailable(f"ERROR: the diff against {diff_base!r} is empty — nothing to review.")
    if what_changed:
        return f"{what_changed}\n\n{diff}"
    return diff


def build_plan_prompt(root: str, what_changed: str, review_focus: str, acceptance_criteria: str,
                      extra_context: str) -> str:
    return f"""
You are Codex acting as an INDEPENDENT ADVERSARIAL REVIEWER.

Role split:
- Claude Opus is the architect and orchestrator: it wrote the plan and reviews every change itself.
- A Claude implementer agent writes the code. You never implement.
- Your value is finding what Claude missed.
- You are READ-ONLY: do not edit, create or delete files. Do not commit, branch, push, or run any
  command that mutates the repository or the environment.
- Read the actual code. Do NOT trust any claim in the description below — verify it.
- Where you can, REPRODUCE a defect (a throwaway script in /tmp is fine) rather than asserting it.
  A reproduced finding is worth ten speculative ones.
- Report only defects that would actually bite: wrong behaviour, security or tenancy holes, data
  corruption, broken invariants, missing coverage of a stated requirement.
- Style preferences are not defects. Do not restate what the code does.

{MODE_FOCUS[MODE_PLAN]}

Project root:
{root}

What is under review (Claude's account — verify it, do not assume it is true):
{what_changed}

What to focus on:
{review_focus}

Acceptance criteria the work is supposed to meet:
{acceptance_criteria or "[none given — infer from the task]"}

Extra context:
{extra_context or "[none]"}

{OUTPUT_FORMAT}
""".strip()


def build_code_prompt(root: str, what_changed: str, review_focus: str, acceptance_criteria: str,
                      extra_context: str) -> str:
    return f"""
Read-only code review. Report BUGS only.
Bug: wrong behaviour, crash, data loss or corruption, security hole, broken contract with a caller, or a bug fix without a test that fails without it.
Never report: style, naming, comments, formatting, refactors, alternative designs or solutions, "could/consider" suggestions, performance unless it is a defect.
Read only the changed code and what it directly calls or is called by. Do not scan the repo. The change is below; do not re-fetch it. Run a command only when one short check settles a real doubt. Never edit anything.

Root: {root}
Change:
{what_changed}
Focus: {review_focus}
Acceptance: {acceptance_criteria or "-"}
Context: {extra_context or "-"}

Output only these lines, no preamble, no summary, no code:
[BLOCKER] or [IMPORTANT] file:line — the bug in one sentence — trigger -> effect
If something material could not be checked, one line: Not checked: <what>
Last line: PASS when there is no bug, otherwise FAIL.
""".strip()


PROMPT_BUILDERS = {
    MODE_PLAN: build_plan_prompt,
    MODE_CODE: build_code_prompt,
}

MODE_EXTRA_OVERRIDES = {
    MODE_PLAN: [],
    MODE_CODE: ["-c", LOW_VERBOSITY_OVERRIDE],
}


@dataclass(slots=True)
class CodexJob:
    """One codex exec invocation to run."""

    root: str
    prompt: str
    model: str
    reasoning_effort: str
    overrides: list[str]
    timeout: int
    task: str


@dataclass(slots=True)
class CodexRun:
    """Outcome of one finished codex exec process."""

    returncode: int
    last_message: str
    stdout: str
    stderr: str


class CodexUnavailableError(Exception):
    """Codex could not be run to completion."""


def read_last_message(path: str) -> str:
    """Read the file codex wrote its final message to."""
    try:
        text = Path(path).read_text(
            encoding=LAST_MESSAGE_ENCODING, errors=GIT_DECODE_ERRORS
        )
    except OSError:
        return ""
    return text.strip()


def run_codex(job: CodexJob) -> CodexRun:
    """Run codex exec with the prompt on stdin and collect its output."""
    codex_bin = os.environ.get(CODEX_BIN_ENV, DEFAULT_CODEX_BIN)
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as out:
        last_message_path = out.name

    args = [
        codex_bin,
        "exec",
        "--skip-git-repo-check",
        IGNORE_USER_CONFIG_FLAG,
        "-m",
        job.model,
        *job.overrides,
        "-c",
        f'model_reasoning_effort="{job.reasoning_effort}"',
        "-o",
        last_message_path,
        "-C",
        job.root,
        "-",
    ]

    try:
        result = subprocess.run(
            args,
            input=job.prompt,
            cwd=job.root,
            text=True,
            capture_output=True,
            check=False,
            timeout=job.timeout,
        )
        last_message = read_last_message(last_message_path)
    except FileNotFoundError as error:
        raise CodexUnavailableError(CODEX_NOT_FOUND_ERROR) from error
    except subprocess.TimeoutExpired as error:
        message = (
            f"ERROR: Codex {job.task} timed out after {job.timeout} seconds."
        )
        raise CodexUnavailableError(message) from error
    finally:
        with contextlib.suppress(OSError):
            Path(last_message_path).unlink()

    return CodexRun(
        returncode=result.returncode,
        last_message=last_message,
        stdout=(result.stdout or "").strip(),
        stderr=(result.stderr or "").strip(),
    )


def format_streams(codex_run: CodexRun) -> str:
    """Format the tails of the codex stdout and stderr."""
    return f"""STDOUT:
{codex_run.stdout[-STDOUT_TAIL_LIMIT:]}

STDERR:
{codex_run.stderr[-STDERR_TAIL_LIMIT:]}"""


@mcp.tool()
def codex_review_changes(
    review_focus: str,
    mode: str,
    what_changed: str = "",
    diff_base: str | None = None,
    project_path: str | None = None,
    acceptance_criteria: str = "",
    extra_context: str = "",
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """
    Run Codex as a read-only adversarial REVIEWER.

    mode "plan": critique of the orchestrator's plan before implementation — gpt-6.1-sol, reasoning
    effort high; points out problems only. mode "code": final review of the implemented diff before
    the PR — gpt-6.1-sol, reasoning effort medium, bugs only, tuned for
    the fewest tokens (no user config, low verbosity, one line per bug).
    `mode` is required; model and
    reasoning_effort default per mode.
    Codex never implements and never edits anything.
    Pass `diff_base` (a git ref such as origin/develop or a milestone
    commit SHA) instead of pasting the diff into `what_changed`; the
    server runs git diff plus untracked files itself.
    """
    if mode not in MODE_PROFILES:
        allowed = ", ".join(MODE_PROFILES)
        return f"ERROR: unknown mode {mode!r}. Allowed modes: {allowed}."

    profile = MODE_PROFILES[mode]
    model = model or profile.model
    reasoning_effort = reasoning_effort or profile.reasoning_effort
    root = resolve_project_path(project_path)
    try:
        what_changed = resolve_change_description(root, what_changed, diff_base)
    except DiffUnavailable as error:
        return str(error)
    prompt = PROMPT_BUILDERS[mode](
        root, what_changed, review_focus, acceptance_criteria, extra_context
    )
    job = CodexJob(
        root=root,
        prompt=prompt,
        model=model,
        reasoning_effort=reasoning_effort,
        overrides=[
            *MODE_EXTRA_OVERRIDES[mode],
            "-c",
            f'sandbox_mode="{SANDBOX_MODE}"',
        ],
        timeout=REVIEW_TIMEOUT_SECONDS,
        task=REVIEW_TASK,
    )
    try:
        codex_run = run_codex(job)
    except CodexUnavailableError as error:
        return str(error)

    if codex_run.returncode != 0:
        return f"""ERROR: Codex review exited with code {codex_run.returncode}.

{format_streams(codex_run)}
"""

    return f"""Codex review completed (mode={mode}, model={model}, reasoning_effort={reasoning_effort}, \
sandbox={SANDBOX_MODE}).

Findings:
{(codex_run.last_message or codex_run.stdout)[-FINDINGS_LIMIT:]}
"""


if __name__ == "__main__":
    mcp.run()
