import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import codex_worker
import pytest

TRACKED_FILE = "tracked.txt"
UNTRACKED_FILE = "untracked.txt"
ORIGINAL_LINE = "original line\n"
MODIFIED_LINE = "modified tracked line"
UNTRACKED_CONTENT = "brand new untracked content"
MARKER_FILE = "codex_ran.marker"
FAKE_CODEX_FILE = "fake_codex.py"
EXECUTABLE_MODE = 0o755
REVIEW_FOCUS = "bugs"
WHAT_CHANGED_TEXT = "hand written description of the change"
UNKNOWN_REF = "no-such-ref"
HEAD_REF = "HEAD"
OPTION_LIKE_BASE = f"--output={TRACKED_FILE}"
NON_UTF8_FILE = "latin1.txt"
NON_UTF8_BYTES = bytes([0xE6, 0xB3, 0xFF])
REPLACEMENT_CHARACTER = "\ufffd"
GIT_IDENTITY = [
    "-c",
    "user.email=t@t",
    "-c",
    "user.name=t",
    "-c",
    "commit.gpgsign=false",
]
FAKE_EXIT_ENV = "FAKE_CODEX_EXIT"
FAKE_SLEEP_ENV = "FAKE_CODEX_SLEEP"
NONZERO_EXIT_CODE = 3
SLEEP_SECONDS = 5
SHORT_TIMEOUT_SECONDS = 1
GIT_TIMEOUT_SECONDS = 30
MISSING_CODEX_BIN = "no-such-dir/codex"

FAKE_CODEX_SOURCE = f"""#!{sys.executable}
import os
import pathlib
import sys
import time

arguments = sys.argv
time.sleep(float(os.environ.get({FAKE_SLEEP_ENV!r}, "0")))
output_path = arguments[arguments.index("-o") + 1]
pathlib.Path(output_path).write_text(sys.stdin.read())
pathlib.Path({{marker!r}}).touch()
sys.exit(int(os.environ.get({FAKE_EXIT_ENV!r}, "0")))
"""


@dataclass(slots=True)
class FakeCodex:
    marker: Path

    def ran(self) -> bool:
        return self.marker.exists()


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


