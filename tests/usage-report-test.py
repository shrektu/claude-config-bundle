#!/usr/bin/env python3
"""Unit tests for the test-run classification of claude/bin/usage-report."""
import importlib.machinery
import importlib.util
import json
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
}


def load_module():
    loader = importlib.machinery.SourceFileLoader("usage_report", str(USAGE_REPORT))
    spec = importlib.util.spec_from_loader("usage_report", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcript_line(command):
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


if __name__ == "__main__":
    unittest.main()
