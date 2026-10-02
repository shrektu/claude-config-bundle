#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("codex-worker")

REVIEW_TIMEOUT_SECONDS = 5100
MAX_DIFF_CHARS = 120_000
MAX_STDERR_CHARS = 2000
INDEX_FILE_NAME = "index"
OUTPUT_FILE_NAME = "last-message.txt"
DEFAULT_BASE = "HEAD"
DISABLED_FEATURES = (
    "apps", "browser_use", "browser_use_external", "computer_use", "goals", "image_generation",
    "in_app_browser", "multi_agent", "personality", "plugins", "remote_plugin", "skill_search", "sleep_tool",
    "tool_suggest", "view_image", "workspace_dependencies", "fast_mode",
)
ACCEPTANCE_HEADING = re.compile(r"(?m)^##[ \t]+acceptance_criteria[ \t]*$")
NEXT_HEADING = re.compile(r"(?m)^#{1,2}[ \t]")
RECHECK_HEADER = "PREVIOUSLY REPORTED — report each again only if still present:"
TOOL_DESCRIPTION = (
    'Read-only Codex review. mode "plan": gpt-6-sol reviews the plan file. mode "code": gpt-6-sol reviews the '
    "diff of project_path against base (a commit; use the review checkpoint SHA after a fix round) with the "
    "plan's acceptance_criteria; recheck lists the previously reported defects. Returns a token header line "
    "and then `PASS` or one line per defect."
)

COMMON_RULES = """You are a read-only reviewer: never modify files, never commit, never run a command that changes \
the repository or the environment. Report ONLY defects. Read other files only to check a claim or to confirm a \
suspected defect. No fixes, no alternatives, no new plan, no style remarks, no praise, no summary, no preamble.
Output one line per defect, at most 30 words, most severe first, in the form `H: {line_form}` or `L: {line_form}`. \
H = wrong behaviour, data loss, security, a broken criterion or contract, a missing or vacuous test. \
L = an edge case needing contrived input, a cosmetic or hint-quality issue.
If there is no defect, output exactly PASS"""

PLAN_INSTRUCTIONS = """Review the PLAN below before it is implemented. Read only the files the plan names, and \
only to check a claim the plan makes about them. Defects to report: false claims about the \
existing code, contradictions, missing steps or dependencies, an unsafe order of steps, missing or uncheckable \
acceptance criteria, behaviour without a test in test_plan, no integration test for a real path.
""" + COMMON_RULES.format(line_form="<section>: <defect>")

CODE_INSTRUCTIONS = """Review the CODE CHANGE below (the DIFF against BASE) against the acceptance criteria. \
Defects to report: bugs, regressions, broken contracts or invariants, security holes, acceptance criteria not \
met, behaviour changed without a test, tests that cannot fail or are skipped.
""" + COMMON_RULES.format(line_form="<path>:<line>: <defect>")


class EventType(StrEnum):
    ERROR = "error"
    TURN_FAILED = "turn.failed"
    TURN_COMPLETED = "turn.completed"


class ReviewMode(StrEnum):
    PLAN = "plan"
    CODE = "code"


@dataclass(frozen=True)
class ReviewProfile:
    model: str
    effort: str
    instructions: str


PROFILES = {
    ReviewMode.PLAN: ReviewProfile("gpt-6-sol", "high", PLAN_INSTRUCTIONS),
    ReviewMode.CODE: ReviewProfile("gpt-6-sol", "high", CODE_INSTRUCTIONS),
}


@dataclass(slots=True)
class TokenUsage:
    input: int = 0
    cached: int = 0
    output: int = 0


class ReviewError(Exception):
    pass


def resolve_project_path(project_path: str | None) -> Path:
    if project_path:
        return Path(project_path).expanduser().resolve()
    for key in ("CLAUDE_PROJECT_DIR", "PWD"):
        value = os.environ.get(key)
        if value and Path(value).exists():
            return Path(value).resolve()
    return Path.cwd().resolve()


def git(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def read_plan(plan_file: str) -> str:
    path = Path(plan_file)
    if not path.is_absolute():
        raise ReviewError(f"plan_file {plan_file!r} is not an absolute path")
    if not path.is_file():
        raise ReviewError(f"plan_file {plan_file!r} is not a file")
    return path.read_text(encoding="utf-8", errors="replace")


def acceptance_section(plan: str) -> str:
    heading = ACCEPTANCE_HEADING.search(plan)
    rest = plan[heading.end():] if heading else ""
    following = NEXT_HEADING.search(rest)
    body = (rest[:following.start()] if following else rest).strip()
    if not body:
        raise ReviewError("the plan has no `## acceptance_criteria` section")
    return f"{heading.group(0)}\n{body}"


def resolve_commit(root: Path, base: str) -> str:
    if git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise ReviewError(f"{root} is not a git work tree")
    found = None if base.startswith("-") else git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if found is None or found.returncode != 0:
        raise ReviewError(f"base {base!r} is not a commit in {root}")
    return found.stdout.strip()


@contextmanager
def snapshot_index(root: Path) -> Iterator[dict[str, str]]:
    real_index = root / git(root, "rev-parse", "--git-path", INDEX_FILE_NAME).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="codex-review-index-") as tmp:
        index = Path(tmp) / INDEX_FILE_NAME
        if real_index.is_file():
            shutil.copyfile(real_index, index)
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        added = git(root, "add", "-A", env=env)
        if added.returncode != 0:
            raise ReviewError(f"git add -A into a temporary index failed in {root}: {added.stderr.strip()}")
        yield env


