import asyncio
import os
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path

import agy_worker
import pytest
from agy_prompts import code_review_prompt
from agy_workspace import (
    TEXT_ENCODING,
    Workspace,
    snapshot_diff,
    snapshot_workspace,
)
from helpers_test import (
    ARGON_MODEL,
    FLASH_LOW_MODEL,
    FLASH_MEDIUM_MODEL,
    IGNORED_FILE,
    NO_TOOLS_SENTENCE,
    TRACKED_FILE,
    FakeAgy,
    force_add_ignored_file,
    git,
    git_output,
)

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
    f"(mode=code, model={FLASH_LOW_MODEL}, workspace=clean).\n\n"
    "Findings:\n" + CODE_FINDINGS
)
WRITTEN_TEXT = "Dodano obsługę przerwania zamiast pętli odpytującej."
WRITE_SUCCESS_TEXT = (
    f"Gemini text completed (model={FLASH_LOW_MODEL}, kind=pr_description, "
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


def inline_review_size(repo: Path) -> int:
    diff = snapshot_diff(edited_repo(repo), "HEAD").diff
    prompt = code_review_prompt("data loss", "", "", diff=diff)
    return len(prompt.encode(TEXT_ENCODING))


def review_of_edited_repo(repo: Path) -> str:
    return code_review(edited_repo(repo))


CALL_SITES_LABEL = "Call sites in unchanged files"
FILES_LABEL = "Repository files"
MORE_FILES_PATTERN = re.compile(r"\.\.\. (\d+) more files not listed")
PRICING_BEFORE = (
    "def total(price, customer):\n    return price * customer.discount\n"
)
PRICING_AFTER = (
    "def total(price, customer):\n    return price * (1 - customer.discount)\n"
)
API_SOURCE = (
    "import pricing\n\n\n"
    "def checkout(price, customer):\n"
    "    return pricing.total(price, customer)\n"
)
INVENTORY_SOURCE = (
    "import pricing\n\n\n"
    "def restock(price, customer):\n"
    "    return pricing.total(price, customer)\n"
)
LONG_DIRECTORY = "modules_with_a_long_directory_name"
FILLER_FILE = "filler.py"
FILLER_LINES = 5000
SMALL_LIMIT = 20_000
LIST_SQUEEZE_BYTES = 300


def pricing_repo(repo: Path) -> Path:
    (repo / "pricing.py").write_text(PRICING_BEFORE)
    (repo / "api.py").write_text(API_SOURCE)
    git(repo, "add", "pricing.py", "api.py")
    git(repo, "commit", "-q", "-m", "pricing")
    (repo / "pricing.py").write_text(PRICING_AFTER)
    return repo


def reviewed_prompt(fake_agy: FakeAgy) -> str:
    return fake_agy.invocation().argv[1]


def test_code_review_lists_call_sites_of_changed_names(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    pricing_repo(allowlisted_repo)

    code_review(allowlisted_repo)

    prompt = reviewed_prompt(fake_agy)
    assert CALL_SITES_LABEL in prompt
    section = prompt.split(CALL_SITES_LABEL, 1)[1]
    assert "total:\n" in section
    assert "api.py:5:" in section
    assert "pricing.total(price, customer)" in section


def test_code_review_excludes_call_sites_in_changed_files(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    pricing_repo(allowlisted_repo)
    (allowlisted_repo / "inventory.py").write_text(INVENTORY_SOURCE)
    git(allowlisted_repo, "add", "inventory.py")
    git(allowlisted_repo, "commit", "-q", "-m", "inventory")
    (allowlisted_repo / "inventory.py").write_text(
        INVENTORY_SOURCE + "\n\nX = 1\n"
    )

    code_review(allowlisted_repo)

    prompt = reviewed_prompt(fake_agy)
    assert CALL_SITES_LABEL in prompt
    section = prompt.split(CALL_SITES_LABEL, 1)[1]
    assert "api.py:5:" in section
    assert "inventory.py:5:" not in section
    assert "pricing.py:2:" not in section


def test_code_review_lists_repository_files(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    pricing_repo(allowlisted_repo)
    (allowlisted_repo / "notes dir").mkdir()
    (allowlisted_repo / "notes dir" / "untracked note.txt").write_text("n\n")
    (allowlisted_repo / ".gitignore").write_text(f"{IGNORED_FILE}\n")
    (allowlisted_repo / IGNORED_FILE).write_text("ignored\n")

    code_review(allowlisted_repo)

    prompt = reviewed_prompt(fake_agy)
    assert FILES_LABEL in prompt
    section = prompt.split(FILES_LABEL, 1)[1].split("\n\n", 1)[0] + "\n"
    for path in (
        TRACKED_FILE,
        "pricing.py",
        "api.py",
        ".gitignore",
        "notes dir/untracked note.txt",
    ):
        assert f"\n{path}\n" in section
    assert IGNORED_FILE not in section


def test_code_review_truncates_file_list_before_dropping_inline_diff(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_repo(allowlisted_repo)
    many = allowlisted_repo / LONG_DIRECTORY
    many.mkdir()
    for index in range(60):
        (many / f"module_{index:03d}.py").write_text("X = 1\n")
    code_review(allowlisted_repo)
    full_size = len(reviewed_prompt(fake_agy).encode(TEXT_ENCODING))
    limit = full_size - LIST_SQUEEZE_BYTES
    monkeypatch.setattr(agy_worker, "MAX_PROMPT_BYTES", limit)

    code_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    prompt = invocation.argv[1]
    assert MORE_FILES_PATTERN.search(prompt)
    assert len(prompt.encode(TEXT_ENCODING)) <= limit
    assert "+    return price * (1 - customer.discount)" in prompt
    assert REVIEW_DIFF not in invocation.files


def test_code_review_attached_diff_keeps_call_sites(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pricing_repo(allowlisted_repo)
    (allowlisted_repo / FILLER_FILE).write_text(
        "".join(f"VALUE_{index} = {index}\n" for index in range(FILLER_LINES))
    )
    monkeypatch.setattr(agy_worker, "MAX_PROMPT_BYTES", SMALL_LIMIT)

    code_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    prompt = invocation.argv[1]
    assert f"@{REVIEW_DIFF}" in prompt
    assert "VALUE_4999" in (invocation.files.get(REVIEW_DIFF) or "")
    assert CALL_SITES_LABEL in prompt
    assert "api.py:5:" in prompt
    assert len(prompt.encode(TEXT_ENCODING)) <= SMALL_LIMIT


def test_code_review_workspace_matches_the_context_snapshot(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edited_repo(allowlisted_repo)
    real_checkout = snapshot_workspace

    def edit_then_checkout(
        root: Path,
        attachments: Mapping[str, bytes] | None = None,
        commit: str | None = None,
    ) -> AbstractContextManager[Workspace]:
        (allowlisted_repo / TRACKED_FILE).write_text("late edit\n")
        return real_checkout(root, attachments, commit)

    monkeypatch.setattr(agy_worker, "snapshot_workspace", edit_then_checkout)

    code_review(allowlisted_repo)

    assert fake_agy.invocation().files[TRACKED_FILE] == "edited\n"


def test_plan_review_lists_repository_files(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    pricing_repo(allowlisted_repo)

    agy_worker.agy_plan_review(
        "Change pricing.total to a fraction",
        review_focus="contracts",
        project_path=str(allowlisted_repo),
    )

    prompt = reviewed_prompt(fake_agy)
    assert FILES_LABEL in prompt
    assert "\napi.py\n" in prompt.split(FILES_LABEL, 1)[1]
    assert CALL_SITES_LABEL not in prompt


def test_debug_consult_lists_repository_files(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    pricing_repo(allowlisted_repo)

    debug_consult(allowlisted_repo)

    prompt = reviewed_prompt(fake_agy)
    assert FILES_LABEL in prompt
    assert "\napi.py\n" in prompt.split(FILES_LABEL, 1)[1]
    assert CALL_SITES_LABEL not in prompt


def test_code_review_success_contract(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", CODE_FINDINGS)

    result = review_of_edited_repo(allowlisted_repo)

    assert result == CODE_SUCCESS_TEXT
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == FLASH_LOW_MODEL


def test_code_review_explicit_model_overrides_default(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", CODE_FINDINGS)

    result = code_review(
        edited_repo(allowlisted_repo), model=FLASH_MEDIUM_MODEL
    )

    assert f"model={FLASH_MEDIUM_MODEL}," in result
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == FLASH_MEDIUM_MODEL


def test_write_success_contract(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", WRITTEN_TEXT)

    result = write(allowlisted_repo)

    assert result == WRITE_SUCCESS_TEXT
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == FLASH_LOW_MODEL


def test_write_explicit_model_overrides_default(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", WRITTEN_TEXT)

    result = write(allowlisted_repo, model=FLASH_MEDIUM_MODEL)

    assert result == WRITE_SUCCESS_TEXT.replace(
        FLASH_LOW_MODEL, FLASH_MEDIUM_MODEL
    )
    argv = fake_agy.invocation().argv
    assert argv[argv.index("--model") + 1] == FLASH_MEDIUM_MODEL


def test_write_review_comment_kind_reaches_agy(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_RESPONSE", WRITTEN_TEXT)

    result = write(allowlisted_repo, kind="review_comment")

    assert result == WRITE_SUCCESS_TEXT.replace(
        "kind=pr_description", "kind=review_comment"
    )
    assert "review comment" in fake_agy.invocation().argv[1]


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


def test_code_review_inlines_small_diff(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    edited_repo(allowlisted_repo)
    (allowlisted_repo / UNTRACKED_FILE).write_text(UNTRACKED_CONTENT)

    code_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    prompt = invocation.argv[1]
    assert "-original" in prompt
    assert "+edited" in prompt
    assert f"+++ b/{UNTRACKED_FILE}" in prompt
    assert "+freshly created" in prompt
    assert f"@{REVIEW_DIFF}" not in prompt
    assert REVIEW_DIFF not in invocation.files


def test_code_review_attaches_diff_over_limit(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inline_size = inline_review_size(allowlisted_repo)
    monkeypatch.setattr(agy_worker, "MAX_PROMPT_BYTES", inline_size - 1)

    code_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    assert "+edited" in (invocation.files.get(REVIEW_DIFF) or "")
    assert f"@{REVIEW_DIFF}" in invocation.argv[1]
    assert "+edited" not in invocation.argv[1]


def test_code_review_inlines_diff_at_exact_limit(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inline_size = inline_review_size(allowlisted_repo)
    monkeypatch.setattr(agy_worker, "MAX_PROMPT_BYTES", inline_size)

    code_review(allowlisted_repo)

    invocation = fake_agy.invocation()
    assert "+edited" in invocation.argv[1]
    assert REVIEW_DIFF not in invocation.files


def test_code_review_diff_includes_force_added_ignored_file(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    index_before = force_add_ignored_file(allowlisted_repo)

    result = code_review(allowlisted_repo)

    assert result.startswith("Gemini review completed")
    prompt = fake_agy.invocation().argv[1]
    assert f"+++ b/{IGNORED_FILE}" in prompt
    assert "+forced in" in prompt
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
        "review_comment",
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


def test_write_inlines_facts_template_and_style_guide(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(STYLE_GUIDE)
    monkeypatch.setenv("AGY_STYLE_GUIDE", str(guide))

    write(allowlisted_repo, template=TEMPLATE)

    prompt = fake_agy.invocation().argv[1]
    assert prompt.startswith(f"{NO_TOOLS_SENTENCE}\n\n")
    assert FACTS in prompt
    assert TEMPLATE.strip() in prompt
    assert STYLE_GUIDE.strip() in prompt
    assert "@.agy/" not in prompt


def test_machine_mode_env_does_not_leak_into_tests() -> None:
    assert "CLAUDE_MODE" not in os.environ


def test_style_guide_inlined_when_machine_runs_personal_mode(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(STYLE_GUIDE)
    monkeypatch.setenv("AGY_STYLE_GUIDE", str(guide))

    write(allowlisted_repo)

    assert STYLE_GUIDE.strip() in fake_agy.invocation().argv[1]


@pytest.mark.parametrize("mode", ["personal", "PERSONAL", " Personal "])
def test_write_skips_style_guide_in_personal_mode(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(STYLE_GUIDE)
    monkeypatch.setenv("AGY_STYLE_GUIDE", str(guide))
    monkeypatch.setenv("CLAUDE_MODE", mode)

    write(allowlisted_repo, template=TEMPLATE)

    prompt = fake_agy.invocation().argv[1]
    assert agy_worker.style_guide_content() is None
    assert STYLE_GUIDE.strip() not in prompt
    assert "Style guide" not in prompt
    assert TEMPLATE.strip() in prompt


@pytest.mark.parametrize("mode", ["", "work", "persnal"])
def test_write_inlines_style_guide_outside_personal_mode(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    guide = tmp_path / "guide.md"
    guide.write_text(STYLE_GUIDE)
    monkeypatch.setenv("AGY_STYLE_GUIDE", str(guide))
    monkeypatch.setenv("CLAUDE_MODE", mode)

    write(allowlisted_repo)

    assert agy_worker.style_guide_content() == STYLE_GUIDE.encode()
    assert STYLE_GUIDE.strip() in fake_agy.invocation().argv[1]


def test_write_without_style_guide_file(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = write(allowlisted_repo)

    prompt = fake_agy.invocation().argv[1]
    assert result.startswith("Gemini text completed")
    assert FACTS in prompt
    assert "Style guide" not in prompt
    assert "Template" not in prompt


def test_write_runs_in_empty_workspace(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    write(allowlisted_repo)

    assert set(fake_agy.invocation().files) == {".git"}


def test_write_over_size_limit_unavailable(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = write(allowlisted_repo, facts="x" * 100_001)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "byte limit" in result
    assert not fake_agy.ran()


def test_write_not_allowlisted(fake_agy: FakeAgy, foreign_repo: Path) -> None:
    result = write(foreign_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "gitlab.com/acme/widgets" in result
    assert not fake_agy.ran()


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


@pytest.mark.parametrize("call", [review_of_edited_repo, debug_consult])
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


PRICE_CALLER = "import pricing\n\n\ndef checkout(p):\n    return total(p)\n"
COMPUTE_CALLER = "import compute\n\n\ndef run():\n    compute.compute(1)\n"
C_TOTAL_TEMPLATE = "int compute_total(int price) {{ return price * {}; }}\n"
TOTAL_BEFORE = "def total(price):\n    return price\n"
TOTAL_AFTER = "def total(price):\n    return price + 1\n"


def commit_files(repo: Path, files: Mapping[str, str]) -> None:
    for name, content in files.items():
        (repo / name).write_text(content)
    git(repo, "add", *files)
    git(repo, "commit", "-q", "-m", "files")


def client_source(method: str, result: str) -> str:
    return f"class Client {{\n{method}    return {result};\n  }}\n}}\n"


def call_sites_text(prompt: str) -> str:
    return prompt.split(CALL_SITES_LABEL, 1)[1].split("\n\n", 1)[0]


def test_blank_first_added_block_names_the_enclosing_function(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    commit_files(
        allowlisted_repo,
        {
            "compute.py": "def compute(a):\n    x = 1\n    return a\n",
            "api.py": COMPUTE_CALLER,
        },
    )
    (allowlisted_repo / "compute.py").write_text(
        "def compute(a):\n    x = 1\n\n    y = 2\n    return a\n"
    )

    code_review(allowlisted_repo)

    assert "api.py:5:" in call_sites_text(reviewed_prompt(fake_agy))


def test_quoted_path_changed_file_is_excluded_and_its_name_found(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    weird = 'we"ird.py'
    commit_files(
        allowlisted_repo, {weird: TOTAL_BEFORE, "api.py": PRICE_CALLER}
    )
    (allowlisted_repo / weird).write_text(TOTAL_AFTER)

    code_review(allowlisted_repo)

    section = call_sites_text(reviewed_prompt(fake_agy))
    assert "api.py:5:" in section
    assert weird not in section


def test_non_ascii_changed_file_is_excluded_from_call_sites(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    name = "zażółć.py"
    commit_files(
        allowlisted_repo, {name: TOTAL_BEFORE, "api.py": PRICE_CALLER}
    )
    (allowlisted_repo / name).write_text(TOTAL_AFTER)

    code_review(allowlisted_repo)

    section = call_sites_text(reviewed_prompt(fake_agy))
    assert "api.py:5:" in section
    assert name not in section


def test_column_zero_definition_with_inline_body_finds_its_callers(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    commit_files(
        allowlisted_repo,
        {
            "pricing.c": C_TOTAL_TEMPLATE.format(2),
            "main.c": "int main(void)\n{\n    return compute_total(4);\n}\n",
        },
    )
    (allowlisted_repo / "pricing.c").write_text(C_TOTAL_TEMPLATE.format(3))

    code_review(allowlisted_repo)

    assert "main.c:3:" in call_sites_text(reviewed_prompt(fake_agy))


def test_method_with_generics_and_return_type_finds_its_callers(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    method = "  async fetchAll<T>(url: string): Promise<T[]> {\n"
    commit_files(
        allowlisted_repo,
        {
            "client.ts": client_source(method, "one"),
            "use.ts": "const all = client.fetchAll(url);\n",
        },
    )
    (allowlisted_repo / "client.ts").write_text(client_source(method, "three"))

    code_review(allowlisted_repo)

    assert "use.ts:1:" in call_sites_text(reviewed_prompt(fake_agy))


def test_suppress_blank_empty_context_line_does_not_merge_blocks(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    git(allowlisted_repo, "config", "diff.suppressBlankEmpty", "true")
    commit_files(
        allowlisted_repo,
        {
            "compute.py": "def compute(a):\n    x = 1\n\n    return a\n",
            "api.py": COMPUTE_CALLER,
        },
    )
    (allowlisted_repo / "compute.py").write_text(
        "def compute(a):\n    x = 1\n\n    return a + x\n"
    )

    code_review(allowlisted_repo)

    assert "api.py:5:" in call_sites_text(reviewed_prompt(fake_agy))


def test_code_review_inline_diff_precedes_call_sites_and_file_list(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    pricing_repo(allowlisted_repo)

    code_review(allowlisted_repo)

    prompt = reviewed_prompt(fake_agy)
    assert (
        prompt.index("Output only these lines")
        < prompt.index("Diff:\n")
        < prompt.index(CALL_SITES_LABEL)
        < prompt.index(FILES_LABEL)
    )
    assert prompt.rstrip().endswith("tracked.txt")
