from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent
PYTHON_SHEBANG = re.compile(rb"\A#![^\n]*python")
REQUIRES_PYTHON_FLOOR = re.compile(r">=\s*3\.(\d+)")


def floor_version() -> tuple[int, int]:
    requirement = tomllib.loads((BIN / "pyproject.toml").read_text())[
        "project"
    ]["requires-python"]
    match = REQUIRES_PYTHON_FLOOR.search(requirement)
    assert match is not None
    return (3, int(match.group(1)))


def python_sources() -> list[Path]:
    return sorted(
        path
        for path in BIN.iterdir()
        if path.is_file()
        and (
            path.suffix == ".py"
            or (not path.suffix and PYTHON_SHEBANG.match(path.read_bytes()))
        )
    )


def test_python_sources_are_found() -> None:
    names = {path.name for path in python_sources()}
    assert {"bb-sweep", "lint-strict", "magic_numbers.py"} <= names


@pytest.mark.parametrize("path", python_sources(), ids=lambda path: path.name)
def test_source_parses_at_requires_python_floor(path: Path) -> None:
    ast.parse(path.read_text(), str(path), feature_version=floor_version())
