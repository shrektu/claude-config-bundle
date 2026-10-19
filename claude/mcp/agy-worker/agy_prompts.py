import json
from collections.abc import Mapping, Sequence
from enum import StrEnum, auto

from agy_reports import DatasheetOutput, TranslationOutput

DOCUMENT_REFERENCE = "@document.pdf"
REVIEW_DIFF_PATH = ".agy/review.diff"
FACTS_PATH = ".agy/facts.md"
TEMPLATE_PATH = ".agy/template.md"
STYLE_GUIDE_PATH = ".agy/style-guide.md"
EVIDENCE_PATH = ".agy/evidence.txt"
READ_ONLY_PREAMBLE = (
    "You may read files in the working directory, but you must never run "
    "commands and never create, edit or delete files."
)
NO_TOOLS_PREAMBLE = (
    "You have no tools: never run commands, never read or write files. "
    "Produce the answer in a single reply from this prompt alone."
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
The change under review is the unified diff in {diff}. Review it for bugs
only. A bug is wrong behaviour, a crash, data
loss or corruption, a security hole, a broken contract with a caller, or a
bug fix without a test that fails without it. Never report style, naming,
comments, formatting, refactors, alternative designs, suggestions phrased
as "could" or "consider", or performance unless it is a defect. Read only
the changed code and what it directly calls or is called by."""

CODE_REVIEW_OUTPUT_FORMAT = """\
Output only these lines, with no preamble, no summary and no code:
[BLOCKER] or [IMPORTANT] file:line — the bug in one sentence — \
trigger -> effect
When something material could not be checked, add one line:
Not checked: <what>
The last line is PASS when there is no bug, otherwise FAIL."""

WRITE_INSTRUCTIONS = """\
Write the ready-to-publish text of a {kind} in the language {language}.
Use only the facts in {facts} and what the code in the working directory
shows; never invent a fact. Where a fact is missing, write [BRAK: <what is
missing>] in its place. Output the text itself and nothing around it."""

WRITE_NO_WRAPPER_RULE = (
    "Write no AI header and no AI footer, whatever the style guide says "
    "— the footer is added later."
)

WRITE_TEMPLATE_RULE = "Follow the structure of the template in {template}."
WRITE_STYLE_GUIDE_RULE = "Follow the style guide in {style_guide}."

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
) -> str:
    """Compose the plan review prompt."""
    sections = [PLAN_READ_ONLY_NOTE, PLAN_INSTRUCTIONS]
    labelled(sections, "What the plan changes", what_changed)
    labelled(sections, "Review focus", review_focus)
    labelled(sections, "Acceptance criteria", acceptance_criteria)
    labelled(sections, "Further context", extra_context)
    sections.append(PLAN_OUTPUT_FORMAT)
    return "\n\n".join(sections)


def code_review_prompt(
    review_focus: str, acceptance_criteria: str, extra_context: str
) -> str:
    """Compose the code review prompt."""
    sections = [
        READ_ONLY_PREAMBLE,
        CODE_REVIEW_INSTRUCTIONS.format(diff=reference(REVIEW_DIFF_PATH)),
    ]
    labelled(sections, "Review focus", review_focus)
    labelled(sections, "Acceptance criteria", acceptance_criteria)
    labelled(sections, "Further context", extra_context)
    sections.append(CODE_REVIEW_OUTPUT_FORMAT)
    return "\n\n".join(sections)


def write_prompt(
    kind: WriteKind,
    language: str,
    *,
    has_template: bool,
    has_style_guide: bool,
) -> str:
    """Compose the writing prompt."""
    sections = [
        READ_ONLY_PREAMBLE,
        WRITE_INSTRUCTIONS.format(
            kind=kind.label, language=language, facts=reference(FACTS_PATH)
        ),
    ]
    if has_template:
        sections.append(
            WRITE_TEMPLATE_RULE.format(template=reference(TEMPLATE_PATH))
        )
    if has_style_guide:
        sections.append(
            WRITE_STYLE_GUIDE_RULE.format(
                style_guide=reference(STYLE_GUIDE_PATH)
            )
        )
    sections.append(WRITE_NO_WRAPPER_RULE)
    return "\n\n".join(sections)


def debug_prompt(problem: str) -> str:
    """Compose the debug consult prompt."""
    sections = [
        READ_ONLY_PREAMBLE,
        DEBUG_INSTRUCTIONS.format(evidence=reference(EVIDENCE_PATH)),
    ]
    labelled(sections, "Problem", problem)
    return "\n\n".join(sections)


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
