import asyncio
from collections.abc import Callable
from pathlib import Path

import agy_worker
import pytest
from helpers_test import (
    ARGON_MODEL,
    IGNORED_FILE,
    NO_TOOLS_SENTENCE,
    TRACKED_FILE,
    FakeAgy,
    force_add_ignored_file,
    git,
    git_output,
)

FLASH_MODEL = "gemini-3.8-flash-medium"
READ_ONLY_SENTENCE = (
    "You may read files in the working directory, but you must never run "
    "commands and never create, edit or delete files."
)
NO_HEADER_SENTENCE = (
    "Write no AI header and no AI footer, whatever the style guide says "
    "— the footer is added later."
)
REVIEW_DIFF = ".agy/review.diff"
FACTS_FILE = ".agy/facts.md"
TEMPLATE_FILE = ".agy/template.md"
STYLE_GUIDE_FILE = ".agy/style-guide.md"
EVIDENCE_FILE = ".agy/evidence.txt"
CODE_FINDINGS = (
    "[IMPORTANT] tracked.txt:1 — value is dropped — empty file -> data loss\n"
    "FAIL"
)
CODE_SUCCESS_TEXT = (
    "Gemini review completed "
    f"(mode=code, model={FLASH_MODEL}, workspace=clean).\n\n"
    "Findings:\n" + CODE_FINDINGS
)
WRITTEN_TEXT = "Dodano obsługę przerwania zamiast pętli odpytującej."
WRITE_SUCCESS_TEXT = (
    f"Gemini text completed (model={FLASH_MODEL}, kind=pr_description, "
    "workspace=clean).\n\n" + WRITTEN_TEXT
)
DEBUG_FINDINGS = "H1 tracked.txt:1 — stale value — rerun with logging"
DEBUG_SUCCESS_TEXT = (
    f"Argon debug consult completed (model={ARGON_MODEL}, "
    "workspace=clean).\n\n"
    "Findings:\n" + DEBUG_FINDINGS
)
FACTS = "- polling loop removed\n- interrupt handler added"
TEMPLATE = "## Opis\n\n## Testy\n"
STYLE_GUIDE = "Pisz krótko i w stronie czynnej.\n"
PROBLEM = "The counter stays at zero after the first interrupt"
EVIDENCE = "log line 12: counter=0"
UNTRACKED_FILE = "brand_new.txt"
UNTRACKED_CONTENT = "freshly created\n"


def edited_repo(repo: Path) -> Path:
    (repo / TRACKED_FILE).write_text("edited\n")
    return repo


def code_review(repo: Path, **kwargs: str) -> str:
    result: str = agy_worker.agy_code_review(
        diff_base=kwargs.pop("diff_base", "HEAD"),
        review_focus="data loss",
        project_path=str(repo),
        **kwargs,
    )
    return result


def write(repo: Path, **kwargs: str) -> str:
    result: str = agy_worker.agy_write(
        project_path=str(repo),
        kind=kwargs.pop("kind", "pr_description"),
        facts=kwargs.pop("facts", FACTS),
        **kwargs,
    )
    return result


def debug_consult(repo: Path, **kwargs: str) -> str:
    result: str = agy_worker.agy_debug_consult(
        problem=PROBLEM,
        evidence=EVIDENCE,
        project_path=str(repo),
        **kwargs,
    )
    return result


def review_of_edited_repo(repo: Path) -> str:
    return code_review(edited_repo(repo))


