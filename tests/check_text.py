#!/usr/bin/env python3
"""Static checks for the TEXT/AGENT/PROMPT half of the bundle."""
import importlib.util
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO / "claude" / "CLAUDE.md"
SKILLS_DIR = REPO / "claude" / "skills"
AGENTS_DIR = REPO / "claude" / "agents"
CODEX_WORKER = REPO / "claude" / "mcp" / "codex-worker" / "codex_worker.py"
CODEX_WORKER_TEST = CODEX_WORKER.parent / "codex_worker_test.py"
HOOKS_DIR = REPO / "claude" / "hooks"
SETTINGS = REPO / "claude" / "settings.json"
RETIRE = REPO / "retire.json"
CODEX_AGENTS_MD = REPO / "codex" / "AGENTS.md"
README = REPO / "README.md"
USAGE_REPORT = REPO / "claude" / "bin" / "usage-report"
VENV_PYTHON = Path(os.path.expanduser("~/.claude/mcp/codex-worker/.venv/bin/python"))

CLAUDE_MD_MAX_BYTES = 8400
DESCRIPTION_MAX_CHARS = 1024
USAGE_REPORT_MAX_SECONDS = 30
USAGE_REPORT_MAX_LINES = 40
USAGE_REPORT_DAYS = "30"
STREAMED_USAGE = {
    "input_tokens": 10,
    "cache_creation_input_tokens": 20,
    "cache_read_input_tokens": 30,
    "output_tokens": 40,
}

HOOK_NAMES = (
    "git-guard",
    "git-policy",
    "verify-guard",
    "read-guard",
    "delegation-guard",
    "subagent-verify-check",
    "tdd-guard",
    "comment-guard",
)
SHARED_HOOK_MODULES = ("shell_words.py", "code_files.py")
SKILL_NAMES = ("delegate", "review", "commit", "pr-description", "repo-standards", "tdd", "quality-bar")
DEVELOPER_AGENT = "developer"
DEVELOPER_MODEL = "claude-sonnet-5-5"
DEVELOPER_EFFORT = "medium"
DEVELOPER_SKILLS = ("tdd", "repo-standards", "quality-bar")
RUNNER_AGENT = "codex-runner"
RUNNER_MODEL = "haiku"
AGENT_NAMES = (DEVELOPER_AGENT, RUNNER_AGENT)
RETIRED_AGENTS = ("implementer", "implementer-hard", "implementer-opus", "commander-opus")
RETIRED_ALLOW = tuple(f"Agent({name})" for name in RETIRED_AGENTS)
DEVELOPER_ALLOW = f"Agent({DEVELOPER_AGENT})"
SESSION_MODEL = "claude-opus-5-5"
SESSION_MODEL_EFFORT = "high"
TDD_GUARD_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
TDD_GUARD_COMMAND = "python3 __HOME__/.claude/hooks/tdd-guard.py"
COMMENT_GUARD_COMMAND = "python3 __HOME__/.claude/hooks/comment-guard.py"
RETIRED_MODE = "final-audit"
STALE_TERMS = re.compile(r"implementer|commander-opus|final-audit|\bXL\b")
REVERT_SENTENCE = (
    "Never revert or discard changes you did not make (checkout/restore/stash/reset/clean are blocked "
    "by a hook); if you think a revert is needed, stop and report."
)
ACCEPTANCE_HEADING = re.compile(r"(?m)^## acceptance_criteria\s*$")
TEST_PLAN_HEADING = re.compile(r"(?m)^## test_plan\s*$")
ABSOLUTE_PATH = re.compile(r"(?m)(?:^|\s)/[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+")
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
HOME_LITERAL = "/home/" + "seba"
SCANNED_TREES = ("claude", "codex")
SCANNED_FILES = ("README.md",)
SKIPPED_DIRS = {"__pycache__", ".git"}

failures = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def frontmatter_of(path: Path) -> dict:
    match = FRONTMATTER.match(path.read_text())
    if not match:
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if re.match(r"^\S[^:]*:", line):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def check_claude_md() -> None:
    size = CLAUDE_MD.stat().st_size
    check(size <= CLAUDE_MD_MAX_BYTES, f"CLAUDE.md is {size} bytes (max {CLAUDE_MD_MAX_BYTES})")
    text = CLAUDE_MD.read_text()
    for hook in HOOK_NAMES:
        check(hook in text, f"CLAUDE.md does not mention the hook {hook}")
    for skill in SKILL_NAMES:
        check(skill in text, f"CLAUDE.md does not mention the skill {skill}")


