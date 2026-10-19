import json
from pathlib import Path

import agy_pdf
import agy_reports
import agy_worker
import jsonschema
import pytest
from agy_errors import AgyUnavailableError
from agy_pdf import PageWindow
from agy_reports import Bucket, ClaimVerdict, Verdict
from helpers_test import (
    DATASHEET_CLAIMS,
    DATASHEET_STRUCTURED,
    FakeAgy,
    datasheet_claims,
    make_pdf,
)


def test_map_pages_adds_offset_and_rejects_pages_outside_the_cut() -> None:
    window = PageWindow(first=10, last=20, total=100)

    assert agy_pdf.map_pages([1, 11], window) == [10, 20]
    assert agy_pdf.map_pages([], window) == []
    assert agy_pdf.map_pages([0], window) is None
    assert agy_pdf.map_pages([12], window) is None


def test_page_window_resolves_defaults_and_rejects_bad_ranges(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "ten.pdf"
    make_pdf(pdf, 10)

    assert agy_pdf.page_window(pdf, None, None) == PageWindow(1, 10, 10)
    assert agy_pdf.page_window(pdf, 3, None) == PageWindow(3, 10, 10)
    for first, last in [(0, 5), (4, 3), (3, 11)]:
        with pytest.raises(AgyUnavailableError):
            agy_pdf.page_window(pdf, first, last)


@pytest.mark.parametrize("verdict", [Verdict.CONFIRMED, Verdict.REFUTED])
def test_decided_verdict_without_page_is_invalid_citation_unit(
    verdict: Verdict,
) -> None:
    uncited = ClaimVerdict(id=1, verdict=verdict, evidence="evidence 1")

    bucket, line = agy_reports.place_claim(
        1, "Claim one", [uncited], PageWindow(1, 10, 10)
    )

    assert bucket == Bucket.INVALID_CITATION
    assert line == '#1 Claim one — no page cited: "evidence 1"'


def test_uncertain_verdict_without_page_stays_uncertain_unit() -> None:
    unsure = ClaimVerdict(id=1, verdict=Verdict.UNCERTAIN, evidence="vague")

    bucket, line = agy_reports.place_claim(
        1, "Claim one", [unsure], PageWindow(1, 10, 10)
    )

    assert bucket == Bucket.UNCERTAIN
    assert line == '#1 Claim one — PDF p. none: "vague"'


@pytest.mark.usefixtures("fake_agy")
def test_datasheet_confirmed_without_page_invalid_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 3)
    monkeypatch.setenv(
        "AGY_FAKE_STRUCTURED",
        datasheet_claims(
            (1, "confirmed", []), (2, "refuted", []), (3, "uncertain", [])
        ),
    )

    result = agy_worker.agy_datasheet_check(
        pdf_path=str(pdf), claims=["One", "Two", "Three"]
    )

    assert (
        "INVALID CITATION\n"
        '#1 One — no page cited: "evidence 1"\n'
        '#2 Two — no page cited: "evidence 2"'
    ) in result
    assert 'UNCERTAIN\n#3 Three — PDF p. none: "evidence 3"' in result
    assert "CONFIRMED\n(none)" in result
    assert "REFUTED\n(none)" in result


@pytest.mark.usefixtures("fake_agy")
def test_datasheet_page_offset_mapping(
    fake_agy: FakeAgy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 10)
    monkeypatch.setenv(
        "AGY_FAKE_STRUCTURED", datasheet_claims((1, "confirmed", [1, 3]))
    )

    result = agy_worker.agy_datasheet_check(
        pdf_path=str(pdf),
        claims=["Claim one"],
        first_page=4,
        last_page=6,
    )

    assert fake_agy.invocation().pdf_pages == 3
    assert result.startswith(
        "Argon datasheet check completed (model=gemini-4-argon-high, "
        "pdf=spec.pdf, pages=4-6, workspace=clean)."
    )
    assert '#1 Claim one — PDF p. 4, 6: "evidence 1"' in result


@pytest.mark.usefixtures("fake_agy")
def test_datasheet_page_out_of_range_invalid_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 10)
    monkeypatch.setenv(
        "AGY_FAKE_STRUCTURED", datasheet_claims((1, "confirmed", [4]))
    )

    result = agy_worker.agy_datasheet_check(
        pdf_path=str(pdf),
        claims=["Claim one"],
        first_page=4,
        last_page=6,
    )

    assert (
        "INVALID CITATION\n#1 Claim one — cited PDF p. 4 but only 3" in result
    )
    assert "CONFIRMED\n(none)" in result