def test_code_review_success_contract(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", CODE_FINDINGS)

    result = review_of_edited_repo(allowlisted_repo)

    assert result == CODE_SUCCESS_TEXT
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == FLASH_MODEL


def test_write_success_contract(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", WRITTEN_TEXT)

    result = write(allowlisted_repo)

    assert result == WRITE_SUCCESS_TEXT
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == FLASH_MODEL


def test_debug_consult_success_contract(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", DEBUG_FINDINGS)

    result = debug_consult(allowlisted_repo)

    assert result == DEBUG_SUCCESS_TEXT
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == ARGON_MODEL


def test_code_review_attaches_diff_with_untracked(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    edited_repo(allowlisted_repo)
    (allowlisted_repo / UNTRACKED_FILE).write_text(UNTRACKED_CONTENT)

    code_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    diff = invocation.files.get(REVIEW_DIFF) or ""
    assert "-original" in diff
    assert "+edited" in diff
    assert f"+++ b/{UNTRACKED_FILE}" in diff
    assert "+freshly created" in diff
    assert f"@{REVIEW_DIFF}" in invocation.argv[1]


def test_code_review_diff_includes_force_added_ignored_file(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    index_before = force_add_ignored_file(allowlisted_repo)

    result = code_review(allowlisted_repo)

    assert result.startswith("Gemini review completed")
    diff = fake_agy.invocation().files.get(REVIEW_DIFF) or ""
    assert f"+++ b/{IGNORED_FILE}" in diff
    assert "+forced in" in diff
    assert (allowlisted_repo / ".git" / "index").read_bytes() == index_before


def test_write_kind_schema_is_enum() -> None:
    tools = asyncio.run(agy_worker.mcp.list_tools())

    schema = next(tool for tool in tools if tool.name == "agy_write")
    kind = schema.inputSchema.get("$defs", {}).get("WriteKind", {})
    assert kind.get("enum") == [
        "pr_description",
        "jira_comment",
        "jira_description",
        "ui_message",
    ]
    assert schema.inputSchema["properties"]["kind"] == {
        "$ref": "#/$defs/WriteKind"
    }


def test_code_review_empty_diff_unavailable(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = code_review(allowlisted_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "empty" in result
    assert not fake_agy.ran()


@pytest.mark.parametrize("base", ["no-such-ref", f"--output={TRACKED_FILE}"])
def test_code_review_bad_base_unavailable(
    fake_agy: FakeAgy, allowlisted_repo: Path, base: str
) -> None:
    edited_repo(allowlisted_repo)

    result = code_review(allowlisted_repo, diff_base=base)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert not fake_agy.ran()
    assert (allowlisted_repo / TRACKED_FILE).read_text() == "edited\n"


def test_code_review_not_allowlisted(
    fake_agy: FakeAgy, foreign_repo: Path
) -> None:
    result = review_of_edited_repo(foreign_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "gitlab.com/acme/widgets" in result
    assert not fake_agy.ran()


def test_write_attaches_facts_template_and_style_guide(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(STYLE_GUIDE)
    monkeypatch.setenv("AGY_STYLE_GUIDE", str(guide))

    write(allowlisted_repo, template=TEMPLATE)

    invocation = fake_agy.invocation()
    assert invocation.files.get(FACTS_FILE) == FACTS
    assert invocation.files.get(TEMPLATE_FILE) == TEMPLATE
    assert invocation.files.get(STYLE_GUIDE_FILE) == STYLE_GUIDE
    for attachment in (FACTS_FILE, TEMPLATE_FILE, STYLE_GUIDE_FILE):
        assert f"@{attachment}" in invocation.argv[1]


def test_write_without_style_guide_file(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = write(allowlisted_repo)

    invocation = fake_agy.invocation()
    assert result.startswith("Gemini text completed")
    assert invocation.files.get(FACTS_FILE) == FACTS
    assert STYLE_GUIDE_FILE not in invocation.files
    assert TEMPLATE_FILE not in invocation.files
    assert STYLE_GUIDE_FILE not in invocation.argv[1]


def test_write_refuses_argon(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = write(allowlisted_repo, model=ARGON_MODEL)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "argon" in result.lower()
    assert not fake_agy.ran()


def test_write_unknown_kind_unavailable(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = write(allowlisted_repo, kind="poem")

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "poem" in result
    assert not fake_agy.ran()


def test_write_prompt_forbids_header_and_footer(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    write(allowlisted_repo)

    assert NO_HEADER_SENTENCE in fake_agy.invocation().argv[1]


def test_debug_consult_attaches_evidence(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    debug_consult(allowlisted_repo)

    invocation = fake_agy.invocation()
    assert invocation.files.get(EVIDENCE_FILE) == EVIDENCE
    assert f"@{EVIDENCE_FILE}" in invocation.argv[1]
    assert PROBLEM in invocation.argv[1]


@pytest.mark.parametrize("call", [review_of_edited_repo, write, debug_consult])
def test_new_tools_use_read_only_preamble(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    call: Callable[[Path], str],
) -> None:
    call(allowlisted_repo)

    prompt = fake_agy.invocation().argv[1]
    assert prompt.startswith(f"{READ_ONLY_SENTENCE}\n\n")
    assert NO_TOOLS_SENTENCE not in prompt


def test_new_tools_leave_the_repository_untouched(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    edited_repo(allowlisted_repo)
    git(allowlisted_repo, "add", TRACKED_FILE)
    status_before = git_output(allowlisted_repo, "status", "--porcelain")

    code_review(allowlisted_repo)
    write(allowlisted_repo)
    debug_consult(allowlisted_repo)

    status_after = git_output(allowlisted_repo, "status", "--porcelain")
    assert status_after == status_before
    assert list(fake_agy.work_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (
            "agy_code_review",
            {"diff_base": "HEAD", "review_focus": "data loss"},
        ),
        ("agy_write", {"kind": "jira_comment", "facts": FACTS}),
        (
            "agy_debug_consult",
            {"problem": PROBLEM, "evidence": EVIDENCE},
        ),
    ],
)
def test_new_tools_callable_through_fastmcp(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tool: str,
    arguments: dict[str, str],
) -> None:
    edited_repo(allowlisted_repo)

    outcome = asyncio.run(
        agy_worker.mcp.call_tool(
            tool, {"project_path": str(allowlisted_repo), **arguments}
        )
    )

    assert "completed" in repr(outcome)
    assert fake_agy.ran()