def check_skills() -> None:
    present = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
    check(present == sorted(SKILL_NAMES), f"skills/ holds {present}, expected {sorted(SKILL_NAMES)}")
    for name in present:
        path = SKILLS_DIR / name / "SKILL.md"
        check(path.is_file(), f"{name}: SKILL.md missing")
        if not path.is_file():
            continue
        fields = frontmatter_of(path)
        check(bool(fields), f"{name}: no YAML frontmatter")
        check(fields.get("name") == name, f"{name}: frontmatter name is {fields.get('name')!r}")
        description = fields.get("description", "")
        check(bool(description), f"{name}: frontmatter description missing")
        check(
            len(description) <= DESCRIPTION_MAX_CHARS,
            f"{name}: description is {len(description)} chars (max {DESCRIPTION_MAX_CHARS})",
        )


def check_delegate_markers() -> None:
    text = (SKILLS_DIR / "delegate" / "SKILL.md").read_text()
    check(bool(ACCEPTANCE_HEADING.search(text)), "delegate: no `## acceptance_criteria` heading")
    check(bool(TEST_PLAN_HEADING.search(text)), "delegate: no `## test_plan` heading")
    check("plan_file:" in text, "delegate: no `plan_file:` in the spawn prompts")
    check("verify --" in text, "delegate: no `verify --` in the commands")
    check(bool(ABSOLUTE_PATH.search(text)), "delegate: no absolute path in the template")
    check("may not touch" in text, "delegate: no repo boundary line with `may not touch`")


def check_agents() -> None:
    names = sorted(p.stem for p in AGENTS_DIR.glob("*.md"))
    check(names == sorted(AGENT_NAMES), f"agents/ holds {names}, expected {sorted(AGENT_NAMES)}")
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fields = frontmatter_of(path)
        check(bool(fields.get("model")), f"{path.name}: no model in frontmatter")
        check(bool(fields.get("effort")), f"{path.name}: no effort in frontmatter")
    developer = AGENTS_DIR / f"{DEVELOPER_AGENT}.md"
    if developer.is_file():
        fields = frontmatter_of(developer)
        check(fields.get("model") == DEVELOPER_MODEL, f"{DEVELOPER_AGENT}: model is {fields.get('model')!r}")
        check(fields.get("effort") == DEVELOPER_EFFORT, f"{DEVELOPER_AGENT}: effort is {fields.get('effort')!r}")
        skills = fields.get("skills", "")
        for skill in DEVELOPER_SKILLS:
            check(skill in skills, f"{DEVELOPER_AGENT}: skills: does not preload {skill} (got {skills!r})")
        body = " ".join(FRONTMATTER.sub("", developer.read_text()).split())
        check(REVERT_SENTENCE in body, f"{DEVELOPER_AGENT}: the git-safety sentence is missing or reworded")
    runner = AGENTS_DIR / f"{RUNNER_AGENT}.md"
    if runner.is_file():
        model = frontmatter_of(runner).get("model")
        check(model == RUNNER_MODEL, f"{RUNNER_AGENT}: model is {model!r}")


def check_no_stale_workflow_text() -> None:
    targets = [CLAUDE_MD, CODEX_AGENTS_MD, README]
    targets += sorted(AGENTS_DIR.glob("*.md")) + sorted(SKILLS_DIR.glob("*/SKILL.md"))
    for path in targets:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = STALE_TERMS.search(line)
            if match:
                failures.append(f"{path.relative_to(REPO)}:{number} still mentions {match.group(0)!r}")


def check_hooks_and_settings() -> None:
    for hook in HOOK_NAMES:
        check((HOOKS_DIR / f"{hook}.py").is_file(), f"hooks/{hook}.py missing")
        check((HOOKS_DIR / f"{hook}-test.py").is_file(), f"hooks/{hook}-test.py missing")
    for module in SHARED_HOOK_MODULES:
        check((HOOKS_DIR / module).is_file(), f"hooks/{module} missing")
    readme = README.read_text()
    for name in HOOK_NAMES + SHARED_HOOK_MODULES:
        check(name in readme, f"README.md does not mention {name}")
    check(CODEX_WORKER_TEST.is_file(), "codex_worker_test.py missing")
    settings = json.loads(SETTINGS.read_text())
    check(settings.get("model") == SESSION_MODEL, f"settings.json model is {settings.get('model')!r}")
    effort = settings.get("modelSettings", {}).get(SESSION_MODEL, {}).get("effortLevel")
    check(effort == SESSION_MODEL_EFFORT, f"settings.json modelSettings.{SESSION_MODEL} effort is {effort!r}")
    allow = settings.get("permissions", {}).get("allow", [])
    check(DEVELOPER_ALLOW in allow, f"settings.json does not allow {DEVELOPER_ALLOW}")
    for stale in RETIRED_ALLOW:
        check(stale not in allow, f"settings.json still allows {stale}")
    groups = [entry for entry in settings.get("hooks", {}).get("PreToolUse", [])
              if entry.get("matcher") == TDD_GUARD_MATCHER]
    commands = [hook.get("command") for entry in groups for hook in entry.get("hooks", [])]
    check(commands == [TDD_GUARD_COMMAND, COMMENT_GUARD_COMMAND], f"PreToolUse {TDD_GUARD_MATCHER} runs {commands}")
    retire = json.loads(RETIRE.read_text())
    for name in RETIRED_AGENTS:
        check(f"agents/{name}.md" in retire.get("files", []), f"retire.json does not retire agents/{name}.md")
    retired_allow = retire.get("settings", {}).get("permissions.allow", [])
    for stale in RETIRED_ALLOW:
        check(stale in retired_allow, f"retire.json does not retire the permission {stale}")


