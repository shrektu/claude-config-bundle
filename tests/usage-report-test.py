#!/usr/bin/env python3
"""Unit tests for the test-run classification of claude/bin/usage-report."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
USAGE_REPORT = Path(__file__).resolve().parent.parent / "claude" / "bin" / "usage-report"
HEREDOC_WRITE = "cat > e2e/login.spec.ts <<'EOF'\nimport { test } from 'playwright';\npytest\nnpm test\nEOF"
HEREDOC_THEN_RUN = "cat <<EOF\npytest\nEOF\nnpm test"
CASES = {
    "playwright heredoc write is not a run": (HEREDOC_WRITE, (0, 0)),
    "heredoc text then a real run": (HEREDOC_THEN_RUN, (0, 1)),
    "raw pytest": ("pytest -q", (0, 1)),
    "raw npm test": ("npm test", (0, 1)),
    "raw python -m pytest": ("python3 -m pytest tests", (0, 1)),
    "raw after cd": ("cd /srv/app && uv run pytest", (0, 1)),
    "raw ruff by path": ("/usr/bin/ruff check .", (0, 1)),
    "via verify": ("~/.claude/bin/verify -- pytest -q", (1, 0)),
    "via verify with a quoted chain": ("~/.claude/bin/verify -- 'cd /srv/app && npm test'", (1, 0)),
    "verify only in an echo": ("echo verify && pytest", (0, 1)),
    "verify as an argument": ("grep verify notes.txt && pytest", (0, 1)),
    "grep for a runner name": ("grep -rn pytest docs", (0, 0)),
    "echo of a runner name": ("echo run pytest later", (0, 0)),
    "no test command": ("ls -la", (0, 0)),
    "hyphenated quoted heredoc delimiter": ("cat > f.txt <<'PY-END'\npytest\nPY-END\nnpm test", (0, 1)),
    "dash heredoc with a hyphenated delimiter": ("cat > f.txt <<-END-X\n\tpytest\n\tEND-X\nnpm test", (0, 1)),
    "bash -c raw": ("bash -c 'pytest -q'", (0, 1)),
    "sh -c raw": ('sh -c "npm test"', (0, 1)),
    "bash -c verify": ("bash -c '~/.claude/bin/verify -- pytest'", (1, 0)),
    "bash -lc raw": ("bash -lc 'cd /srv && pytest'", (0, 1)),
    "bash -c without a runner": ("bash -c 'ls -la'", (0, 0)),
    "env and timeout wrappers": ("FOO=1 timeout 600 pytest", (0, 1)),
    "subshell run": ("(cd x && pytest)", (0, 1)),
    "if condition run": ("if pytest; then echo ok; fi", (0, 1)),
    "npx runner": ("npx vitest run", (0, 1)),
    "runner in a comment": ("echo a # pytest", (0, 0)),
    "unbalanced quote": ('echo "pytest', (0, 0)),
    "verify without a runner": ("~/.claude/bin/verify -- ls", (0, 0)),
    "two runs in one call": (
        "pytest; ~/.claude/bin/verify -- npm test",
        (1, 1),
    ),
    "verify in a pipeline after grep": ("grep -q x f | pytest", (0, 1)),
    "verify option value named like a runner": (
        "~/.claude/bin/verify --repo /src/pytest-plugin -- ls",
        (0, 0),
    ),
    "here-string is not a heredoc": ("cat <<< pytest", (0, 0)),
    "shell nesting beyond the depth limit": (
        'bash -c "bash -c \'bash -c \\"bash -c pytest\\"\'"',
        (0, 0),
    ),
}
VERIFY = "~/.claude/bin/verify"
BUG_CASES = {
    "apostrophe in a trailing comment": ("pytest -q  # it's fine", (0, 1)),
    "hash-led double-quoted word is not a comment": (
        'git commit -m "#12 fix"; pytest',
        (0, 1),
    ),
    "hash-led single-quoted word is not a comment": (
        "echo '# header' > f && pytest",
        (0, 1),
    ),
    "backslash continuation before the separator": (
        f"{VERIFY} --repo /r \\\n  -- uv run pytest",
        (1, 0),
    ),
    "backslash continuation after the separator": (
        f"{VERIFY} --repo /r -- \\\n  uv run pytest",
        (1, 0),
    ),
    "arithmetic shift is not a heredoc": ("echo $((1<<3))\npytest", (0, 1)),
    "quoted shift is not a heredoc": ("echo 'a<<b'\npytest\nb", (0, 1)),
    "unterminated heredoc keeps its lines": ("cat <<EOF\npytest", (0, 1)),
    "escaped heredoc delimiter": ("cat <<\\EOF\nit's\nEOF\npytest", (0, 1)),
    "nice with a value option": ("nice -n 10 pytest", (0, 1)),
    "sudo with a value option": ("sudo -u x pytest", (0, 1)),
    "timeout with a signal option": ("timeout -s KILL 60 pytest", (0, 1)),
    "command -v is a lookup": ("command -v pytest", (0, 0)),
    "command -V is a lookup": ("command -V pytest", (0, 0)),
    "brace group": ("{ pytest; } 2>&1", (0, 1)),
    "verify without a separator and a runner-like option value": (
        f"{VERIFY} --repo /src/ruff-x ls",
        (0, 0),
    ),
    "verify long name option value": (
        f"{VERIFY} --name ruff-fix -- ls",
        (0, 0),
    ),
    "verify long tail option value": (
        f"{VERIFY} --tail 5 --name pytest-a -- ls",
        (0, 0),
    ),
    "sudo with a long value option": ("sudo --user x pytest", (0, 1)),
    "env with a long value option": ("env --unset X pytest", (0, 1)),
    "timeout with a long value option": (
        "timeout --kill-after 5 60 pytest",
        (0, 1),
    ),
    "nice with a long value option": ("nice --adjustment 5 pytest", (0, 1)),
    "verify without a separator wrapping a runner": (
        f"{VERIFY} -t 50 --repo /r pytest -q",
        (1, 0),
    ),
}
CASES |= BUG_CASES
CLI_BUG_COMMANDS = tuple(command for command, _ in BUG_CASES.values())
CLI_TIMEOUT_SECONDS = 60
CLI_COMMANDS = (
    "echo verify && pytest",
    "grep -rn pytest docs",
    "~/.claude/bin/verify -- pytest -q",
)


def load_module():
    loader = importlib.machinery.SourceFileLoader("usage_report", str(USAGE_REPORT))
    spec = importlib.util.spec_from_loader("usage_report", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcript_line(command: str) -> str:
    return json.dumps({"type": "assistant", "message": {"id": "msg", "content": [
        {"type": "tool_use", "id": "tool", "name": "Bash", "input": {"command": command}}]}})


class ClassificationTest(unittest.TestCase):
    def count(self, command):
        module = load_module()
        stats = module.Stats()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text(transcript_line(command) + "\n")
            module.scan(str(path), stats)
        return stats.tests_verify, stats.tests_raw

    def test_each_command_is_classified(self):
        for label, (command, expected) in CASES.items():
            with self.subTest(label):
                self.assertEqual(self.count(command), expected, command)


def report_stdout(commands: tuple[str, ...]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        session = Path(tmp) / ".claude" / "projects" / "p" / "s.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text(
            "".join(transcript_line(c) + "\n" for c in commands)
        )
        result = subprocess.run(
            [sys.executable, str(USAGE_REPORT)],
            env={**os.environ, "HOME": tmp},
            capture_output=True,
            text=True,
            check=True,
            timeout=CLI_TIMEOUT_SECONDS,
        )
    return result.stdout


class ReportCliTest(unittest.TestCase):
    def test_report_prints_run_counts(self) -> None:
        stdout = report_stdout(CLI_COMMANDS)
        assert "test/lint/build runs: via verify 1, raw 1" in stdout

    def test_report_counts_the_review_bug_commands(self) -> None:
        stdout = report_stdout(CLI_BUG_COMMANDS)
        assert "test/lint/build runs: via verify 3, raw 15 (83% raw)" in stdout


if __name__ == "__main__":
    unittest.main()
