import json
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum, auto
from typing import NamedTuple

from agy_context import (
    MAX_CALL_SITES,
    MAX_CALL_SITES_BYTES,
    MAX_FILE_LIST_BYTES,
    MAX_SITES_PER_NAME,
    byte_size,
    fit_lines,
)
from agy_reports import DatasheetOutput, TranslationOutput

SECTION_SEPARATOR = "\n\n"
CALL_SITES_LABEL = "Call sites in unchanged files"
FILES_LABEL = "Repository files"
CALL_SITES_RULE = "Check every listed call site against the changed contract."
CALL_SITES_HEADER = (
    f"{CALL_SITES_LABEL} (at most {MAX_SITES_PER_NAME} per name, "
    f"{MAX_CALL_SITES} in total). {CALL_SITES_RULE}"
)
FILES_HEADER = f"{FILES_LABEL}:"
NO_GUESSING_RULE = (
    "Never guess a file name: read a path only when it appears in the "
    "repository file list, the diff, the call sites, or an import or "
    "include of a file you have read."
)

DOCUMENT_REFERENCE = "@document.pdf"
REVIEW_DIFF_PATH = ".agy/review.diff"
EVIDENCE_PATH = ".agy/evidence.txt"
READ_ONLY_PREAMBLE = (
    "You may read files in the working directory, but you must never run "
    "commands and never create, edit or delete files."
)
NO_TOOLS_PREAMBLE = (
    "You have no tools: never run commands, never read or write files. "
    "Produce the answer in a single reply from this prompt alone."
)
READ_BATCH_RULE = (
    "Read files in as few turns as possible: request every file you need "
    "in one turn as parallel read_file calls, and read a long file in one "
    "turn as parallel read_file calls for consecutive line ranges. Never "
    "read .git or anything outside the working directory."
)
DATASHEET_NO_COMMANDS = (
    "Use only the attached document; never run commands and never write files."
)
PLAN_READ_ONLY_NOTE = (
    "You may read files in the working directory, "
    "but you must never run commands."
)

PLAN_INSTRUCTIONS = """\
You are an independent, adversarial reviewer of an engineering plan that has
not been implemented yet. The repository as it stands today is checked out in
your working directory. Treat it as read-only: do not create, edit or delete
files and do not run commands.
Whenever the plan states something about the code, open the code and check
the statement instead of trusting it.
Look for: steps that contradict each other, dependencies the plan overlooked,
an order of rollout that leaves the system broken halfway, risks to stored
data and wire protocols (migrations, compatibility, irreversible steps,
backfills), designs that cannot work under the stated constraints, and
acceptance criteria that are missing, vague or impossible to check.
Report problems only. Do not write a replacement plan, do not propose another
architecture and do not list substitute steps. For every finding state the
plan step, what is wrong with it and what breaks if the plan is carried out
as written, then stop: choosing the remedy belongs to the plan's author."""

PLAN_OUTPUT_FORMAT = """\
Answer with these sections, in exactly this order:

BLOCKER
IMPORTANT
OPTIONAL
  Each entry: one sentence naming the defect, the plan step or file:line, the
  conditions that trigger it, what happens when it triggers, and whether you
  reproduced it (yes/no). BLOCKER means the plan must not start before this
  is fixed. IMPORTANT means fix it now unless it is a deliberate trade-off.
  OPTIONAL means worth knowing but not required. Leave a section empty rather
  than padding it.

Checked and clean
  What you verified and found correct, so the reader knows your coverage.

Could not verify
  What you were unable to check and why. This is not the same as clean, so
  never move an item from here into "Checked and clean".

PASS
  Write PASS alone on the last line if, and only if, there is neither a
  BLOCKER nor an IMPORTANT entry."""

DATASHEET_INSTRUCTIONS = """\
The attached PDF is the only source of truth. For every numbered claim below
decide whether the document confirms it, refutes it, or leaves it uncertain.
Never guess: if the document does not settle the claim, answer uncertain.
Give pdf_pages as the physical 1-based position of the page inside the
attached file, and printed_pages as the labels printed on those pages. Quote
the deciding evidence in evidence, and for a refuted claim state the correct
fact in correction. Return exactly one verdict for every claim id."""

TRANSLATE_INSTRUCTIONS = """\
You translate user interface strings. Translate every value of the JSON
object below from {source} to {target} and return one entry per input key,
using the key unchanged. Keep every placeholder byte for byte: {{{{name}}}},
{{name}}, %s, %d, HTML-like tags and $t(...) references must appear in the
translation exactly as often as in the source. Do not add, drop or rename
keys, and do not explain anything."""

