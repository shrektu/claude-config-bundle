#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})
SUPPORTED_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hpp",
    }
)
OFF_VALUES = frozenset({"off", "0", "false", "no"})
DEFAULT_LINT_STRICT = "~/.claude/bin/lint-strict"
DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_LOG_DIR = "~/.cache/claude-autofix"
ERROR_LOG_NAME = "errors.log"
GIT_TIMEOUT_SECONDS = 5.0
MAX_LISTED_VIOLATIONS = 15
OK_EXIT_CODES = (0, 1)
VIOLATIONS_HEADER = "lint-strict on changed lines:"


@dataclass(frozen=True, slots=True)
class Violation:
    """One lint-strict violation."""

    path: str
    line: int
    rule: str
    message: str


@dataclass(frozen=True, slots=True)
class LintReport:
    """The parsed lint-strict JSON report."""

    violations: tuple[Violation, ...]
    fixed_lines: int


class AutofixError(Exception):
    """A failure that is logged and never surfaced."""


def parse_report(raw: str) -> LintReport:
    """Parse lint-strict JSON output into a typed report."""
    try:
        data = json.loads(raw)
        violations = tuple(
            Violation(
                path=str(item["path"]),
                line=int(item["line"]),
                rule=str(item["rule"]),
                message=str(item["message"]),
            )
            for item in data["violations"]
        )
        return LintReport(violations, int(data["fixed_lines"]))
    except (ValueError, KeyError, TypeError) as error:
        message = f"unparseable lint-strict output: {error}"
        raise AutofixError(message) from error


def render_context(report: LintReport, relative: str) -> str:
    """Build the additionalContext text for the model."""
    lines: list[str] = []
    if report.fixed_lines > 0:
        lines.append(
            f"autofix: {report.fixed_lines} changed lines fixed in "
            f"{relative}; re-read the file before the next edit."
        )
    if report.violations:
        lines.append(VIOLATIONS_HEADER)
        listed = report.violations[:MAX_LISTED_VIOLATIONS]
        lines.extend(
            f"{item.path}:{item.line} {item.rule} {item.message}"
            for item in listed
        )
        hidden = len(report.violations) - len(listed)
        if hidden > 0:
            lines.append(f"...and {hidden} more")
    return "\n".join(lines)


def repo_root(file_path: Path) -> Path | None:
    """Return the git work tree root of the file, if any."""
    done = subprocess.run(
        ["git", "-C", str(file_path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return Path(done.stdout.strip())


def run_lint_strict(root: Path, relative: str) -> LintReport:
    """Run lint-strict with --fix on one file and parse its report."""
    executable = Path(
        os.environ.get("AUTOFIX_LINT_STRICT", DEFAULT_LINT_STRICT)
    ).expanduser()
    timeout = float(os.environ.get("AUTOFIX_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    command = [
        str(executable),
        "--repo",
        str(root),
        "--fix",
        "--quick",
        "--paths",
        relative,
        "--json",
    ]
    done = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode not in OK_EXIT_CODES:
        message = f"lint-strict exit code {done.returncode}"
        raise AutofixError(message)
    return parse_report(done.stdout)


def log_error(file_path: str, reason: str) -> None:
    """Append one failure line to the error log, ignoring log errors."""
    directory = Path(
        os.environ.get("AUTOFIX_LOG_DIR", DEFAULT_LOG_DIR)
    ).expanduser()
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{stamp} {file_path} {' '.join(reason.split())}\n"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ERROR_LOG_NAME).open("a") as handle:
            handle.write(line)
    except OSError:
        return


def target_path(payload: object) -> Path | None:
    """Return the edited file path when the payload is in scope."""
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str) or tool_name not in EDIT_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if path.suffix not in SUPPORTED_SUFFIXES or not path.is_file():
        return None
    return path


def process(path: Path) -> None:
    """Autofix one edited file and print the model-facing report."""
    root = repo_root(path)
    if root is None or ".git" in path.resolve().parts:
        return
    relative = os.path.relpath(path.resolve(), root.resolve())
    report = run_lint_strict(root, relative)
    if report.fixed_lines <= 0 and not report.violations:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": render_context(report, relative),
                }
            }
        )
    )


def main() -> None:
    """Run the hook and never fail."""
    if os.environ.get("CLAUDE_AUTOFIX", "").lower() in OFF_VALUES:
        return
    path: Path | None = None
    try:
        path = target_path(json.load(sys.stdin))
        if path is not None:
            process(path)
    except subprocess.TimeoutExpired:
        log_error(str(path), "lint-strict timed out")
    except (AutofixError, OSError, ValueError) as error:
        log_error(str(path), str(error))


if __name__ == "__main__":
    main()
