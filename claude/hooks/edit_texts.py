"""Before/after file texts of an Edit, Write, MultiEdit or NotebookEdit payload, shared by the guard hooks."""
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from code_files import Language, language_of, suffix_of

NOTEBOOK_SUFFIX = "ipynb"
PYTHON_SUFFIX = "py"
PYTHON_KERNEL = "python"
CODE_CELL = "code"
CELL_INDEX = re.compile(r"^cell-(\d+)$")


class Tool(Enum):
    EDIT = "Edit"
    WRITE = "Write"
    MULTI_EDIT = "MultiEdit"
    NOTEBOOK_EDIT = "NotebookEdit"


class CellEdit(Enum):
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class Change:
    language: Language
    suffix: str | None
    before: str
    after: str


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def python_kernel(notebook):
    metadata = notebook.get("metadata")
    if not isinstance(metadata, dict):
        return True
    for section, key in (("kernelspec", "language"), ("language_info", "name")):
        value = metadata.get(section, {}).get(key) if isinstance(metadata.get(section), dict) else None
        if isinstance(value, str) and value.lower() != PYTHON_KERNEL:
            return False
    return True


def cell_source(cell):
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(part for part in source if isinstance(part, str))
    return source if isinstance(source, str) else ""


def notebook_code(text):
    if not text.strip():
        return ""
    try:
        notebook = json.loads(text)
    except ValueError:
        return None
    if not isinstance(notebook, dict) or not python_kernel(notebook):
        return None
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        return ""
    return "\n".join(cell_source(cell) for cell in cells
                     if isinstance(cell, dict) and cell.get("cell_type") == CODE_CELL)


def find_cell(cells, cell_id):
    for cell in cells:
        if isinstance(cell, dict) and cell.get("id") == cell_id:
            return cell
    index = CELL_INDEX.match(cell_id) if isinstance(cell_id, str) else None
    if index and int(index.group(1)) < len(cells) and isinstance(cells[int(index.group(1))], dict):
        return cells[int(index.group(1))]
    return None


def notebook_change(data):
    path, new_source = data.get("notebook_path"), data.get("new_source")
    if not isinstance(path, str) or not isinstance(new_source, str):
        return None
    mode = data.get("edit_mode") or CellEdit.REPLACE.value
    if mode == CellEdit.DELETE.value:
        return None
    notebook = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(notebook, dict) or not python_kernel(notebook):
        return None
    cells = notebook.get("cells") if isinstance(notebook.get("cells"), list) else []
    cell = None if mode == CellEdit.INSERT.value else find_cell(cells, data.get("cell_id"))
    cell_type = data.get("cell_type") or (cell.get("cell_type") if cell else None) or CODE_CELL
    if cell_type != CODE_CELL:
        return None
    return Change(Language.PYTHON, PYTHON_SUFFIX, cell_source(cell) if cell else "", new_source)


def edited(before, data):
    old, new = data.get("old_string"), data.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str) or old not in before:
        return None
    return before.replace(old, new) if data.get("replace_all") is True else before.replace(old, new, 1)


def multi_edited(before, edits):
    if not isinstance(edits, list) or not edits:
        return None
    after = before
    for step in edits:
        after = edited(after, step) if isinstance(step, dict) else None
        if after is None:
            return None
    return after


def file_change(tool, data):
    path = data.get("file_path")
    if not isinstance(path, str) or not path:
        return None
    before = read_text(path)
    match tool:
        case Tool.WRITE:
            after = data.get("content")
        case Tool.EDIT:
            after = edited(before, data)
        case Tool.MULTI_EDIT:
            after = multi_edited(before, data.get("edits"))
        case _:
            after = None
    if not isinstance(after, str):
        return None
    suffix = suffix_of(path)
    if suffix == NOTEBOOK_SUFFIX:
        before, after = notebook_code(before) or "", notebook_code(after)
        if after is None:
            return None
    language = language_of(path, after) or language_of(path, before)
    if language is None:
        return None
    return Change(language, suffix, before, after)


def change_of(tool_name, data):
    tool = next((member for member in Tool if member.value == tool_name), None)
    if tool is None:
        return None
    if tool is Tool.NOTEBOOK_EDIT:
        return notebook_change(data)
    return file_change(tool, data)
