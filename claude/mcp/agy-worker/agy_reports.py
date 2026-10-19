import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from enum import StrEnum, auto

from agy_pdf import PageWindow, map_pages
from pydantic import BaseModel, Field

PLACEHOLDER_PATTERN = re.compile(
    r"\{\{[^{}]+\}\}|\{[^{}]+\}|%[sd]"
    r"|</?[A-Za-z](?:[^<>\"']|\"[^\"]*\"|'[^']*')*>|\$t\((?:[^)\"']|\"[^\"]*\"|'[^']*')*\)"
)


class Verdict(StrEnum):
    """Verdict a datasheet claim can receive."""

    CONFIRMED = auto()
    REFUTED = auto()
    UNCERTAIN = auto()


class Bucket(StrEnum):
    """Section of the datasheet report a claim lands in."""

    REFUTED = "REFUTED"
    UNCERTAIN = "UNCERTAIN"
    INVALID_CITATION = "INVALID CITATION"
    MISSING_VERDICT = "MISSING VERDICT"
    CONFIRMED = "CONFIRMED"


VERDICT_BUCKETS = {
    Verdict.CONFIRMED: Bucket.CONFIRMED,
    Verdict.REFUTED: Bucket.REFUTED,
    Verdict.UNCERTAIN: Bucket.UNCERTAIN,
}


class ClaimVerdict(BaseModel):
    """One verdict returned for a datasheet claim."""

    id: int
    verdict: Verdict
    pdf_pages: list[int] = Field(default_factory=list)
    printed_pages: list[int | str] = Field(default_factory=list)
    evidence: str = ""
    correction: str = ""


class DatasheetOutput(BaseModel):
    """Structured output of the datasheet check."""

    claims: list[ClaimVerdict]


class TranslationOutput(BaseModel):
    """Structured output of the translation job."""

    translations: dict[str, str]


class Problem(BaseModel):
    """A defect found in a returned translation."""

    key: str
    problem: str


class TranslationReport(BaseModel):
    """What agy_translate returns as JSON text."""

    model: str
    translations: dict[str, str]
    problems: list[Problem]


def one_line(text: str) -> str:
    """Collapse all whitespace runs into single spaces."""
    return " ".join(text.split())


def join_values(values: Sequence[int | str]) -> str:
    """Join page numbers or labels with commas."""
    return ", ".join(str(value) for value in values)


def claim_line(
    number: int, claim: str, verdict: ClaimVerdict, pages: Sequence[int]
) -> str:
    """Format a claim with its cited pages and evidence."""
    printed = (
        f" (printed {join_values(verdict.printed_pages)})"
        if verdict.printed_pages
        else ""
    )
    correction = f" [→ {verdict.correction}]" if verdict.correction else ""
    return (
        f"#{number} {claim} — PDF p. {join_values(pages) or 'none'}{printed}: "
        f'"{one_line(verdict.evidence)}"{correction}'
    )


def invalid_citation_line(
    number: int, claim: str, verdict: ClaimVerdict, window: PageWindow
) -> str:
    """Format a claim whose cited pages lie outside the PDF sent."""
    return (
        f"#{number} {claim} — cited PDF p. {join_values(verdict.pdf_pages)} "
        f"but only {window.sent} pages were sent: "
        f'"{one_line(verdict.evidence)}"'
    )


def no_page_line(number: int, claim: str, verdict: ClaimVerdict) -> str:
    """Format a decided claim that cites no page."""
    return f'#{number} {claim} — no page cited: "{one_line(verdict.evidence)}"'


def place_claim(
    number: int,
    claim: str,
    entries: Sequence[ClaimVerdict],
    window: PageWindow,
) -> tuple[Bucket, str]:
    """Choose the bucket and the report line of one claim."""
    if len(entries) != 1:
        note = "no verdict returned" if not entries else "conflicting verdicts"
        return Bucket.MISSING_VERDICT, f"#{number} {claim} — {note}"
    verdict = entries[0]
    if not verdict.pdf_pages and verdict.verdict is not Verdict.UNCERTAIN:
        return Bucket.INVALID_CITATION, no_page_line(number, claim, verdict)
    pages = map_pages(verdict.pdf_pages, window)
    if pages is None:
        line = invalid_citation_line(number, claim, verdict, window)
        return Bucket.INVALID_CITATION, line
    return (
        VERDICT_BUCKETS[verdict.verdict],
        claim_line(number, claim, verdict, pages),
    )


def datasheet_report(
    header: str,
    claims: Sequence[str],
    output: DatasheetOutput,
    window: PageWindow,
) -> str:
    """Group the verdicts into buckets and format the report."""
    by_id: dict[int, list[ClaimVerdict]] = defaultdict(list)
    for verdict in output.claims:
        by_id[verdict.id].append(verdict)
    buckets: dict[Bucket, list[str]] = {bucket: [] for bucket in Bucket}
    for number, claim in enumerate(claims, start=1):
        bucket, line = place_claim(
            number, claim, by_id.pop(number, []), window
        )
        buckets[bucket].append(line)
    buckets[Bucket.MISSING_VERDICT] += [
        f"#{unknown} — not a claim id, ignored" for unknown in by_id
    ]
    blocks = [
        f"{bucket}\n" + ("\n".join(lines) if lines else "(none)")
        for bucket, lines in buckets.items()
    ]
    return "\n\n".join([header, *blocks])


def placeholders(text: str) -> Counter[str]:
    """Count the placeholders and tags in a UI string."""
    return Counter(PLACEHOLDER_PATTERN.findall(text))


def placeholder_problem(source: str, translated: str) -> str | None:
    """Describe a placeholder mismatch, or None if they agree."""
    expected, actual = placeholders(source), placeholders(translated)
    if expected == actual:
        return None
    return (
        f"placeholders differ: expected {sorted(expected.elements())}, "
        f"got {sorted(actual.elements())}"
    )


def translation_report(
    model: str, entries: Mapping[str, str], output: TranslationOutput
) -> TranslationReport:
    """Validate returned translations against the input entries."""
    returned = output.translations
    problems: list[Problem] = []
    for key, source in entries.items():
        if key not in returned:
            problems.append(Problem(key=key, problem="missing"))
            continue
        mismatch = placeholder_problem(source, returned[key])
        if mismatch:
            problems.append(Problem(key=key, problem=mismatch))
    problems += [
        Problem(key=key, problem="not in the input")
        for key in returned
        if key not in entries
    ]
    translations = {key: returned[key] for key in entries if key in returned}
    return TranslationReport(
        model=model, translations=translations, problems=problems
    )
