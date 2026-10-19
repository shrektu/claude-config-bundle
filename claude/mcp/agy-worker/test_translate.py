import json
from collections import Counter
from pathlib import Path

import agy_reports
import agy_worker
import jsonschema
import pytest
from agy_reports import Problem, TranslationOutput
from helpers_test import (
    NO_TOOLS_SENTENCE,
    TRANSLATE_ENTRIES,
    TRANSLATE_STRUCTURED,
    FakeAgy,
    translate,
)

LINK_SOURCE = '<a title=">original">Open</a>'
LINK_CHANGED = '<a title=">changed">Otwórz</a>'
REFERENCE = '$t(key, {"defaultValue":"a)b"})'
REFERENCE_SOURCE = f"Hello {REFERENCE}"
REFERENCE_CHANGED = 'Cześć $t(key, {"defaultValue":"a)c"})'


def test_placeholders_counts_every_supported_syntax() -> None:
    text = "Hi {{name}} {count} %s %d <b>x</b> $t(a.b) {{name}}"

    assert agy_reports.placeholders(text) == Counter(
        {
            "{{name}}": 2,
            "{count}": 1,
            "%s": 1,
            "%d": 1,
            "<b>": 1,
            "</b>": 1,
            "$t(a.b)": 1,
        }
    )


def test_placeholder_problem_names_expected_and_actual() -> None:
    assert agy_reports.placeholder_problem("A {{x}}", "B {{x}}") is None
    assert agy_reports.placeholder_problem("A {{x}}", "B {{y}}") == (
        "placeholders differ: expected ['{{x}}'], got ['{{y}}']"
    )


def test_tag_attribute_change_reported_unit() -> None:
    problem = agy_reports.placeholder_problem(LINK_SOURCE, LINK_CHANGED)

    assert problem == (
        "placeholders differ: expected ['</a>', '<a title=\">original\">'], "
        "got ['</a>', '<a title=\">changed\">']"
    )


def test_tag_with_quoted_angle_bracket_kept_intact_is_clean() -> None:
    kept = '<a title=">original">Otwórz</a>'

    assert agy_reports.placeholder_problem(LINK_SOURCE, kept) is None


def test_translation_report_flags_missing_extra_and_placeholder_unit() -> None:
    entries = {
        "greeting": "Hello {{name}}",
        "bye": "Goodbye",
        "ok": "OK",
    }
    output = TranslationOutput(
        translations={
            "greeting": "Cześć",
            "ok": "Dobrze",
            "farewell": "Pa",
        }
    )

    report = agy_reports.translation_report("m", entries, output)

    assert report.translations == {"greeting": "Cześć", "ok": "Dobrze"}
    assert report.problems == [
        Problem(
            key="greeting",
            problem="placeholders differ: expected ['{{name}}'], got []",
        ),
        Problem(key="bye", problem="missing"),
        Problem(key="farewell", problem="not in the input"),
    ]


def test_i18n_reference_argument_change_reported_unit() -> None:
    problem = agy_reports.placeholder_problem(
        REFERENCE_SOURCE, REFERENCE_CHANGED
    )

    assert problem is not None
    assert problem.startswith("placeholders differ")


def test_i18n_reference_kept_intact_is_clean_unit() -> None:
    kept = f"Cześć {REFERENCE}"

    assert agy_reports.placeholder_problem(REFERENCE_SOURCE, kept) is None


@pytest.mark.usefixtures("fake_agy")
def test_translate_i18n_reference_argument_change_reported(
    allowlisted_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = {"translations": {"k": REFERENCE_CHANGED}}
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(changed))

    result = json.loads(translate(allowlisted_repo, {"k": REFERENCE_SOURCE}))

    assert [problem["key"] for problem in result["problems"]] == ["k"]
    assert result["problems"][0]["problem"].startswith("placeholders differ")


@pytest.mark.usefixtures("fake_agy")
def test_translate_tag_attribute_change_reported(
    allowlisted_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = {"translations": {"link": LINK_CHANGED}}
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(changed))

    result = json.loads(translate(allowlisted_repo, {"link": LINK_SOURCE}))

    assert [problem["key"] for problem in result["problems"]] == ["link"]
    assert result["problems"][0]["problem"].startswith("placeholders differ")


@pytest.mark.usefixtures("fake_agy")
def test_translate_placeholder_lost_reported(
    allowlisted_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lost = {
        "translations": {"greeting": "Cześć", "bye": "Do widzenia"},
    }
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(lost))

    result = json.loads(translate(allowlisted_repo, TRANSLATE_ENTRIES))

    assert result["problems"] == [
        {
            "key": "greeting",
            "problem": "placeholders differ: expected ['{{name}}'], got []",
        }
    ]
    assert result["translations"]["bye"] == "Do widzenia"


@pytest.mark.usefixtures("fake_agy")
def test_translate_missing_and_extra_keys_reported(
    allowlisted_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong_keys = {
        "translations": {"greeting": "Cześć {{name}}", "farewell": "Pa"},
    }
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(wrong_keys))

    result = json.loads(translate(allowlisted_repo, TRANSLATE_ENTRIES))

    assert result["translations"] == {"greeting": "Cześć {{name}}"}
    assert result["problems"] == [
        {"key": "bye", "problem": "missing"},
        {"key": "farewell", "problem": "not in the input"},
    ]


def test_translate_refusal_names_the_offending_model_case_insensitively(
    fake_agy: FakeAgy, allowlisted_repo: Path
) -> None:
    result = agy_worker.agy_translate(
        project_path=str(allowlisted_repo),
        entries=TRANSLATE_ENTRIES,
        source_lang="en",
        target_lang="pl",
        model="Gemini-4-ARGON-low",
    )

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert "Gemini-4-ARGON-low" in result
    assert not fake_agy.ran()


def test_nul_in_project_path_unavailable(fake_agy: FakeAgy) -> None:
    result = agy_worker.agy_translate(
        project_path="repo\0x",
        entries=TRANSLATE_ENTRIES,
        source_lang="en",
        target_lang="pl",
    )

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert not fake_agy.ran()


def test_translate_sends_no_tools_preamble_and_mapping_schema(
    fake_agy: FakeAgy, allowlisted_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(TRANSLATE_STRUCTURED))
    translate(allowlisted_repo, TRANSLATE_ENTRIES)
    argv = fake_agy.invocation().argv
    schema = json.loads(argv[argv.index("--json-schema") + 1])

    assert argv[1].startswith(f"{NO_TOOLS_SENTENCE}\n\n")
    assert schema["properties"]["translations"] == {
        "additionalProperties": {"type": "string"},
        "title": "Translations",
        "type": "object",
    }
    assert "$defs" not in schema
    jsonschema.validate(TRANSLATE_STRUCTURED, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"translations": [{"key": "a"}]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"translations": {"a": 3}}, schema)
