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
MCP_DIR = REPO / "claude" / "mcp"
CODEX_WORKER_DIR = MCP_DIR / "codex-worker"
CODEX_WORKER = CODEX_WORKER_DIR / "codex_worker.py"
CODEX_WORKER_TEST = CODEX_WORKER_DIR / "test_codex_worker.py"
LEGACY_CODEX_WORKER_TEST = CODEX_WORKER_DIR / "codex_worker_test.py"
AGY_WORKER_DIR = MCP_DIR / "agy-worker"
AGY_WORKER_FILES = (
    "agy_worker.py",
    "test_agy_worker.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "allowed-remotes.txt",
)
AGY_WORKER_FORBIDDEN = (".venv", "__pycache__", ".pytest_cache", ".hypothesis")
MCP_SERVERS = REPO / "claude" / "mcp-servers.json"
AGY_SERVER_ENTRY = {
    "type": "stdio",
    "command": "__HOME__/.claude/mcp/agy-worker/.venv/bin/python",
    "args": ["__HOME__/.claude/mcp/agy-worker/agy_worker.py"],
    "env": {"AGY_BIN": "__AGY_BIN__"},
    "timeout": 5400000,
}
AGY_BIN_PLACEHOLDER = "__AGY_BIN__"
HOOKS_DIR = REPO / "claude" / "hooks"
SETTINGS = REPO / "claude" / "settings.json"
RETIRE = REPO / "retire.json"
CODEX_AGENTS_MD = REPO / "codex" / "AGENTS.md"
README = REPO / "README.md"
BIN_DIR = REPO / "claude" / "bin"
USAGE_REPORT = BIN_DIR / "usage-report"
EXPORT_SCRIPT = REPO / "export.sh"
INSTALL_SCRIPT = REPO / "install.sh"
VENV_PYTHON = Path(os.path.expanduser("~/.claude/mcp/codex-worker/.venv/bin/python"))

DESCRIPTION_MAX_CHARS = 1024
USAGE_REPORT_MAX_SECONDS = 30
USAGE_REPORT_MAX_LINES = 40
USAGE_REPORT_DAYS = "1"
STREAMED_USAGE = {
    "input_tokens": 10,
    "cache_creation_input_tokens": 20,
    "cache_read_input_tokens": 30,
    "output_tokens": 40,
}

HOOK_NAMES = (
    "autofix-on-edit",
    "codex-gate",
    "comment-guard",
    "context-guard",
    "delegation-guard",
    "git-guard",
    "git-policy",
    "read-guard",
    "standards-gate",
    "subagent-verify-check",
    "tdd-guard",
    "verify-guard",
)
REQUIRED_SKILLS = (
    "bb",
    "commit",
    "delegate",
    "epic",
    "parallel",
    "pr-description",
    "qa",
    "repo-standards",
    "review",
    "task",
    "ui-texts",
)
RETIRED_SKILLS = ("rownolegle", "epik", "teksty-ui", "tdd", "quality-bar")
REQUIRED_AGENTS = (
    "codex-runner",
    "flash-review-runner",
    "implementer",
    "plan-gate-runner",
    "reviewer-opus",
    "ui-writer",
    "writer",
)
RETIRED_AGENT_FILE = "implementer-strong.md"
RETIRED_FILES_V1 = (
    "audit-2026-09-12",
    "prompts",
    "settings.json.bak-manual",
    "settings.json.bak-manual2",
)
RETIRED_FILES_V2 = (
    "agents/implementer-strong.md",
    "skills/rownolegle",
    "skills/epik",
    "skills/teksty-ui",
    "skills/qa/references/scenariusze.md",
)
RETIRED_ALLOW_V2 = (
    "Agent(implementer-strong)",
    "Write(/__HOME__/.claude/hooks/**)",
)
REQUIRED_ALLOW = (
    "Agent(implementer)",
    "mcp__codex-worker__*",
    "mcp__agy-worker__*",
)
SESSION_MODEL = "opus[1m]"
RETIRED_MODE = "final-audit"
STALE_TERMS = re.compile(
    r"implementer-strong|rownolegle|\bepik\b(?!/)|teksty-ui"
)
README_STALE_PHRASES = ("reviews every round itself", "before every commit")
README_REVIEW_TERMS = (
    "once per milestone",
    "`--fixup`",
    "delta trio",
    "about 100 lines",
    "autosquash",
)
README_WORKFLOW_TERMS = (
    "plan-gate-runner",
    "flash-review-runner",
    "reviewer-opus",
    "Gemini 3.8 Flash",
    "evidence",
    "agy_debug_consult",
    "Argon",
    "🤖 Wygenerowane przez <model>",
    "`parallel`",
    "`epic`",
    "`ui-texts`",
    "agy-worker",
    "allowed-remotes.txt",
    "poppler-utils",
    "bubblewrap",
    "antigravity.google/cli/install.sh",
    "without `-s`",
)
HOME_LITERAL = "/home/" + "seba"
SCANNED_TREES = ("claude", "codex")
SCANNED_FILES = ("README.md",)
SKIPPED_DIRS = {"__pycache__", ".git"}
HOOK_COMMAND_FILE = re.compile(r"__HOME__/\.claude/hooks/([\w.-]+\.py)")
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

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
    check(CLAUDE_MD.is_file(), "CLAUDE.md missing")
    check(CODEX_AGENTS_MD.is_file(), "codex/AGENTS.md missing")


