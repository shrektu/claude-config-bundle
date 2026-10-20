import asyncio
import json
from pathlib import Path

import agy_worker
import pytest
from helpers_test import (
    ARGON_MODEL,
    DATASHEET_CLAIMS,
    DATASHEET_STRUCTURED,
    DATASHEET_SUCCESS_TEXT,
    PLAN_SUCCESS_TEXT,
    REAL_BWRAP,
    REVIEW_BODY,
    TRANSLATE_ENTRIES,
    TRANSLATE_STRUCTURED,
    FLASH_LOW_MODEL,
    FLASH_MEDIUM_MODEL,
    FakeAgy,
    make_pdf,
    plan_review,
)

TOOL_PARAMETERS = {
    "agy_models": (set(), set()),
    "agy_plan_review": (
        {
            "what_changed",
            "review_focus",
            "project_path",
            "acceptance_criteria",
            "extra_context",
            "model",
        },
        {"what_changed", "review_focus", "project_path"},
    ),
    "agy_datasheet_check": (
        {
            "pdf_path",
            "claims",
            "context",
            "first_page",
            "last_page",
            "model",
        },
        {"pdf_path", "claims"},
    ),
    "agy_translate": (
        {
            "project_path",
            "entries",
            "source_lang",
            "target_lang",
            "glossary",
            "context",
            "model",
        },
        {"project_path", "entries", "source_lang", "target_lang"},
    ),
    "agy_code_review": (
        {
            "diff_base",
            "review_focus",
            "project_path",
            "acceptance_criteria",
            "extra_context",
            "model",
        },
        {"diff_base", "review_focus", "project_path"},
    ),
    "agy_write": (
        {
            "project_path",
            "kind",
            "facts",
            "template",
            "language",
            "model",
        },
        {"project_path", "kind", "facts"},
    ),
    "agy_debug_consult": (
        {"problem", "evidence", "project_path", "model"},
        {"problem", "evidence", "project_path"},
    ),
}


@pytest.mark.usefixtures("fake_agy")
def test_plan_review_success_on_allowlisted_repo(
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_BWRAP", REAL_BWRAP)
    monkeypatch.setenv("AGY_FAKE_RESPONSE", REVIEW_BODY)

    result = plan_review(allowlisted_repo)

    assert result == PLAN_SUCCESS_TEXT


def test_plan_review_defaults_to_flash_low(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = plan_review(allowlisted_repo)

    argv = fake_agy.invocation().argv
    assert result.startswith(
        "Gemini review completed "
        f"(mode=plan, model={FLASH_LOW_MODEL}, workspace=clean)."
    )
    assert argv[argv.index("--model") + 1] == FLASH_LOW_MODEL


def test_plan_review_explicit_model_overrides_default(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = plan_review(allowlisted_repo, model=FLASH_MEDIUM_MODEL)

    argv = fake_agy.invocation().argv
    assert f"model={FLASH_MEDIUM_MODEL}," in result
    assert argv[argv.index("--model") + 1] == FLASH_MEDIUM_MODEL


def test_plan_review_not_allowlisted_does_not_spawn_agy(
    fake_agy: FakeAgy, foreign_repo: Path
) -> None:
    result = plan_review(foreign_repo)

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "gitlab.com/acme/widgets" in result
    assert not fake_agy.ran()


@pytest.mark.usefixtures("fake_agy")
def test_datasheet_check_formats_verdict_buckets_with_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 10)
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(DATASHEET_STRUCTURED))

    result = agy_worker.agy_datasheet_check(
        pdf_path=str(pdf), claims=DATASHEET_CLAIMS
    )

    assert result == DATASHEET_SUCCESS_TEXT


@pytest.mark.usefixtures("fake_agy")
def test_translate_success_returns_translations_json(
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(TRANSLATE_STRUCTURED))

    result = agy_worker.agy_translate(
        project_path=str(allowlisted_repo),
        entries=TRANSLATE_ENTRIES,
        source_lang="en",
        target_lang="pl",
    )

    assert json.loads(result) == {
        "model": FLASH_MEDIUM_MODEL,
        "translations": {
            "greeting": "Cześć {{name}}",
            "bye": "Do widzenia",
        },
        "problems": [],
    }


def test_translate_refuses_argon_model_without_spawning(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = agy_worker.agy_translate(
        project_path=str(allowlisted_repo),
        entries=TRANSLATE_ENTRIES,
        source_lang="en",
        target_lang="pl",
        model=ARGON_MODEL,
    )

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "argon" in result.lower()
    assert not fake_agy.ran()


def test_tool_descriptions_are_one_short_line() -> None:
    tools = asyncio.run(agy_worker.mcp.list_tools())

    assert sorted(tool.name for tool in tools) == sorted(TOOL_PARAMETERS)
    for tool in tools:
        assert tool.description is not None
        assert "\n" not in tool.description
        assert len(tool.description) <= 72


def test_tools_callable_through_fastmcp(
    fake_agy: FakeAgy,
    allowlisted_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(TRANSLATE_STRUCTURED))

    tools = asyncio.run(agy_worker.mcp.list_tools())
    outcome = asyncio.run(
        agy_worker.mcp.call_tool(
            "agy_translate",
            {
                "project_path": str(allowlisted_repo),
                "entries": TRANSLATE_ENTRIES,
                "source_lang": "en",
                "target_lang": "pl",
            },
        )
    )

    schemas = {
        tool.name: (
            set(tool.inputSchema["properties"]),
            set(tool.inputSchema.get("required", [])),
        )
        for tool in tools
    }
    assert schemas == TOOL_PARAMETERS
    assert "Do widzenia" in repr(outcome)
    assert fake_agy.ran()
