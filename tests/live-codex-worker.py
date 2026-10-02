#!/usr/bin/env python3
"""Live integration test: starts the INSTALLED codex-worker over MCP stdio and runs one real plan review
(gpt-6-sol) and one real code review (gpt-6-sol) on a throwaway repo with planted defects.
Spends Codex tokens. Run with ~/.claude/mcp/codex-worker/.venv/bin/python."""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

WORKER_DIR = Path.home() / ".claude" / "mcp" / "codex-worker"
WORKER_PYTHON = WORKER_DIR / ".venv" / "bin" / "python"
WORKER_SCRIPT = WORKER_DIR / "codex_worker.py"
TOOL_NAME = "codex_review_changes"
EXPECTED_PARAMS = {"mode", "plan_file", "project_path", "base", "recheck"}
FORBIDDEN_PARAMS = {"model", "reasoning_effort", "service_tier"}
CALL_TIMEOUT = timedelta(minutes=30)
HEADER_RE = re.compile(r"^codex (?P<mode>plan|code) (?P<model>\S+)/(?P<effort>\S+) tokens in=(?P<tin>\d+) cached=(?P<tcached>\d+) out=(?P<tout>\d+)$")
PLAN_LINE_RE = re.compile(r"^[^:\n]{1,80}: \S")
CODE_LINE_RE = re.compile(r"^(?P<path>[^:\s]+):(?P<line>\d+)(?:-\d+)?: \S")
PASS = "PASS"
SUGGESTION_WORDS = ("should ", "consider ", "instead ", "suggest", "recommend")

WINDOW_SOURCE = '''def last_n(items: list[int], n: int) -> list[int]:
    if n <= 0:
        return []
    return items[-n:]
'''
WINDOW_BUGGY = '''def last_n(items: list[int], n: int) -> list[int]:
    if n <= 0:
        return []
    return items[len(items) - n + 1:]
'''
TEST_SOURCE = '''from src.window import last_n


def test_last_two() -> None:
    assert last_n([1, 2, 3], 2) == [2, 3]
'''
PLAN_TEXT = '''# Plan: window helpers

## task
Add `first_n` next to the existing `middle_n` helper in src/window.py.

## architecture
src/window.py already defines `middle_n(items, n)`; reuse it inside `first_n`.

## test_plan
- unit — test_first_two — first_n([1,2,3], 2) == [1,2] — first_n does not exist

## acceptance_criteria
- first_n returns the first n items
- last_n keeps returning the last n items

## commands
Unit: ~/.claude/bin/verify -- 'python3 -m pytest -q'

## repos
You may only touch this repo; you may not touch anything else.
'''


@dataclass(frozen=True)
class Outcome:
    header: re.Match
    body: list[str]


failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)
        print(f"FAIL {message}")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "window.py").write_text(WINDOW_SOURCE)
    (repo / "tests" / "test_window.py").write_text(TEST_SOURCE)
    git(repo, "init", "-q")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    return repo


def parse(text: str) -> Outcome | None:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    header = HEADER_RE.match(lines[0]) if lines else None
    check(header is not None, f"no token header in {text[:200]!r}")
    return Outcome(header, lines[1:]) if header else None


async def review(session: ClientSession, arguments: dict[str, str]) -> Outcome | None:
    result = await session.call_tool(TOOL_NAME, arguments, read_timeout_seconds=CALL_TIMEOUT)
    text = "".join(part.text for part in result.content if hasattr(part, "text"))
    print(f"--- {arguments['mode']} review\n{text}\n")
    return parse(text)


def check_terse(outcome: Outcome, line_re: re.Pattern) -> None:
    check(outcome.body != [PASS], "the planted defects were not reported")
    for line in outcome.body:
        check(bool(line_re.match(line)), f"line not in the required format: {line!r}")
        check(len(line.split()) <= 40, f"line longer than the word budget: {line!r}")
        check(not any(word in line.lower() for word in SUGGESTION_WORDS), f"line proposes a fix: {line!r}")


async def main() -> int:
    codex_bin = shutil.which("codex") or os.environ.get("CODEX_BIN", "")
    params = StdioServerParameters(command=str(WORKER_PYTHON), args=[str(WORKER_SCRIPT)],
                                   env={**os.environ, "CODEX_BIN": codex_bin})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = make_repo(root)
        plan = root / "plan.md"
        plan.write_text(PLAN_TEXT)
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            check(TOOL_NAME in tools, f"{TOOL_NAME} not exposed")
            props = set(tools[TOOL_NAME].inputSchema.get("properties", {})) if TOOL_NAME in tools else set()
            check(props == EXPECTED_PARAMS, f"tool parameters are {sorted(props)}")
            check(not props & FORBIDDEN_PARAMS, f"model/effort are overridable: {sorted(props & FORBIDDEN_PARAMS)}")

            planned = await review(session, {"mode": "plan", "plan_file": str(plan), "project_path": str(repo)})
            if planned:
                check((planned.header["model"], planned.header["effort"]) == ("gpt-6-sol", "high"),
                      f"plan review ran on {planned.header['model']}/{planned.header['effort']}")
                check_terse(planned, PLAN_LINE_RE)
                check(any("middle_n" in line for line in planned.body), "the false middle_n claim was not flagged")

            (repo / "src" / "window.py").write_text(WINDOW_BUGGY)
            (repo / "src" / "extra.py").write_text("LIMIT = 3\n")
            coded = await review(session, {"mode": "code", "plan_file": str(plan), "project_path": str(repo),
                                           "base": "HEAD"})
            if coded:
                check((coded.header["model"], coded.header["effort"]) == ("gpt-6-sol", "high"),
                      f"code review ran on {coded.header['model']}/{coded.header['effort']}")
                check_terse(coded, CODE_LINE_RE)
                paths = {m["path"] for line in coded.body if (m := CODE_LINE_RE.match(line))}
                check(any(p.endswith("window.py") for p in paths), f"the off-by-one was not flagged: {paths}")
    print("LIVE CODEX WORKER: " + ("PASS" if not failures else f"{len(failures)} FAILED"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