def build_diff(root: Path, base: str, commit: str) -> str:
    with snapshot_index(root) as env:
        diff = git(root, "diff", "--cached", "--no-color", "--no-ext-diff", commit, env=env).stdout.strip("\n")
        if len(diff) <= MAX_DIFF_CHARS:
            return diff or "(no changes)"
        stat = git(root, "diff", "--cached", "--no-color", "--stat", commit, env=env).stdout.strip("\n")
    return (f"The diff is too large to inline ({len(diff)} chars). Stat against {base}, new files included:\n"
            f"{stat}\nRead the patch with `git diff {base} -- <path>`; read files new since {base} directly.")


def plan_prompt(root: Path, plan_file: str, plan: str) -> str:
    return f"{PLAN_INSTRUCTIONS}\n\nProject root: {root}\n\nPLAN ({plan_file}):\n{plan}"


def code_prompt(root: Path, base: str, plan: str, recheck: str) -> str:
    acceptance = acceptance_section(plan)
    commit = resolve_commit(root, base)
    sections = [CODE_INSTRUCTIONS, f"Project root: {root}\nBASE: {base} ({commit})", acceptance]
    if recheck.strip():
        sections.append(f"{RECHECK_HEADER}\n{recheck.strip()}")
    sections.append("DIFF:\n" + build_diff(root, base, commit))
    return "\n\n".join(sections)


def codex_argv(codex_bin: str, profile: ReviewProfile, output_path: str, root: Path) -> list[str]:
    argv = [codex_bin, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "--ignore-user-config"]
    for feature in DISABLED_FEATURES:
        argv += ["-c", f"features.{feature}=false"]
    argv += ["-c", 'web_search="disabled"', "-c", 'model_reasoning_summary="none"', "-m", profile.model,
             "-c", f'model_reasoning_effort="{profile.effort}"', "-o", output_path, "-C", str(root), "-"]
    return argv


def json_events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def event_error(event: dict) -> str:
    match event.get("type"):
        case EventType.ERROR:
            message = event.get("message")
        case EventType.TURN_FAILED:
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
        case _:
            message = None
    return message.strip() if isinstance(message, str) else ""


def failure_detail(stdout: str, stderr: str) -> str:
    messages = dict.fromkeys(message for message in map(event_error, json_events(stdout)) if message)
    detail = "\n".join([*messages, stderr.strip()]).strip()
    return detail[-MAX_STDERR_CHARS:]


def token_usage(stdout: str) -> TokenUsage:
    usage = TokenUsage()
    for event in json_events(stdout):
        if event.get("type") != EventType.TURN_COMPLETED:
            continue
        counts = event.get("usage")
        if isinstance(counts, dict):
            usage.input += int(counts.get("input_tokens") or 0)
            usage.cached += int(counts.get("cached_input_tokens") or 0)
            usage.output += int(counts.get("output_tokens") or 0)
    return usage


def run_codex(mode: ReviewMode, profile: ReviewProfile, root: Path, prompt: str) -> str:
    codex_bin = os.environ.get("CODEX_BIN", "codex")
    with tempfile.TemporaryDirectory(prefix="codex-review-") as tmp:
        output_path = os.path.join(tmp, OUTPUT_FILE_NAME)
        try:
            result = subprocess.run(codex_argv(codex_bin, profile, output_path, root), input=prompt, cwd=root,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=REVIEW_TIMEOUT_SECONDS)
        except OSError as error:
            return f"ERROR: Codex CLI not found or not runnable ({codex_bin}): {error}. Set CODEX_BIN."
        except subprocess.TimeoutExpired:
            return f"ERROR: Codex review timed out after {REVIEW_TIMEOUT_SECONDS} seconds."
        if result.returncode != 0 or not os.path.isfile(output_path):
            detail = failure_detail(result.stdout or "", result.stderr or "")
            return f"ERROR: codex exited {result.returncode}\n{detail}"
        answer = Path(output_path).read_text(encoding="utf-8", errors="replace").strip()
    usage = token_usage(result.stdout or "")
    tokens = f"tokens in={usage.input} cached={usage.cached} out={usage.output}"
    return f"codex {mode} {profile.model}/{profile.effort} {tokens}\n{answer}"


@mcp.tool(description=TOOL_DESCRIPTION)
def codex_review_changes(
    mode: str,
    plan_file: str,
    project_path: str | None = None,
    base: str = DEFAULT_BASE,
    recheck: str = "",
) -> str:
    try:
        review_mode = ReviewMode(mode)
    except ValueError:
        return f"ERROR: unknown mode {mode!r}. Allowed modes: {', '.join(ReviewMode)}."
    try:
        plan = read_plan(plan_file)
        root = resolve_project_path(project_path)
        if not root.is_dir():
            raise ReviewError(f"project path {root} is not a directory")
        if review_mode is ReviewMode.PLAN:
            prompt = plan_prompt(root, plan_file, plan)
        else:
            prompt = code_prompt(root, base, plan, recheck)
    except ReviewError as error:
        return f"ERROR: {error}"
    return run_codex(review_mode, PROFILES[review_mode], root, prompt)


if __name__ == "__main__":
    mcp.run()
