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


def test_read_batch_rule_in_plan_code_and_debug_prompts_unit() -> None:
    rule = (
        "Read files in as few turns as possible: request every file you "
        "need in one turn as parallel read_file calls, and read a long "
        "file in one turn as parallel read_file calls for consecutive "
        "line ranges. Never read .git or anything outside the working "
        "directory."
    )
    plan = agy_prompts.plan_prompt("change", "focus", "", "")
    code = agy_prompts.code_review_prompt("focus", "", "", diff=None)
    debug = agy_prompts.debug_prompt("problem")

    for prompt in (plan, code, debug):
        assert rule in prompt
    assert plan.index(rule) == len(
        "You may read files in the working directory, "
        "but you must never run commands.\n\n"
    )


NO_GUESSING_SENTENCE = (
    "Never guess a file name: read a path only when it appears in the "
    "repository file list, the diff, the call sites, or an import or "
    "include of a file you have read."
)
FOCUS = ("focus", "", "")
HUGE_REPO_FILES = 5000
LARGE_DIFF = "+x\n" * 700


def size(text: str) -> int:
    return len(text.encode())


def test_no_guessing_rule_in_plan_code_and_debug_prompts_unit() -> None:
    plan = agy_prompts.plan_prompt("change", "focus", "", "")
    code = agy_prompts.code_review_prompt("focus", "", "", diff=None)
    debug = agy_prompts.debug_prompt("problem")

    for prompt in (plan, code, debug):
        assert NO_GUESSING_SENTENCE in prompt


def test_file_list_omitted_when_no_room_unit() -> None:
    bare = agy_prompts.code_review_prompt(*FOCUS, diff="DIFF")

    fitted = agy_prompts.fit_code_review(
        FOCUS, "DIFF", [], ["a.py", "b.py"], size(bare)
    )

    assert fitted == agy_prompts.FittedReview(bare, True)
    assert "Repository files" not in fitted.prompt


def test_file_list_truncated_in_huge_repo_unit() -> None:
    paths = [f"src/module_{index:05d}.py" for index in range(HUGE_REPO_FILES)]

    fitted = agy_prompts.fit_code_review(FOCUS, "DIFF", [], paths, 1_000_000)

    section = fitted.prompt.split("Repository files:\n", 1)[1]
    section = section.split("\n\n", 1)[0]
    listed = section.splitlines()[:-1]
    assert size(section) <= 40_000
    assert section.splitlines()[-1] == (
        f"... {HUGE_REPO_FILES - len(listed)} more files not listed"
    )
    assert listed == paths[: len(listed)]
    assert 0 < len(listed) < HUGE_REPO_FILES


def test_call_sites_outrank_the_inline_diff_unit() -> None:
    sites = ["total:", "  api.py:5: pricing.total(price)"]
    inline = agy_prompts.fit_code_review(
        FOCUS, LARGE_DIFF, sites, [], 1_000_000
    ).prompt
    limit = size(inline) - 1

    fitted = agy_prompts.fit_code_review(FOCUS, LARGE_DIFF, sites, [], limit)

    assert fitted.diff_inline is False
    assert "api.py:5: pricing.total(price)" in fitted.prompt
    assert size(fitted.prompt) <= limit


def test_call_sites_truncated_to_the_room_left_unit() -> None:
    sites = [f"  caller_{index:03d}.py:1: total()" for index in range(200)]
    attached = agy_prompts.code_review_prompt(*FOCUS, diff=None)
    limit = size(attached) + 600

    fitted = agy_prompts.fit_code_review(FOCUS, LARGE_DIFF, sites, [], limit)

    assert size(fitted.prompt) <= limit
    assert "call site lines not listed" in fitted.prompt
    assert fitted.diff_inline is False


OUTPUT_FORMAT_START = "Output only these lines"
CALL_SITES_START = "Call sites in unchanged files"
FILES_START = "Repository files:"
SITE_LINES = ["total:", "  api.py:5: pricing.total(price)"]


def test_inline_diff_precedes_call_sites_and_file_list_unit() -> None:
    fitted = agy_prompts.fit_code_review(
        FOCUS, "DIFF", SITE_LINES, ["a.py"], 1_000_000
    )

    prompt = fitted.prompt
    assert fitted.diff_inline
    assert (
        prompt.index(OUTPUT_FORMAT_START)
        < prompt.index("Diff:\nDIFF")
        < prompt.index(CALL_SITES_START)
        < prompt.index(FILES_START)
    )
    assert prompt.endswith("Repository files:\na.py")


def test_attached_diff_keeps_context_before_output_format_unit() -> None:
    fitted = agy_prompts.fit_code_review(
        FOCUS, LARGE_DIFF, SITE_LINES, ["a.py"], 3_000
    )

    prompt = fitted.prompt
    assert not fitted.diff_inline
    assert (
        prompt.index(CALL_SITES_START)
        < prompt.index(FILES_START)
        < prompt.index(OUTPUT_FORMAT_START)
    )