def check_skills() -> None:
    present = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
    for name in REQUIRED_SKILLS:
        check(name in present, f"skills/ lacks {name}")
    for name in RETIRED_SKILLS:
        check(name not in present, f"skills/ still holds the retired {name}")
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


LOADED_REFERENCE = re.compile(r"Load `(references/[^`]+)`")


def check_loaded_references_exist() -> None:
    for skill in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        for match in LOADED_REFERENCE.finditer(skill.read_text()):
            check(
                (skill.parent / match.group(1)).is_file(),
                f"{skill.parent.name}: loads {match.group(1)}, "
                "which is not in the bundle",
            )


def check_agents() -> None:
    names = sorted(p.stem for p in AGENTS_DIR.glob("*.md"))
    check(
        names == sorted(REQUIRED_AGENTS),
        f"agents/ holds {names}, expected {sorted(REQUIRED_AGENTS)}",
    )
    check(
        not (AGENTS_DIR / RETIRED_AGENT_FILE).exists(),
        f"agents/{RETIRED_AGENT_FILE} is still in the bundle",
    )
    for path in sorted(AGENTS_DIR.glob("*.md")):
        fields = frontmatter_of(path)
        check(bool(fields.get("model")), f"{path.name}: no model in frontmatter")
        check(bool(fields.get("effort")), f"{path.name}: no effort in frontmatter")


def check_no_stale_workflow_text() -> None:
    targets = [CLAUDE_MD, CODEX_AGENTS_MD, README]
    targets += sorted(AGENTS_DIR.glob("*.md")) + sorted(SKILLS_DIR.glob("*/SKILL.md"))
    for path in targets:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            match = STALE_TERMS.search(line)
            if match:
                failures.append(f"{path.relative_to(REPO)}:{number} still mentions {match.group(0)!r}")


def check_readme_workflow() -> None:
    readme = README.read_text()
    flat_readme = " ".join(readme.split())
    for term in README_WORKFLOW_TERMS + README_REVIEW_TERMS:
        check(term in flat_readme, f"README.md does not mention {term!r}")
    for phrase in README_STALE_PHRASES:
        check(phrase not in flat_readme, f"README.md still says {phrase!r}")
    for name in HOOK_NAMES:
        check(name in readme, f"README.md does not mention the hook {name}")


def check_hooks_and_settings() -> None:
    for hook in HOOK_NAMES:
        check((HOOKS_DIR / f"{hook}.py").is_file(), f"hooks/{hook}.py missing")
        check((HOOKS_DIR / f"{hook}-test.py").is_file(), f"hooks/{hook}-test.py missing")
    settings = json.loads(SETTINGS.read_text())
    check(settings.get("model") == SESSION_MODEL, f"settings.json model is {settings.get('model')!r}")
    allow = settings.get("permissions", {}).get("allow", [])
    for wanted in REQUIRED_ALLOW:
        check(wanted in allow, f"settings.json does not allow {wanted}")
    for stale in RETIRED_ALLOW_V2:
        check(stale not in allow, f"settings.json still allows {stale}")
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                for script in HOOK_COMMAND_FILE.findall(
                    hook.get("command", "")
                ):
                    check(
                        (HOOKS_DIR / script).is_file(),
                        f"{event} hook runs the missing hooks/{script}",
                    )
    retire = json.loads(RETIRE.read_text())
    for name in RETIRED_FILES_V1 + RETIRED_FILES_V2:
        check(name in retire.get("files", []), f"retire.json does not retire {name}")
    retired_allow = retire.get("settings", {}).get("permissions.allow", [])
    for stale in RETIRED_ALLOW_V2:
        check(stale in retired_allow, f"retire.json does not retire the permission {stale}")


def check_mcp_servers() -> None:
    check(CODEX_WORKER_TEST.is_file(), "test_codex_worker.py missing")
    check(
        not LEGACY_CODEX_WORKER_TEST.exists(),
        "codex_worker_test.py is still in the bundle",
    )
    for name in AGY_WORKER_FILES:
        check(
            (AGY_WORKER_DIR / name).is_file(), f"mcp/agy-worker/{name} missing"
        )
    for name in AGY_WORKER_FORBIDDEN:
        check(
            not (AGY_WORKER_DIR / name).exists(),
            f"mcp/agy-worker/{name} must not be in the bundle",
        )
    servers = json.loads(MCP_SERVERS.read_text()).get("mcpServers", {})
    check("codex-worker" in servers, "mcp-servers.json has no codex-worker")
    check(
        servers.get("agy-worker") == AGY_SERVER_ENTRY,
        f"mcp-servers.json agy-worker entry is {servers.get('agy-worker')!r}",
    )
    check(
        AGY_BIN_PLACEHOLDER in EXPORT_SCRIPT.read_text(),
        f"export.sh does not write {AGY_BIN_PLACEHOLDER}",
    )
    check(
        AGY_BIN_PLACEHOLDER in INSTALL_SCRIPT.read_text(),
        f"install.sh does not render {AGY_BIN_PLACEHOLDER}",
    )


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
        "print(w.codex_review_changes(review_focus='x', mode=%r,"
        " project_path='/tmp'), end='')"
        % (str(CODEX_WORKER.parent), RETIRED_MODE)
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
        check_loaded_references_exist,
        check_agents,
        check_no_stale_workflow_text,
        check_readme_workflow,
        check_hooks_and_settings,
        check_mcp_servers,
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
