#!/usr/bin/env python3
import contextlib
import json
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
DETACHED_HEAD_EXIT = 1
DEV_NULL = "/dev/null"
GIT_OUTPUT_ENCODING = "utf-8"
GIT_DECODE_ERRORS = "replace"
LAST_MESSAGE_ENCODING = "utf-8"
CODEX_BIN_ENV = "CODEX_BIN"
DEFAULT_CODEX_BIN = "codex"
END_OF_OPTIONS = "--end-of-options"
MISSING_CHANGE_ERROR = "ERROR: pass diff_base (preferred) or what_changed."

IMPLEMENT_TIMEOUT_SECONDS = 3600
IMPLEMENT_SANDBOX_MODE = "workspace-write"
IMPLEMENT_NETWORK_OVERRIDE = "sandbox_workspace_write.network_access=false"
WRITABLE_ROOTS_KEY = "sandbox_workspace_write.writable_roots"
VERIFY_CACHE_PARTS = (".cache", "claude-verify")
WORK_BRANCH_PREFIXES = ("feature/", "bugfix/", "hotfix/", "test/")
GIT_INDEX_FILE_ENV = "GIT_INDEX_FILE"
TEMP_INDEX_NAME = "index"
REVIEW_TASK = "review"
IMPLEMENT_TASK = "implement run"
DETACHED_HEAD = "[detached HEAD]"
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
IMPLEMENT_PROFILE = CodexProfile(model="gpt-6.1-sol", reasoning_effort="medium")

IMPLEMENT_PREAMBLE = """\
You are Codex acting as the IMPLEMENTER for the plan below.
Follow it; do not redesign it.

Hard rules:
- You are the implementer: edit files and run checks only. Never run a \
git command that changes history, the index or the working tree beyond \
your own file edits: no commit, add, stash, checkout, restore, reset, \
clean, rebase, merge, push.
- Write zero comments in code. Rename, extract a named function or name \
the constant instead.
- Python docstrings: one line, one sentence, at most 72 characters, \
never a module docstring.
- Never add a suppression (noqa, type: ignore, eslint-disable, NOLINT); \
report the line instead.
- Run every test, lint and build through \
~/.claude/bin/verify --repo <repo> -- '<command>'; never a bare test \
command.
- Each TDD phase starts with a RED verify run of its new test, before \
the production edit; keep its log path.
- Stay inside the repo named below; touch nothing outside it.
- Finish with a report under 60 lines: changed files, the RED verify log \
path per phase, the verify summary lines, deviations and concerns."""


