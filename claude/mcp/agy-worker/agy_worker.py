from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from agy_errors import AgyUnavailableError, fail
from agy_pdf import page_window, pdf_workspace, validate_pdf
from agy_prompts import (
    DATASHEET_SCHEMA,
    EVIDENCE_PATH,
    FACTS_PATH,
    REVIEW_DIFF_PATH,
    STYLE_GUIDE_PATH,
    TEMPLATE_PATH,
    TRANSLATE_SCHEMA,
    WriteKind,
    code_review_prompt,
    datasheet_prompt,
    debug_prompt,
    plan_prompt,
    translate_prompt,
    write_prompt,
)
from agy_remotes import require_allowlisted
from agy_reports import (
    DatasheetOutput,
    TranslationOutput,
    datasheet_report,
    one_line,
    translation_report,
)
from agy_runner import (
    AgyJob,
    check_model,
    check_outcome,
    check_prompt_size,
    run_agy,
    run_job,
    stderr_tail,
)
from agy_workspace import (
    TEXT_ENCODING,
    build_diff,
    empty_workspace,
    path_from_env,
    resolve_repo_root,
    snapshot_workspace,
)
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ValidationError

mcp = FastMCP("agy-worker")

DEFAULT_ARGON_MODEL = "gemini-4-argon-high"
DEFAULT_FLASH_MODEL = "gemini-3.8-flash-medium"
ARGON_MARKER = "argon"
PLAN_TIMEOUT_SECONDS = 1800
DATASHEET_TIMEOUT_SECONDS = 1800
TRANSLATE_TIMEOUT_SECONDS = 600
MODELS_TIMEOUT_SECONDS = 60
CODE_REVIEW_TIMEOUT_SECONDS = 1800
WRITE_TIMEOUT_SECONDS = 600
DEBUG_TIMEOUT_SECONDS = 1800
STYLE_GUIDE_ENV = "AGY_STYLE_GUIDE"
DEFAULT_STYLE_GUIDE_PARTS = (
    "claude-skills",
    "_shared",
    "references",
    "jezyk-acme.md",
)


@dataclass(frozen=True, slots=True)
class CodeReviewRequest:
    """Arguments of agy_code_review."""

    diff_base: str
    review_focus: str
    project_path: str
    acceptance_criteria: str
    extra_context: str
    model: str


@dataclass(frozen=True, slots=True)
class WriteRequest:
    """Arguments of agy_write."""

    project_path: str
    kind: str
    facts: str
    template: str
    language: str
    model: str


