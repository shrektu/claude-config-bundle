#!/usr/bin/env python3
"""PreToolUse(Edit|Write|MultiEdit) hook: an edit may not add a ruff or eslint violation to a code file."""
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True
from edit_texts import Tool, change_of  # noqa: E402

LINT_TIMEOUT_S = 8
MAX_REPORTED = 5
GIT_MARKER = ".git"
RUFF_CONFIG_ENV = "LINT_GUARD_RUFF_CONFIG"
GLOBAL_RUFF_CONFIG = "~/.claude/lint/ruff.toml"
PYTHON_SUFFIXES = frozenset({"py", "pyi"})
SCRIPT_SUFFIXES = frozenset({"ts", "tsx", "js", "jsx", "mjs", "cjs"})
LINTED_TOOLS = frozenset({Tool.EDIT.value, Tool.WRITE.value, Tool.MULTI_EDIT.value})
RUFF_CONFIG_FILES = ("ruff.toml", ".ruff.toml")
PYPROJECT = "pyproject.toml"
PYPROJECT_RUFF_TABLE = "[tool.ruff"
ESLINT_CONFIG_FILES = frozenset({
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts", "eslint.config.mts",
    "eslint.config.cts", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yaml",
    ".eslintrc.yml",
})
PACKAGE_JSON = "package.json"
PACKAGE_ESLINT_KEY = '"eslintConfig"'
ESLINT_BIN = Path("node_modules") / ".bin" / "eslint"
REASON_HEAD = "lint-guard: this edit adds lint violations:"
REASON_MORE = "… and {count} more."
RUFF_FIX_HINT = "fix them, or run `ruff check --fix {path}` and re-read the file"
ESLINT_FIX_HINT = "fix them, or run `eslint --fix {path}` and re-read the file"


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    message: str
    line: int

    @property
    def key(self):
        return self.code, self.message


@dataclass(frozen=True, slots=True)
class Linter:
    argv: list[str]
    cwd: str | None
    parse: Callable[[object], list[Violation]]
    fix_hint: str


def parse_ruff(data):
    return [
        Violation(item["code"], item["message"], item["location"]["row"]) for item in data if item.get("code")
    ]


def parse_eslint(data):
    return [Violation(message["ruleId"], message["message"], message.get("line", 0))
            for result in data for message in result["messages"] if message.get("ruleId")]


def project_dirs(path):
    parent = Path(path).parent
    for directory in (parent, *parent.parents):
        yield directory
        if (directory / GIT_MARKER).exists():
            return


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def has_ruff_config(directory):
    if any((directory / name).is_file() for name in RUFF_CONFIG_FILES):
        return True
    return PYPROJECT_RUFF_TABLE in read_text(directory / PYPROJECT)


def has_eslint_config(directory):
    if any((directory / name).is_file() for name in ESLINT_CONFIG_FILES):
        return True
    return PACKAGE_ESLINT_KEY in read_text(directory / PACKAGE_JSON)


def plan_ruff(path):
    binary = shutil.which("ruff")
    if binary is None:
        return None
    argv = [binary, "check", "--output-format", "json", "--stdin-filename", path]
    if not any(has_ruff_config(directory) for directory in project_dirs(path)):
        argv += ["--config", os.environ.get(RUFF_CONFIG_ENV) or str(Path(GLOBAL_RUFF_CONFIG).expanduser())]
    return Linter([*argv, "-"], None, parse_ruff, RUFF_FIX_HINT.format(path=path))


def plan_eslint(path):
    directories = list(project_dirs(path))
    if not any(has_eslint_config(directory) for directory in directories):
        return None
    root = next((directory for directory in directories if (directory / ESLINT_BIN).is_file()), None)
    if root is None:
        return None
    argv = [str(root / ESLINT_BIN), "--format", "json", "--stdin", "--stdin-filename", path]
    return Linter(argv, str(root), parse_eslint, ESLINT_FIX_HINT.format(path=path))


def linter_for(suffix, path):
    if suffix in PYTHON_SUFFIXES:
        return plan_ruff(path)
    if suffix in SCRIPT_SUFFIXES:
        return plan_eslint(path)
    return None


def execute(linter, text, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        done = subprocess.run(linter.argv, input=text, capture_output=True, text=True, timeout=remaining,
                              cwd=linter.cwd, check=False)
        return linter.parse(json.loads(done.stdout))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def added(before, after):
    budget = Counter(violation.key for violation in before)
    fresh = []
    for violation in after:
        if budget[violation.key] > 0:
            budget[violation.key] -= 1
        else:
            fresh.append(violation)
    return fresh


def deny(violations, linter):
    shown = violations[:MAX_REPORTED]
    lines = [f"L{violation.line} {violation.code} {violation.message}" for violation in shown]
    if len(violations) > MAX_REPORTED:
        lines.append(REASON_MORE.format(count=len(violations) - MAX_REPORTED))
    reason = "\n".join([REASON_HEAD, *lines, linter.fix_hint])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def lint_delta(linter, change):
    deadline = time.monotonic() + LINT_TIMEOUT_S
    before = execute(linter, change.before, deadline) if change.before.strip() else []
    after = execute(linter, change.after, deadline)
    if before is None or after is None:
        return []
    return added(before, after)


def hook():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("tool_name") not in LINTED_TOOLS:
            return
        data = payload.get("tool_input")
        change = change_of(payload["tool_name"], data) if isinstance(data, dict) else None
        linter = linter_for(change.suffix, data["file_path"]) if change else None
        violations = lint_delta(linter, change) if linter else []
        if violations:
            deny(violations, linter)
    except Exception:
        return


if __name__ == "__main__":
    hook()