def check_codex_worker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            py_compile.compile(str(CODEX_WORKER), doraise=True, cfile=os.path.join(tmp, "cw.pyc"))
        except py_compile.PyCompileError as error:
            failures.append(f"codex_worker.py does not compile: {error}")
            return
    interpreter = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    code = (
        "import sys; sys.path.insert(0, %r); import codex_worker as w;"
        "print(w.codex_review_changes(mode=%r, plan_file=%r, project_path='/tmp'), end='')"
        % (str(CODEX_WORKER.parent), RETIRED_MODE, str(CLAUDE_MD))
    )
    result = subprocess.run([str(interpreter), "-c", code], capture_output=True, text=True)
    check(
        result.returncode == 0 and result.stdout.startswith("ERROR: unknown mode"),
        f"codex_review_changes(mode={RETIRED_MODE!r}) returned {result.stdout[:80]!r} "
        f"(rc={result.returncode}, stderr={result.stderr.strip()[-200:]!r})",
    )


def check_no_home_literal() -> None:
    targets = [REPO / name for name in SCANNED_FILES]
    for tree in SCANNED_TREES:
        for root, dirs, names in os.walk(REPO / tree):
            dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
            targets += [Path(root) / name for name in names]
    for path in targets:
        text = path.read_text(errors="ignore")
        for number, line in enumerate(text.splitlines(), 1):
            if HOME_LITERAL in line:
                failures.append(f"{path.relative_to(REPO)}:{number} contains a hardcoded home path")


def load_usage_report():
    spec = importlib.util.spec_from_loader(
        "usage_report", importlib.machinery.SourceFileLoader("usage_report", str(USAGE_REPORT))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_usage_dedup() -> None:
    module = load_usage_report()
    fragment = {"type": "assistant", "message": {"id": "msg_1", "usage": STREAMED_USAGE, "content": []}}
    with tempfile.TemporaryDirectory() as tmp:
        first = os.path.join(tmp, "session.jsonl")
        with open(first, "w") as handle:
            for _ in range(2):
                handle.write(json.dumps(fragment) + "\n")
        resumed = os.path.join(tmp, "resumed.jsonl")
        with open(resumed, "w") as handle:
            handle.write(json.dumps(fragment) + "\n")
        stats = module.Stats()
        module.scan(first, stats)
        module.scan(resumed, stats)
        module.aggregate(stats)
    check(
        stats.main.turns == 1,
        f"one message across two transcripts counted as {stats.main.turns} turns",
    )
    check(
        stats.main.output == STREAMED_USAGE["output_tokens"],
        f"output tokens doubled: {stats.main.output}",
    )
    check(len(stats.contexts) == 1, f"context samples doubled: {len(stats.contexts)}")


def check_usage_report() -> None:
    started = time.monotonic()
    result = subprocess.run(
        [str(USAGE_REPORT), "--days", USAGE_REPORT_DAYS],
        capture_output=True,
        text=True,
        timeout=USAGE_REPORT_MAX_SECONDS * 2,
    )
    elapsed = time.monotonic() - started
    check(result.returncode == 0, f"usage-report exited {result.returncode}: {result.stderr[-300:]}")
    check(elapsed < USAGE_REPORT_MAX_SECONDS, f"usage-report took {elapsed:.1f}s")
    lines = result.stdout.strip().splitlines()
    check(
        0 < len(lines) <= USAGE_REPORT_MAX_LINES,
        f"usage-report printed {len(lines)} lines (max {USAGE_REPORT_MAX_LINES})",
    )


def main() -> int:
    for step in (
        check_claude_md,
        check_skills,
        check_delegate_markers,
        check_agents,
        check_no_stale_workflow_text,
        check_hooks_and_settings,
        check_codex_worker,
        check_usage_dedup,
        check_no_home_literal,
        check_usage_report,
    ):
        step()
    if failures:
        print(f"check_text: {len(failures)} failure(s)")
        for failure in failures:
            print(f"  FAIL {failure}")
        return 1
    print("check_text: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