@pytest.fixture
def fake_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCodex:
    marker = tmp_path / MARKER_FILE
    script = tmp_path / FAKE_CODEX_FILE
    script.write_text(FAKE_CODEX_SOURCE.format(marker=str(marker)))
    script.chmod(EXECUTABLE_MODE)
    monkeypatch.setenv("CODEX_BIN", str(script))
    return FakeCodex(marker=marker)


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / TRACKED_FILE).write_text(ORIGINAL_LINE)
    git(repo, "add", TRACKED_FILE)
    git(repo, *GIT_IDENTITY, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def dirty_repo(clean_repo: Path) -> Path:
    (clean_repo / TRACKED_FILE).write_text(MODIFIED_LINE + "\n")
    (clean_repo / UNTRACKED_FILE).write_text(UNTRACKED_CONTENT + "\n")
    return clean_repo


def review(repo: Path, **kwargs: str) -> str:
    result: str = codex_worker.codex_review_changes(
        review_focus=REVIEW_FOCUS,
        mode=codex_worker.MODE_CODE,
        project_path=str(repo),
        **kwargs,
    )
    return result


def test_server_registers_only_review_tool() -> None:
    tools = asyncio.run(codex_worker.mcp.list_tools())

    assert [tool.name for tool in tools] == ["codex_review_changes"]


def test_review_sends_diff_from_base_including_untracked_file(
    dirty_repo: Path, fake_codex: FakeCodex
) -> None:
    result = review(dirty_repo, diff_base=HEAD_REF)

    assert fake_codex.ran()
    assert MODIFIED_LINE in result
    assert UNTRACKED_CONTENT in result


@pytest.mark.usefixtures("fake_codex")
def test_codex_code_mode_defaults_to_medium(dirty_repo: Path) -> None:
    code_result = review(dirty_repo, diff_base=HEAD_REF)
    plan_result = codex_worker.codex_review_changes(
        review_focus=REVIEW_FOCUS,
        mode=codex_worker.MODE_PLAN,
        what_changed=WHAT_CHANGED_TEXT,
        project_path=str(dirty_repo),
    )

    assert (
        "mode=code, model=gpt-6.1-sol, reasoning_effort=medium," in code_result
    )
    assert (
        "mode=plan, model=gpt-6.1-sol, reasoning_effort=high," in plan_result
    )


def test_review_with_unknown_base_returns_error_without_calling_codex(
    dirty_repo: Path, fake_codex: FakeCodex
) -> None:
    result = review(dirty_repo, diff_base=UNKNOWN_REF)

    assert result.startswith("ERROR: cannot compute the diff")
    assert not fake_codex.ran()


def test_review_with_empty_diff_returns_error_without_calling_codex(
    clean_repo: Path, fake_codex: FakeCodex
) -> None:
    result = review(clean_repo, diff_base=HEAD_REF)

    assert result.startswith("ERROR: the diff against")
    assert "is empty" in result
    assert not fake_codex.ran()


def test_review_without_what_changed_or_diff_base_returns_error(
    clean_repo: Path, fake_codex: FakeCodex
) -> None:
    result = review(clean_repo)

    assert result == "ERROR: pass diff_base (preferred) or what_changed."
    assert not fake_codex.ran()


def test_review_with_what_changed_only_still_runs(
    clean_repo: Path, fake_codex: FakeCodex
) -> None:
    result = review(clean_repo, what_changed=WHAT_CHANGED_TEXT)

    assert fake_codex.ran()
    assert WHAT_CHANGED_TEXT in result


def test_build_diff_treats_option_like_base_as_ref_and_writes_nothing(
    dirty_repo: Path,
) -> None:
    tracked_before = (dirty_repo / TRACKED_FILE).read_bytes()

    with pytest.raises(codex_worker.DiffUnavailable):
        codex_worker.build_diff(str(dirty_repo), OPTION_LIKE_BASE)

    assert (dirty_repo / TRACKED_FILE).read_bytes() == tracked_before


def test_option_like_diff_base_returns_error_and_leaves_repo_untouched(
    dirty_repo: Path, fake_codex: FakeCodex
) -> None:
    tracked_before = (dirty_repo / TRACKED_FILE).read_bytes()

    result = review(dirty_repo, diff_base=OPTION_LIKE_BASE)

    assert result.startswith("ERROR: cannot compute the diff")
    assert not fake_codex.ran()
    assert (dirty_repo / TRACKED_FILE).read_bytes() == tracked_before


def test_build_diff_decodes_non_utf8_content_without_crashing(
    clean_repo: Path,
) -> None:
    (clean_repo / NON_UTF8_FILE).write_bytes(NON_UTF8_BYTES)

    diff = codex_worker.build_diff(str(clean_repo), HEAD_REF)

    assert isinstance(diff, str)
    assert REPLACEMENT_CHARACTER in diff


def test_review_with_non_utf8_diff_reaches_codex(
    clean_repo: Path, fake_codex: FakeCodex
) -> None:
    (clean_repo / NON_UTF8_FILE).write_bytes(NON_UTF8_BYTES)

    result = review(clean_repo, diff_base=HEAD_REF)

    assert fake_codex.ran()
    assert NON_UTF8_FILE in result


@pytest.mark.usefixtures("fake_codex")
def test_review_nonzero_exit_reports_code(
    dirty_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FAKE_EXIT_ENV, str(NONZERO_EXIT_CODE))

    result = review(dirty_repo, diff_base=HEAD_REF)

    assert result.startswith("ERROR:")
    assert "exited with code 3" in result


@pytest.mark.usefixtures("fake_codex")
def test_review_timeout_reports_error(
    dirty_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        codex_worker, "REVIEW_TIMEOUT_SECONDS", SHORT_TIMEOUT_SECONDS
    )
    monkeypatch.setenv(FAKE_SLEEP_ENV, str(SLEEP_SECONDS))

    result = review(dirty_repo, diff_base=HEAD_REF)

    assert result.startswith("ERROR:")
    assert "timed out after 1 seconds" in result


def test_review_missing_codex_binary_reports_error(
    dirty_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_BIN", str(tmp_path / MISSING_CODEX_BIN))

    result = review(dirty_repo, diff_base=HEAD_REF)

    assert "Codex CLI not found" in result
