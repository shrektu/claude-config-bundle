import contextlib
import re
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NamedTuple

from agy_errors import fail
from agy_workspace import (
    Workspace,
    commit_workspace,
    create_workspace,
    run_tool,
    scratch_dir,
)

DOCUMENT_NAME = "document.pdf"
PDF_MAGIC = b"%PDF-"
PDF_PAGES_PATTERN = re.compile(r"^Pages:\s+(\d+)", re.MULTILINE)
PART_NAME_TEMPLATE = "p-%d.pdf"
PARTS_NAME = "parts"


class PageWindow(NamedTuple):
    """Pages of the source PDF handed to agy."""

    first: int
    last: int
    total: int

    @property
    def sent(self) -> int:
        """Return how many pages the attached PDF has."""
        return self.last - self.first + 1

    @property
    def label(self) -> str:
        """Return the page range as shown in the report."""
        if self.sent == self.total:
            return "all"
        return f"{self.first}-{self.last}"


def validate_pdf(pdf_path: str) -> Path:
    """Return the resolved PDF path or explain why it cannot be used."""
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        fail(f"PDF {path} does not exist")
    with path.open("rb") as handle:
        magic = handle.read(len(PDF_MAGIC))
    if magic != PDF_MAGIC:
        fail(f"{path} is not a PDF file")
    return path


def page_window(
    pdf: Path, first_page: int | None, last_page: int | None
) -> PageWindow:
    """Read the page count and resolve the requested page range."""
    info = run_tool(["pdfinfo", str(pdf)], {})
    match = PDF_PAGES_PATTERN.search(info)
    if match is None:
        fail(f"cannot read the page count of {pdf}")
    total = int(match.group(1))
    first = 1 if first_page is None else first_page
    last = total if last_page is None else last_page
    if not 1 <= first <= last <= total:
        fail(f"invalid page range {first}-{last} for a PDF with {total} pages")
    return PageWindow(first, last, total)


def map_pages(pages: Sequence[int], window: PageWindow) -> list[int] | None:
    """Map cut-relative pages to source pages, or None if one is invalid."""
    if not all(1 <= page <= window.sent for page in pages):
        return None
    return [page + window.first - 1 for page in pages]


def cut_pages(
    pdf: Path, window: PageWindow, parts: Path, target: Path
) -> None:
    """Write the selected pages of a PDF to target."""
    parts.mkdir()
    pattern = str(parts / PART_NAME_TEMPLATE)
    first, last = str(window.first), str(window.last)
    run_tool(["pdfseparate", "-f", first, "-l", last, str(pdf), pattern], {})
    pages = [
        str(parts / (PART_NAME_TEMPLATE % number))
        for number in range(window.first, window.last + 1)
    ]
    if len(pages) == 1:
        shutil.copyfile(pages[0], target)
        return
    run_tool(["pdfunite", *pages, str(target)], {})


@contextlib.contextmanager
def pdf_workspace(pdf: Path, window: PageWindow) -> Iterator[Workspace]:
    """Provide a git workspace holding only document.pdf."""
    with scratch_dir() as scratch:
        workspace = create_workspace(scratch)
        target = workspace.path / DOCUMENT_NAME
        if window.sent == window.total:
            shutil.copyfile(pdf, target)
        else:
            cut_pages(pdf, window, scratch / PARTS_NAME, target)
        commit_workspace(workspace)
        yield workspace