MODE_PROFILES = {
    MODE_PLAN: CodexProfile(model="gpt-6.1-sol", reasoning_effort="high"),
    MODE_CODE: CodexProfile(model="gpt-6.1-sol", reasoning_effort="high"),
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
    env: dict[str, str] | None = None,
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
            env={**os.environ, **(env or {})},
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


class Snapshot(NamedTuple):
    """Working tree state captured before an implement run."""

    head: str
    tree: str


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


def is_work_branch(branch: str) -> bool:
    """Tell whether the branch name has a work-branch prefix."""
    return branch.startswith(WORK_BRANCH_PREFIXES)


def current_branch(root: str) -> str:
    """Return the checked-out branch name, empty when detached."""
    output = run_git(
        root,
        ["symbolic-ref", "--short", "-q", "HEAD"],
        accepted_exit_codes=(0, DETACHED_HEAD_EXIT),
    )
    return output.strip()


def work_branch_error(root: str) -> str | None:
    """Return a refusal message unless the repo is on a work branch."""
    try:
        branch = current_branch(root)
    except DiffUnavailable as error:
        return f"ERROR: cannot read the current branch of {root}: {error}"
    if is_work_branch(branch):
        return None
    allowed = ", ".join(WORK_BRANCH_PREFIXES)
    name = repr(branch or DETACHED_HEAD)
    return (
        f"ERROR: refusing to implement on branch {name}: "
        f"only work branches ({allowed}) are allowed."
    )


def verify_cache_dir() -> Path:
    """Return the directory where verify keeps its logs and ledger."""
    return Path.home().joinpath(*VERIFY_CACHE_PARTS)


def snapshot_working_tree(root: str) -> Snapshot:
    """Save HEAD and the whole working tree as a git tree object."""
    head = run_git(root, ["rev-parse", "HEAD"]).strip()
    with tempfile.TemporaryDirectory() as scratch:
        index_file = str(Path(scratch) / TEMP_INDEX_NAME)
        index_env = {GIT_INDEX_FILE_ENV: index_file}
        run_git(root, ["read-tree", head], env=index_env)
        run_git(root, ["add", "-A"], env=index_env)
        tree = run_git(root, ["write-tree"], env=index_env).strip()
    return Snapshot(head=head, tree=tree)


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


def describe_worktree(root: str) -> str:
    """Describe the repo state with git status and the diff stat."""
    try:
        status = run_git(root, ["status", "--short"]).rstrip()
        diffstat = run_git(root, ["diff", "HEAD", "--stat"]).rstrip()
    except DiffUnavailable as error:
        return f"unavailable: {error}"
    return f"""git status --short:
{status or "[clean]"}

git diff HEAD --stat:
{diffstat or "[empty]"}"""


def build_implement_report(
    root: str, snapshot: Snapshot, headline: str, body: str
) -> str:
    """Assemble the implement result around the pre-run snapshot."""
    return f"""{headline}

Snapshot before the run:
HEAD: {snapshot.head}
TREE: {snapshot.tree}

{body}

{describe_worktree(root)}
"""


def implement_overrides() -> list[str]:
    """Return the codex config overrides of the write sandbox."""
    writable_roots = json.dumps([str(verify_cache_dir())])
    settings = [
        LOW_VERBOSITY_OVERRIDE,
        f'sandbox_mode="{IMPLEMENT_SANDBOX_MODE}"',
        IMPLEMENT_NETWORK_OVERRIDE,
        f"{WRITABLE_ROOTS_KEY}={writable_roots}",
    ]
    return [arg for setting in settings for arg in ("-c", setting)]


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
    the PR — gpt-6.1-sol, reasoning effort high, bugs only, tuned for the fewest tokens (no user
    config, low verbosity, one line per bug). `mode` is required; model and reasoning_effort default per mode.
    Codex never implements and never edits anything.
    Pass `diff_base` (a git ref such as origin/develop or a review-checkpoint SHA) instead of pasting the
    diff into `what_changed`; the server runs git diff plus untracked files itself.
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


@mcp.tool()
def codex_implement(
    prompt: str,
    project_path: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> str:
    """Run the escalation Codex implementer on a work-branch repo."""
    root = resolve_project_path(project_path)
    refusal = work_branch_error(root)
    if refusal:
        return refusal
    try:
        snapshot = snapshot_working_tree(root)
    except DiffUnavailable as error:
        return f"ERROR: cannot snapshot {root} before the run: {error}"

    model = model or IMPLEMENT_PROFILE.model
    effort = reasoning_effort or IMPLEMENT_PROFILE.reasoning_effort
    job = CodexJob(
        root=root,
        prompt=f"{IMPLEMENT_PREAMBLE}\n\nRepository root: {root}\n\n{prompt}",
        model=model,
        reasoning_effort=effort,
        overrides=implement_overrides(),
        timeout=IMPLEMENT_TIMEOUT_SECONDS,
        task=IMPLEMENT_TASK,
    )
    try:
        codex_run = run_codex(job)
    except CodexUnavailableError as error:
        return build_implement_report(root, snapshot, str(error), "")

    if codex_run.returncode != 0:
        code = codex_run.returncode
        headline = f"ERROR: Codex implement run exited with code {code}."
        return build_implement_report(
            root, snapshot, headline, format_streams(codex_run)
        )

    headline = (
        f"Codex implement run completed (mode=implement, model={model}, "
        f"reasoning_effort={effort}, sandbox={IMPLEMENT_SANDBOX_MODE})."
    )
    final_message = codex_run.last_message or codex_run.stdout
    body = f"Codex final message:\n{final_message[-FINDINGS_LIMIT:]}"
    return build_implement_report(root, snapshot, headline, body)


if __name__ == "__main__":
    mcp.run()