CODE_REVIEW_INSTRUCTIONS = """\
The change under review is {diff}. Review it for bugs
only. A bug is wrong behaviour, a crash, data
loss or corruption, a security hole, a broken contract with a caller, or a
bug fix without a test that fails without it. Never report style, naming,
comments, formatting, refactors, alternative designs, suggestions phrased
as "could" or "consider", or performance unless it is a defect. Read only
the changed code and what it directly calls or is called by."""

INLINE_DIFF_SOURCE = "the unified diff below"
ATTACHED_DIFF_SOURCE = "the unified diff in {path}"

CODE_REVIEW_OUTPUT_FORMAT = """\
Output only these lines, with no preamble, no summary and no code:
[BLOCKER] or [IMPORTANT] file:line — the bug in one sentence — \
trigger -> effect
When something material could not be checked, add one line:
Not checked: <what>
The last line is PASS when there is no bug, otherwise FAIL."""

WRITE_INSTRUCTIONS = """\
Write the ready-to-publish text of a {kind} in the language {language}.
Use only the facts below; never invent a fact. Where a fact is missing,
write [BRAK: <what is missing>] in its place. Output the text itself and
nothing around it."""

WRITE_NO_WRAPPER_RULE = (
    "Write no AI header and no AI footer, whatever the style guide says "
    "— the footer is added later."
)

DEBUG_INSTRUCTIONS = """\
Find the root cause of the problem below; the evidence is in {evidence}.
Give ranked hypotheses; for each one name the file:line, the evidence for
and against it, and the cheapest experiment that confirms or kills it.
Propose no fixes."""

DATASHEET_SCHEMA = json.dumps(DatasheetOutput.model_json_schema())
TRANSLATE_SCHEMA = json.dumps(TranslationOutput.model_json_schema())


class WriteKind(StrEnum):
    """The kinds of text agy_write can produce."""

    PR_DESCRIPTION = auto()
    JIRA_COMMENT = auto()
    JIRA_DESCRIPTION = auto()
    UI_MESSAGE = auto()
    REVIEW_COMMENT = auto()

    @property
    def label(self) -> str:
        """Return the kind as plain words."""
        return self.value.replace("_", " ")


def reference(path: str) -> str:
    """Return the prompt reference to an attached file."""
    return f"@{path}"


def labelled(sections: list[str], label: str, text: str) -> None:
    """Append a labelled section when the text is not blank."""
    if text.strip():
        sections.append(f"{label}:\n{text.strip()}")


def plan_prompt(
    what_changed: str,
    review_focus: str,
    acceptance_criteria: str,
    extra_context: str,
    *,
    files: str = "",
) -> str:
    """Compose the plan review prompt."""
    sections = [
        PLAN_READ_ONLY_NOTE,
        READ_BATCH_RULE,
        NO_GUESSING_RULE,
        PLAN_INSTRUCTIONS,
    ]
    labelled(sections, "What the plan changes", what_changed)
    labelled(sections, "Review focus", review_focus)
    labelled(sections, "Acceptance criteria", acceptance_criteria)
    labelled(sections, "Further context", extra_context)
    if files:
        sections.append(files)
    sections.append(PLAN_OUTPUT_FORMAT)
    return SECTION_SEPARATOR.join(sections)


def code_review_prompt(
    review_focus: str,
    acceptance_criteria: str,
    extra_context: str,
    *,
    diff: str | None,
    call_sites: str = "",
    files: str = "",
) -> str:
    """Compose the code review prompt, inlining the diff when given."""
    diff_source = (
        INLINE_DIFF_SOURCE
        if diff is not None
        else ATTACHED_DIFF_SOURCE.format(path=reference(REVIEW_DIFF_PATH))
    )
    sections = [
        READ_ONLY_PREAMBLE,
        READ_BATCH_RULE,
        NO_GUESSING_RULE,
        CODE_REVIEW_INSTRUCTIONS.format(diff=diff_source),
    ]
    labelled(sections, "Review focus", review_focus)
    labelled(sections, "Acceptance criteria", acceptance_criteria)
    labelled(sections, "Further context", extra_context)
    context = [section for section in (call_sites, files) if section]
    if diff is None:
        sections.extend([*context, CODE_REVIEW_OUTPUT_FORMAT])
    else:
        sections.extend(
            [CODE_REVIEW_OUTPUT_FORMAT, f"Diff:\n{diff}", *context]
        )
    return SECTION_SEPARATOR.join(sections)


