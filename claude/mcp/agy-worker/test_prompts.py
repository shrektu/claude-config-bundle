import agy_prompts
from helpers_test import NO_TOOLS_SENTENCE


def test_translate_prompt_starts_with_the_no_tools_preamble_unit() -> None:
    prompt = agy_prompts.translate_prompt(
        {"a": "A"}, "en", "pl", "glossary text", "context text"
    )

    assert prompt.startswith(f"{NO_TOOLS_SENTENCE}\n\n")
    assert prompt.index(NO_TOOLS_SENTENCE) < prompt.index("glossary text")


def test_datasheet_prompt_forbids_commands_after_the_document_unit() -> None:
    prompt = agy_prompts.datasheet_prompt(["claim"], "context text")

    assert prompt.startswith(
        "@document.pdf\n\nUse only the attached document; "
        "never run commands and never write files.\n\n"
    )


def test_plan_prompt_allows_reading_but_never_running_commands_unit() -> None:
    prompt = agy_prompts.plan_prompt("change", "focus", "", "")

    assert prompt.startswith(
        "You may read files in the working directory, "
        "but you must never run commands.\n\n"
    )
