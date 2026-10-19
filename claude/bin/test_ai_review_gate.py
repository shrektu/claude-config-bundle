import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

SCRIPT = Path(__file__).resolve().parent / "ai-review-gate"
MODULE_NAME = "ai_review_gate"
EXIT_PASS = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2
TEST_TIMEOUT = 60
EXECUTABLE_MODE = 0o755
PINNED_SHEBANG = "#!__HOME__/.pyenv/versions/3.14.3/bin/python3"
ID_LENGTH = 10
EARLIER_HEADING = "Earlier rounds on this branch:"
DELTA_HEADING = "Changed since the last round:"
NEXT_SECTION = "\n\n"
DIFF_HEADING = "Diff:"
MISSING_TREE = "0" * 40
WAIVER_REASON = "accepted trade-off for this module"
ROUND_CAP = 5
FINDING_CAP = 60
ELAPSED_LINE = re.compile(r"^ai-review-gate: .*\(\d+s\)$", re.MULTILINE)
CACHED_LINE = re.compile(r"^ai-review-gate: .*\(cached\)$", re.MULTILINE)
BASE_SOURCE = '"""Module."""\n\nVALUE = 1\n'
FINDING = {
    "path": "a.py",
    "line": 3,
    "category": "architecture",
    "text": "Move VALUE into the settings module like the other options.",
}
NAMING_FINDING = {
    "path": "a.py",
    "line": 3,
    "category": "naming",
    "text": "Rename VALUE to MAX_RETRIES; the name lies about its role.",
}
TEST_QUALITY_FINDING = {
    "path": "test_a.py",
    "line": 3,
    "category": "test-quality",
    "text": "Assert a hand-written literal instead of recomputing it.",
}
PREVIOUS_PROMPT_VERSION = "1"
CHECKLIST_MARKERS = (
    "mirror assertion",
    "change detector",
    "partial mock",
    "mock-only assertion",
    "replaces the very thing",
    "exists only for tests",
    "fixed sleep",
)
UNICODE_FINDING = {
    "path": "a.py",
    "line": 3,
    "category": "duplication",
    "text": "Zamień pętlę na comprehension — łatwiej przeczytać ✓.",
}
ENGINE_SOURCE = """
import json, os, pathlib, sys, time
state = pathlib.Path(os.environ["STUB_STATE"])
state.mkdir(parents=True, exist_ok=True)
calls = state / "calls"
count = int(calls.read_text()) + 1 if calls.exists() else 1
calls.write_text(str(count))
(state / "prompt").write_text(sys.stdin.read(), encoding="utf-8")
(state / "cwd").write_text(os.getcwd(), encoding="utf-8")
(state / "guard").write_text(
    os.environ.get("CLAUDE_AI_REVIEW_GATE", ""), encoding="utf-8"
)
time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
first = os.environ.get("STUB_OUTPUT_FIRST")
if count == 1 and first is not None:
    sys.stdout.write(first)
else:
    sys.stdout.write(os.environ.get("STUB_OUTPUT", ""))
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


@dataclass(frozen=True)
class Run:
    code: int
    out: str
    err: str


@dataclass(frozen=True)
class Gate:
    repo: Path
    cache: Path
    state: Path
    engine: Path

    def env(self, **extra: str) -> dict[str, str]:
        env = git_env()
        env.pop("CLAUDE_AI_REVIEW_GATE", None)
        env.update(
            {
                "AI_REVIEW_CACHE_DIR": str(self.cache),
                "AI_REVIEW_ENGINE_CMD": shlex.join(
                    [sys.executable, str(self.engine)]
                ),
                "AI_REVIEW_HABITS_BIN": "/nonexistent/habits",
                "STUB_STATE": str(self.state),
                "STUB_OUTPUT": verdict(),
            }
        )
        env.update(extra)
        return env

    def run(self, *args: str, **extra: str) -> Run:
        done = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT,
            check=False,
        )
        return Run(done.returncode, done.stdout, done.stderr)

    def check(self, *args: str, **extra: str) -> Run:
        return self.run("check", "--repo", str(self.repo), *args, **extra)

    @property
    def calls(self) -> int:
        calls = self.state / "calls"
        return int(calls.read_text()) if calls.exists() else 0

    @property
    def prompt(self) -> str:
        return (self.state / "prompt").read_text(encoding="utf-8")


def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    return env


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=git_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def verdict(*findings: dict[str, object]) -> str:
    return json.dumps({"findings": list(findings)})


def envelope(result: str) -> str:
    return json.dumps(
        {"type": "result", "is_error": False, "result": result}
    )


def load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(MODULE_NAME, str(SCRIPT))
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate_module() -> ModuleType:
    return load_module()


@pytest.fixture
def gate(tmp_path: Path) -> Gate:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "a.py", BASE_SOURCE)
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "init")
    engine = tmp_path / "engine.py"
    engine.write_text(ENGINE_SOURCE, encoding="utf-8")
    return Gate(repo, tmp_path / "cache", tmp_path / "state", engine)


def stage_change(gate: Gate) -> None:
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 2\n")
    git(gate.repo, "add", "a.py")


def finding_id(finding: dict[str, object]) -> str:
    raw = f"{finding['path']}{finding['category']}{finding['text']}"
    return hashlib.sha1(raw.encode()).hexdigest()[:ID_LENGTH]


def test_script_is_executable_with_pinned_shebang() -> None:
    assert os.access(SCRIPT, os.X_OK)
    first = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert first == PINNED_SHEBANG


def test_finding_blocks_with_id_and_waive_hint(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    ident = finding_id(FINDING)
    assert run.code == EXIT_FINDINGS, run
    expected = f"a.py:3 [architecture] {FINDING['text']} (id {ident})"
    assert expected in run.out.splitlines()
    assert (
        f"ai-review-gate waive --repo {gate.repo} --finding" in run.out
    )
    assert "--reason" in run.out
    assert gate.calls == 1


def test_clean_verdict_passes(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict())

    assert run.code == EXIT_PASS, run
    assert gate.calls == 1


def test_engine_runs_in_repo_root_with_recursion_guard(gate: Gate) -> None:
    stage_change(gate)
    (gate.repo / "pkg").mkdir()

    run = gate.run(
        "check", "--repo", str(gate.repo / "pkg"), "--staged"
    )

    assert run.code == EXIT_PASS, run
    assert (gate.state / "cwd").read_text() == str(gate.repo.resolve())
    assert (gate.state / "guard").read_text() == "1"


def test_prompt_carries_diff_files_and_instructions(gate: Gate) -> None:
    stage_change(gate)

    gate.check("--staged")

    prompt = gate.prompt
    assert "+OTHER = 2" in prompt
    assert "a.py" in prompt
    assert '"findings"' in prompt
    for category in (
        "architecture",
        "duplication",
        "habit",
        "test-quality",
    ):
        assert category in prompt


def test_test_quality_category_accepted(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict(TEST_QUALITY_FINDING))

    ident = finding_id(TEST_QUALITY_FINDING)
    assert run.code == EXIT_FINDINGS, run
    expected = (
        f"test_a.py:3 [test-quality] {TEST_QUALITY_FINDING['text']}"
        f" (id {ident})"
    )
    assert expected in run.out.splitlines()


def test_unknown_category_is_dropped(gate: Gate) -> None:
    stage_change(gate)
    unknown = {**FINDING, "category": "test-qualty"}

    run = gate.check("--staged", STUB_OUTPUT=verdict(unknown))

    assert run.code == EXIT_PASS, run
    assert gate.calls == 1


def test_out_of_scope_category_is_dropped(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict(NAMING_FINDING, FINDING))

    assert run.code == EXIT_FINDINGS, run
    assert finding_id(FINDING) in run.out
    assert finding_id(NAMING_FINDING) not in run.out
    assert "[naming]" not in run.out


def test_instructions_list_test_quality_checklist(
    gate_module: ModuleType,
) -> None:
    instructions = " ".join(gate_module.REVIEW_INSTRUCTIONS.split())

    assert "- test-quality:" in instructions
    assert "architecture, duplication, habit, test-quality" in instructions
    for marker in CHECKLIST_MARKERS:
        assert marker in instructions


def test_prompt_version_bump_invalidates_cache(
    gate_module: ModuleType,
) -> None:
    prompt = "same prompt"
    command = ["engine", "--flag"]
    old_identity = f"{prompt}{PREVIOUS_PROMPT_VERSION}{shlex.join(command)}"
    old_key = hashlib.sha256(old_identity.encode()).hexdigest()

    current = gate_module.cache_path(prompt, command)

    assert gate_module.PROMPT_VERSION != PREVIOUS_PROMPT_VERSION
    assert current.stem != old_key


def test_prompt_uses_ten_lines_of_context(gate: Gate) -> None:
    lines = [f"LINE_{index} = {index}\n" for index in range(30)]
    write(gate.repo, "b.py", "".join(lines))
    git(gate.repo, "add", "b.py")
    git(gate.repo, "commit", "-q", "-m", "b")
    lines[15] = "LINE_15 = 99\n"
    write(gate.repo, "b.py", "".join(lines))
    git(gate.repo, "add", "b.py")

    gate.check("--staged")

    assert "\n LINE_5 = 5\n" in gate.prompt
    assert "\n LINE_4 = 4\n" not in gate.prompt


def test_prompt_includes_habits_when_available(
    gate: Gate, tmp_path: Path
) -> None:
    habits = tmp_path / "habits"
    habits.write_text(
        "#!/bin/sh\necho \"H999 habit rule for $@\"\n", encoding="utf-8"
    )
    habits.chmod(EXECUTABLE_MODE)
    stage_change(gate)

    gate.check("--staged", AI_REVIEW_HABITS_BIN=str(habits))

    assert "H999 habit rule" in gate.prompt
    assert f"--repo {gate.repo}" in gate.prompt


def test_verdict_is_cached_per_diff(gate: Gate) -> None:
    stage_change(gate)

    first = gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    second = gate.check("--staged", STUB_OUTPUT=verdict())

    assert first.code == second.code == EXIT_FINDINGS
    assert gate.calls == 1
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 3\n")
    git(gate.repo, "add", "a.py")
    third = gate.check("--staged", STUB_OUTPUT=verdict())
    assert third.code == EXIT_PASS
    assert gate.calls == 2


def test_cache_key_depends_on_engine(gate: Gate) -> None:
    stage_change(gate)
    args = ("--tracked", "--paths", "a.py")
    gate.check(*args, STUB_OUTPUT=verdict(FINDING))

    gate.check(
        *args,
        AI_REVIEW_ENGINE_CMD=shlex.join(
            [sys.executable, str(gate.engine), "--other"]
        ),
    )

    assert gate.calls == 2


def test_waived_finding_passes(gate: Gate) -> None:
    stage_change(gate)
    ident = finding_id(FINDING)
    blocked = gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    assert blocked.code == EXIT_FINDINGS

    waived = gate.run(
        "waive",
        "--repo",
        str(gate.repo),
        "--finding",
        ident,
        "--reason",
        "name kept for API compatibility",
    )
    run = gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    assert waived.code == EXIT_PASS, waived
    assert run.code == EXIT_PASS, run
    assert f"waived: {ident} name kept for API compatibility" in run.out
    stored = json.loads((gate.cache / "waivers.json").read_text())
    assert json.dumps(stored).count(ident) == 1


def test_waiver_is_scoped_to_repo(gate: Gate, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    ident = finding_id(FINDING)
    gate.run(
        "waive", "--repo", str(other), "--finding", ident, "--reason", "x"
    )
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    assert run.code == EXIT_FINDINGS


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_waive_requires_reason(gate: Gate, reason: str | None) -> None:
    args = ["waive", "--repo", str(gate.repo), "--finding", "abcdef0123"]
    if reason is not None:
        args += ["--reason", reason]

    run = gate.run(*args)

    assert run.code == EXIT_ERROR
    assert not (gate.cache / "waivers.json").exists()


def test_merge_commit_is_skipped(gate: Gate) -> None:
    stage_change(gate)
    head = git(gate.repo, "rev-parse", "HEAD").strip()
    (gate.repo / ".git" / "MERGE_HEAD").write_text(head + "\n")

    run = gate.check("--staged")

    assert run.code == EXIT_PASS
    assert "merge" in run.out
    assert gate.calls == 0


def test_empty_diff_is_skipped(gate: Gate) -> None:
    run = gate.check("--staged")

    assert run.code == EXIT_PASS
    assert "empty diff" in run.out
    assert gate.calls == 0


def test_recursion_guard_skips(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", CLAUDE_AI_REVIEW_GATE="1")

    assert run.code == EXIT_PASS
    assert "recursion" in run.out
    assert gate.calls == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"AI_REVIEW_ENGINE_CMD": "/nonexistent/engine"},
        {"STUB_EXIT": "3"},
        {"STUB_SLEEP": "5", "AI_REVIEW_TIMEOUT": "0.5"},
        {"STUB_OUTPUT": "no json here"},
        {"STUB_OUTPUT": '{"findings": [{"path": "a.py"}]}'},
        {"STUB_OUTPUT": verdict({**FINDING, "line": "3"})},
        {"STUB_OUTPUT": json.dumps({"findings": "none"})},
        {"STUB_OUTPUT": json.dumps({"is_error": True, "result": "boom"})},
    ],
    ids=[
        "missing",
        "non-zero",
        "timeout",
        "garbage",
        "incomplete-finding",
        "string-line",
        "findings-not-list",
        "envelope-error",
    ],
)
def test_engine_failure_exits_2(gate: Gate, extra: dict[str, str]) -> None:
    stage_change(gate)

    run = gate.check("--staged", **extra)

    assert run.code == EXIT_ERROR, run
    assert run.err.strip()
    assert not list(gate.cache.glob("*.json"))


def test_engine_failure_is_not_cached(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_EXIT="3")

    run = gate.check("--staged")

    assert run.code == EXIT_PASS
    assert gate.calls == 2


def test_unparseable_output_is_retried(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check(
        "--staged",
        STUB_OUTPUT_FIRST="no verdict here",
        STUB_OUTPUT=verdict(FINDING),
    )

    assert run.code == EXIT_FINDINGS, run
    assert gate.calls == 2


def test_unparseable_output_gives_up_after_max_attempts(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT="still no verdict")

    assert run.code == EXIT_ERROR, run
    assert "3 attempts" in run.err
    assert gate.calls == 3


def test_attempts_are_overridable(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check(
        "--staged", STUB_OUTPUT="garbage", AI_REVIEW_ATTEMPTS="1"
    )

    assert run.code == EXIT_ERROR
    assert gate.calls == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"STUB_EXIT": "3"},
        {"STUB_SLEEP": "5", "AI_REVIEW_TIMEOUT": "0.5"},
    ],
    ids=["non-zero", "timeout"],
)
def test_engine_failure_is_not_retried(
    gate: Gate, extra: dict[str, str]
) -> None:
    stage_change(gate)

    run = gate.check("--staged", **extra)

    assert run.code == EXIT_ERROR
    assert gate.calls == 1


def test_fenced_json_is_parsed(gate: Gate) -> None:
    stage_change(gate)
    text = (
        "Here is the review {not json}:\n```json\n"
        + verdict(FINDING)
        + "\n```\nDone."
    )

    run = gate.check("--staged", STUB_OUTPUT=envelope(text))

    assert run.code == EXIT_FINDINGS, run
    assert f"(id {finding_id(FINDING)})" in run.out


def test_bare_verdict_and_envelope_both_accepted(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=envelope(verdict()))

    assert run.code == EXIT_PASS, run


def test_unicode_finding_text(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict(UNICODE_FINDING))

    assert run.code == EXIT_FINDINGS
    assert UNICODE_FINDING["text"] in run.out
    assert f"(id {finding_id(UNICODE_FINDING)})" in run.out


def test_json_output(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", "--json", STUB_OUTPUT=verdict(FINDING))

    assert run.code == EXIT_FINDINGS
    document = json.loads(run.out)
    assert document["findings"][0]["id"] == finding_id(FINDING)
    assert document["findings"][0]["path"] == "a.py"


def test_repo_without_head_diffs_against_empty_tree(tmp_path: Path) -> None:
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "new.py", "NEW = 1\n")
    git(repo, "add", "new.py")
    engine = tmp_path / "engine.py"
    engine.write_text(ENGINE_SOURCE, encoding="utf-8")
    gate = Gate(repo, tmp_path / "cache", tmp_path / "state", engine)

    run = gate.check("--staged")

    assert run.code == EXIT_PASS, run
    assert "+NEW = 1" in gate.prompt


def test_not_a_repo_exits_2(gate: Gate, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    run = gate.run("check", "--repo", str(plain), "--staged")

    assert run.code == EXIT_ERROR


def scope_repo(gate: Gate) -> None:
    for name in ("b.py", "d.py"):
        write(gate.repo, name, BASE_SOURCE)
    git(gate.repo, "add", "b.py")
    git(gate.repo, "commit", "-q", "-m", "b")
    write(gate.repo, "a.py", BASE_SOURCE + "STAGED_A = 1\n")
    git(gate.repo, "add", "a.py", "d.py")
    write(gate.repo, "d.py", BASE_SOURCE + "DISK_D = 1\n")
    write(gate.repo, "b.py", BASE_SOURCE + "DISK_B = 1\n")
    write(gate.repo, "c.py", "UNTRACKED_C = 1\n")


def changed_files(prompt: str) -> set[str]:
    section = prompt.split("Changed files:\n", 1)[1].split("\n\n", 1)[0]
    return {line.strip("- ").strip() for line in section.splitlines()}


@pytest.mark.parametrize(
    ("args", "expected", "present", "absent"),
    [
        (("--staged",), {"a.py", "d.py"}, "STAGED_A", "DISK_D"),
        (("--tracked",), {"a.py", "b.py", "d.py"}, "DISK_D", "UNTRACKED_C"),
        ((), {"a.py", "b.py", "c.py", "d.py"}, "UNTRACKED_C", None),
        (
            ("--paths", "b.py", "c.py"),
            {"b.py", "c.py"},
            "UNTRACKED_C",
            "STAGED_A",
        ),
        (
            ("--tracked", "--paths", "b.py", "c.py"),
            {"b.py"},
            "DISK_B",
            "UNTRACKED_C",
        ),
        (
            ("--staged", "--paths", "a.py", "b.py"),
            {"a.py"},
            "STAGED_A",
            "DISK_B",
        ),
    ],
    ids=[
        "staged",
        "tracked",
        "worktree",
        "paths",
        "tracked-paths",
        "staged-paths",
    ],
)
def test_scope_flags_match_lint_strict(
    gate: Gate,
    args: tuple[str, ...],
    expected: set[str],
    present: str,
    absent: str | None,
) -> None:
    scope_repo(gate)

    run = gate.check(*args)

    assert run.code == EXIT_PASS, run
    assert changed_files(gate.prompt) == expected
    diff = gate.prompt.split("Changed files:\n", 1)[1]
    assert present in diff
    if absent is not None:
        assert f"\n+{absent}" not in diff


def test_paths_are_relative_to_repo_argument(gate: Gate) -> None:
    write(gate.repo, "pkg/e.py", "E = 1\n")
    write(gate.repo, "f.py", "F = 1\n")

    run = gate.run(
        "check", "--repo", str(gate.repo / "pkg"), "--paths", "e.py"
    )

    assert run.code == EXIT_PASS, run
    assert changed_files(gate.prompt) == {"pkg/e.py"}


def test_finding_id_is_stable(gate_module: ModuleType) -> None:
    finding = gate_module.Finding(
        path="a.py",
        line=3,
        category=gate_module.Category("architecture"),
        text=FINDING["text"],
    )
    moved = gate_module.Finding(
        path="a.py",
        line=40,
        category=gate_module.Category("architecture"),
        text=FINDING["text"],
    )

    assert finding.id == moved.id == finding_id(FINDING)
    assert len(finding.id) == ID_LENGTH


def test_extract_verdict_prefers_findings_object(
    gate_module: ModuleType,
) -> None:
    text = 'noise {"a": 1} then {"findings": []} trailing {'

    assert gate_module.extract_verdict_object(text) == {"findings": []}


def test_default_engine_command_is_read_only(
    gate_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REVIEW_ENGINE_CMD", raising=False)
    monkeypatch.setenv("AI_REVIEW_MODEL", "sonnet")
    monkeypatch.delenv("AI_REVIEW_EFFORT", raising=False)

    command = gate_module.engine_command()

    assert command == [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        "sonnet",
        "--effort",
        "high",
        "--allowedTools",
        "Read",
        "Grep",
        "Glob",
        "--disallowedTools",
        "Bash",
        "Edit",
        "Write",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "Agent",
    ]


def test_default_engine_model_is_sonnet(
    gate_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REVIEW_ENGINE_CMD", raising=False)
    monkeypatch.delenv("AI_REVIEW_MODEL", raising=False)

    command = gate_module.engine_command()

    assert command[command.index("--model") + 1] == "sonnet"


def test_verdict_text_reads_envelope_result(gate_module: ModuleType) -> None:
    assert gate_module.verdict_text(envelope("inner")) == "inner"
    assert gate_module.verdict_text("plain text") == "plain text"


def test_boolean_line_is_rejected(gate_module: ModuleType) -> None:
    with pytest.raises(gate_module.GateError):
        gate_module.finding_from({**FINDING, "line": True})


def test_unwritable_cache_still_reports_verdict(
    gate: Gate, tmp_path: Path
) -> None:
    blocker = tmp_path / "cache-is-a-file"
    blocker.write_text("x")
    stage_change(gate)

    clean = gate.check("--staged", AI_REVIEW_CACHE_DIR=str(blocker))
    found = gate.check(
        "--staged",
        AI_REVIEW_CACHE_DIR=str(blocker),
        STUB_OUTPUT=verdict(FINDING),
    )

    assert clean.code == EXIT_PASS, clean
    assert found.code == EXIT_FINDINGS, found


def test_corrupt_waivers_file_exits_2(gate: Gate) -> None:
    gate.cache.mkdir()
    (gate.cache / "waivers.json").write_text("[1, 2")
    stage_change(gate)

    run = gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    assert run.code == EXIT_ERROR
    assert "waivers" in run.err


def section(prompt: str, heading: str) -> str:
    body = prompt.split(heading, 1)[1]
    return body.split(NEXT_SECTION, 1)[0]


def round_files(gate: Gate) -> list[Path]:
    return sorted((gate.cache / "rounds").glob("*.json"))


def restage(gate: Gate, extra_line: str) -> None:
    source = (gate.repo / "a.py").read_text(encoding="utf-8")
    write(gate.repo, "a.py", source + extra_line)
    git(gate.repo, "add", "a.py")


def test_engine_command_effort_default_and_override(
    gate_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_REVIEW_ENGINE_CMD", raising=False)
    monkeypatch.delenv("AI_REVIEW_EFFORT", raising=False)

    default = gate_module.engine_command()
    monkeypatch.setenv("AI_REVIEW_EFFORT", "medium")
    override = gate_module.engine_command()

    assert default[default.index("--effort") + 1] == "high"
    assert override[override.index("--effort") + 1] == "medium"


def test_second_round_prompt_has_memory(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    gate.run(
        "waive",
        "--repo",
        str(gate.repo),
        "--finding",
        finding_id(FINDING),
        "--reason",
        WAIVER_REASON,
    )
    restage(gate, "\nTHIRD = 3\n")

    gate.check("--staged")

    earlier = section(gate.prompt, EARLIER_HEADING)
    assert str(FINDING["text"]) in earlier
    assert finding_id(FINDING) in earlier
    assert WAIVER_REASON in earlier


def test_first_round_prompt_has_no_memory(gate: Gate) -> None:
    stage_change(gate)

    gate.check("--staged")

    assert EARLIER_HEADING not in gate.prompt
    assert DELTA_HEADING not in gate.prompt


def test_second_round_prompt_has_delta_only(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged")
    restage(gate, "\nTHIRD = 3\n")

    gate.check("--staged")

    delta = section(gate.prompt, DELTA_HEADING)
    assert "+THIRD = 3" in delta
    assert "+OTHER = 2" not in delta
    assert "+OTHER = 2" in gate.prompt.split(DIFF_HEADING)[-1]


def test_unchanged_tree_delta_reports_no_changes(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    (state_file,) = round_files(gate)
    document = json.loads(state_file.read_text(encoding="utf-8"))
    document["complete"] = False
    state_file.write_text(json.dumps(document), encoding="utf-8")

    gate.check("--staged", **fresh_cache_key(gate))

    assert "no changes" in section(gate.prompt, DELTA_HEADING)


def test_delta_omitted_without_old_tree(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    (state_file,) = round_files(gate)
    document = json.loads(state_file.read_text(encoding="utf-8"))
    document["tree"] = MISSING_TREE
    state_file.write_text(json.dumps(document), encoding="utf-8")
    restage(gate, "\nTHIRD = 3\n")

    run = gate.check("--staged")

    assert run.code == EXIT_PASS, run
    assert EARLIER_HEADING in gate.prompt
    assert DELTA_HEADING not in gate.prompt


def test_detached_head_keeps_no_memory(gate: Gate) -> None:
    git(gate.repo, "switch", "-q", "--detach")
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    restage(gate, "\nTHIRD = 3\n")

    gate.check("--staged")

    assert not round_files(gate)
    assert EARLIER_HEADING not in gate.prompt
    assert DELTA_HEADING not in gate.prompt


def test_memory_is_per_branch(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    git(gate.repo, "switch", "-q", "-c", "other")
    restage(gate, "\nTHIRD = 3\n")

    gate.check("--staged")

    assert EARLIER_HEADING not in gate.prompt
    assert len(round_files(gate)) == 2


def test_engine_failure_keeps_no_memory(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_EXIT="3")

    assert run.code == EXIT_ERROR
    assert not round_files(gate)


def test_cached_verdict_still_writes_memory(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    (state_file,) = round_files(gate)
    state_file.unlink()

    gate.check("--staged", STUB_OUTPUT=verdict())

    assert gate.calls == 1
    assert len(round_files(gate)) == 1


def test_corrupt_memory_is_ignored_and_rewritten(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    (state_file,) = round_files(gate)
    state_file.write_text("{not json", encoding="utf-8")
    restage(gate, "\nTHIRD = 3\n")

    run = gate.check("--staged")

    assert run.code == EXIT_PASS, run
    assert EARLIER_HEADING not in gate.prompt
    assert json.loads(state_file.read_text(encoding="utf-8"))["rounds"]


def test_waivers_of_other_repos_are_not_sent(
    gate: Gate, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    gate.run(
        "waive",
        "--repo",
        str(other),
        "--finding",
        "abcdef0123",
        "--reason",
        WAIVER_REASON,
    )
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    restage(gate, "\nTHIRD = 3\n")

    gate.check("--staged")

    assert WAIVER_REASON not in gate.prompt
    assert "abcdef0123" not in gate.prompt


def test_state_path_hashes_root_and_branch(
    gate_module: ModuleType, gate: Gate, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_REVIEW_CACHE_DIR", str(gate.cache))
    root = gate.repo

    path = gate_module.memory_path(root, "main")

    digest = hashlib.sha256(f"{root}\0main".encode()).hexdigest()
    assert path == gate.cache / "rounds" / f"{digest}.json"
    assert path != gate_module.memory_path(root, "other")


def test_memory_is_capped(gate_module: ModuleType) -> None:
    def batch(index: int, size: int) -> tuple[object, ...]:
        return tuple(
            gate_module.Finding(
                "a.py",
                1,
                gate_module.Category.ARCHITECTURE,
                f"text {index} {n}",
            )
            for n in range(size)
        )

    memory = gate_module.Memory(None, ())
    for index in range(ROUND_CAP + 3):
        memory = memory.record(
            batch(index, 1), None, None, complete=False, reviewer="r"
        )
    assert len(memory.rounds) == ROUND_CAP
    assert memory.rounds[-1] == batch(ROUND_CAP + 2, 1)
    assert memory.rounds[0] == batch(3, 1)

    wide = gate_module.Memory(None, ()).record(
        batch(0, 100), None, None, complete=False, reviewer="r"
    )
    assert sum(map(len, wide.rounds)) == FINDING_CAP
    assert wide.rounds[-1] == batch(0, 100)[-FINDING_CAP:]


def test_report_shows_elapsed_or_cached(gate: Gate) -> None:
    stage_change(gate)

    args = ("--tracked", "--paths", "a.py")
    first = gate.check(*args, STUB_OUTPUT=verdict(FINDING))
    second = gate.check(*args, STUB_OUTPUT=verdict(FINDING))

    assert ELAPSED_LINE.search(first.out), first.out
    assert "(cached)" not in first.out
    assert CACHED_LINE.search(second.out), second.out
    (stored,) = (
        p for p in gate.cache.glob("*.json") if p.name != "waivers.json"
    )
    assert "elapsed_seconds" in json.loads(stored.read_text())


def test_pass_line_shows_elapsed(gate: Gate) -> None:
    stage_change(gate)

    run = gate.check("--staged")

    assert ELAPSED_LINE.search(run.out), run.out


def other_engine(gate: Gate) -> str:
    return shlex.join([sys.executable, str(gate.engine), "--other"])


def test_staged_after_tracked_uses_tracked_tree(gate: Gate) -> None:
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 2\n")
    write(gate.repo, "new.py", "NEW = 1\n")
    tracked = gate.check("--tracked")
    assert tracked.code == EXIT_PASS, tracked
    assert not git(gate.repo, "diff", "--cached", "--name-only").strip()
    git(gate.repo, "add", "-A")

    gate.check("--staged", **fresh_cache_key(gate))

    assert "no changes" in section(gate.prompt, DELTA_HEADING)


def test_staged_after_tracked_delta_holds_only_the_new_edit(
    gate: Gate,
) -> None:
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 2\n")
    gate.check("--tracked")
    restage(gate, "\nTHIRD = 3\n")

    gate.check("--staged")

    delta = section(gate.prompt, DELTA_HEADING)
    assert "+THIRD = 3" in delta
    assert "+OTHER = 2" not in delta


def test_paths_run_keeps_the_remembered_tree(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged")
    (state_file,) = round_files(gate)
    before = json.loads(state_file.read_text(encoding="utf-8"))["tree"]

    gate.check("--tracked", "--paths", "a.py")

    after = json.loads(state_file.read_text(encoding="utf-8"))["tree"]
    assert before
    assert after == before


UNCHANGED_LABEL = "(unchanged since the last review)"
FAILING_ENGINE = {"STUB_EXIT": "3"}


def fresh_cache_key(gate: Gate) -> dict[str, str]:
    habits = gate.engine.parent / "habits"
    habits.write_text("#!/bin/sh\necho H998 another rule\n", encoding="utf-8")
    habits.chmod(EXECUTABLE_MODE)
    return {"AI_REVIEW_HABITS_BIN": str(habits)}


def test_identical_clean_tree_skips_engine(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged")

    run = gate.check("--staged", **fresh_cache_key(gate), **FAILING_ENGINE)

    assert run.code == EXIT_PASS, run
    assert f"ai-review-gate: pass {UNCHANGED_LABEL}" in run.out
    assert gate.calls == 1


def test_moved_head_same_tree_reviews(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged")
    write(gate.repo, "a.py", BASE_SOURCE + "\nMOVED = 9\n")
    git(gate.repo, "add", "a.py")
    git(gate.repo, "commit", "-q", "-m", "move head")
    stage_change(gate)

    run = gate.check("--staged", **fresh_cache_key(gate))

    assert run.code == EXIT_PASS, run
    assert "unchanged" not in run.out
    assert gate.calls == 2


def test_last_round_findings_all_waived_counts_clean(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    gate.run(
        "waive",
        "--repo",
        str(gate.repo),
        "--finding",
        finding_id(FINDING),
        "--reason",
        WAIVER_REASON,
    )

    run = gate.check("--staged", **fresh_cache_key(gate), **FAILING_ENGINE)

    assert run.code == EXIT_PASS, run
    assert UNCHANGED_LABEL in run.out
    assert gate.calls == 1


def test_unchanged_state_with_unwaived_finding_reuses_verdict(
    gate: Gate,
) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    run = gate.check("--staged", **fresh_cache_key(gate), **FAILING_ENGINE)

    assert run.code == EXIT_FINDINGS, run
    assert finding_id(FINDING) in run.out
    assert UNCHANGED_LABEL in run.out
    assert gate.calls == 1


def test_unchanged_state_with_partial_waivers_blocks_only_unwaived(
    gate: Gate,
) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING, TEST_QUALITY_FINDING))
    gate.run(
        "waive",
        "--repo",
        str(gate.repo),
        "--finding",
        finding_id(FINDING),
        "--reason",
        WAIVER_REASON,
    )

    run = gate.check("--staged", **fresh_cache_key(gate), **FAILING_ENGINE)

    assert run.code == EXIT_FINDINGS, run
    assert finding_id(TEST_QUALITY_FINDING) in run.out
    assert f"waived: {finding_id(FINDING)}" in run.out
    assert "a.py:3 [architecture]" not in run.out
    assert UNCHANGED_LABEL in run.out
    assert gate.calls == 1


def test_changed_tree_after_denial_is_reviewed_again(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 3\n")
    git(gate.repo, "add", "a.py")

    gate.check("--staged", **fresh_cache_key(gate))

    assert gate.calls == 2


def test_memory_without_base_is_not_trusted(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    (state_file,) = round_files(gate)
    document = json.loads(state_file.read_text(encoding="utf-8"))
    document.pop("base", None)
    state_file.write_text(json.dumps(document), encoding="utf-8")

    gate.check("--staged", **fresh_cache_key(gate))

    assert gate.calls == 2
    assert EARLIER_HEADING in gate.prompt


def test_remembered_round_with_dropped_category_is_ignored(
    gate: Gate,
) -> None:
    stage_change(gate)
    gate.check("--staged")
    (state_file,) = round_files(gate)
    document = json.loads(state_file.read_text(encoding="utf-8"))
    document["rounds"] = [[NAMING_FINDING]]
    state_file.write_text(json.dumps(document), encoding="utf-8")

    run = gate.check("--staged", **fresh_cache_key(gate), **FAILING_ENGINE)

    assert run.code == EXIT_PASS, run
    assert "[naming]" not in run.out
    assert gate.calls == 1


def test_reviewer_change_invalidates_remembered_verdict(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    gate.check("--staged", AI_REVIEW_ENGINE_CMD=other_engine(gate))

    assert gate.calls == 2


def test_memory_without_fingerprint_is_not_trusted(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))
    (state_file,) = round_files(gate)
    document = json.loads(state_file.read_text(encoding="utf-8"))
    document.pop("reviewer", None)
    state_file.write_text(json.dumps(document), encoding="utf-8")

    gate.check("--staged", **fresh_cache_key(gate))

    assert gate.calls == 2
    assert EARLIER_HEADING not in gate.prompt


def test_reviewer_change_drops_foreign_history(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged", STUB_OUTPUT=verdict(FINDING))

    gate.check("--staged", AI_REVIEW_ENGINE_CMD=other_engine(gate))

    assert gate.calls == 2
    assert EARLIER_HEADING not in gate.prompt
    assert DELTA_HEADING not in gate.prompt


def test_paths_round_records_current_reviewer(gate: Gate) -> None:
    stage_change(gate)
    paths = ("--tracked", "--paths", "a.py")
    gate.check(*paths, STUB_OUTPUT=verdict(FINDING))

    gate.check(*paths, **fresh_cache_key(gate))

    assert EARLIER_HEADING in gate.prompt
    assert str(FINDING["text"]) in gate.prompt


def test_unchanged_state_after_capped_round_is_reviewed_again(
    gate: Gate,
) -> None:
    stage_change(gate)
    many = [
        {**FINDING, "text": f"Rename VALUE variant {n}."}
        for n in range(FINDING_CAP + 1)
    ]
    gate.check("--staged", STUB_OUTPUT=verdict(*many))

    gate.check("--staged", **fresh_cache_key(gate))

    assert gate.calls == 2


def test_tracked_run_does_not_reuse_untracked_file_finding(
    gate: Gate,
) -> None:
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 2\n")
    write(gate.repo, "new.py", "NEW = 1\n")
    gate.check(STUB_OUTPUT=verdict({**FINDING, "path": "new.py"}))

    run = gate.check("--tracked", **fresh_cache_key(gate))

    assert run.code == EXIT_PASS, run
    assert gate.calls == 2


def test_tracked_round_with_untracked_file_is_not_trusted(
    gate: Gate,
) -> None:
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 2\n")
    write(gate.repo, "new.py", "NEW = 1\n")
    gate.check("--tracked")
    git(gate.repo, "add", "-A")

    gate.check("--staged", **fresh_cache_key(gate))

    assert gate.calls == 2


def test_worktree_round_is_trusted_by_the_staged_run(gate: Gate) -> None:
    write(gate.repo, "a.py", BASE_SOURCE + "\nOTHER = 2\n")
    write(gate.repo, "new.py", "NEW = 1\n")
    gate.check()
    git(gate.repo, "add", "-A")

    run = gate.check("--staged", **fresh_cache_key(gate), **FAILING_ENGINE)

    assert run.code == EXIT_PASS, run
    assert UNCHANGED_LABEL in run.out
    assert gate.calls == 1


def test_paths_round_is_not_trusted(gate: Gate) -> None:
    stage_change(gate)
    gate.check("--staged")
    gate.check("--tracked", "--paths", "a.py")

    gate.check("--staged", **fresh_cache_key(gate))

    assert gate.calls == 2


def real_index_bytes(repo: Path) -> bytes:
    return (repo / ".git" / "index").read_bytes()


def fresh_index_tree(repo: Path, tmp_path: Path) -> str:
    env = {**git_env(), "GIT_INDEX_FILE": str(tmp_path / "fresh-index")}
    for args in (["read-tree", "HEAD"], ["add", "-A"]):
        subprocess.run(
            ["git", *args], cwd=repo, env=env, check=True, capture_output=True
        )
    done = subprocess.run(
        ["git", "write-tree"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def test_worktree_tree_matches_fresh_index_build(
    gate_module: ModuleType,
    gate: Gate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in git_env().items():
        monkeypatch.setenv(name, value)
    write(gate.repo, ".gitignore", "ignored.txt\n")
    write(gate.repo, "ignored.txt", "IGNORED = 1\n")
    write(gate.repo, "b.py", "B = 1\n")
    git(gate.repo, "add", "b.py")
    write(gate.repo, "a.py", BASE_SOURCE + "\nSTAGED = 1\n")
    git(gate.repo, "add", "a.py")
    write(gate.repo, "a.py", BASE_SOURCE + "\nSTAGED = 1\nUNSTAGED = 2\n")
    write(gate.repo, "new.py", "NEW = 1\n")
    before = real_index_bytes(gate.repo)

    seeded = gate_module.worktree_tree(gate.repo)

    assert seeded == fresh_index_tree(gate.repo, tmp_path)
    assert real_index_bytes(gate.repo) == before


def test_worktree_tree_seeds_from_the_real_index(
    gate_module: ModuleType,
    gate: Gate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in git_env().items():
        monkeypatch.setenv(name, value)
    calls: list[str] = []
    real_run_git: Callable[..., str] = gate_module.run_git

    def recording(root: Path, *args: str, **kwargs: object) -> str:
        calls.append(args[0])
        return real_run_git(root, *args, **kwargs)

    monkeypatch.setattr(gate_module, "run_git", recording)

    gate_module.worktree_tree(gate.repo)

    assert "read-tree" not in calls


def test_worktree_tree_without_real_index_reads_head(
    gate_module: ModuleType,
    gate: Gate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in git_env().items():
        monkeypatch.setenv(name, value)
    (gate.repo / ".git" / "index").unlink()
    write(gate.repo, "new.py", "NEW = 1\n")

    tree = gate_module.worktree_tree(gate.repo)

    assert tree == fresh_index_tree(gate.repo, tmp_path)


def test_new_docstrings_are_one_short_sentence(
    gate_module: ModuleType,
) -> None:
    for name in (
        "review",
        "fresh_verdict",
        "remembered_findings",
        "covers_whole_state",
        "worktree_tree",
        "base_tree",
    ):
        doc = getattr(gate_module, name).__doc__
        assert doc
        assert "\n" not in doc.strip()
        assert len(doc) <= 72


def test_nonzero_exit_error_carries_reviewer_result(gate: Gate) -> None:
    stage_change(gate)
    output = json.dumps(
        {"is_error": True, "result": "Failed to authenticate: X"}
    )

    run = gate.check("--staged", STUB_EXIT="1", STUB_OUTPUT=output)

    assert run.code == EXIT_ERROR, run
    assert "reviewer exit 1" in run.err
    assert "Failed to authenticate: X" in run.err


def test_nonzero_exit_error_keeps_stderr_without_envelope(
    gate: Gate,
) -> None:
    stage_change(gate)

    run = gate.check("--staged", STUB_EXIT="3", STUB_OUTPUT="plain text")

    assert run.code == EXIT_ERROR, run
    assert "reviewer exit 3" in run.err