@pytest.mark.usefixtures("fake_agy")
def test_datasheet_missing_verdict_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 3)
    monkeypatch.setenv(
        "AGY_FAKE_STRUCTURED",
        datasheet_claims(
            (1, "confirmed", [1]),
            (3, "refuted", [2]),
            (3, "confirmed", [2]),
            (9, "confirmed", [1]),
        ),
    )

    result = agy_worker.agy_datasheet_check(
        pdf_path=str(pdf), claims=["One", "Two", "Three"]
    )

    assert (
        "MISSING VERDICT\n#2 Two — no verdict returned\n"
        "#3 Three — conflicting verdicts\n"
        "#9 — not a claim id, ignored"
    ) in result


def test_datasheet_missing_or_non_pdf_input(
    fake_agy: FakeAgy, tmp_path: Path
) -> None:
    text_file = tmp_path / "notes.pdf"
    text_file.write_text("not really a pdf")

    missing = agy_worker.agy_datasheet_check(
        pdf_path=str(tmp_path / "gone.pdf"), claims=["x"]
    )
    wrong = agy_worker.agy_datasheet_check(
        pdf_path=str(text_file), claims=["x"]
    )

    assert missing.startswith("AGY-UNAVAILABLE: ")
    assert "does not exist" in missing
    assert wrong.startswith("AGY-UNAVAILABLE: ")
    assert "not a PDF" in wrong
    assert not fake_agy.ran()


def test_nul_in_pdf_path_unavailable(fake_agy: FakeAgy) -> None:
    result = agy_worker.agy_datasheet_check(
        pdf_path="spec\0.pdf", claims=["x"]
    )

    assert result.startswith("AGY-UNAVAILABLE: ")
    assert not fake_agy.ran()


def test_global_git_ignore_rules_do_not_hide_the_document(
    fake_agy: FakeAgy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "xdg"
    (config / "git").mkdir(parents=True)
    (config / "git" / "ignore").write_text("*.pdf\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 3)
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(DATASHEET_STRUCTURED))

    result = agy_worker.agy_datasheet_check(
        pdf_path=str(pdf), claims=DATASHEET_CLAIMS
    )

    assert result.startswith("Argon datasheet check completed")
    assert "workspace=clean" in result
    assert "document.pdf" in fake_agy.invocation().files


def test_unknown_user_home_in_pdf_path_unavailable(fake_agy: FakeAgy) -> None:
    result = agy_worker.agy_datasheet_check(
        pdf_path="~no-such-user-4711/spec.pdf", claims=["x"]
    )

    assert result.startswith("AGY-UNAVAILABLE: invalid argument: ")
    assert not fake_agy.ran()


def test_datasheet_prompt_forbids_commands_right_after_the_document(
    fake_agy: FakeAgy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 3)
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(DATASHEET_STRUCTURED))

    agy_worker.agy_datasheet_check(pdf_path=str(pdf), claims=DATASHEET_CLAIMS)

    assert (
        fake_agy.invocation()
        .argv[1]
        .startswith(
            "@document.pdf\n\nUse only the attached document; "
            "never run commands and never write files.\n\n"
        )
    )


def test_datasheet_prompt_attaches_document_with_schema(
    fake_agy: FakeAgy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 10)
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(DATASHEET_STRUCTURED))

    agy_worker.agy_datasheet_check(pdf_path=str(pdf), claims=DATASHEET_CLAIMS)

    invocation = fake_agy.invocation()
    argv = invocation.argv
    assert argv[1].startswith("@document.pdf\n")
    assert "1. Reset value of CTRL is 0x00" in argv[1]
    assert "--json-schema" in argv
    assert "document.pdf" in invocation.files
    assert invocation.pdf_pages == 10


def test_datasheet_schema_on_argv_validates_a_sample_output(
    fake_agy: FakeAgy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "spec.pdf"
    make_pdf(pdf, 10)
    monkeypatch.setenv("AGY_FAKE_STRUCTURED", json.dumps(DATASHEET_STRUCTURED))
    agy_worker.agy_datasheet_check(pdf_path=str(pdf), claims=DATASHEET_CLAIMS)
    argv = fake_agy.invocation().argv
    schema = json.loads(argv[argv.index("--json-schema") + 1])

    jsonschema.validate(DATASHEET_STRUCTURED, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"claims": [{"id": 1, "verdict": "maybe"}]}, schema
        )