def write_prompt(
    kind: WriteKind,
    language: str,
    facts: str,
    template: str,
    style_guide: str,
) -> str:
    """Compose the writing prompt."""
    sections = [
        NO_TOOLS_PREAMBLE,
        WRITE_INSTRUCTIONS.format(kind=kind.label, language=language),
    ]
    labelled(sections, "Template — follow its structure", template)
    labelled(sections, "Style guide — follow it", style_guide)
    sections.append(WRITE_NO_WRAPPER_RULE)
    labelled(sections, "Facts", facts)
    return "\n\n".join(sections)


def debug_prompt(problem: str, *, files: str = "") -> str:
    """Compose the debug consult prompt."""
    sections = [
        READ_ONLY_PREAMBLE,
        READ_BATCH_RULE,
        NO_GUESSING_RULE,
        DEBUG_INSTRUCTIONS.format(evidence=reference(EVIDENCE_PATH)),
    ]
    labelled(sections, "Problem", problem)
    if files:
        sections.append(files)
    return SECTION_SEPARATOR.join(sections)


class FittedReview(NamedTuple):
    """A code review prompt and whether it carries the diff inline."""

    prompt: str
    diff_inline: bool


def more_files_line(count: int) -> str:
    """Mark how many files the list leaves out."""
    return f"... {count} more files not listed"


def more_sites_line(count: int) -> str:
    """Mark how many call site lines the section leaves out."""
    return f"... {count} more call site lines not listed"


def room_for_section(prompt: str, limit: int, cap: int) -> int:
    """Return the bytes a new section may take under the prompt limit."""
    room = limit - byte_size(prompt) - len(SECTION_SEPARATOR)
    return min(cap, room)


def files_section(
    build: Callable[[str], str], paths: Sequence[str], limit: int
) -> str:
    """Fit the repository file list into what the prompt leaves."""
    budget = room_for_section(build(""), limit, MAX_FILE_LIST_BYTES)
    return fit_lines(FILES_HEADER, paths, budget, more_files_line)


def fit_listed_prompt(
    build: Callable[[str], str], paths: Sequence[str], limit: int
) -> str:
    """Build a prompt with as much of the file list as fits the limit."""
    return build(files_section(build, paths, limit))


def fit_code_review(
    focus: tuple[str, str, str],
    diff: str,
    call_site_lines: Sequence[str],
    paths: Sequence[str],
    limit: int,
) -> FittedReview:
    """Fit call sites, the diff and the file list under the limit."""
    attached = code_review_prompt(*focus, diff=None)
    budget = room_for_section(attached, limit, MAX_CALL_SITES_BYTES)
    sites = fit_lines(
        CALL_SITES_HEADER, call_site_lines, budget, more_sites_line
    )
    inline = code_review_prompt(*focus, diff=diff, call_sites=sites)
    diff_inline = byte_size(inline) <= limit

    def build(files: str) -> str:
        """Compose the review prompt around a file list section."""
        return code_review_prompt(
            *focus,
            diff=diff if diff_inline else None,
            call_sites=sites,
            files=files,
        )

    return FittedReview(fit_listed_prompt(build, paths, limit), diff_inline)


def datasheet_prompt(claims: Sequence[str], context: str) -> str:
    """Compose the datasheet check prompt."""
    numbered = "\n".join(
        f"{number}. {claim}" for number, claim in enumerate(claims, start=1)
    )
    sections = [
        DOCUMENT_REFERENCE,
        DATASHEET_NO_COMMANDS,
        DATASHEET_INSTRUCTIONS,
    ]
    labelled(sections, "Context", context)
    sections.append(f"Claims:\n{numbered}")
    return "\n\n".join(sections)


def translate_prompt(
    entries: Mapping[str, str],
    source_lang: str,
    target_lang: str,
    glossary: str,
    context: str,
) -> str:
    """Compose the translation prompt."""
    sections = [
        NO_TOOLS_PREAMBLE,
        TRANSLATE_INSTRUCTIONS.format(source=source_lang, target=target_lang),
    ]
    labelled(sections, "Glossary", glossary)
    labelled(sections, "Context", context)
    strings = json.dumps(entries, ensure_ascii=False, indent=2)
    sections.append(f"Strings:\n{strings}")
    return "\n\n".join(sections)