@dataclass(frozen=True, slots=True)
class DebugRequest:
    """Arguments of agy_debug_consult."""

    problem: str
    evidence: str
    project_path: str
    model: str


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Arguments of agy_plan_review."""

    what_changed: str
    review_focus: str
    project_path: str
    acceptance_criteria: str
    extra_context: str
    model: str


@dataclass(frozen=True, slots=True)
class DatasheetRequest:
    """Arguments of agy_datasheet_check."""

    pdf_path: str
    claims: list[str]
    context: str
    first_page: int | None
    last_page: int | None
    model: str


@dataclass(frozen=True, slots=True)
class TranslateRequest:
    """Arguments of agy_translate."""

    project_path: str
    entries: dict[str, str]
    source_lang: str
    target_lang: str
    glossary: str
    context: str
    model: str


def guarded(action: Callable[[], str]) -> str:
    """Run a tool body and turn its failures into AGY-UNAVAILABLE."""
    try:
        return action()
    except AgyUnavailableError as error:
        return error.render()
    except OSError as error:
        return AgyUnavailableError(f"system error: {error}").render()
    except (ValueError, RuntimeError) as error:
        return AgyUnavailableError(f"invalid argument: {error}").render()


def structured[ModelT: BaseModel](
    model_type: type[ModelT], payload: object
) -> ModelT:
    """Validate the structured output of agy against a model."""
    try:
        return model_type.model_validate(payload)
    except ValidationError as error:
        fail(f"schema output invalid: {error}")


def reject_argon(tool: str, model: str) -> None:
    """Refuse an Argon model for a tool that is Flash only."""
    if ARGON_MARKER in model.lower():
        fail(
            f"{tool} never uses Argon models; "
            f"pass a Flash model instead of {model}"
        )


def parse_write_kind(kind: str) -> WriteKind:
    """Return the write kind a name stands for."""
    try:
        return WriteKind(kind)
    except ValueError:
        allowed = ", ".join(WriteKind)
        fail(f"unknown kind {kind!r}; allowed kinds: {allowed}")


def style_guide_content() -> bytes | None:
    """Return the style guide text, or None when the file is absent."""
    default = Path.home().joinpath(*DEFAULT_STYLE_GUIDE_PARTS)
    path = path_from_env(STYLE_GUIDE_ENV, default)
    return path.read_bytes() if path.is_file() else None


def write_attachments(request: WriteRequest) -> dict[str, bytes]:
    """Collect the files agy_write attaches to the workspace."""
    attachments = {FACTS_PATH: request.facts.encode(TEXT_ENCODING)}
    if request.template.strip():
        attachments[TEMPLATE_PATH] = request.template.encode(TEXT_ENCODING)
    style_guide = style_guide_content()
    if style_guide is not None:
        attachments[STYLE_GUIDE_PATH] = style_guide
    return attachments


def run_snapshot_job(
    root: Path,
    prompt: str,
    model: str,
    timeout_seconds: int,
    attachments: Mapping[str, bytes] | None = None,
) -> str:
    """Run a prompt against a snapshot of the repository."""
    check_prompt_size(prompt)
    job = AgyJob(prompt, model, timeout_seconds, None)
    envelope = run_job(lambda: snapshot_workspace(root, attachments), job)
    return (envelope.response or "").strip()


def review_plan(request: PlanRequest) -> str:
    """Run the adversarial plan review and format its report."""
    check_model(request.model)
    root = resolve_repo_root(request.project_path)
    require_allowlisted(root)
    prompt = plan_prompt(
        request.what_changed,
        request.review_focus,
        request.acceptance_criteria,
        request.extra_context,
    )
    findings = run_snapshot_job(
        root, prompt, request.model, PLAN_TIMEOUT_SECONDS
    )
    header = (
        f"Gemini review completed (mode=plan, model={request.model}, "
        "workspace=clean)."
    )
    return f"{header}\n\nFindings:\n{findings}"


def review_code(request: CodeReviewRequest) -> str:
    """Run the bug-only code review and format its report."""
    check_model(request.model)
    root = resolve_repo_root(request.project_path)
    require_allowlisted(root)
    diff = build_diff(root, request.diff_base)
    if not diff.strip():
        fail(f"the diff against {request.diff_base!r} is empty")
    prompt = code_review_prompt(
        request.review_focus,
        request.acceptance_criteria,
        request.extra_context,
    )
    findings = run_snapshot_job(
        root,
        prompt,
        request.model,
        CODE_REVIEW_TIMEOUT_SECONDS,
        {REVIEW_DIFF_PATH: diff.encode(TEXT_ENCODING)},
    )
    header = (
        f"Gemini review completed (mode=code, model={request.model}, "
        "workspace=clean)."
    )
    return f"{header}\n\nFindings:\n{findings}"


def write_text(request: WriteRequest) -> str:
    """Write a text from facts and return it under a status header."""
    reject_argon("agy_write", request.model)
    check_model(request.model)
    kind = parse_write_kind(request.kind)
    root = resolve_repo_root(request.project_path)
    require_allowlisted(root)
    attachments = write_attachments(request)
    prompt = write_prompt(
        kind,
        request.language,
        has_template=TEMPLATE_PATH in attachments,
        has_style_guide=STYLE_GUIDE_PATH in attachments,
    )
    text = run_snapshot_job(
        root, prompt, request.model, WRITE_TIMEOUT_SECONDS, attachments
    )
    header = (
        f"Gemini text completed (model={request.model}, "
        f"kind={kind}, workspace=clean)."
    )
    return f"{header}\n\n{text}"


def consult_debug(request: DebugRequest) -> str:
    """Analyse a problem read-only and return ranked hypotheses."""
    check_model(request.model)
    root = resolve_repo_root(request.project_path)
    require_allowlisted(root)
    prompt = debug_prompt(request.problem)
    findings = run_snapshot_job(
        root,
        prompt,
        request.model,
        DEBUG_TIMEOUT_SECONDS,
        {EVIDENCE_PATH: request.evidence.encode(TEXT_ENCODING)},
    )
    header = (
        f"Argon debug consult completed (model={request.model}, "
        "workspace=clean)."
    )
    return f"{header}\n\nFindings:\n{findings}"


def check_datasheet(request: DatasheetRequest) -> str:
    """Check claims against a PDF and format the verdicts."""
    check_model(request.model)
    claims = [one_line(claim) for claim in request.claims if claim.strip()]
    if not claims:
        fail("claims is empty")
    pdf = validate_pdf(request.pdf_path)
    window = page_window(pdf, request.first_page, request.last_page)
    prompt = datasheet_prompt(claims, request.context)
    check_prompt_size(prompt)
    job = AgyJob(
        prompt, request.model, DATASHEET_TIMEOUT_SECONDS, DATASHEET_SCHEMA
    )
    envelope = run_job(lambda: pdf_workspace(pdf, window), job)
    output = structured(DatasheetOutput, envelope.structured_output)
    header = (
        f"Argon datasheet check completed (model={request.model}, "
        f"pdf={pdf.name}, pages={window.label}, workspace=clean)."
    )
    return datasheet_report(header, claims, output, window)


def translate_entries(request: TranslateRequest) -> str:
    """Translate the entries and return the validated JSON report."""
    reject_argon("agy_translate", request.model)
    check_model(request.model)
    if not request.entries:
        fail("entries is empty")
    require_allowlisted(resolve_repo_root(request.project_path))
    prompt = translate_prompt(
        request.entries,
        request.source_lang,
        request.target_lang,
        request.glossary,
        request.context,
    )
    check_prompt_size(prompt)
    job = AgyJob(
        prompt, request.model, TRANSLATE_TIMEOUT_SECONDS, TRANSLATE_SCHEMA
    )
    envelope = run_job(empty_workspace, job)
    output = structured(TranslationOutput, envelope.structured_output)
    report = translation_report(request.model, request.entries, output)
    return report.model_dump_json(indent=2)


def list_models() -> str:
    """Return the model listing printed by agy."""
    with empty_workspace() as workspace:
        run = run_agy(workspace.path, ["models"], MODELS_TIMEOUT_SECONDS)
    check_outcome(run, MODELS_TIMEOUT_SECONDS)
    listing = run.stdout.strip()
    if run.returncode or not listing:
        fail(
            f"agy models failed (exit code {run.returncode}): "
            f"{stderr_tail(run.stderr)}"
        )
    return listing


@mcp.tool()
def agy_models() -> str:
    """List the models agy offers; fails when agy is not logged in."""
    return guarded(list_models)


@mcp.tool()
def agy_plan_review(  # noqa: PLR0913
    what_changed: str,
    *,
    review_focus: str,
    project_path: str,
    acceptance_criteria: str = "",
    extra_context: str = "",
    model: str = DEFAULT_FLASH_MODEL,
) -> str:
    """Adversarial plan review by Gemini in a sandboxed worktree."""
    request = PlanRequest(
        what_changed,
        review_focus,
        project_path,
        acceptance_criteria,
        extra_context,
        model,
    )
    return guarded(lambda: review_plan(request))


@mcp.tool()
def agy_datasheet_check(  # noqa: PLR0913
    pdf_path: str,
    *,
    claims: list[str],
    context: str = "",
    first_page: int | None = None,
    last_page: int | None = None,
    model: str = DEFAULT_ARGON_MODEL,
) -> str:
    """Check numbered claims against a PDF datasheet with Gemini Argon."""
    request = DatasheetRequest(
        pdf_path, claims, context, first_page, last_page, model
    )
    return guarded(lambda: check_datasheet(request))


@mcp.tool()
def agy_translate(  # noqa: PLR0913
    project_path: str,
    *,
    entries: dict[str, str],
    source_lang: str,
    target_lang: str,
    glossary: str = "",
    context: str = "",
    model: str = DEFAULT_FLASH_MODEL,
) -> str:
    """Translate UI strings with Gemini Flash and validate placeholders."""
    request = TranslateRequest(
        project_path,
        entries,
        source_lang,
        target_lang,
        glossary,
        context,
        model,
    )
    return guarded(lambda: translate_entries(request))


@mcp.tool()
def agy_code_review(  # noqa: PLR0913
    *,
    diff_base: str,
    review_focus: str,
    project_path: str,
    acceptance_criteria: str = "",
    extra_context: str = "",
    model: str = DEFAULT_FLASH_MODEL,
) -> str:
    """Bug-only code review of a diff by Gemini Flash in a sandbox."""
    request = CodeReviewRequest(
        diff_base,
        review_focus,
        project_path,
        acceptance_criteria,
        extra_context,
        model,
    )
    return guarded(lambda: review_code(request))


@mcp.tool()
def agy_write(  # noqa: PLR0913
    *,
    project_path: str,
    kind: WriteKind,
    facts: str,
    template: str = "",
    language: str = "pl",
    model: str = DEFAULT_FLASH_MODEL,
) -> str:
    """Write a PR, Jira or UI text from given facts with Gemini Flash."""
    request = WriteRequest(
        project_path, kind, facts, template, language, model
    )
    return guarded(lambda: write_text(request))


@mcp.tool()
def agy_debug_consult(
    *,
    problem: str,
    evidence: str,
    project_path: str,
    model: str = DEFAULT_ARGON_MODEL,
) -> str:
    """Read-only root-cause consult by Gemini Argon, no fixes."""
    request = DebugRequest(problem, evidence, project_path, model)
    return guarded(lambda: consult_debug(request))


if __name__ == "__main__":
    mcp.run()
