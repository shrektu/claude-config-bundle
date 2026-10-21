import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

SCRIPT = Path(__file__).resolve().parent / "lint-strict"
MODULE_NAME = "lint_strict"
GREEN_LINE = "LINT-STRICT PASS"
FAIL_PREFIX = "LINT-STRICT FAIL"
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
MAIN = "main"
FEATURE = "feature"
NO_TOOL = "/nonexistent/tool"
PINNED_SHEBANG = "#!__HOME__/.pyenv/versions/3.14.3/bin/python3"
TOOL_OVERRIDES = (
    "LINT_STRICT_PRETTIER",
    "LINT_STRICT_CLANG_TIDY",
    "LINT_STRICT_CLANG_FORMAT",
    "LINT_STRICT_MYPY",
    "LINT_STRICT_TSC",
    "LINT_STRICT_JSCPD",
)
CLEAN_MODULE = '"""Clean module."""\n\nVALUE = 1\n'
NOT_ROOT = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root reads files with mode 000",
)
UNREADABLE_REASON = "cannot read the file: Permission denied"
UNDOCUMENTED = "\n\ndef added():\n    return 2\n"
DOCUMENTED = '\n\ndef added() -> int:\n    """Return two."""\n    return 2\n'


@dataclass(frozen=True)
class Run:
    code: int
    out: str
    err: str

    @property
    def last_line(self) -> str:
        lines = self.out.strip().splitlines()
        return lines[-1] if lines else ""

    def json(self) -> dict:
        return json.loads(self.out)


def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    return env


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=git_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def write(repo: Path, name: str, text: str) -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def append(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def commit_all(repo: Path, message: str = "commit") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    path.mkdir()
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", MAIN)
    write(root, "base.py", CLEAN_MODULE)
    commit_all(root, "base")
    return root


def cache_path(log_dir: Path) -> Path:
    return log_dir.parent / "lint-cache"


def lint(
    repo: Path,
    log_dir: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Run:
    env = git_env()
    env["LINT_STRICT_LOG_DIR"] = str(log_dir)
    env["LINT_STRICT_CACHE_DIR"] = str(cache_path(log_dir))
    env.pop("ZEPHYR_BASE", None)
    for name in TOOL_OVERRIDES:
        env[name] = NO_TOOL
    env.update(extra_env or {})
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    return Run(done.returncode, done.stdout, done.stderr)


def violations(run: Run) -> set[tuple[str, int, str]]:
    return {
        (item["path"], item["line"], item["rule"])
        for item in run.json()["violations"]
    }


def rules_at(run: Run, path: str) -> set[str]:
    return {rule for name, _, rule in violations(run) if name == path}


def load_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(MODULE_NAME, str(SCRIPT))
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ls() -> ModuleType:
    return load_module()


def test_changed_function_without_docstring_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", '"""Mod."""\n\n\ndef old():\n    return 1\n')
    commit_all(repo)
    append(repo, "mod.py", UNDOCUMENTED)

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_FAIL
    found = violations(run)
    assert found & {("mod.py", 8, "D103"), ("mod.py", 8, "DOC100")}
    assert not {item for item in found if item[1] == 4}


def test_unchanged_function_without_docstring_is_not_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", '"""Mod."""\n\n\ndef old():\n    return 1\n')
    commit_all(repo)
    append(repo, "mod.py", DOCUMENTED)

    run = lint(repo, log_dir)

    assert run.code == EXIT_PASS, run.out
    assert run.last_line == GREEN_LINE


PRIVATE_AND_NESTED = '''"""Lib."""


def public() -> int:
    """Return one."""

    def inner() -> int:
        return 1

    return inner()


def _private() -> int:
    return 2
'''


def test_private_and_nested_functions_need_docstrings(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "lib.py", PRIVATE_AND_NESTED)

    run = lint(repo, log_dir, "--json")

    found = violations(run)
    assert ("lib.py", 7, "DOC100") in found
    assert ("lib.py", 13, "DOC100") in found
    assert run.code == EXIT_FAIL


@pytest.mark.parametrize(
    "name",
    [
        "test_lib.py",
        "lib_test.py",
        "lib-test.py",
        "conftest.py",
        "tests/lib.py",
        "test/lib.py",
        "pkg/tests/deep/lib.py",
    ],
)
def test_test_files_are_exempt_from_docstrings(
    repo: Path,
    log_dir: Path,
    name: str,
) -> None:
    write(repo, name, PRIVATE_AND_NESTED.replace('"""Lib."""\n', ""))

    run = lint(repo, log_dir, "--json")

    assert not {rule for rule in rules_at(run, name) if rule.startswith("D")}
    assert run.json()["violations"] is not None


UNDOCUMENTED_STUB = """def public() -> int: ...

class Model:
    def value(self) -> int: ...
"""


def test_stub_files_are_exempt_from_docstrings(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "lib.pyi", UNDOCUMENTED_STUB)
    write(repo, "lib.py", UNDOCUMENTED_STUB)

    run = lint(repo, log_dir, "--json")

    assert not {
        rule for rule in rules_at(run, "lib.pyi") if rule.startswith("D")
    }
    assert any(rule.startswith("D") for rule in rules_at(run, "lib.py"))


MODULE_DOCSTRING_ONLY = '"""Module."""\n\nVALUE = 1\n'
TWO_SENTENCES = 'def f() -> int:\n    """Do one. Do two."""\n    return 1\n'
DOC_SHAPE_RULES = {"DOC101", "DOC102"}
MAX_DOCSTRING_LENGTH = 72


def test_module_docstring_not_required(repo: Path, log_dir: Path) -> None:
    write(repo, "mod.py", "VALUE = 1\n")
    write(repo, "pkg/__init__.py", "VALUE = 2\n")

    run = lint(repo, log_dir, "--json")

    found = rules_at(run, "mod.py") | rules_at(run, "pkg/__init__.py")
    assert not found & {"DOC100", "D100", "D104"}


def test_doc101_module_docstring_on_changed_line(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", MODULE_DOCSTRING_ONLY)

    run = lint(repo, log_dir, "--json")

    assert ("mod.py", 1, "DOC101") in violations(run)
    assert run.code == EXIT_FAIL


def test_doc101_points_at_docstring_below_a_shebang(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "tool.py", "#!/usr/bin/env python3\n" + MODULE_DOCSTRING_ONLY)

    run = lint(repo, log_dir, "--json")

    assert ("tool.py", 2, "DOC101") in violations(run)


def test_doc102_multi_sentence(repo: Path, log_dir: Path) -> None:
    write(repo, "mod.py", TWO_SENTENCES)

    run = lint(repo, log_dir, "--json")

    assert ("mod.py", 2, "DOC102") in violations(run)
    assert run.code == EXIT_FAIL


@pytest.mark.parametrize(
    "name",
    ["test_lib.py", "lib_test.py", "conftest.py", "tests/lib.py"],
)
def test_doc102_in_test_file(repo: Path, log_dir: Path, name: str) -> None:
    write(repo, name, TWO_SENTENCES)

    run = lint(repo, log_dir, "--json")

    assert (name, 2, "DOC102") in violations(run)


def test_doc101_in_test_file(repo: Path, log_dir: Path) -> None:
    write(repo, "test_lib.py", MODULE_DOCSTRING_ONLY)

    run = lint(repo, log_dir, "--json")

    assert ("test_lib.py", 1, "DOC101") in violations(run)


REQUIRE_MODULE_DOCSTRINGS = '[lint]\nselect = ["D", "I"]\n'
FORCE_SORT_CONFIG = (
    REQUIRE_MODULE_DOCSTRINGS
    + "\n[lint.isort]\nforce-sort-within-sections = true\n"
)
MIXED_IMPORTS_MODULE = (
    '"""Module."""\n\n'
    "import os\n"
    "from pathlib import Path\n"
    "import sys\n\n"
    "VALUE = (os.sep, Path, sys.platform)\n"
)


def test_doc101_skipped_when_repo_ruff_requires_module_docstrings(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "ruff.toml", REQUIRE_MODULE_DOCSTRINGS)
    write(repo, "mod.py", MODULE_DOCSTRING_ONLY)

    run = lint(repo, log_dir, "--json")

    assert "DOC101" not in rules_at(run, "mod.py")


def test_doc101_reported_when_repo_ignores_d100(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "ruff.toml",
        REQUIRE_MODULE_DOCSTRINGS + 'ignore = ["D100"]\n',
    )
    write(repo, "mod.py", MODULE_DOCSTRING_ONLY)

    run = lint(repo, log_dir, "--json")

    assert ("mod.py", 1, "DOC101") in violations(run)


def test_isort_follows_repo_force_sort_within_sections(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "ruff.toml", FORCE_SORT_CONFIG)
    write(repo, "mod.py", MIXED_IMPORTS_MODULE)

    run = lint(repo, log_dir, "--json")

    assert "I001" not in rules_at(run, "mod.py")
    assert "DOC101" not in rules_at(run, "mod.py")


def test_isort_default_without_repo_config(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", MIXED_IMPORTS_MODULE)

    run = lint(repo, log_dir, "--json")

    assert {"I001", "DOC101"} <= rules_at(run, "mod.py")


@pytest.mark.parametrize(
    ("config_text", "expected"),
    [
        ('[lint]\nselect = ["D"]\n', True),
        ('[lint]\nselect = ["ALL"]\n', True),
        ('[lint]\nselect = ["D1"]\n', True),
        ('[lint]\nselect = ["E"]\n', False),
        ('[lint]\nselect = ["D"]\nignore = ["D100"]\n', False),
        ('[lint]\nselect = ["D"]\nextend-ignore = ["D1"]\n', False),
        ('select = ["D"]\nignore = ["D"]\n', False),
        ('[lint]\nselect = ["D"]\nignore = ["D104"]\n', True),
        ('extend = "base.toml"\n', True),
    ],
)
def test_resolve_module_docstrings_required_follows_extend(
    ls: ModuleType,
    tmp_path: Path,
    config_text: str,
    expected: bool,
) -> None:
    (tmp_path / "base.toml").write_text('[lint]\nselect = ["D"]\n')
    (tmp_path / "ruff.toml").write_text(config_text)

    resolved = ls.resolve_module_docstrings_required(
        tmp_path,
        tmp_path / "mod.py",
    )

    assert resolved is expected


def test_isort_arguments_render_toml_literals(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    (tmp_path / "ruff.toml").write_text(
        "[lint.isort]\n"
        "force-sort-within-sections = true\n"
        "lines-after-imports = 2\n"
        'known-first-party = ["app", "lib"]\n'
        'order-by-type = "no"\n',
    )

    arguments = ls.resolve_isort_arguments(tmp_path, tmp_path / "mod.py")

    assert arguments == (
        "--config",
        "lint.isort.force-sort-within-sections=true",
        "--config",
        "lint.isort.lines-after-imports=2",
        "--config",
        'lint.isort.known-first-party=["app", "lib"]',
        "--config",
        'lint.isort.order-by-type="no"',
    )


def test_doc_shape_rules_skip_stubs(repo: Path, log_dir: Path) -> None:
    write(repo, "lib.pyi", '"""Stub."""\ndef f() -> int:\n    """A. B."""\n')

    run = lint(repo, log_dir, "--json")

    assert not rules_at(run, "lib.pyi") & DOC_SHAPE_RULES


def test_legacy_docstring_unchanged_passes(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", TWO_SENTENCES)
    commit_all(repo)
    append(repo, "mod.py", DOCUMENTED)

    run = lint(repo, log_dir)

    assert run.code == EXIT_PASS, run.out
    assert run.last_line == GREEN_LINE


def test_one_sentence_docstrings_pass_without_module_docstring(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", "VALUE = 1\n" + DOCUMENTED)

    run = lint(repo, log_dir, "--json")

    assert not rules_at(run, "mod.py") & (DOC_SHAPE_RULES | {"DOC100"})


def shaped(ls: ModuleType, source: str) -> list[tuple[int, str]]:
    return [(p.line, p.rule) for p in ls.badly_shaped_docstrings(source)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Do it.", True),
        ("Return a value, e.g. an int or i.e. a str.", True),
        ("Do one. Do two.", False),
        ("Is it? Yes.", False),
        ("Stop! Go.", False),
        ("Do one.\nMore.", False),
        ("x" * (MAX_DOCSTRING_LENGTH - 1) + ".", True),
        ("x" * MAX_DOCSTRING_LENGTH + ".", False),
    ],
)
def test_is_one_line_sentence(
    ls: ModuleType,
    text: str,
    expected: bool,
) -> None:
    assert ls.is_one_line_sentence(text) is expected


def test_badly_shaped_docstrings_edge_cases(ls: ModuleType) -> None:
    source = (
        '"""Mod."""\n'
        "class A:\n"
        '    """Fine."""\n'
        "    class B:\n"
        '        """One. Two."""\n'
        "    async def run(self) -> None:\n"
        '        """Go.\n'
        "\n"
        '        More."""\n'
        "def g():\n"
        "    pass\n"
    )

    assert shaped(ls, source) == [(1, "DOC101"), (5, "DOC102"), (7, "DOC102")]


def test_badly_shaped_docstrings_bad_source(ls: ModuleType) -> None:
    assert shaped(ls, "") == []
    assert shaped(ls, "def (:\n") == []
    assert shaped(ls, "X = 1\n") == []


def long_lines_module() -> str:
    lines = ['"""Lines."""', ""]
    for name, width in (("A", 85), ("B", 95), ("C", 105)):
        prefix = f'{name} = "'
        filler = "x" * (width - len(prefix) - 1)
        lines.append(f'{prefix}{filler}"')
    return "\n".join(lines) + "\n"


def e501_lines(run: Run) -> set[int]:
    return {
        line
        for path, line, rule in violations(run)
        if path == "lines.py" and rule == "E501"
    }


@pytest.mark.parametrize(
    ("config_name", "config_text", "expected"),
    [
        (None, "", {3, 4, 5}),
        ("pyproject.toml", "[tool.ruff]\nline-length = 120\n", {5}),
        ("pyproject.toml", "[tool.ruff]\nline-length = 90\n", {4, 5}),
        ("pyproject.toml", "[tool.black]\nline-length = 120\n", {5}),
        ("pyproject.toml", "[tool.black]\nline-length = 90\n", {4, 5}),
        ("ruff.toml", "line-length = 90\n", {4, 5}),
        (".ruff.toml", "line-length = 120\n", {5}),
    ],
)
def test_line_length_follows_repo_config_capped_at_99(
    repo: Path,
    log_dir: Path,
    config_name: str | None,
    config_text: str,
    expected: set[int],
) -> None:
    if config_name:
        write(repo, config_name, config_text)
    write(repo, "lines.py", long_lines_module())

    run = lint(repo, log_dir, "--json")

    assert e501_lines(run) == expected


TYPING_ONLY_IMPORT_MODULE = (
    '"""Paths."""\n\n'
    "from __future__ import annotations\n\n"
    "from pathlib import Path\n\n\n"
    "def name_of(path: Path) -> str:\n"
    '    """Return the file name."""\n'
    "    return path.name\n"
)


def typing_only_import_rules(run: Run) -> set[str]:
    return {
        rule
        for path, _line, rule in violations(run)
        if path == "paths.py" and rule.startswith("TC")
    }


@pytest.mark.parametrize(
    ("config_name", "config_text", "expected"),
    [
        (None, "", set()),
        ("pyproject.toml", '[tool.ruff.lint]\nselect = ["E"]\n', set()),
        ("pyproject.toml", '[tool.ruff.lint]\nselect = ["TC"]\n', {"TC003"}),
        ("pyproject.toml", '[tool.ruff.lint]\nextend-select = ["TC003"]\n', {"TC003"}),
        ("pyproject.toml", '[tool.ruff]\nselect = ["ALL"]\n', {"TC003"}),
        ("ruff.toml", '[lint]\nselect = ["TC"]\n', {"TC003"}),
        ("pyproject.toml", '[tool.ruff]\nextend = "base.toml"\n', {"TC003"}),
    ],
)
def test_typing_only_imports_follow_repo_config(
    repo: Path,
    log_dir: Path,
    config_name: str | None,
    config_text: str,
    expected: set[str],
) -> None:
    write(repo, "base.toml", '[lint]\nselect = ["TC"]\n')
    if config_name:
        write(repo, config_name, config_text)
    write(repo, "paths.py", TYPING_ONLY_IMPORT_MODULE)

    run = lint(repo, log_dir, "--json")

    assert typing_only_import_rules(run) == expected


def test_formatting_drift_on_changed_line_is_fmt(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "fmt.py", '"""Fmt."""\n\nA = 1\n')
    commit_all(repo)
    append(repo, "fmt.py", "B = {  'a':1 }\n")

    run = lint(repo, log_dir, "--json")

    assert ("fmt.py", 4, "FMT") in violations(run)
    assert run.code == EXIT_FAIL


def test_reformat_three_lines_below_changed_line_is_not_fmt(
    repo: Path,
    log_dir: Path,
) -> None:
    lines = ['"""Fmt."""', "", "A = 1", "B = 2", "C = 3", "D = 4", "E = [1,2]"]
    write(repo, "fmt.py", "\n".join(lines) + "\n")
    commit_all(repo)
    lines[3] = "B = 5"
    write(repo, "fmt.py", "\n".join(lines) + "\n")

    run = lint(repo, log_dir, "--json")

    assert "FMT" not in rules_at(run, "fmt.py")
    assert run.code == EXIT_PASS, run.out


def test_staged_reports_only_staged_changes(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", CLEAN_MODULE)
    write(repo, "b.py", CLEAN_MODULE)
    commit_all(repo)
    append(repo, "a.py", UNDOCUMENTED)
    git(repo, "add", "a.py")
    append(repo, "b.py", UNDOCUMENTED)
    write(repo, "c.py", CLEAN_MODULE + UNDOCUMENTED)

    run = lint(repo, log_dir, "--staged", "--json")

    paths = {path for path, _, _ in violations(run)}
    assert paths == {"a.py"}
    assert run.code == EXIT_FAIL


def start_merge_of_violating_branch(repo: Path) -> None:
    write(repo, "a.py", CLEAN_MODULE)
    commit_all(repo)
    git(repo, "switch", "-q", "-c", "incoming")
    append(repo, "a.py", UNDOCUMENTED)
    write(repo, "b.py", CLEAN_MODULE + UNDOCUMENTED)
    commit_all(repo, "incoming")
    git(repo, "switch", "-q", MAIN)
    write(repo, "c.py", CLEAN_MODULE)
    commit_all(repo, "ours")
    git(repo, "merge", "-q", "--no-commit", "--no-ff", "incoming")


def test_staged_merge_ignores_lines_of_the_merged_branch(
    repo: Path,
    log_dir: Path,
) -> None:
    start_merge_of_violating_branch(repo)

    run = lint(repo, log_dir, "--staged", "--json")

    assert violations(run) == set()
    assert run.code == EXIT_PASS, run.out


def test_staged_merge_reports_lines_written_while_merging(
    repo: Path,
    log_dir: Path,
) -> None:
    start_merge_of_violating_branch(repo)
    append(repo, "b.py", "\n\ndef resolved():\n    return 3\n")
    git(repo, "add", "b.py")

    run = lint(repo, log_dir, "--staged", "--json")

    lines = {line for path, line, _ in violations(run) if path == "b.py"}
    assert lines
    assert min(lines) > len((CLEAN_MODULE + UNDOCUMENTED).splitlines())
    assert run.code == EXIT_FAIL


def test_worktree_merge_ignores_lines_of_the_merged_branch(
    repo: Path,
    log_dir: Path,
) -> None:
    start_merge_of_violating_branch(repo)

    run = lint(repo, log_dir, "--json")

    assert violations(run) == set()
    assert run.code == EXIT_PASS, run.out


def test_worktree_merge_reports_lines_written_while_merging(
    repo: Path,
    log_dir: Path,
) -> None:
    start_merge_of_violating_branch(repo)
    append(repo, "b.py", "\n\ndef resolved():\n    return 3\n")

    run = lint(repo, log_dir, "--json")

    lines = {line for path, line, _ in violations(run) if path == "b.py"}
    assert lines
    assert min(lines) > len((CLEAN_MODULE + UNDOCUMENTED).splitlines())
    assert run.code == EXIT_FAIL


def test_tracked_merge_ignores_lines_of_the_merged_branch(
    repo: Path,
    log_dir: Path,
) -> None:
    start_merge_of_violating_branch(repo)

    run = lint(repo, log_dir, "--tracked", "--json")

    assert violations(run) == set()
    assert run.code == EXIT_PASS, run.out


def test_staged_violation_under_clean_unstaged_edit_fails(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", CLEAN_MODULE)
    commit_all(repo)
    append(repo, "a.py", UNDOCUMENTED)
    git(repo, "add", "a.py")
    write(repo, "a.py", CLEAN_MODULE + DOCUMENTED)

    run = lint(repo, log_dir, "--staged")

    assert run.code == EXIT_FAIL, run.out
    assert run.last_line.startswith(FAIL_PREFIX)


def test_clean_staged_under_violating_unstaged_edit_passes(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", CLEAN_MODULE)
    commit_all(repo)
    append(repo, "a.py", DOCUMENTED)
    git(repo, "add", "a.py")
    append(repo, "a.py", UNDOCUMENTED.replace("added", "later"))

    run = lint(repo, log_dir, "--staged")

    assert run.code == EXIT_PASS, run.out
    assert run.last_line == GREEN_LINE


def test_base_uses_merge_base(repo: Path, log_dir: Path) -> None:
    write(repo, "shared.py", '"""Shared."""\n\n\ndef f():\n    return 1\n')
    commit_all(repo, "fork point")
    git(repo, "checkout", "-q", "-b", FEATURE)
    write(repo, "feat.py", CLEAN_MODULE + UNDOCUMENTED)
    commit_all(repo, "feature work")
    git(repo, "checkout", "-q", MAIN)
    write(
        repo,
        "shared.py",
        '"""Shared."""\n\n\ndef f() -> int:\n    """Return 1."""\n'
        "    return 1\n",
    )
    commit_all(repo, "main after fork")
    git(repo, "checkout", "-q", FEATURE)

    run = lint(repo, log_dir, "--base", MAIN, "--json")

    paths = {path for path, _, _ in violations(run)}
    assert paths == {"feat.py"}


def test_tracked_ignores_untracked_files(repo: Path, log_dir: Path) -> None:
    write(repo, "a.py", CLEAN_MODULE)
    commit_all(repo)
    append(repo, "a.py", UNDOCUMENTED)
    write(repo, "new.py", CLEAN_MODULE + UNDOCUMENTED)

    default = lint(repo, log_dir, "--json")
    tracked = lint(repo, log_dir, "--tracked", "--json")

    assert {path for path, _, _ in violations(default)} == {"a.py", "new.py"}
    assert {path for path, _, _ in violations(tracked)} == {"a.py"}


@pytest.mark.parametrize(
    "mode",
    [[], ["--tracked"], ["--staged"], ["--base", MAIN]],
)
def test_paths_restrict_every_mode(
    repo: Path,
    log_dir: Path,
    mode: list[str],
) -> None:
    write(repo, "a.py", CLEAN_MODULE)
    write(repo, "b.py", CLEAN_MODULE)
    commit_all(repo)
    append(repo, "a.py", UNDOCUMENTED)
    append(repo, "b.py", UNDOCUMENTED)
    git(repo, "add", "a.py", "b.py")

    run = lint(repo, log_dir, *mode, "--paths", "a.py", "--json")

    assert {path for path, _, _ in violations(run)} == {"a.py"}


def test_extensionless_python_shebang_is_linted(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "tool",
        '#!/usr/bin/env python3\n"""Tool."""\n\n\ndef run():\n    return 1\n',
    )
    write(repo, "script", "#!/bin/sh\necho hi\n")

    run = lint(repo, log_dir, "--json")

    paths = {path for path, _, _ in violations(run)}
    assert "tool" in paths
    assert "script" not in paths


def test_suppressions_are_listed_not_counted(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "sup.py", "import os  # noqa: F401\n")
    write(repo, "web.js", "// eslint-disable-next-line\nlet a = 1;\n")

    text = lint(repo, log_dir)
    data = lint(repo, log_dir, "--json").json()

    assert text.code == EXIT_PASS, text.out
    assert "Suppressions added:" in text.out
    assert "sup.py:1" in text.out
    assert text.last_line == GREEN_LINE
    found = {(item["path"], item["line"]) for item in data["suppressions"]}
    assert found == {("sup.py", 1), ("web.js", 1)}
    assert data["violations"] == []
    assert data["passed"] is True


def test_json_shape(repo: Path, log_dir: Path) -> None:
    append(repo, "base.py", UNDOCUMENTED)

    data = lint(repo, log_dir, "--json").json()

    assert set(data) == {"violations", "not_checked", "suppressions", "passed"}
    assert data["passed"] is False
    assert set(data["violations"][0]) == {
        "path",
        "line",
        "column",
        "rule",
        "message",
        "url",
        "tool",
    }


def test_exit_codes(repo: Path, log_dir: Path, tmp_path: Path) -> None:
    clean = lint(repo, log_dir)
    append(repo, "base.py", UNDOCUMENTED)
    dirty = lint(repo, log_dir)
    outside = tmp_path / "plain"
    outside.mkdir()
    not_repo = lint(outside, log_dir)
    unknown_ref = lint(repo, log_dir, "--base", "no-such-ref")
    conflicting = lint(repo, log_dir, "--staged", "--tracked")

    assert clean.code == EXIT_PASS
    assert dirty.code == EXIT_FAIL
    assert dirty.last_line.startswith(FAIL_PREFIX)
    assert not_repo.code == EXIT_USAGE
    assert unknown_ref.code == EXIT_USAGE
    assert conflicting.code == EXIT_USAGE


def test_output_is_capped_with_log_path(repo: Path, log_dir: Path) -> None:
    body = "".join(
        f"\n\ndef f{index}():\n    return {index}\n" for index in range(5)
    )
    write(repo, "many.py", '"""Many."""\n' + body)

    run = lint(repo, log_dir, "--max-lines", "2")

    violation_lines = [
        line for line in run.out.splitlines() if line.startswith("many.py:")
    ]
    assert len(violation_lines) == 2
    more = [line for line in run.out.splitlines() if "more" in line]
    assert len(more) == 1
    log_path = Path(more[0].rsplit(": ", 1)[1])
    assert log_path.parent == log_dir
    assert log_path.read_text(encoding="utf-8").count("many.py:") > 2


def test_log_file_is_always_written(repo: Path, log_dir: Path) -> None:
    run = lint(repo, log_dir)

    logs = list(log_dir.glob("*-repo.txt"))
    assert run.code == EXIT_PASS
    assert len(logs) == 1
    assert GREEN_LINE in logs[0].read_text(encoding="utf-8")


def test_header_names_ruff_version_and_mode(
    repo: Path,
    log_dir: Path,
) -> None:
    append(repo, "base.py", DOCUMENTED)
    git(repo, "add", "base.py")

    run = lint(repo, log_dir, "--staged")

    header = run.out.splitlines()[0]
    assert "ruff" in header
    assert "staged" in header


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        ("@@ -1 +1 @@\n-a\n+b\n", {1}),
        ("@@ -3,2 +4,3 @@ def f():\n", {4, 5, 6}),
        ("@@ -5,2 +4,0 @@\n", set()),
        ("@@ -0,0 +1,2 @@\n@@ -9 +10 @@\n", {1, 2, 10}),
        ("+@@ not a header\n", set()),
    ],
)
def test_parse_hunk_lines(ls: ModuleType, patch: str, expected: set) -> None:
    assert ls.parse_hunk_lines(patch) == frozenset(expected)


def test_parse_raw_listing_handles_renames_and_spaces(ls: ModuleType) -> None:
    raw = (
        ":100644 100644 aaa bbb M\0a b.py\0"
        ":100644 100644 aaa bbb R090\0old.py\0new dir/new.py\0"
        ":100644 000000 aaa 000 D\0gone.py\0"
    )

    entries = ls.parse_raw_listing(raw)

    assert [(e.status, e.path, e.old_path) for e in entries] == [
        ("M", "a b.py", None),
        ("R", "new dir/new.py", "old.py"),
        ("D", "gone.py", None),
    ]
    assert entries[2].mode == "000000"


def drift_lines(
    ls: ModuleType,
    original: list[str],
    formatted: list[str],
    changed: set[int],
) -> list[tuple[int, int, int]]:
    drifts = ls.formatting_drift(original, formatted, frozenset(changed))
    return [(d.line, d.first, d.last) for d in drifts]


def test_formatting_drift_replace_on_changed_line(ls: ModuleType) -> None:
    original = ["a", "b=1", "c"]
    formatted = ["a", "b = 1", "c"]

    assert drift_lines(ls, original, formatted, {2}) == [(2, 2, 2)]
    assert drift_lines(ls, original, formatted, {1, 3}) == []


def test_formatting_drift_pure_insertion_touches_both_neighbours(
    ls: ModuleType,
) -> None:
    original = ["a", "b", "c"]
    formatted = ["a", "b", "", "c"]

    assert drift_lines(ls, original, formatted, {2}) == [(2, 2, 3)]
    assert drift_lines(ls, original, formatted, {3}) == [(3, 2, 3)]
    assert drift_lines(ls, original, formatted, {1}) == []


def test_formatting_drift_deletion(ls: ModuleType) -> None:
    original = ["a", "", "", "", "b"]
    formatted = ["a", "", "", "b"]

    assert drift_lines(ls, original, formatted, {4}) == [(4, 4, 4)]
    assert drift_lines(ls, original, formatted, {1}) == []


def test_formatting_drift_far_below_change_is_ignored(ls: ModuleType) -> None:
    original = ["a", "b", "c", "d", "e=[1,2]"]
    formatted = ["a", "b", "c", "d", "e = [1, 2]"]

    assert drift_lines(ls, original, formatted, {2}) == []


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({}, 79),
        ({"pyproject.toml": "[tool.ruff]\nline-length = 120\n"}, 99),
        ({"pyproject.toml": "[tool.ruff]\nline-length = 88\n"}, 88),
        ({"pyproject.toml": "[tool.black]\nline-length = 100\n"}, 99),
        ({"pyproject.toml": "[tool.ruff\nbroken"}, 79),
        ({"ruff.toml": "line-length = 72\n"}, 72),
        (
            {
                ".ruff.toml": "line-length = 90\n",
                "pyproject.toml": "[tool.ruff]\nline-length = 70\n",
            },
            90,
        ),
    ],
)
def test_resolve_line_length(
    ls: ModuleType,
    tmp_path: Path,
    files: dict[str, str],
    expected: int,
) -> None:
    for name, text in files.items():
        write(tmp_path, name, text)

    assert ls.resolve_line_length(tmp_path, tmp_path / "m.py") == expected


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        (">=3.11", 11),
        ("~=3.12.1", 12),
        (">=3.10,<4", 10),
        ("==3.9.*", 9),
        ("", None),
        ("<4", None),
    ],
)
def test_requires_python_minor(
    ls: ModuleType,
    requirement: str,
    expected: int | None,
) -> None:
    assert ls.requires_python_minor(requirement) == expected


def test_target_version_from_pyproject_or_interpreter(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    fallback = f"py3{sys.version_info.minor}"
    module = tmp_path / "m.py"
    assert ls.resolve_target_version(tmp_path, module) == fallback
    write(
        tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.12"\n'
    )
    assert ls.resolve_target_version(tmp_path, module) == "py312"


def test_target_version_from_python_version_file(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    write(tmp_path, ".python-version", "3.11.9\n")
    assert ls.resolve_target_version(tmp_path, tmp_path / "m.py") == "py311"


@pytest.mark.parametrize(
    ("base_image", "expected"),
    [
        ("FROM python:3.11.14-alpine3.23 AS builder", "py311"),
        (
            "FROM --platform=$BUILDPLATFORM docker.io/library/python:3.12-slim",
            "py312",
        ),
    ],
)
def test_target_version_from_dockerfile_base_image(
    ls: ModuleType,
    tmp_path: Path,
    base_image: str,
    expected: str,
) -> None:
    write(tmp_path, "Dockerfile", f"{base_image}\nRUN true\n")
    assert ls.resolve_target_version(tmp_path, tmp_path / "m.py") == expected


def test_requires_python_wins_over_pinned_python(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    write(tmp_path, ".python-version", "3.11.9\n")
    write(tmp_path, "Dockerfile", "FROM python:3.10-slim\n")
    write(
        tmp_path,
        "pkg/pyproject.toml",
        '[project]\nrequires-python = ">=3.12"\n',
    )
    module = tmp_path / "pkg" / "m.py"
    assert ls.resolve_target_version(tmp_path, module) == "py312"
    write(
        tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.13"\n'
    )
    (tmp_path / "pkg" / "pyproject.toml").unlink()
    assert ls.resolve_target_version(tmp_path, module) == "py313"


def test_non_python_dockerfile_falls_back_to_interpreter(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    write(tmp_path, "Dockerfile", "FROM alpine:3.20\n")
    fallback = f"py3{sys.version_info.minor}"
    assert ls.resolve_target_version(tmp_path, tmp_path / "m.py") == fallback


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("test_x.py", True),
        ("pkg/x_test.py", True),
        ("hooks/x-test.py", True),
        ("conftest.py", True),
        ("tests/helpers.py", True),
        ("a/test/b/c.py", True),
        ("x.py", False),
        ("testing/x.py", False),
        ("latest.py", False),
        ("contest.py", False),
    ],
)
def test_is_test_file(ls: ModuleType, path: str, expected: bool) -> None:
    assert ls.is_test_file(path) is expected


@pytest.mark.parametrize(
    ("path", "first_line", "expected"),
    [
        ("tool", "#!/usr/bin/env python3", "python"),
        ("tool", "#!/usr/bin/python3.14", "python"),
        ("tool", "#!/usr/bin/env python", "python"),
        ("tool", "#!/usr/bin/env node", "js"),
        ("tool", "#!/bin/sh", None),
        ("tool", "", None),
        ("x.py", "", "python"),
        ("x.tsx", "", "ts"),
        ("x.hpp", "", "cpp"),
        ("x.sh", "#!/usr/bin/env python3", None),
    ],
)
def test_language_from(
    ls: ModuleType,
    path: str,
    first_line: str,
    expected: str | None,
) -> None:
    assert ls.language_from(path, first_line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("import os  # noqa: F401", True),
        ("x = f()  # type: ignore[attr-defined]", True),
        ("// eslint-disable-next-line no-console", True),
        ("// @ts-ignore", True),
        ("// @ts-expect-error", True),
        ("int x; // NOLINT(readability)", True),
        ("# pylint: disable=invalid-name", True),
        ("x = 1", False),
        ("value = typed_ignore", False),
    ],
)
def test_suppression_pattern(
    ls: ModuleType, line: str, expected: bool
) -> None:
    assert bool(ls.SUPPRESSION_PATTERN.search(line)) is expected


def test_cap_violations(ls: ModuleType, tmp_path: Path) -> None:
    log = tmp_path / "run.txt"
    lines = ["a", "b", "c"]

    assert ls.cap_violations(lines, None) == lines
    assert ls.cap_violations(lines, ls.OutputCap(3, log)) == lines
    capped = ls.cap_violations(lines, ls.OutputCap(2, log))
    assert capped[:2] == ["a", "b"]
    assert capped[2] == f"\u2026 1 more \u2014 full list: {log}"


def test_missing_docstrings_skips_overloads(ls: ModuleType) -> None:
    source = (
        '"""Mod."""\n'
        "from typing import overload\n"
        "import typing\n"
        "@overload\n"
        "def f(x: int) -> int: ...\n"
        "@typing.overload\n"
        "def f(x: str) -> str: ...\n"
        "def f(x):\n"
        '    """Doc."""\n'
        "class K:\n"
        "    async def m(self): pass\n"
    )

    found = [(m.line, m.message) for m in ls.missing_docstrings(source)]

    assert found == [
        (10, "Missing docstring in class `K`"),
        (11, "Missing docstring in function `m`"),
    ]


def test_missing_docstrings_module_and_bad_source(ls: ModuleType) -> None:
    assert ls.missing_docstrings("") == []
    assert ls.missing_docstrings("def (:\n") == []
    assert ls.missing_docstrings("a\0") == []
    assert ls.missing_docstrings("X = 1\n") == []


def test_split_lines_matches_git_numbering(ls: ModuleType) -> None:
    assert ls.split_lines("a\nb\n") == ["a", "b"]
    assert ls.split_lines("a\nb") == ["a", "b"]
    assert ls.split_lines("a\r\nb\x0cc\n") == ["a\r", "b\x0cc"]
    assert ls.split_lines("") == []


def test_rename_reports_new_path_changed_lines_only(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "old.py", '"""Old."""\n\n\ndef f():\n    return 1\n')
    commit_all(repo)
    git(repo, "mv", "old.py", "new.py")
    append(repo, "new.py", UNDOCUMENTED)

    run = lint(repo, log_dir, "--json")

    found = violations(run)
    assert {path for path, _, _ in found} == {"new.py"}
    assert {line for _, line, _ in found} == {8}


def test_deleted_file_and_deleted_lines_are_ignored(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "gone.py", "def f():\n    return 1\n")
    write(repo, "keep.py", '"""Keep."""\n\nA = 1\nB = 2\n')
    commit_all(repo)
    (repo / "gone.py").unlink()
    write(repo, "keep.py", '"""Keep."""\n\nA = 1\n')

    run = lint(repo, log_dir)

    assert run.code == EXIT_PASS, run.out
    assert run.last_line == GREEN_LINE


def test_crlf_file_is_linted_on_changed_lines(
    repo: Path,
    log_dir: Path,
) -> None:
    text = '"""Crlf."""\r\n\r\nA = 1\r\n'
    (repo / "crlf.py").write_bytes(text.encode())
    commit_all(repo)
    (repo / "crlf.py").write_bytes(
        (text + "\r\n\r\ndef f():\r\n    return 1\r\n").encode(),
    )

    run = lint(repo, log_dir, "--json")

    found = violations(run)
    assert ("crlf.py", 6, "D103") in found
    assert "FMT" not in rules_at(run, "crlf.py")
    assert not {item for item in found if item[1] < 6}


def test_non_utf8_changed_file_does_not_crash(
    repo: Path,
    log_dir: Path,
) -> None:
    (repo / "latin.py").write_bytes(
        b'"""Latin."""\n\nNAME = "caf\xe9"\n',
    )

    run = lint(repo, log_dir, "--json")

    assert run.code in {EXIT_PASS, EXIT_FAIL}, run.err
    assert run.json()["passed"] is (run.code == EXIT_PASS)


@NOT_ROOT
def test_unreadable_untracked_file_is_not_checked(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "secret.py", CLEAN_MODULE)
    (repo / "secret.py").chmod(0)

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_PASS, run.err
    assert not_checked_reasons(run) == {
        ("secret.py", "lint-strict"): UNREADABLE_REASON,
    }


@NOT_ROOT
def test_unreadable_untracked_file_is_listed_in_text_output(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "secret.py", CLEAN_MODULE)
    (repo / "secret.py").chmod(0)

    run = lint(repo, log_dir)

    assert run.code == EXIT_PASS, run.err
    assert "Not checked:" in run.out


@NOT_ROOT
def test_unreadable_untracked_script_without_suffix_is_not_checked(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "tool", PINNED_SHEBANG + "\n" + CLEAN_MODULE)
    (repo / "tool").chmod(0)

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_PASS, run.err
    reasons = not_checked_reasons(run)
    assert reasons["tool", "lint-strict"] == UNREADABLE_REASON


@NOT_ROOT
def test_fix_unreadable_untracked_file_is_not_checked(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "secret.py", CLEAN_MODULE)
    (repo / "secret.py").chmod(0)

    run = fix(repo, log_dir)

    assert run.code == EXIT_PASS, run.err
    skipped = [
        item
        for item in run.json()["not_checked"]
        if item["path"] == "secret.py"
    ]
    assert skipped == [
        {
            "path": "secret.py",
            "tool": "lint-strict",
            "reason": UNREADABLE_REASON,
        },
    ]


def test_empty_diff_passes_with_no_changed_files_line(
    repo: Path,
    log_dir: Path,
) -> None:
    run = lint(repo, log_dir)

    assert run.code == EXIT_PASS
    assert "No changed files." in run.out
    assert run.last_line == GREEN_LINE


def test_path_with_spaces(repo: Path, log_dir: Path) -> None:
    name = "dir with space/my file.py"
    write(repo, name, CLEAN_MODULE)
    commit_all(repo)
    append(repo, name, UNDOCUMENTED)
    write(repo, "new dir/other file.py", CLEAN_MODULE + UNDOCUMENTED)

    run = lint(repo, log_dir, "--json")
    only = lint(repo, log_dir, "--paths", name, "--json")

    paths = {path for path, _, _ in violations(run)}
    assert paths == {name, "new dir/other file.py"}
    assert {path for path, _, _ in violations(only)} == {name}


def test_path_with_spaces_in_staged_partial_file(
    repo: Path,
    log_dir: Path,
) -> None:
    name = "a b.py"
    write(repo, name, CLEAN_MODULE)
    commit_all(repo)
    append(repo, name, UNDOCUMENTED)
    git(repo, "add", name)
    write(repo, name, CLEAN_MODULE + DOCUMENTED)

    run = lint(repo, log_dir, "--staged", "--json")

    assert {path for path, _, _ in violations(run)} == {name}


def test_staged_file_deleted_from_worktree_is_read_from_index(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", CLEAN_MODULE + UNDOCUMENTED)
    git(repo, "add", "a.py")
    (repo / "a.py").unlink()

    run = lint(repo, log_dir, "--staged", "--json")

    assert {path for path, _, _ in violations(run)} == {"a.py"}


def test_ruff_missing_is_not_checked_and_passes(
    repo: Path,
    log_dir: Path,
) -> None:
    append(repo, "base.py", DOCUMENTED)
    missing = {"LINT_STRICT_RUFF": "/nonexistent/ruff"}

    text = lint(repo, log_dir, extra_env=missing)
    data = lint(repo, log_dir, "--json", extra_env=missing).json()

    assert text.code == EXIT_PASS, text.out
    assert "Not checked:" in text.out
    assert text.last_line == GREEN_LINE
    ruff_skipped = [i for i in data["not_checked"] if i["tool"] == "ruff"]
    assert ruff_skipped == [
        {
            "path": "base.py",
            "tool": "ruff",
            "reason": ruff_skipped[0]["reason"],
        },
    ]


def test_repo_without_commits(tmp_path: Path, log_dir: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q", "-b", MAIN)
    write(root, "a.py", CLEAN_MODULE + UNDOCUMENTED)

    default = lint(root, log_dir, "--json")
    git(root, "add", "a.py")
    staged = lint(root, log_dir, "--staged", "--json")

    assert {path for path, _, _ in violations(default)} == {"a.py"}
    assert {path for path, _, _ in violations(staged)} == {"a.py"}


def test_repo_option_accepts_subdirectory(repo: Path, log_dir: Path) -> None:
    write(repo, "pkg/mod.py", CLEAN_MODULE + UNDOCUMENTED)

    run = lint(repo / "pkg", log_dir, "--json")

    assert {path for path, _, _ in violations(run)} == {"pkg/mod.py"}


def test_syntax_error_on_changed_line_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "broken.py", '"""Broken."""\n\ndef f(:\n')

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_FAIL
    assert any(path == "broken.py" for path, _, _ in violations(run))


def test_script_is_executable_with_pinned_interpreter() -> None:
    assert os.access(SCRIPT, os.X_OK)
    first = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert first == PINNED_SHEBANG


RECORDER = """
def record(entry):
    folder = Path(sys.argv[0] + ".records")
    folder.mkdir(exist_ok=True)
    name = f"{os.getpid()}-{time.time_ns()}.json"
    (folder / name).write_text(json.dumps(entry))
"""

FAKE_ESLINT = """
args = sys.argv[1:]
if args == ["--version"]:
    print("v9.30.0")
    raise SystemExit(0)
takes_value = {"-c", "--format", "--stdin-filename"}
files = []
skip = False
for arg in args:
    if skip:
        skip = False
    elif arg in takes_value:
        skip = True
    elif not arg.startswith("-"):
        files.append(arg)
overlay = Path(args[args.index("-c") + 1]).read_text()
stdin = None
if "--stdin-filename" in args:
    files = [args[args.index("--stdin-filename") + 1]]
    stdin = sys.stdin.read()
record(
    {"argv": args, "cwd": os.getcwd(), "overlay": overlay, "stdin": stdin},
)
messages = json.loads(os.environ.get("FAKE_MESSAGES", "[]"))
results = [
    {"filePath": str(Path(name).resolve()), "messages": messages}
    for name in files
]
print(json.dumps(results))
raise SystemExit(1 if messages else 0)
"""

FAKE_PRETTIER = """
args = sys.argv[1:]
if args == ["--version"]:
    print("3.9.9")
    raise SystemExit(0)
single = "--single-quote" in args
no_semi = "--no-semi" in args
text = sys.stdin.read()
lines = []
for line in text.splitlines():
    body = line.rstrip(";")
    body = body.replace('"', "'") if single else body.replace("'", '"')
    if body.strip() and not no_semi and not body.endswith(("{", "}")):
        body += ";"
    lines.append(body)
record({"exe": sys.argv[0], "argv": args, "cwd": os.getcwd(), "stdin": text})
print("\\n".join(lines))
"""

FAKE_CLANG_TIDY = """
args = sys.argv[1:]
if args == ["--version"]:
    print("Ubuntu LLVM version 18.1.3")
    raise SystemExit(0)
overlay = None
for arg in args:
    if arg.startswith("--vfsoverlay="):
        data = json.loads(Path(arg.split("=", 1)[1]).read_text())
        contents = {
            root["name"]: Path(root["external-contents"]).read_text()
            for root in data["roots"]
        }
        overlay = {"yaml": data, "contents": contents}
record({"argv": args, "overlay": overlay})
sys.stdout.write(os.environ.get("FAKE_TIDY_OUTPUT", ""))
sys.stderr.write(os.environ.get("FAKE_TIDY_STDERR", ""))
raise SystemExit(int(os.environ.get("FAKE_TIDY_EXIT", "0")))
"""

FAKE_CHECKPATCH = """
conf = Path.cwd() / ".checkpatch.conf"
record(
    {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "conf": conf.read_text() if conf.exists() else None,
        "stdin": sys.stdin.read(),
    },
)
sys.stdout.write(os.environ.get("FAKE_CHECKPATCH_OUTPUT", ""))
"""


def make_fake(path: Path, body: str) -> Path:
    header = f"#!{sys.executable}\nimport json, os, sys, time\n"
    header += "from pathlib import Path\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + RECORDER + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def records(fake: Path) -> list[dict]:
    folder = Path(f"{fake}.records")
    if not folder.is_dir():
        return []
    return [
        json.loads(item.read_text(encoding="utf-8"))
        for item in sorted(folder.iterdir())
    ]


def make_package(
    repo: Path,
    name: str = "web",
    *,
    eslint: bool = True,
    config: bool = True,
    modules: bool = True,
) -> Path:
    write(repo, ".gitignore", "node_modules/\n")
    package = repo / name
    write(package, "package.json", '{"name": "web"}\n')
    if config:
        write(package, "eslint.config.js", "export default [];\n")
    if modules:
        for module in ("typescript-eslint", "@eslint/js"):
            write(package, f"node_modules/{module}/package.json", "{}\n")
    if eslint:
        make_fake(package / "node_modules/.bin/eslint", FAKE_ESLINT)
    return package


def eslint_message(line: int, rule: str | None, severity: int = 2) -> dict:
    return {
        "ruleId": rule,
        "severity": severity,
        "message": f"problem {rule}",
        "line": line,
        "column": 1,
    }


def test_ts_overlay_strict_and_changed_line_filter(
    repo: Path,
    log_dir: Path,
) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "const a = 1;\nconst b = 2;\nconst c = 3;\n")
    commit_all(repo)
    write(package, "src/a.ts", "const a = 1;\nconst b = 2;\nconst c = 4;\n")
    messages = [
        eslint_message(1, "no-unused-vars"),
        eslint_message(3, "@typescript-eslint/no-magic-numbers", 1),
        eslint_message(3, None),
        eslint_message(3, "off-rule", 0),
    ]

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"FAKE_MESSAGES": json.dumps(messages)},
    )

    found = violations(run)
    assert found == {
        ("web/src/a.ts", 3, "@typescript-eslint/no-magic-numbers"),
        ("web/src/a.ts", 3, "eslint"),
    }
    assert run.code == EXIT_FAIL
    calls = records(package / "node_modules/.bin/eslint")
    assert len(calls) == 1
    call = calls[0]
    assert call["cwd"] == str(package.resolve())
    assert "--no-warn-ignored" in call["argv"]
    assert call["argv"][call["argv"].index("--format") + 1] == "json"
    overlay = call["overlay"]
    assert (package / "eslint.config.js").resolve().as_uri() in overlay
    assert "strictTypeChecked" in overlay
    assert "stylisticTypeChecked" in overlay
    assert "projectService" in overlay


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_overlay_passes_node_check(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir)

    overlay = tmp_path / "overlay.mjs"
    overlay.write_text(
        records(package / "node_modules/.bin/eslint")[0]["overlay"],
        encoding="utf-8",
    )
    done = subprocess.run(
        ["node", "--check", str(overlay)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_missing_package_eslint_is_not_checked(
    repo: Path,
    log_dir: Path,
) -> None:
    package = make_package(repo, eslint=False)
    write(package, "src/a.ts", "const a = 1;\n")

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_PASS, run.out
    checked = {(i["path"], i["tool"]) for i in run.json()["not_checked"]}
    assert ("web/src/a.ts", "eslint") in checked


JS_DEFAULT_STYLE = (
    'const a = "x";\nconst b = "y";\nconst c = "z";\n'
    "const d = \"w\";\nconst e = 'v';\n"
)


def test_prettier_fmt_only_on_changed_lines(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    package = make_package(repo, eslint=False)
    write(package, "a.js", JS_DEFAULT_STYLE)
    commit_all(repo)
    write(package, "a.js", JS_DEFAULT_STYLE.replace('"x";', "'q';"))

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_PRETTIER": str(prettier)},
    )

    assert {
        line
        for path, line, rule in violations(run)
        if rule == "FMT" and path == "web/a.js"
    } == {1}
    assert run.code == EXIT_FAIL


def test_prettier_combo_follows_file_style(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    package = make_package(repo, eslint=False)
    write(package, "a.js", "const a = 'x'\nconst b = 'y'\n")
    commit_all(repo)
    current = "const a = 'x'\nconst b = 'y'\nconst c = 'z'\n"
    write(package, "a.js", current)

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_PRETTIER": str(prettier)},
    )

    assert "FMT" not in rules_at(run, "web/a.js")
    final = [c for c in records(prettier) if c["stdin"] == current]
    assert final
    assert {"--single-quote", "--no-semi"} <= set(final[-1]["argv"])


JS_NEVER_PRETTIER_FORMATTED = "".join(
    f"const v{i} = 'x';\n" if i % 2 else f'const v{i} = "x"\n'
    for i in range(10)
)


def test_prettier_skips_file_unformatted_at_head(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    package = make_package(repo, eslint=False)
    write(package, "a.js", JS_NEVER_PRETTIER_FORMATTED)
    commit_all(repo)
    write(
        package,
        "a.js",
        JS_NEVER_PRETTIER_FORMATTED.replace("const v0", "const w0"),
    )

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_PRETTIER": str(prettier)},
    )

    assert "FMT" not in rules_at(run, "web/a.js")
    assert ("web/a.js", "prettier") in not_checked_reasons(run)
    assert run.code == EXIT_PASS, run.out


def test_prettier_skips_new_file_when_siblings_unformatted(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    package = make_package(repo, eslint=False)
    write(package, "a.js", JS_NEVER_PRETTIER_FORMATTED)
    write(package, "b.js", JS_NEVER_PRETTIER_FORMATTED)
    commit_all(repo)
    write(package, "c.js", "const c = 'x';\n")

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_PRETTIER": str(prettier)},
    )

    assert "FMT" not in rules_at(run, "web/c.js")
    assert ("web/c.js", "prettier") in not_checked_reasons(run)
    assert run.code == EXIT_PASS, run.out


def test_package_prettier_config_uses_package_prettier(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fallback = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    package = make_package(repo, eslint=False)
    write(package, ".prettierrc", "{}\n")
    own = make_fake(package / "node_modules/.bin/prettier", FAKE_PRETTIER)
    write(package, "a.js", 'const a = "x";\n')

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_PRETTIER": str(fallback)},
    )

    assert run.code == EXIT_PASS, run.out
    assert records(own)
    assert not records(fallback)
    assert all("--single-quote" not in c["argv"] for c in records(own))


C_SOURCE = '#include "util.h"\n\nint main(void)\n{\n    return 0;\n}\n'


def make_c_repo(repo: Path, *, relative: bool = True) -> Path:
    write(repo, "src/util.h", "#define UTIL 1\nint util(void);\n")
    write(repo, "src/main.c", C_SOURCE)
    build = repo / "build"
    source = "../src/main.c" if relative else str(repo / "src/main.c")
    entry = {
        "directory": str(build),
        "file": source,
        "arguments": ["gcc", "-std=c99", "-c", source],
    }
    write(build, "compile_commands.json", json.dumps([entry]))
    commit_all(repo)
    return build


def tidy_env(fake: Path, output: str = "", **extra: str) -> dict[str, str]:
    env = {"LINT_STRICT_CLANG_TIDY": str(fake), "FAKE_TIDY_OUTPUT": output}
    env.update(extra)
    return env


def test_clang_tidy_macro_notes_filter(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo)
    main = repo / "src/main.c"
    write(repo, "src/main.c", C_SOURCE.replace("return 0;", "return 7;"))
    sdk = tmp_path / "sdk/fw.h"
    output = (
        f"{main}:5:12: warning: magic from sdk [readability-magic-numbers]\n"
        f"{sdk}:1:9: note: expanded from macro 'FW'\n"
        f"{main}:5:5: warning: tracked macro [bugprone-branch-clone]\n"
        f"{repo / 'src/util.h'}:1:9: note: expanded from macro 'UTIL'\n"
        f"{main}:1:1: warning: unchanged line [misc-include-cleaner]\n"
    )

    run = lint(repo, log_dir, "--json", extra_env=tidy_env(fake, output))

    assert violations(run) == {("src/main.c", 5, "bugprone-branch-clone")}
    item = run.json()["violations"][0]
    assert item["url"] == (
        "https://clang.llvm.org/extra/clang-tidy/checks/bugprone/"
        "branch-clone.html"
    )
    argv = records(fake)[0]["argv"]
    assert argv[argv.index("-p") + 1] == str(repo / "build")
    assert "--extra-arg=-Wpedantic" in argv
    assert run.code == EXIT_FAIL


def test_no_compile_db_is_not_checked(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    write(repo, "lone.c", "int lone(void) { return 0; }\n")

    run = lint(repo, log_dir, "--json", extra_env=tidy_env(fake))

    assert run.code == EXIT_PASS, run.out
    reasons = {
        (i["path"], i["tool"]): i["reason"] for i in run.json()["not_checked"]
    }
    assert "compile_commands.json" in reasons["lone.c", "clang-tidy"]
    assert not records(fake)


def test_changed_header_checked_through_including_unit(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo)
    header = repo / "src/util.h"
    write(repo, "src/util.h", "#define UTIL 2\nint util(void);\n")
    output = (
        f"{header}:1:14: warning: in header [readability-magic-numbers]\n"
        f"{repo / 'src/main.c'}:5:5: warning: in unit [misc-x]\n"
    )

    run = lint(repo, log_dir, "--json", extra_env=tidy_env(fake, output))

    assert violations(run) == {
        ("src/util.h", 1, "readability-magic-numbers"),
    }
    argv = records(fake)[0]["argv"]
    assert f"--header-filter={re.escape(str(header))}" in argv
    assert argv[-1] == str(repo / "src/main.c")


def test_staged_partial_c_file_uses_vfs_overlay(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo)
    staged = C_SOURCE.replace("return 0;", "return 7;")
    write(repo, "src/main.c", staged)
    git(repo, "add", "src/main.c")
    write(repo, "src/main.c", staged + "\nint extra(void);\n")

    lint(repo, log_dir, "--staged", "--json", extra_env=tidy_env(fake))

    calls = records(fake)
    assert len(calls) == 1
    overlay = calls[0]["overlay"]
    assert overlay is not None
    assert overlay["yaml"]["version"] == 0
    assert overlay["contents"] == {str(repo / "src/main.c"): staged}


def make_zephyr(repo: Path) -> Path:
    base = repo / "zephyr"
    fake = make_fake(base / "scripts/checkpatch.pl", FAKE_CHECKPATCH)
    write(base, "scripts/checkpatch/typedefsfile", "u8\n")
    write(
        base,
        ".checkpatch.conf",
        "--emacs\n--typedefsfile=scripts/checkpatch/typedefsfile\n",
    )
    write(repo, ".gitignore", "*.records/\n")
    write(repo, "app/main.c", "int a;\nint b;\nint c;\n")
    commit_all(repo)
    return fake


def test_zephyr_checkpatch(repo: Path, log_dir: Path) -> None:
    fake = make_zephyr(repo)
    write(repo, "app/main.c", "int a;\nint b;\nint cc;\n")
    output = (
        "app/main.c:3: WARNING:LONG_LINE: line too long\n"
        "app/main.c:1: WARNING:SPACING: unchanged\n"
    )

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"FAKE_CHECKPATCH_OUTPUT": output},
    )

    assert violations(run) == {("app/main.c", 3, "checkpatch:LONG_LINE")}
    call = records(fake)[0]
    assert not Path(call["cwd"]).is_relative_to(repo)
    typedefs = repo / "zephyr/scripts/checkpatch/typedefsfile"
    assert f"--typedefsfile={typedefs}" in call["conf"].splitlines()
    assert "--showfile" in call["conf"].splitlines()
    assert INDENT_IGNORE in call["conf"].splitlines()
    assert "+int cc;" in call["stdin"]
    assert run.code == EXIT_FAIL


CLANG_STYLE = "BasedOnStyle: LLVM\n"
NO_C_STYLE = "no project C style (.clang-format)"
INDENT_IGNORE = (
    "--ignore=LEADING_SPACE,CODE_INDENT,SUSPECT_CODE_INDENT,TABSTOP,"
    "SPACE_BEFORE_TAB,INDENTED_LABEL,SWITCH_CASE_INDENT_LEVEL,"
    "PARENTHESIS_ALIGNMENT"
)
C_FORMATTED = (
    "int a(void) { return 1; }\n\nint b(void) { return 2; }\n\n"
    "int  d  (void){return 4;}\n"
)


@pytest.mark.skipif(
    shutil.which("clang-format") is None,
    reason="clang-format missing",
)
def test_real_clang_format_fmt_on_changed_lines(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, ".clang-format", CLANG_STYLE)
    write(repo, "fmt.c", C_FORMATTED)
    commit_all(repo)
    write(repo, "fmt.c", C_FORMATTED.replace("int a(", "int   a("))
    real = {"LINT_STRICT_CLANG_FORMAT": str(shutil.which("clang-format"))}

    run = lint(repo, log_dir, "--json", extra_env=real)

    assert {line for path, line, rule in violations(run) if rule == "FMT"} == {
        1
    }


@pytest.mark.skipif(
    shutil.which("clang-format") is None,
    reason="clang-format missing",
)
def test_no_clang_style_is_not_checked(repo: Path, log_dir: Path) -> None:
    write(repo, "fmt.c", C_FORMATTED)
    real = {"LINT_STRICT_CLANG_FORMAT": str(shutil.which("clang-format"))}

    run = lint(repo, log_dir, "--json", extra_env=real)

    reasons = {
        (i["path"], i["tool"]): i["reason"] for i in run.json()["not_checked"]
    }
    assert reasons["fmt.c", "clang-format"] == NO_C_STYLE


@pytest.mark.skipif(
    shutil.which("prettier") is None
    and not Path.home().joinpath(".claude/tools/node").is_dir(),
    reason="prettier missing",
)
def test_real_ts_package_without_node_modules(
    repo: Path,
    log_dir: Path,
) -> None:
    package = make_package(repo, eslint=False, modules=False)
    write(package, "src/a.ts", "export const a = 1;\n")
    env = {"LINT_STRICT_PRETTIER": ""}

    run = lint(repo, log_dir, "--json", extra_env=env)

    checked = {(i["path"], i["tool"]) for i in run.json()["not_checked"]}
    assert ("web/src/a.ts", "eslint") in checked
    assert "FMT" not in rules_at(run, "web/src/a.ts")


@pytest.mark.skipif(
    shutil.which("clang-tidy") is None,
    reason="clang-tidy missing",
)
def test_real_clang_tidy_reports_missing_braces(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "calc.c",
        "int scale(int value)\n{\n    if (value > 0) return 1;\n"
        "    return 0;\n}\n",
    )
    entry = {
        "directory": str(repo),
        "file": "calc.c",
        "arguments": ["gcc", "-std=c99", "-c", "calc.c"],
    }
    write(repo, "compile_commands.json", json.dumps([entry]))
    real = {"LINT_STRICT_CLANG_TIDY": str(shutil.which("clang-tidy"))}

    run = lint(repo, log_dir, "--json", extra_env=real)

    rules = rules_at(run, "calc.c")
    assert "readability-braces-around-statements" in rules, run.out
    assert run.code == EXIT_FAIL
    header = lint(repo, log_dir, extra_env=real).out.splitlines()[0]
    assert "clang-tidy" in header


@pytest.mark.skipif(
    shutil.which("clang-tidy") is None,
    reason="clang-tidy missing",
)
def test_real_clang_tidy_staged_partial_reports_index_content(
    repo: Path,
    log_dir: Path,
) -> None:
    body = (
        "int scale(int value)\n{{\n    if (value > 0) {open}return 1;{close}\n"
        "    return 0;\n}}\n"
    )
    braced = body.format(open="{ ", close=" }")
    bare = body.format(open="", close="")
    write(repo, "calc.c", braced)
    entry = {
        "directory": str(repo),
        "file": "calc.c",
        "arguments": ["gcc", "-std=c99", "-c", "calc.c"],
    }
    write(repo, "compile_commands.json", json.dumps([entry]))
    commit_all(repo)
    write(repo, "calc.c", bare)
    git(repo, "add", "calc.c")
    write(repo, "calc.c", braced + "\n")
    real = {"LINT_STRICT_CLANG_TIDY": str(shutil.which("clang-tidy"))}

    run = lint(repo, log_dir, "--staged", "--json", extra_env=real)

    assert ("calc.c", 3, "readability-braces-around-statements") in violations(
        run
    )
    assert run.code == EXIT_FAIL


EXEMPT_C_SOURCE = (
    "void delay(int ms);\n"
    "void lv_obj_set_size(void *o, int w, int h);\n"
    "int run(void *o, int *buf, int v, int h)\n"
    "{\n"
    "    int x;\n"
    "    int y;\n"
    "    int s;\n"
    "    delay(DEBOUNCE_MS);\n"
    "    lv_obj_set_size(o, 26, 26);\n"
    "    x = buf[12];\n"
    "    y = v >> 4;\n"
    "    s = h * 3600;\n"
    "    return x + y + s;\n"
    "}\n"
)
MAGIC_RULE_NAMES = {
    "readability-magic-numbers",
    "cppcoreguidelines-avoid-magic-numbers",
    "MAG001",
    "MAG002",
    "MAG003",
}


def real_tidy_env(
    repo: Path,
    name: str,
    compiler: str = "gcc",
    standard: str = "c99",
) -> dict[str, str]:
    entry = {
        "directory": str(repo),
        "file": name,
        "arguments": [compiler, f"-std={standard}", "-c", name],
    }
    write(repo, "compile_commands.json", json.dumps([entry]))
    return {"LINT_STRICT_CLANG_TIDY": str(shutil.which("clang-tidy"))}


@pytest.mark.skipif(
    shutil.which("clang-tidy") is None,
    reason="clang-tidy missing",
)
def test_exempt_c_contexts_report_no_magic_number(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.c", EXEMPT_C_SOURCE)
    real = real_tidy_env(repo, "a.c")

    run = lint(repo, log_dir, "--json", extra_env=real)

    assert not rules_at(run, "a.c") & MAGIC_RULE_NAMES
    assert "clang-tidy" in lint(repo, log_dir, extra_env=real).out


@pytest.mark.skipif(
    shutil.which("clang-tidy") is None,
    reason="clang-tidy missing",
)
def test_clang_tidy_no_longer_reports_magic_numbers_in_cpp(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "a.cpp",
        "void delay(int ms);\nvoid run()\n{\n    delay(DEBOUNCE_MS);\n}\n",
    )
    real = real_tidy_env(repo, "a.cpp", "g++", "c++17")

    run = lint(repo, log_dir, "--json", extra_env=real)

    assert not rules_at(run, "a.cpp") & MAGIC_RULE_NAMES
    assert "clang-tidy" in lint(repo, log_dir, extra_env=real).out


C_COMPARISON_SOURCE = (
    "int f(int temp)\n{\n    if (temp > 37) {\n        return 1;\n    }\n"
    "    return 0;\n}\n"
)
TS_COMPARISON_SOURCE = (
    "export function f(temp: number): number {\n  if (temp > 37) {\n"
    "    return 1;\n  }\n  return 0;\n}\n"
)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (
            "src/a.c",
            C_COMPARISON_SOURCE,
        ),
        (
            "src/a.cpp",
            C_COMPARISON_SOURCE,
        ),
        (
            "src/a.ts",
            TS_COMPARISON_SOURCE,
        ),
    ],
)
def test_comparison_with_magic_number_reports_mag001(
    repo: Path,
    log_dir: Path,
    name: str,
    text: str,
) -> None:
    write(repo, name, text)

    run = lint(repo, log_dir, "--json")

    found = [item for item in run.json()["violations"] if item["path"] == name]
    assert [(item["line"], item["rule"]) for item in found] == [
        (3 if name.endswith(("c", "cpp")) else 2, "MAG001")
    ]
    assert found[0]["tool"] == "magic-numbers"
    assert run.code == EXIT_FAIL


def test_python_comparison_is_left_to_ruff(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", "def f(x: int) -> bool:\n    return x > 37\n")

    run = lint(repo, log_dir, "--json")

    assert not rules_at(run, "a.py") & MAGIC_RULE_NAMES


DELAY_CASES = [
    ("a.cpp", "void delay(int ms);\nvoid run()\n{\n    delay(200);\n}\n", 4),
    ("a.c", "void run(void)\n{\n    k_sleep(K_MSEC(10));\n}\n", 3),
    ("a.ts", "export function run(): void {\n  setTimeout(fn, 500);\n}\n", 2),
    ("a.py", "import time\n\n\ndef run() -> None:\n    time.sleep(5)\n", 5),
]


@pytest.mark.parametrize(("name", "text", "line"), DELAY_CASES)
def test_delay_literal_reports_mag003(
    repo: Path,
    log_dir: Path,
    name: str,
    text: str,
    line: int,
) -> None:
    write(repo, name, text)

    run = lint(repo, log_dir, "--json")

    assert (name, line, "MAG003") in violations(run)


@pytest.mark.parametrize(
    "statement",
    [
        "delay(0);",
        "delay(DEBOUNCE_MS);",
        "delay(200); // debounce of the relay contact",
        "// relay needs 200 ms to settle\n    delay(200);",
    ],
)
def test_named_or_explained_delay_reports_no_mag003(
    repo: Path,
    log_dir: Path,
    statement: str,
) -> None:
    write(repo, "a.cpp", f"void run()\n{{\n    {statement}\n}}\n")

    run = lint(repo, log_dir, "--json")

    assert "MAG003" not in rules_at(run, "a.cpp")


def test_scaled_delay_reports_only_the_unscaled_literal(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.c", "void run(void)\n{\n    sleep(5 * 60);\n}\n")

    run = lint(repo, log_dir, "--json")

    found = [
        item["message"]
        for item in run.json()["violations"]
        if item["rule"] == "MAG003"
    ]
    assert found == ["magic number in a delay: 5 \u2014 name it as a constant"]


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (
            "a.c",
            "int f(int temp)\n{\n    return temp > 37; // fever limit\n}\n",
        ),
        ("a.ts", "export const f = (t: number) => t > 37; // fever limit\n"),
    ],
)
def test_commented_comparison_reports_no_mag001(
    repo: Path,
    log_dir: Path,
    name: str,
    text: str,
) -> None:
    write(repo, name, text)

    run = lint(repo, log_dir, "--json")

    assert "MAG001" not in rules_at(run, name)


def test_delay_callback_body_is_not_a_delay_argument_integration(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "a.ts",
        "export function run(): void {\n"
        "  setTimeout(() => { counter = 37; }, 500);\n"
        "}\n",
    )

    run = lint(repo, log_dir, "--json")

    found = [
        item["message"]
        for item in run.json()["violations"]
        if item["rule"] == "MAG003"
    ]
    assert found == [
        "magic number in a delay: 500 \u2014 name it as a constant"
    ]


REPEATED_SOURCES = {
    "a.py": (
        "def f(base: int) -> int:\n"
        "    first = base + 77\n"
        "    second = base - 77\n"
        "    return first + second + 77\n"
    ),
    "a.ts": (
        "export const f = (base: number): number => {\n"
        "  const first = base + 77;\n"
        "  const second = base - 77;\n"
        "  return first + second + 77;\n"
        "};\n"
    ),
    "a.c": (
        "int f(int base)\n"
        "{\n"
        "    int first = base + 77;\n"
        "    int second = base - 77;\n"
        "    return first + second + 77;\n"
        "}\n"
    ),
}


@pytest.mark.parametrize("name", sorted(REPEATED_SOURCES))
def test_value_on_three_lines_reports_mag002(
    repo: Path,
    log_dir: Path,
    name: str,
) -> None:
    write(repo, name, REPEATED_SOURCES[name])

    run = lint(repo, log_dir, "--json")

    found = sorted(
        item["line"]
        for item in run.json()["violations"]
        if item["path"] == name and item["rule"] == "MAG002"
    )
    assert found == ([2, 3, 4] if name != "a.c" else [3, 4, 5])


def test_value_on_two_lines_reports_no_mag002(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "a.py",
        "def f(base: int) -> int:\n    first = base + 77\n"
        "    return first - 77\n",
    )

    run = lint(repo, log_dir, "--json")

    assert not rules_at(run, "a.py") & MAGIC_RULE_NAMES


@pytest.mark.parametrize(
    "name", ["src/a.test.ts", "tests/test_a.py", "src/a_test.c"]
)
def test_magic_backend_ignores_test_files(
    repo: Path,
    log_dir: Path,
    name: str,
) -> None:
    body = (
        "if (a > 37) {}\n" if name.endswith((".ts", ".c")) else "x = a > 37\n"
    )
    write(repo, name, body)

    run = lint(repo, log_dir, "--json")

    assert not rules_at(run, name) & MAGIC_RULE_NAMES


def test_magic_backend_reads_index_text_in_staged_mode(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.c", "int f(int t)\n{\n    return t > 37;\n}\n")
    git(repo, "add", "a.c")
    write(repo, "a.c", "int f(int t)\n{\n    return t > 0;\n}\n")

    run = lint(repo, log_dir, "--staged", "--json")

    assert ("a.c", 3, "MAG001") in violations(run)


def overlay_plan(
    ls: ModuleType,
    package: Path,
    *,
    config: bool = True,
    recommended: bool = True,
    strict: bool = True,
) -> object:
    return ls.OverlayPlan(
        package=package,
        config=package / "eslint.config.mjs" if config else None,
        recommended=recommended,
        strict=strict,
    )


def test_overlay_source_contents(ls: ModuleType, tmp_path: Path) -> None:
    full = ls.overlay_source(overlay_plan(ls, tmp_path))
    bare = ls.overlay_source(
        overlay_plan(
            ls,
            tmp_path,
            config=False,
            recommended=False,
            strict=False,
        ),
    )

    assert json.dumps((tmp_path / "eslint.config.mjs").as_uri()) in full
    assert json.dumps(str(tmp_path / "package.json")) in full
    assert "if (true) {" in full
    assert "const configUrl = null;" in bare
    assert "if (true)" not in bare
    assert "$" not in full
    assert '"max-depth": ["error", 3]' in bare
    assert "explicit-function-return-type" in full


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_overlay_evaluates_to_layered_config(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    package = tmp_path / "pkg"
    write(package, "package.json", '{"name": "pkg"}\n')
    write(package, "eslint.config.mjs", 'export default [{name: "own"}];\n')
    modules = {
        "@eslint/js": (
            'module.exports = {configs: {recommended: {name: "rec"}}};'
        ),
        "typescript-eslint": (
            "module.exports = {configs: {"
            'strictTypeChecked: [{name: "s1"}, {name: "s2", files: ["x"]}],'
            'stylisticTypeChecked: [{name: "st"}]}};'
        ),
    }
    for name, source in modules.items():
        write(
            package,
            f"node_modules/{name}/package.json",
            '{"main": "index.js"}',
        )
        write(package, f"node_modules/{name}/index.js", source)
    overlay = tmp_path / "overlay.mjs"
    overlay.write_text(
        ls.overlay_source(overlay_plan(ls, package)),
        encoding="utf-8",
    )
    script = (
        f"import({json.dumps(overlay.as_uri())})"
        ".then(m => console.log(JSON.stringify(m.default)))"
    )

    done = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )

    configs = json.loads(done.stdout)
    ts_files = list(ls.TS_GLOBS)
    assert [c.get("name") for c in configs] == [
        "own",
        "rec",
        "s1",
        "s2",
        "st",
        None,
        None,
    ]
    assert configs[1]["files"] == [*ls.TS_GLOBS, *ls.JS_GLOBS]
    assert configs[2]["files"] == ts_files
    assert configs[3]["files"] == ["x"]
    assert configs[5]["languageOptions"]["parserOptions"] == {
        "projectService": True,
        "tsconfigRootDir": str(package),
    }
    assert configs[5]["rules"] == {
        "@typescript-eslint/explicit-function-return-type": "error",
        "@typescript-eslint/explicit-module-boundary-types": "error",
    }
    assert configs[6] == {
        "files": [*ls.TS_GLOBS, *ls.JS_GLOBS],
        "rules": {
            "complexity": ["error", 10],
            "max-depth": ["error", 3],
            "max-lines-per-function": [
                "error",
                {"max": 60, "skipBlankLines": True, "skipComments": True},
            ],
            "max-params": ["error", 4],
            "max-nested-callbacks": ["error", 3],
        },
    }


def test_parse_eslint_shapes(ls: ModuleType) -> None:
    plain = json.dumps(
        [
            {
                "filePath": "/r/a.ts",
                "messages": [eslint_message(2, None), eslint_message(3, "r")],
            },
        ],
    )
    with_meta = json.dumps(
        {
            "results": [
                {"filePath": "/r/b.js", "messages": [eslint_message(1, "r")]},
            ],
            "metadata": {"rulesMeta": {"r": {"docs": {"url": "https://r"}}}},
        },
    )

    parsed = ls.parse_eslint(plain)
    meta = ls.parse_eslint(with_meta)

    assert [(m.file, m.line, m.rule, m.url) for m in parsed] == [
        ("/r/a.ts", 2, "eslint", ""),
        ("/r/a.ts", 3, "r", ""),
    ]
    assert [(m.rule, m.url) for m in meta] == [("r", "https://r")]
    assert ls.parse_eslint("Oops, crashed") is None


def test_parse_clang_tidy_attaches_notes(ls: ModuleType) -> None:
    output = (
        "/r/a.c:3:5: warning: magic [readability-magic-numbers,cert-x]\n"
        "    3 | int x = 42;\n"
        "/sdk/fw.h:1:9: note: expanded from macro 'FW'\n"
        "/r/a.c:9:1: error: bad [clang-diagnostic-error]\n"
        "/r/a.c:10:1: warning: no check\n"
        "12 warnings generated.\n"
    )

    found = ls.parse_clang_tidy(output)

    assert [(d.path, d.line, d.column, d.check) for d in found] == [
        ("/r/a.c", 3, 5, "readability-magic-numbers"),
        ("/r/a.c", 9, 1, "clang-diagnostic-error"),
        ("/r/a.c", 10, 1, "clang-tidy"),
    ]
    assert [(n.path, n.line) for n in found[0].notes] == [("/sdk/fw.h", 1)]
    assert found[1].notes == ()


def test_expanded_from_untracked(ls: ModuleType, tmp_path: Path) -> None:
    tracked = frozenset({tmp_path / "inc/own.h"})
    diagnostic = ls.parse_clang_tidy(
        "a.c:1:1: warning: w [misc-x]\n"
        "../inc/own.h:1:9: note: expanded from macro 'OWN'\n",
    )[0]
    framework = ls.parse_clang_tidy(
        "a.c:1:1: warning: w [misc-x]\n"
        "/sdk/fw.h:1:9: note: expanded from macro 'FW'\n",
    )[0]
    other_note = ls.parse_clang_tidy(
        "a.c:1:1: warning: w [misc-x]\n/sdk/fw.h:1:9: note: declared here\n",
    )[0]
    build = tmp_path / "build"

    assert not ls.expanded_from_untracked(diagnostic, tracked, build)
    assert ls.expanded_from_untracked(framework, tracked, build)
    assert not ls.expanded_from_untracked(other_note, tracked, build)


@pytest.mark.parametrize(
    ("check", "url"),
    [
        (
            "readability-magic-numbers",
            (
                "https://clang.llvm.org/extra/clang-tidy/checks/readability/"
                "magic-numbers.html"
            ),
        ),
        (
            "clang-analyzer-core.NullDereference",
            (
                "https://clang.llvm.org/extra/clang-tidy/checks/"
                "clang-analyzer/core.NullDereference.html"
            ),
        ),
        ("clang-diagnostic-unused-variable", ""),
        ("clang-tidy", ""),
    ],
)
def test_clang_tidy_url(ls: ModuleType, check: str, url: str) -> None:
    assert ls.clang_tidy_url(check) == url


def test_parse_checkpatch(ls: ModuleType) -> None:
    output = (
        "app/main.c:3: WARNING:LONG_LINE: line length of 120 exceeds 100\n"
        "+int cc;\n"
        "dir with space/x.h:7: ERROR:SPACING: need space\n"
        "total: 1 errors, 1 warnings, 3 lines checked\n"
    )

    found = ls.parse_checkpatch(output)

    assert [(v.path, v.line, v.rule) for v in found] == [
        ("app/main.c", 3, "checkpatch:LONG_LINE"),
        ("dir with space/x.h", 7, "checkpatch:SPACING"),
    ]


def test_vfs_overlay_yaml(ls: ModuleType, tmp_path: Path) -> None:
    data = json.loads(
        ls.vfs_overlay_yaml(tmp_path / "a.c", tmp_path / "blob.c"),
    )

    assert data == {
        "version": 0,
        "use-external-names": False,
        "roots": [
            {
                "name": str(tmp_path / "a.c"),
                "type": "file",
                "external-contents": str(tmp_path / "blob.c"),
            },
        ],
    }


def test_compile_db_lookup(ls: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "src/a.c", "int a;\n")
    entries = [{"directory": str(tmp_path / "build"), "file": "../src/a.c"}]
    write(tmp_path, "build/compile_commands.json", json.dumps(entries))
    write(tmp_path, "a/b/c/d/e/compile_commands.json", json.dumps(entries))
    write(tmp_path, "node_modules/compile_commands.json", json.dumps(entries))
    write(tmp_path, "broken/compile_commands.json", "{not json")

    databases = ls.find_compile_dbs(tmp_path)

    assert [db.directory for db in databases] == [tmp_path / "build"]
    entry = databases[0].entry_for((tmp_path / "src/a.c").resolve())
    assert entry is not None
    assert entry.directory == tmp_path / "build"
    assert databases[0].entry_for(tmp_path / "src/b.c") is None


def test_including_unit_prefers_same_directory(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    write(tmp_path, "other/x.c", '#include "lib/util.h"\n')
    write(tmp_path, "lib/y.c", "#  include <util.h>\n")
    write(tmp_path, "lib/z.c", '#include "unrelated.h"\n')
    entries = [
        {"directory": str(tmp_path), "file": name}
        for name in ("other/x.c", "lib/y.c", "lib/z.c")
    ]
    write(tmp_path, "compile_commands.json", json.dumps(entries))
    databases = ls.find_compile_dbs(tmp_path)

    found = ls.including_unit(databases, tmp_path / "lib/util.h")
    missing = ls.including_unit(databases, tmp_path / "lib/none.h")

    assert found is not None
    assert found[1].file == (tmp_path / "lib/y.c").resolve()
    assert missing is None


def test_choose_combo(ls: ModuleType) -> None:
    samples = [ls.Sample("a.js", "const a = 'x'\n")]

    def fake(options: tuple[str, ...], sample: object) -> str:
        assert sample.path == "a.js"
        quote = "'" if "--single-quote" in options else '"'
        end = "" if "--no-semi" in options else ";"
        return f"const a = {quote}x{quote}{end}\n"

    def unchanged(options: tuple[str, ...], sample: object) -> str:
        return sample.text if options is not None else ""

    assert ls.choose_combo(samples, fake) == ("--single-quote", "--no-semi")
    assert ls.choose_combo(samples, unchanged) == ()
    assert ls.choose_combo([], fake) == ()


def test_rewrite_checkpatch_conf(ls: ModuleType, tmp_path: Path) -> None:
    write(tmp_path, "scripts/checkpatch/typedefsfile", "u8\n")
    text = (
        "# comment --typedefsfile=scripts/checkpatch/typedefsfile\n"
        "--emacs\n"
        "--typedefsfile=scripts/checkpatch/typedefsfile\n"
        "--ignore=SPACING,LONG_LINE\n"
        "--codespellfile=/usr/share/codespell\n"
    )

    lines = ls.rewrite_checkpatch_conf(text, tmp_path).splitlines()

    typedefs = tmp_path / "scripts/checkpatch/typedefsfile"
    assert lines == [
        "# comment --typedefsfile=scripts/checkpatch/typedefsfile",
        "--emacs",
        f"--typedefsfile={typedefs}",
        "--ignore=SPACING,LONG_LINE",
        "--codespellfile=/usr/share/codespell",
        "--showfile",
        INDENT_IGNORE,
    ]


def test_find_package_stays_inside_repo(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    write(tmp_path, "package.json", "{}")
    write(root, "web/package.json", "{}")

    inside = ls.find_package(root, root / "web/src/a.ts")
    outside = ls.find_package(root, root / "lib/b.ts")

    assert inside == root / "web"
    assert outside is None


def test_uses_package_prettier(ls: ModuleType, tmp_path: Path) -> None:
    cases = {
        "rc": (".prettierrc.json", "{}"),
        "config": ("prettier.config.mjs", "export default {};"),
    }
    for name, (config, text) in cases.items():
        write(tmp_path / name, "package.json", "{}")
        write(tmp_path / name, config, text)
    write(tmp_path / "key", "package.json", '{"prettier": {}}')
    write(
        tmp_path / "dep",
        "package.json",
        '{"devDependencies": {"prettier": "3"}}',
    )
    write(tmp_path / "none", "package.json", '{"dependencies": {"x": "1"}}')

    used = {
        name: ls.uses_package_prettier(tmp_path / name)
        for name in ("rc", "config", "key", "dep", "none")
    }

    assert used == {
        "rc": True,
        "config": True,
        "key": True,
        "dep": True,
        "none": False,
    }


def not_checked_reasons(run: Run) -> dict[tuple[str, str], str]:
    return {
        (item["path"], item["tool"]): item["reason"]
        for item in run.json()["not_checked"]
    }


def test_package_above_repo_root_is_not_used(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(tmp_path, "package.json", "{}")
    outer = make_fake(tmp_path / "node_modules/.bin/eslint", FAKE_ESLINT)
    write(repo, "a.ts", "const a = 1;\n")

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_PASS, run.out
    assert "package.json" in not_checked_reasons(run)["a.ts", "eslint"]
    assert not records(outer)


def test_eslint_non_json_output_is_not_checked(
    repo: Path,
    log_dir: Path,
) -> None:
    package = make_package(repo, eslint=False)
    make_fake(
        package / "node_modules/.bin/eslint",
        "sys.stderr.write('Error: config broke\\n')\nprint('boom')\n"
        "raise SystemExit(2)\n",
    )
    write(package, "a.js", "const a = 1;\n")

    run = lint(repo, log_dir, "--json")

    assert run.code == EXIT_PASS, run.out
    assert not_checked_reasons(run)["web/a.js", "eslint"] == (
        "Error: config broke"
    )


def test_compile_db_with_absolute_file(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo, relative=False)
    write(repo, "src/main.c", C_SOURCE.replace("return 0;", "return 7;"))
    main = repo / "src/main.c"
    output = f"{main}:5:12: warning: magic [readability-magic-numbers]\n"

    run = lint(repo, log_dir, "--json", extra_env=tidy_env(fake, output))

    assert violations(run) == {("src/main.c", 5, "readability-magic-numbers")}


def test_relative_diagnostic_paths_resolve_against_entry_directory(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo)
    write(repo, "src/main.c", C_SOURCE.replace("return 0;", "return 7;"))
    output = "../src/main.c:5:12: warning: magic [readability-magic-numbers]\n"

    run = lint(repo, log_dir, "--json", extra_env=tidy_env(fake, output))

    assert violations(run) == {("src/main.c", 5, "readability-magic-numbers")}


def test_clang_tidy_crash_is_not_checked(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo)
    write(repo, "src/main.c", C_SOURCE.replace("return 0;", "return 7;"))
    env = tidy_env(
        fake,
        "",
        FAKE_TIDY_EXIT="139",
        FAKE_TIDY_STDERR="Stack dump:\nSegmentation fault\n",
    )

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert run.code == EXIT_PASS, run.out
    reason = not_checked_reasons(run)["src/main.c", "clang-tidy"]
    assert reason == "Stack dump:"


def test_checkpatch_absent_is_skipped(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "zephyr/.checkpatch.conf", "--emacs\n")
    write(repo, "app/main.c", "int a;\n")
    env = {"ZEPHYR_BASE": str(tmp_path / "no-zephyr")}

    run = lint(repo, log_dir, extra_env=env)

    assert run.code == EXIT_PASS, run.out
    assert "checkpatch" not in run.out


def test_zephyr_base_from_environment(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    base = tmp_path / "zephyr-base"
    fake = make_fake(base / "scripts/checkpatch.pl", FAKE_CHECKPATCH)
    write(repo, "app/new.c", "int a;\n")
    output = "app/new.c:1: WARNING:NEW: new file line\n"
    env = {"ZEPHYR_BASE": str(base), "FAKE_CHECKPATCH_OUTPUT": output}

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert violations(run) == {("app/new.c", 1, "checkpatch:NEW")}
    call = records(fake)[0]
    assert "+++ b/app/new.c" in call["stdin"]
    assert "--showfile" in call["conf"].splitlines()


def test_staged_checkpatch_reads_cached_diff(
    repo: Path, log_dir: Path
) -> None:
    fake = make_zephyr(repo)
    write(repo, "app/main.c", "int a;\nint b;\nint staged;\n")
    git(repo, "add", "app/main.c")
    write(repo, "app/main.c", "int a;\nint b;\nint unstaged;\n")

    lint(repo, log_dir, "--staged")

    stdin = records(fake)[0]["stdin"]
    assert "+int staged;" in stdin
    assert "unstaged" not in stdin


def test_nested_configs_walk_up_from_the_file(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    write(
        tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.11"\n'
    )
    write(tmp_path, "a/pyproject.toml", "[tool.ruff]\nline-length = 88\n")
    write(tmp_path, "a/b/pyproject.toml", '[project]\nname = "b"\n')
    write(tmp_path, "a/b/.ruff.toml", "indent-width = 4\n")
    write(tmp_path, "c/ruff.toml", "line-length = 120\n")
    write(
        tmp_path, "c/pyproject.toml", '[project]\nrequires-python = "~=3.13"\n'
    )
    outside = tmp_path.parent / "pyproject.toml"
    deep = tmp_path / "a/b/m.py"

    assert ls.resolve_line_length(tmp_path, deep) == 88
    assert ls.resolve_target_version(tmp_path, deep) == "py311"
    assert ls.resolve_line_length(tmp_path, tmp_path / "c/m.py") == 99
    assert ls.resolve_target_version(tmp_path, tmp_path / "c/m.py") == "py313"
    assert ls.resolve_line_length(tmp_path, tmp_path / "m.py") == 79
    assert not outside.exists()


def test_paths_are_relative_to_the_repo_directory(
    repo: Path,
    log_dir: Path,
) -> None:
    undocumented = '"""X."""\n\n\ndef f(a):\n    return a\n'
    write(repo, "sub/x.py", CLEAN_MODULE)
    write(repo, "other.py", CLEAN_MODULE)
    commit_all(repo)
    write(repo, "sub/x.py", undocumented)
    write(repo, "other.py", undocumented)
    sub = repo / "sub"

    top = lint(repo, log_dir, "--tracked", "--paths", "sub/x.py", "--json")
    nested = lint(sub, log_dir, "--tracked", "--paths", "x.py", "--json")
    parent = lint(
        sub, log_dir, "--tracked", "--paths", "../other.py", "--json"
    )
    absolute = lint(
        sub,
        log_dir,
        "--tracked",
        "--paths",
        str(repo / "other.py"),
        "--json",
    )
    escaping = lint(sub, log_dir, "--tracked", "--paths", "../../x.py")

    assert top.code == EXIT_FAIL
    assert nested.code == EXIT_FAIL, nested.out
    assert {path for path, _, _ in violations(nested)} == {"sub/x.py"}
    assert {path for path, _, _ in violations(parent)} == {"other.py"}
    assert {path for path, _, _ in violations(absolute)} == {"other.py"}
    assert escaping.code == EXIT_USAGE


FAKE_RUFF = """
real = os.environ["REAL_RUFF"]
record({"argv": sys.argv[1:]})
os.execv(real, [real, *sys.argv[1:]])
"""

SIM_MODULE = (
    '"""Sim."""\n\n\ndef parse(text: str) -> int | None:\n'
    '    """Parse text as an integer."""\n    try:\n'
    "        return int(text)\n    except (ValueError, TypeError):\n"
    "        return None\n"
)


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff missing")
def test_nested_pyproject_sets_target_version(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/ruff", FAKE_RUFF)
    write(
        repo, "sim/pyproject.toml", '[project]\nrequires-python = "==3.12.*"\n'
    )
    write(repo, "sim/m.py", SIM_MODULE)
    write(repo, "top.py", SIM_MODULE)
    env = {
        "LINT_STRICT_RUFF": str(fake),
        "REAL_RUFF": str(shutil.which("ruff")),
    }

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert "FMT" not in rules_at(run, "sim/m.py")
    assert "FMT" in rules_at(run, "top.py")
    targets = {}
    for call in records(fake):
        argv = call["argv"]
        if "--target-version" not in argv:
            continue
        version = argv[argv.index("--target-version") + 1]
        for name in ("sim/m.py", "top.py"):
            if any(arg.endswith(name) for arg in argv):
                targets.setdefault(name, set()).add(version)
    current = f"py3{sys.version_info.minor}"
    assert targets == {"sim/m.py": {"py312"}, "top.py": {current}}


def test_nested_ruff_toml_sets_line_length(repo: Path, log_dir: Path) -> None:
    write(repo, "tools/ruff.toml", "line-length = 100\n")
    write(repo, "tools/lines.py", long_lines_module())
    write(repo, "lines.py", long_lines_module())

    run = lint(repo, log_dir, "--json")

    found = violations(run)
    nested = {
        line
        for path, line, rule in found
        if path == "tools/lines.py" and rule == "E501"
    }
    top = {
        line
        for path, line, rule in found
        if path == "lines.py" and rule == "E501"
    }
    assert nested == {5}
    assert top == {3, 4, 5}


def test_zephyr_has_no_clang_format_fallback(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    make_zephyr(repo)
    write(repo, "zephyr/.clang-format", CLANG_STYLE)
    commit_all(repo)
    write(repo, "app/main.c", "int a;\nint b;\nint cc;\n")
    formatter = make_fake(tmp_path / "tools/clang-format", "print('x')\n")
    env = {"LINT_STRICT_CLANG_FORMAT": str(formatter)}

    run = lint(repo, log_dir, "--json", extra_env=env)

    reasons = not_checked_reasons(run)
    assert reasons["app/main.c", "clang-format"] == NO_C_STYLE
    assert not records(formatter)


REAL_MYPY = {"LINT_STRICT_MYPY": ""}
NEEDS_UVX = pytest.mark.skipif(shutil.which("uvx") is None, reason="no uvx")
NEEDS_CLANG_TIDY = pytest.mark.skipif(
    shutil.which("clang-tidy") is None,
    reason="clang-tidy missing",
)
MYPY_BROKEN = (
    '\n\ndef broken() -> int:\n    """Return a number."""\n    return "x"\n'
)
MYPY_BROKEN_LINE = 8


def mypy_rules(run: Run) -> set[tuple[str, int, str]]:
    return {item for item in violations(run) if item[2].startswith("mypy:")}


@NEEDS_UVX
def test_mypy_error_on_changed_line_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    append(repo, "base.py", MYPY_BROKEN)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert ("base.py", MYPY_BROKEN_LINE, "mypy:return-value") in violations(
        run
    ), run.out
    assert run.code == EXIT_FAIL


@NEEDS_UVX
def test_mypy_error_on_unchanged_line_is_ignored(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "mod.py", '"""Mod."""' + MYPY_BROKEN)
    commit_all(repo)
    append(repo, "mod.py", DOCUMENTED)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)
    text = lint(repo, log_dir, extra_env=REAL_MYPY)

    assert not mypy_rules(run), run.out
    assert ("mod.py", "mypy") not in not_checked_reasons(run)
    assert "mypy" in text.out.splitlines()[0]


@NEEDS_UVX
def test_mypy_error_in_test_file_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "tests/test_value.py",
        'def test_value() -> None:\n    value: int = "x"\n    assert value\n',
    )

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert ("tests/test_value.py", 2, "mypy:assignment") in mypy_rules(run)


def test_missing_mypy_is_not_checked(repo: Path, log_dir: Path) -> None:
    append(repo, "base.py", DOCUMENTED)
    missing = {"LINT_STRICT_MYPY": NO_TOOL}

    run = lint(repo, log_dir, "--json", extra_env=missing)

    assert "mypy" in not_checked_reasons(run)["base.py", "mypy"]
    assert run.code == EXIT_PASS


def test_missing_return_annotation_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    append(
        repo,
        "base.py",
        "\n\nfrom typing import Any\n\n\n"
        'def untyped(value):\n    """Return value."""\n    return value\n\n\n'
        'def loose(value: Any) -> int:\n    """Return one."""\n'
        "    return 1 if value else 0\n",
    )

    rules = rules_at(lint(repo, log_dir, "--json"), "base.py")

    assert {"ANN201", "ANN001", "ANN401"} <= rules


def branchy_function(branches: int) -> str:
    body = "".join(
        f"    if value == {index}:\n        return {index}\n"
        for index in range(1, branches)
    )
    return (
        '"""Branchy."""\n\n\ndef pick(value: int) -> int:\n'
        f'    """Pick a value."""\n{body}    return 0\n'
    )


def test_complexity_above_limit_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "branchy.py", branchy_function(11))

    assert "C901" in rules_at(lint(repo, log_dir, "--json"), "branchy.py")


def test_complexity_at_limit_passes(repo: Path, log_dir: Path) -> None:
    write(repo, "branchy.py", branchy_function(10))

    assert "C901" not in rules_at(lint(repo, log_dir, "--json"), "branchy.py")


TOOLCHAIN_DIR = Path.home() / ".cache" / "claude-lint-strict-tests" / "node"
TOOLCHAIN_PACKAGES = (
    "typescript@5.9",
    "eslint@9",
    "typescript-eslint@8",
    "@eslint/js@9",
)
TOOLCHAIN_BINARIES = ("tsc", "eslint")
TS_CONFIG = (
    '{"compilerOptions": {"strict": true, "noEmit": true, '
    '"target": "es2022", "module": "nodenext"}, "include": ["src"]}\n'
)
REAL_TS_TOOLS = {"LINT_STRICT_TSC": ""}


@pytest.fixture(scope="session")
def node_toolchain() -> Path:
    if shutil.which("node") is None or shutil.which("npm") is None:
        pytest.skip("node or npm missing")
    modules = TOOLCHAIN_DIR / "node_modules"
    if all((modules / ".bin" / name).exists() for name in TOOLCHAIN_BINARIES):
        return modules
    write(TOOLCHAIN_DIR, "package.json", '{"private": true}\n')
    done = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund", *TOOLCHAIN_PACKAGES],
        cwd=TOOLCHAIN_DIR,
        capture_output=True,
        check=False,
    )
    if done.returncode:
        pytest.skip("cannot install the TypeScript toolchain")
    return modules


def make_ts_package(repo: Path, modules: Path) -> Path:
    write(repo, ".gitignore", "node_modules\n")
    package = repo / "web"
    write(package, "package.json", '{"name": "web", "type": "module"}\n')
    write(package, "tsconfig.json", TS_CONFIG)
    (package / "node_modules").symlink_to(modules, target_is_directory=True)
    return package


def test_tsc_error_on_changed_line_is_reported(
    repo: Path,
    log_dir: Path,
    node_toolchain: Path,
) -> None:
    package = make_ts_package(repo, node_toolchain)
    write(package, "src/a.ts", 'export const a: number = "x";\n')
    commit_all(repo)
    append(package, "src/a.ts", 'export const b: number = "y";\n')

    run = lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    tsc_found = {
        item for item in violations(run) if item[2].startswith("tsc:")
    }
    assert tsc_found == {("web/src/a.ts", 2, "tsc:TS2322")}, run.out


def test_missing_explicit_return_type_is_reported(
    repo: Path,
    log_dir: Path,
    node_toolchain: Path,
) -> None:
    package = make_ts_package(repo, node_toolchain)
    write(
        package,
        "src/add.ts",
        "export function add(a: number, b: number) {\n  return a + b;\n}\n",
    )

    run = lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    rules = rules_at(run, "web/src/add.ts")
    assert "@typescript-eslint/explicit-function-return-type" in rules, run.out
    assert "@typescript-eslint/explicit-module-boundary-types" in rules


DEEP_TS = """export function deep(values: number[]): number {
  let total = 0;
  for (const value of values) {
    if (value > 0) {
      if (value > 1) {
        if (value > 2) {
          total += value;
        }
      }
    }
  }
  return total;
}
"""


def test_excessive_nesting_is_reported(
    repo: Path,
    log_dir: Path,
    node_toolchain: Path,
) -> None:
    package = make_ts_package(repo, node_toolchain)
    write(package, "src/deep.ts", DEEP_TS)

    run = lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    assert ("web/src/deep.ts", 6, "max-depth") in violations(run), run.out


def test_missing_tsc_is_not_checked(repo: Path, log_dir: Path) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "export const a = 1;\n")

    overridden = lint(repo, log_dir, "--json")
    packaged = lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    assert NO_TOOL in not_checked_reasons(overridden)["web/src/a.ts", "tsc"]
    reason = not_checked_reasons(packaged)["web/src/a.ts", "tsc"]
    assert "node_modules/.bin/tsc" in reason


COGNITIVE_C = """int grade(int a, int b, int c)
{
    int total = 0;
    for (int i = 0; i < a; i++) {
        if (b > i) {
            if (c > i) {
                if (a > c) {
                    while (total < b) {
                        total++;
                    }
                } else {
                    total--;
                }
            }
        }
    }
    return total;
}
"""


@NEEDS_CLANG_TIDY
def test_cognitive_complexity_is_reported(repo: Path, log_dir: Path) -> None:
    write(repo, "grade.c", COGNITIVE_C)
    entry = {
        "directory": str(repo),
        "file": "grade.c",
        "arguments": ["gcc", "-std=c99", "-c", "grade.c"],
    }
    write(repo, "compile_commands.json", json.dumps([entry]))
    real = {"LINT_STRICT_CLANG_TIDY": str(shutil.which("clang-tidy"))}

    run = lint(repo, log_dir, "--json", extra_env=real)

    rules = rules_at(run, "grade.c")
    assert "readability-function-cognitive-complexity" in rules, run.out


def test_parse_mypy_keeps_errors_with_codes(ls: ModuleType) -> None:
    output = (
        "/r/a.py:3:12: error: Incompatible return value type"
        ' (got "str", expected "int")  [return-value]\n'
        "/r/a.py:3:12: note: See the docs\n"
        "/r/b.py:1: error: Something without a column  [misc]\n"
        "/r/c.py:2:1: error: Something without a code\n"
        "Found 3 errors in 3 files (checked 3 source files)\n"
    )

    found = ls.parse_mypy(output)

    assert [(d.path, d.line, d.column, d.rule) for d in found] == [
        ("/r/a.py", 3, 12, "mypy:return-value"),
        ("/r/b.py", 1, 1, "mypy:misc"),
        ("/r/c.py", 2, 1, "mypy"),
    ]
    assert found[0].message == (
        'Incompatible return value type (got "str", expected "int")'
    )


def test_parse_tsc_keeps_file_diagnostics(ls: ModuleType) -> None:
    output = (
        "src/a.ts(2,14): error TS2322: Type 'string' is not assignable"
        " to type 'number'.\n"
        "  Continuation of the message.\n"
        "error TS5058: The specified path does not exist.\n"
    )

    found = ls.parse_tsc(output)

    assert [(d.path, d.line, d.column, d.rule) for d in found] == [
        ("src/a.ts", 2, 14, "tsc:TS2322"),
    ]
    assert found[0].message.startswith("Type 'string'")


RUFF_COMPLEXITY_CONFIG = {
    "lint.mccabe.max-complexity=10",
    "lint.pylint.max-branches=12",
    "lint.pylint.max-statements=50",
    "lint.pylint.max-returns=6",
    "lint.pylint.max-args=5",
    "lint.pylint.max-nested-blocks=4",
}


@pytest.mark.parametrize("test_file", [False, True])
def test_ruff_check_command_sets_complexity_limits(
    ls: ModuleType,
    test_file: bool,
) -> None:
    settings = ls.RuffSettings("ruff", "ruff 0")
    style = ls.PythonStyle(79, "py314")

    argv = settings.check_command(style, test_file=test_file)

    configs = {
        argv[index + 1]
        for index, argument in enumerate(argv)
        if argument == "--config"
    }
    assert configs >= RUFF_COMPLEXITY_CONFIG
    ignored = argv[argv.index("--ignore") + 1].split(",")
    annotation_rules = {rule for rule in ignored if rule.startswith("ANN")}
    assert annotation_rules == ({"ANN201"} if test_file else set())


def test_tidy_command_sets_complexity_thresholds(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    target = ls.LintTarget(
        "a.c",
        ls.Language.C,
        frozenset({1}),
        ls.TextSource.DISK,
    )
    job = ls.TidyJob(target, tmp_path, tmp_path, tmp_path / "a.c", None)

    argv = ls.tidy_command("clang-tidy", job, None)

    config = next(
        argument.removeprefix("--config=")
        for argument in argv
        if argument.startswith("--config=")
    )
    assert json.loads(config) == {
        "InheritParentConfig": True,
        "CheckOptions": {
            "readability-function-cognitive-complexity.Threshold": 15,
            "readability-function-size.LineThreshold": 80,
            "readability-function-size.ParameterThreshold": 5,
            "readability-function-size.NestingThreshold": 4,
        },
    }
    checks = next(a for a in argv if a.startswith("--checks="))
    assert "readability-*" in checks.split(",")


@NEEDS_UVX
def test_staged_mypy_checks_index_content(repo: Path, log_dir: Path) -> None:
    append(repo, "base.py", MYPY_BROKEN)
    git(repo, "add", "base.py")
    write(repo, "base.py", CLEAN_MODULE + DOCUMENTED)

    run = lint(repo, log_dir, "--staged", "--json", extra_env=REAL_MYPY)

    assert ("base.py", MYPY_BROKEN_LINE, "mypy:return-value") in mypy_rules(
        run
    ), run.out


FAKE_UVX = """
record({"argv": sys.argv[1:]})
"""


def test_uvx_mypy_runs_on_the_checked_interpreter(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "bin/uvx", FAKE_UVX)
    append(repo, "base.py", DOCUMENTED)
    env = {
        "LINT_STRICT_MYPY": "",
        "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
    }

    lint(repo, log_dir, "--json", extra_env=env)

    argv = next(
        call["argv"] for call in records(fake) if "--strict" in call["argv"]
    )
    python = argv[argv.index("--python") + 1]
    assert argv[argv.index("--python-executable") + 1] == python
    assert argv.index("--python") < argv.index("mypy")


FAKE_TSC = """
record({"argv": sys.argv[1:], "cwd": os.getcwd()})
"""


def test_tsc_leaves_staged_partial_content_not_checked(
    repo: Path,
    log_dir: Path,
) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", "{}\n")
    tsc = make_fake(package / "node_modules/.bin/tsc", FAKE_TSC)
    write(package, "src/a.ts", "export const a = 1;\n")
    commit_all(repo)
    write(package, "src/a.ts", "export const a = 2;\n")
    git(repo, "add", "web/src/a.ts")
    write(package, "src/a.ts", "export const a = 3;\n")

    run = lint(repo, log_dir, "--staged", "--json", extra_env=REAL_TS_TOOLS)

    reason = not_checked_reasons(run)["web/src/a.ts", "tsc"]
    assert "staged" in reason
    assert not [c for c in records(tsc) if "--noEmit" in c["argv"]]


DEEP_PYTHON = (
    '"""Deep."""\n\n\ndef deep(values: list[int]) -> int:\n'
    '    """Sum the deep values."""\n'
    "    total = 0\n"
    "    for value in values:\n"
    "        if value > 0:\n"
    "            while total < value:\n"
    "                if value > 1:\n"
    "                    if value > 2:\n"
    "                        total += value\n"
    "                total += 1\n"
    "    return total\n"
)
PICKLE_MODULE = '"""Store."""\n\nimport pickle\n\nDUMPED = pickle.dumps(1)\n'


def test_nesting_deeper_than_limit_is_reported(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "deep.py", DEEP_PYTHON)

    rules = rules_at(lint(repo, log_dir, "--json"), "deep.py")

    assert "PLR1702" in rules


def test_no_other_preview_rules_are_enabled(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "store.py", PICKLE_MODULE)

    rules = rules_at(lint(repo, log_dir, "--json"), "store.py")

    assert "S403" not in rules


UNFORMATTED_PAIR = 'def unchanged( a,b ):\n    """Add."""\n    return a+b\n'
UNFORMATTED_NEW_FUNCTION = (
    '\n\ndef changed( a,b ):\n    """Add."""\n    return a+b\n'
)
FORMATTED_NEW_FUNCTION = (
    '\n\ndef changed(a, b):\n    """Add."""\n    return a + b\n'
)
FIX_FLAGS = ("--fix", "--json")
REAL_RUFF = str(shutil.which("ruff"))
FILE_CHANGED_DURING_FIX = "file changed during --fix"


def fix(
    repo: Path,
    log_dir: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> Run:
    return lint(repo, log_dir, *FIX_FLAGS, *args, extra_env=extra_env)


def test_fix_reformats_only_changed_function(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "fmt.py", UNFORMATTED_PAIR)
    commit_all(repo)
    append(repo, "fmt.py", UNFORMATTED_NEW_FUNCTION)

    run = fix(repo, log_dir, "--paths", "fmt.py")

    assert (repo / "fmt.py").read_text() == (
        UNFORMATTED_PAIR + FORMATTED_NEW_FUNCTION
    ), run.out
    assert run.json()["fixed_files"] == ["fmt.py"]


UP017_BASE = (
    "from datetime import datetime, timezone\n"
    "\n\n"
    "def old() -> datetime:\n"
    '    """Return now."""\n'
    "    return datetime.now(tz=timezone.utc)\n"
)
UP017_NEW_FUNCTION = (
    "\n\ndef new() -> datetime:\n"
    '    """Return now."""\n'
    "    return datetime.now(tz=timezone.utc)\n"
)


def test_fix_applies_safe_ruff_fix_on_changed_lines_only(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "clock.py", UP017_BASE)
    commit_all(repo)
    append(repo, "clock.py", UP017_NEW_FUNCTION)

    run = fix(repo, log_dir)

    lines = (repo / "clock.py").read_text().splitlines()
    assert lines[5] == "    return datetime.now(tz=timezone.utc)", run.out
    assert lines[-1] == "    return datetime.now(tz=UTC)"


def test_fix_never_applies_unsafe_fix(repo: Path, log_dir: Path) -> None:
    text = 'def new() -> None:\n    """Do it."""\n    unused = 1\n'
    write(repo, "unsafe.py", text)

    run = fix(repo, log_dir)

    assert (repo / "unsafe.py").read_text() == text
    assert ("unsafe.py", 3, "F841") in violations(run)
    assert run.json()["fixed_files"] == []


def test_fix_keeps_all_edits_of_one_fix_together(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo, "stamp.py", "from datetime import datetime, timezone\n\nA = 0\n"
    )
    commit_all(repo)
    append(repo, "stamp.py", "B = datetime.now(tz=timezone.utc)\n")

    run = fix(repo, log_dir)

    lines = (repo / "stamp.py").read_text().splitlines()
    assert "UTC" in lines[0], run.out
    assert lines[-1] == "B = datetime.now(tz=UTC)"
    done = subprocess.run(
        [sys.executable, str(repo / "stamp.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_fix_adjacent_unchanged_line_stays_identical(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "pair.py", "x=1\n")
    commit_all(repo)
    append(repo, "pair.py", "y=2\n")

    fix(repo, log_dir)

    assert (repo / "pair.py").read_text() == "x=1\ny = 2\n"


SORTING_FORMATTER = """
args = sys.argv[1:]
if args == ["--version"]:
    print("clang-format version 18.1.3")
    raise SystemExit(0)
sys.stdout.write("".join(sorted(sys.stdin.readlines())))
"""


def test_fix_reordering_formatter_rejected_by_canonical_check(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    sorter = make_fake(tmp_path / "tools/clang-format", SORTING_FORMATTER)
    write(repo, ".clang-format", CLANG_STYLE)
    write(repo, "vars.c", "int z;\nint a;\nint b;\n")
    commit_all(repo)
    write(repo, "vars.c", "int c;\nint a;\nint b;\n")

    run = fix(
        repo,
        log_dir,
        extra_env={"LINT_STRICT_CLANG_FORMAT": str(sorter)},
    )

    assert (repo / "vars.c").read_text() == "int c;\nint a;\nint b;\n"
    assert ("vars.c", 1, "FMT") in violations(run)


INTERFERING_RUFF = """
import os
args = sys.argv[1:]
if args and args[0] == "format":
    target = Path(args[args.index("--stdin-filename") + 1])
    marker = Path(os.environ["FAKE_RUFF_MARKER"])
    if not marker.exists():
        marker.touch()
        target.write_text("# edited elsewhere\\n" + target.read_text())
os.execv(os.environ["REAL_RUFF"], [os.environ["REAL_RUFF"], *args])
"""


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff missing")
def test_fix_concurrent_change_is_not_overwritten(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fake = make_fake(tmp_path / "tools/ruff", INTERFERING_RUFF)
    write(repo, "race.py", "x=1\n")
    env = {
        "LINT_STRICT_RUFF": str(fake),
        "REAL_RUFF": REAL_RUFF,
        "FAKE_RUFF_MARKER": str(tmp_path / "marker"),
    }

    run = fix(repo, log_dir, extra_env=env)

    assert (repo / "race.py").read_text() == "# edited elsewhere\nx=1\n"
    reasons = not_checked_reasons(run)
    assert reasons["race.py", "lint-strict"] == FILE_CHANGED_DURING_FIX
    assert run.json()["fixed_files"] == []


def test_fix_literal_paths(repo: Path, log_dir: Path) -> None:
    write(repo, "a[b].py", "x=1\n")
    write(repo, "ab.py", "x=1\n")

    fix(repo, log_dir, "--paths", "a[b].py")

    assert (repo / "a[b].py").read_text() == "x = 1\n"
    assert (repo / "ab.py").read_text() == "x=1\n"


def test_fix_json_reports_fixed_lines_and_remaining_violations(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "fmt.py", "def f( a,b ):\n    return a+b\n")

    run = fix(repo, log_dir)

    report = run.json()
    assert report["fixed_files"] == ["fmt.py"]
    assert report["fixed_lines"] == 2
    assert ("fmt.py", 1, "D103") in violations(run)
    assert run.code == EXIT_FAIL


FAKE_JSCPD = """
args = sys.argv[1:]
if args == ["--version"]:
    print("5.4.0")
    raise SystemExit(0)
takes_value = {"--min-lines", "--min-tokens", "--reporters", "--output"}
files = []
skip = False
for arg in args:
    if skip:
        skip = False
    elif arg in takes_value:
        skip = True
    elif not arg.startswith("-"):
        files.append(arg)
record({"argv": args, "files": files})
time.sleep(float(os.environ.get("FAKE_JSCPD_SLEEP", "0")))
current = any(f.startswith(os.environ["FAKE_JSCPD_REPO"] + "/") for f in files)
template = os.environ["FAKE_JSCPD_CURRENT" if current else "FAKE_JSCPD_BASE"]


def absolute(name):
    return next((f for f in files if f.endswith("/" + name)), None)


found = []
for clone in json.loads(Path(template).read_text()):
    first = absolute(clone["firstFile"]["name"])
    second = absolute(clone["secondFile"]["name"])
    if first and second:
        clone["firstFile"]["name"] = first
        clone["secondFile"]["name"] = second
        found.append(clone)
output = Path(args[args.index("--output") + 1])
output.mkdir(parents=True, exist_ok=True)
(output / "jscpd-report.json").write_text(
    json.dumps({"duplicates": found, "statistics": {}}),
)
"""


def test_fix_skips_slow_backends(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    mypy = make_fake(
        tmp_path / "tools/mypy",
        "record({'argv': sys.argv[1:]})\n",
    )
    jscpd = make_fake(tmp_path / "tools/jscpd", FAKE_JSCPD)
    tidy = make_fake(tmp_path / "tools/clang-tidy", FAKE_CLANG_TIDY)
    make_c_repo(repo)
    write(repo, "src/main.c", C_SOURCE.replace("return 0;", "return 7;"))
    write(repo, "new.py", "X = 1\n")
    env = {
        "LINT_STRICT_MYPY": str(mypy),
        "LINT_STRICT_JSCPD": str(jscpd),
        "LINT_STRICT_CLANG_TIDY": str(tidy),
        "FAKE_JSCPD_REPO": str(repo),
        "FAKE_JSCPD_CURRENT": str(tmp_path / "none.json"),
        "FAKE_JSCPD_BASE": str(tmp_path / "none.json"),
    }
    write(tmp_path, "none.json", "[]")

    fix(repo, log_dir, extra_env=env)
    after_fix = (records(mypy), records(jscpd), records(tidy))
    lint(repo, log_dir, "--json", extra_env=env)

    assert after_fix == ([], [], [])
    assert records(mypy)
    assert records(jscpd)


def test_fix_missing_formatter_leaves_file_untouched(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "fmt.py", "x=1\n")

    run = fix(repo, log_dir, extra_env={"LINT_STRICT_RUFF": NO_TOOL})

    assert (repo / "fmt.py").read_text() == "x=1\n"
    assert ("fmt.py", "ruff") in not_checked_reasons(run)
    assert run.json()["fixed_files"] == []


TS_UNFORMATTED = (
    "export function twice(n: number): number {\n"
    "  let result = n*2;\n"
    "  return result;\n"
    "}\n"
)
TS_KEPT = "export const kept   =  1;\n"
TS_FIXED = TS_KEPT + TS_UNFORMATTED.replace(
    "let result = n*2", "const result = n * 2"
)
REAL_PRETTIER = Path.home() / ".claude/tools/node/node_modules/.bin/prettier"


@pytest.mark.skipif(not REAL_PRETTIER.exists(), reason="prettier missing")
def test_fix_typescript_eslint_and_prettier(
    repo: Path,
    log_dir: Path,
    node_toolchain: Path,
) -> None:
    package = make_ts_package(repo, node_toolchain)
    write(package, "src/a.ts", TS_KEPT)
    commit_all(repo)
    append(package, "src/a.ts", TS_UNFORMATTED)

    run = fix(
        repo,
        log_dir,
        extra_env={"LINT_STRICT_PRETTIER": str(REAL_PRETTIER)},
    )

    assert (package / "src/a.ts").read_text() == TS_FIXED, run.out


@pytest.mark.skipif(
    shutil.which("clang-format") is None,
    reason="clang-format missing",
)
def test_fix_c_clang_format(repo: Path, log_dir: Path) -> None:
    write(repo, ".clang-format", CLANG_STYLE)
    write(repo, "fmt.c", C_FORMATTED)
    commit_all(repo)
    write(repo, "fmt.c", C_FORMATTED.replace("int a(", "int   a("))
    real = {"LINT_STRICT_CLANG_FORMAT": str(shutil.which("clang-format"))}

    run = fix(repo, log_dir, extra_env=real)

    assert (repo / "fmt.c").read_text() == C_FORMATTED, run.out


CLONE_BODY = "".join(
    f"    value_{n} = compute({n}) + helper({n}, {n} * 2)\n" for n in range(12)
)
CLONE_LINES = 14
CLONE_TOKENS = 184
CLONE_MESSAGE = "duplicates src/a.py:1-14 (14 lines)"


def clone_source(name: str) -> str:
    return f"def {name}() -> int:\n{CLONE_BODY}    return value_1\n"


def clone_entry(
    first: str,
    second: str,
    tokens: int = CLONE_TOKENS,
    fragment: str = CLONE_BODY,
) -> dict[str, Any]:
    return {
        "fragment": fragment,
        "firstFile": {"name": first, "start": 1, "end": CLONE_LINES},
        "secondFile": {"name": second, "start": 1, "end": CLONE_LINES},
        "lines": CLONE_LINES,
        "tokens": tokens,
    }


def jscpd_env(
    repo: Path,
    tmp_path: Path,
    *,
    current: list[dict[str, Any]],
    base: list[dict[str, Any]],
) -> tuple[Path, dict[str, str]]:
    fake = make_fake(tmp_path / "tools/jscpd", FAKE_JSCPD)
    write(tmp_path, "current.json", json.dumps(current))
    write(tmp_path, "base.json", json.dumps(base))
    return fake, {
        "LINT_STRICT_JSCPD": str(fake),
        "FAKE_JSCPD_REPO": str(repo.resolve()),
        "FAKE_JSCPD_CURRENT": str(tmp_path / "current.json"),
        "FAKE_JSCPD_BASE": str(tmp_path / "base.json"),
    }


def dup_violations(run: Run) -> set[tuple[str, int]]:
    return {
        (path, line)
        for path, line, rule in violations(run)
        if rule == "DUP001"
    }


def test_dup001_flags_new_clone_of_existing_block(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    _, env = jscpd_env(repo, tmp_path, current=[clone], base=[])

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert dup_violations(run) == {("src/b.py", 1)}, run.out
    message = next(
        item["message"]
        for item in run.json()["violations"]
        if item["rule"] == "DUP001"
    )
    assert message.startswith(CLONE_MESSAGE)
    assert run.code == EXIT_FAIL


def test_dup001_ignores_preexisting_clone(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    write(repo, "src/b.py", clone_source("second"))
    commit_all(repo)
    append(repo, "src/b.py", "\n\nOTHER = 1\n")
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[clone])

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert dup_violations(run) == set(), run.out
    assert len(records(fake)) == 2


def test_dup001_whitespace_edit_inside_preexisting_clone_not_reported(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    write(repo, "src/b.py", clone_source("second"))
    commit_all(repo)
    edited = clone_source("second").replace("value_3 =", "value_3  =")
    write(repo, "src/b.py", edited)
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[clone])

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert dup_violations(run) == set(), run.out
    assert len(records(fake)) == 2


TEST_FILE_NAMES = (
    "tests/test_b.py",
    "src/x.test.ts",
    "src/x.spec.tsx",
    "src/__tests__/y.ts",
    "e2e/z.ts",
)


def test_dup001_ignores_test_files(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    for name in TEST_FILE_NAMES:
        write(repo, name, clone_source("copy"))
    append(repo, "src/a.py", "\n\nOTHER = 1\n")
    clones = [clone_entry("src/a.py", name) for name in TEST_FILE_NAMES]
    fake, env = jscpd_env(repo, tmp_path, current=clones, base=[])

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert dup_violations(run) == set(), run.out
    sent = {Path(f).name for item in records(fake) for f in item["files"]}
    assert "a.py" in sent
    assert sent.isdisjoint({Path(name).name for name in TEST_FILE_NAMES})


def test_dup001_deleted_tracked_file_does_not_abort(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    write(repo, "src/gone.py", clone_source("gone"))
    commit_all(repo)
    (repo / "src/gone.py").unlink()
    append(repo, "src/a.py", "\n\nOTHER = 1\n")
    fake, env = jscpd_env(repo, tmp_path, current=[], base=[])

    run = lint(repo, log_dir, "--json", extra_env=env)

    sent = {Path(f).name for item in records(fake) for f in item["files"]}
    assert "gone.py" not in sent
    assert "a.py" in sent
    assert ("src/a.py", "jscpd") not in not_checked_reasons(run)


def test_dup001_staged_divergent_is_not_checked(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    git(repo, "add", "src/b.py")
    append(repo, "src/b.py", "\n\nUNSTAGED = 1\n")
    clone = clone_entry("src/a.py", "src/b.py")
    _, env = jscpd_env(repo, tmp_path, current=[clone], base=[])

    run = lint(repo, log_dir, "--staged", "--json", extra_env=env)

    reason = not_checked_reasons(run)["src/b.py", "jscpd"]
    assert reason == "staged content differs from the working tree"
    assert dup_violations(run) == set()


@pytest.mark.skipif(shutil.which("jscpd") is None, reason="jscpd missing")
def test_dup001_real_jscpd_flags_new_clone(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    real = {"LINT_STRICT_JSCPD": str(shutil.which("jscpd"))}

    run = lint(repo, log_dir, "--json", extra_env=real)

    assert dup_violations(run) == {("src/b.py", 1)}, run.out


@pytest.fixture
def lint_here(
    ls: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    log_dir: Path,
) -> Callable[..., Run]:
    def run(repo: Path, *args: str, env: dict[str, str]) -> Run:
        monkeypatch.setenv("LINT_STRICT_LOG_DIR", str(log_dir))
        monkeypatch.setenv("LINT_STRICT_CACHE_DIR", str(cache_path(log_dir)))
        for name in TOOL_OVERRIDES:
            monkeypatch.setenv(name, NO_TOOL)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        code = ls.main(["--repo", str(repo), *args])
        captured = capsys.readouterr()
        return Run(code, captured.out, captured.err)

    return run


def test_fix_untracked_file_is_fully_fixed(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "new.py", "def f( a,b ):\n    return a+b\ny=2\n")

    fix(repo, log_dir)

    assert (repo / "new.py").read_text() == (
        "def f(a, b):\n    return a + b\n\n\ny = 2\n"
    )


def test_fix_unchanged_file_is_not_written(
    repo: Path,
    log_dir: Path,
) -> None:
    path = write(repo, "tidy.py", "x = 1\n")
    os.utime(path, ns=(10**9, 10**9))

    run = fix(repo, log_dir)

    assert path.stat().st_mtime_ns == 10**9
    assert run.json()["fixed_files"] == []


@pytest.mark.parametrize("mode", [0o755, 0o640])
def test_fix_preserves_file_mode(repo: Path, log_dir: Path, mode: int) -> None:
    path = write(repo, "mode.py", "x=1\n")
    path.chmod(mode)

    fix(repo, log_dir)

    assert path.read_text() == "x = 1\n"
    assert stat.S_IMODE(path.stat().st_mode) == mode


@pytest.mark.parametrize(
    "flag", [["--staged"], ["--tracked"], ["--base", MAIN]]
)
def test_fix_rejects_other_scopes(
    repo: Path,
    log_dir: Path,
    flag: list[str],
) -> None:
    write(repo, "a.py", "x=1\n")

    run = lint(repo, log_dir, "--fix", *flag)

    assert run.code == EXIT_USAGE
    assert (repo / "a.py").read_text() == "x=1\n"


def test_fix_non_utf8_file_is_not_changed(repo: Path, log_dir: Path) -> None:
    data = b"x=1  # caf\xe9\n"
    (repo / "latin.py").write_bytes(data)

    run = fix(repo, log_dir)

    assert (repo / "latin.py").read_bytes() == data
    reasons = not_checked_reasons(run)
    assert reasons["latin.py", "lint-strict"] == "not readable as UTF-8 text"


def test_dup001_jscpd_timeout_is_not_checked(
    ls: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lint_here: Callable[..., Run],
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    _, env = jscpd_env(repo, tmp_path, current=[clone], base=[])
    env["FAKE_JSCPD_SLEEP"] = "10"
    monkeypatch.setattr(ls, "JSCPD_TIMEOUT_SECONDS", 0.5)

    run = lint_here(repo, "--json", env=env)

    reason = not_checked_reasons(run)["src/b.py", "jscpd"]
    assert reason == ls.JSCPD_TIMEOUT
    assert dup_violations(run) == set()


def test_dup001_large_file_list_is_chunked(
    ls: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lint_here: Callable[..., Run],
) -> None:
    names = [f"a/c{number}.py" for number in range(1, 5)]
    for name in names:
        write(repo, name, clone_source("copy"))
    clones = [
        clone_entry(names[0], names[1]),
        clone_entry(names[2], names[3]),
    ]
    fake, env = jscpd_env(repo, tmp_path, current=clones, base=[])
    cost = len(str(repo.resolve() / names[0])) + 1
    monkeypatch.setattr(ls, "JSCPD_ARGUMENT_LIMIT", 2 * cost)

    run = lint_here(repo, "--json", env=env)

    assert dup_violations(run) == {(name, 1) for name in names}, run.out
    chunks = [item["files"] for item in records(fake)]
    assert len(chunks) >= 3
    assert max(len(chunk) for chunk in chunks) == 2


@pytest.mark.parametrize(
    "case",
    [
        ("a=1\nb=2\n", "a = 1\nb = 2\n", {2}, "a=1\nb = 2\n", 1),
        ("a=1\nb=2\n", "a = 1\nb = 2\n", {1, 2}, "a = 1\nb = 2\n", 2),
        ("a=1\nb=2\n", "a = 1\nb = 2\n", set(), "a=1\nb=2\n", 0),
        ("a\nb\nc\n", "X\nY\nZ\nW\nc\n", {1}, "a\nb\nc\n", 0),
        ("a\nb\nc\n", "X\nY\nZ\nW\nc\n", {1, 2}, "X\nY\nZ\nW\nc\n", 4),
        ("a\nb\n", "a\n\nb\n", {1}, "a\n\nb\n", 1),
        ("a\nb\n", "a\n\nb\n", {2}, "a\nb\n", 0),
        ("a\n", "\na\n", {1}, "\na\n", 1),
        ("a\n", "\na\n", {2}, "a\n", 0),
        ("a\n\n\nb\n", "a\n\nb\n", {1}, "a\n\n\nb\n", 0),
        ("a\n\n\nb\n", "a\n\nb\n", {1, 2, 3, 4}, "a\n\nb\n", 1),
        ("a=1\r\nb=2\r\n", "a = 1\r\nb = 2\r\n", {1}, "a = 1\r\nb=2\r\n", 1),
        ("a=1\r\nb=2\r\n", "a = 1\nb = 2\n", {2}, "a=1\r\nb = 2\r\n", 1),
        ("a=1\nb=2", "a = 1\nb = 2\n", {2}, "a=1\nb = 2", 1),
        ("a=1\nb=2\n", "a = 1\nb = 2", {2}, "a=1\nb = 2\n", 1),
    ],
)
def test_splice_formatting(
    ls: ModuleType,
    case: tuple[str, str, set[int], str, int],
) -> None:
    original, formatted, changed, expected, count = case

    result = ls.splice_formatting(original, formatted, frozenset(changed))

    assert result.text == expected
    assert result.lines_replaced == count


def test_splice_formatting_drops_reordered_lines_only_via_canonical_check(
    ls: ModuleType,
) -> None:
    def sort_lines(text: str) -> str | None:
        return "".join(sorted(text.splitlines(keepends=True)))

    kept = ls.spliced_text("c\na\nb\n", frozenset({1}), sort_lines)
    sorted_all = ls.spliced_text("c\na\nb\n", frozenset({1, 2, 3}), sort_lines)

    assert kept == "c\na\nb\n"
    assert sorted_all == "a\nb\nc\n"


def test_spliced_text_keeps_text_when_formatter_fails(ls: ModuleType) -> None:
    assert ls.spliced_text("a=1\n", frozenset({1}), lambda _: None) == "a=1\n"


def test_select_fixes_skips_overlapping_fix_as_a_whole(
    ls: ModuleType,
) -> None:
    first = ls.TextFix((ls.TextEdit(0, 3, "X"),))
    overlapping = ls.TextFix((ls.TextEdit(9, 10, "Y"), ls.TextEdit(2, 4, "Z")))
    disjoint = ls.TextFix((ls.TextEdit(5, 6, "W"),))

    chosen = ls.select_fixes([first, overlapping, disjoint])

    assert chosen == [first, disjoint]


def test_apply_fixes_applies_from_the_last_offset(ls: ModuleType) -> None:
    fixes = [
        ls.TextFix((ls.TextEdit(1, 2, "X"),)),
        ls.TextFix((ls.TextEdit(5, 6, "YY"), ls.TextEdit(0, 0, ">"))),
    ]

    state = ls.FixState("0123456789", frozenset())

    assert ls.apply_fixes(state, fixes).text == ">0X234YY6789"


def test_ruff_fix_passes_are_limited(
    ls: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def endless(_self: object, _state: object) -> object:
        calls.append("pass")
        return ls.FixState("a\n" + "x" * len(calls), frozenset({1}))

    def no_format(_self: object, _text: str) -> None:
        return None

    monkeypatch.setattr(ls.RuffFixer, "fix_pass", endless)
    monkeypatch.setattr(ls.RuffFixer, "format", no_format)
    target = ls.LintTarget(
        "a.py", ls.Language.PYTHON, frozenset({1}), ls.TextSource.DISK
    )
    fixer = ls.RuffFixer(
        ls.RuffSettings("ruff", "ruff"),
        ls.Repo(Path()),
        target,
        ls.PythonStyle(79, "py314"),
    )

    text = fixer.fixed_text(ls.Snapshot(target, b"", "a\n"))

    assert len(calls) == 3
    assert text == "a\nxxx"


def test_safe_ruff_fixes_take_only_safe_fixes_on_changed_lines(
    ls: ModuleType,
) -> None:
    safe = {
        "applicability": "safe",
        "edits": [
            {
                "content": "UTC",
                "location": {"row": 2, "column": 5},
                "end_location": {"row": 2, "column": 8},
            },
            {
                "content": "import b",
                "location": {"row": 1, "column": 1},
                "end_location": {"row": 1, "column": 9},
            },
        ],
    }
    unsafe = {"applicability": "unsafe", "edits": []}
    items = [
        {"location": {"row": 2}, "fix": safe},
        {"location": {"row": 2}, "fix": unsafe},
        {"location": {"row": 1}, "fix": safe},
        {"location": {"row": 2}, "fix": None},
    ]
    text = "import a\nx = abc\n"

    fixes = ls.safe_ruff_fixes(items, text, frozenset({2}))

    assert len(fixes) == 1
    state = ls.FixState(text, frozenset({2}))

    assert ls.apply_fixes(state, fixes).text == "import b\nx = UTC\n"


def test_eslint_fix_offsets_count_utf16_units(ls: ModuleType) -> None:
    text = "\U0001f600x = 1\n"
    message = ls.EslintMessage(
        "f.ts", 1, 1, "r", "m", "", 2, ls.EslintFix(2, 3, "y")
    )

    fixes = ls.eslint_text_fixes([message], text, frozenset({1}))

    state = ls.FixState(text, frozenset({1}))

    assert ls.apply_fixes(state, fixes).text == "\U0001f600y = 1\n"


def apply_edits(
    ls: ModuleType,
    text: str,
    changed: set[int],
    *edits: tuple[int, int, str],
) -> tuple[str, set[int]]:
    fixes = [ls.TextFix((ls.TextEdit(*edit),)) for edit in edits]
    result = ls.apply_fixes(ls.FixState(text, frozenset(changed)), fixes)
    return result.text, set(result.changed)


def test_apply_fixes_tracks_inserted_whole_line(ls: ModuleType) -> None:
    text, changed = apply_edits(ls, "a\nb\nc\n", {3}, (0, 0, "import x\n"))

    assert text == "import x\na\nb\nc\n"
    assert changed == {1, 4}


def test_apply_fixes_tracks_deleted_whole_line(ls: ModuleType) -> None:
    text, changed = apply_edits(ls, "a\nb\nc\n", {1, 3}, (2, 4, ""))

    assert text == "a\nc\n"
    assert changed == {1, 2}


def test_apply_fixes_marks_partial_line_edit_and_keeps_twins(
    ls: ModuleType,
) -> None:
    text, changed = apply_edits(ls, "x;\nx;\nx;\n", {1}, (1, 2, ""))

    assert text == "x\nx;\nx;\n"
    assert changed == {1}


def test_apply_fixes_shifts_by_multiline_replacement(ls: ModuleType) -> None:
    text, changed = apply_edits(ls, "a\nb\nc\n", {3}, (0, 1, "p\nq"))

    assert text == "p\nq\nb\nc\n"
    assert changed == {1, 2, 4}


@pytest.mark.parametrize(
    ("path", "exempt"),
    [
        ("src/a.py", False),
        ("tests/a.py", True),
        ("src/test_a.py", True),
        ("src/a.test.ts", True),
        ("src/a.spec.tsx", True),
        ("src/__tests__/a.ts", True),
        ("app/e2e/a.ts", True),
        ("cypress/a.js", True),
        ("src/contest.ts", False),
        ("src/a.ts", False),
    ],
)
def test_is_clone_exempt(ls: ModuleType, path: str, exempt: bool) -> None:
    assert ls.is_clone_exempt(path) is exempt


@pytest.mark.parametrize(
    ("path", "eligible"),
    [
        ("src/a.py", True),
        ("src/a.d.ts", False),
        ("src/a.md", False),
        ("node_modules/x/a.js", False),
        ("app/migrations/0001.py", False),
        ("app/generated/a.ts", False),
        ("src/a.test.ts", False),
        ("lib/a.cpp", True),
    ],
)
def test_clone_eligible(ls: ModuleType, path: str, eligible: bool) -> None:
    assert ls.clone_eligible(path) is eligible


def test_read_clone_report_parses_typed_clones(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    root = ls.Repo(tmp_path)
    with_lines = clone_entry(f"{tmp_path}/a.py", f"{tmp_path}/b.py", tokens=90)
    without_counts = {
        "firstFile": {"name": f"{tmp_path}/c.py", "start": 4, "end": 12},
        "secondFile": {"name": f"{tmp_path}/d.py", "start": 1, "end": 9},
    }
    report = write(
        tmp_path,
        "report.json",
        json.dumps({"duplicates": [with_lines, without_counts]}),
    )

    clones = ls.read_clone_report(report, root)

    assert [
        (c.first.path, c.second.path, c.lines, c.tokens) for c in clones
    ] == [
        ("a.py", "b.py", 14, 90),
        ("c.py", "d.py", 9, 0),
    ]
    assert (clones[1].first.start, clones[1].first.end) == (4, 12)


def test_read_clone_report_rejects_garbage(
    ls: ModuleType, tmp_path: Path
) -> None:
    report = write(tmp_path, "report.json", "{}")

    with pytest.raises(ls.CloneCheckError):
        ls.read_clone_report(report, ls.Repo(tmp_path))


def test_clone_key_matches_same_pair_and_size(ls: ModuleType) -> None:
    def key(
        first: str,
        second: str,
        lines: int,
        tokens: int,
    ) -> tuple[frozenset[str], int | str]:
        clone = ls.Clone(
            ls.CloneFragment(first, 1, lines),
            ls.CloneFragment(second, 1, lines),
            lines,
            tokens,
        )
        found: tuple[frozenset[str], int | str] = ls.clone_key(clone)
        return found

    base = key("a.py", "b.py", 14, 184)

    assert key("b.py", "a.py", 20, 184) == base
    assert key("a.py", "b.py", 14, 190) != base
    assert key("a.py", "c.py", 14, 184) != base
    assert key("a.py", "b.py", 14, 0) == (frozenset({"a.py", "b.py"}), 14)


def test_clone_violations_report_first_changed_line_of_each_side(
    ls: ModuleType,
) -> None:
    clone = ls.Clone(
        ls.CloneFragment("a.py", 1, 14),
        ls.CloneFragment("b.py", 10, 23),
        14,
        184,
    )
    targets = [
        ls.LintTarget(
            "a.py", ls.Language.PYTHON, frozenset({30}), ls.TextSource.DISK
        ),
        ls.LintTarget(
            "b.py", ls.Language.PYTHON, frozenset({12, 15}), ls.TextSource.DISK
        ),
    ]

    found = ls.clone_violations(targets, [clone])

    assert [(v.path, v.line, v.rule, v.tool) for v in found] == [
        ("b.py", 12, "DUP001", "jscpd"),
    ]
    assert found[0].message == (
        "duplicates a.py:1-14 (14 lines) — reuse or extract a shared function"
    )


def test_chunk_by_size_keeps_every_chunk_within_the_limit(
    ls: ModuleType,
) -> None:
    chunks = ls.chunk_by_size(["aaaa", "bbbb", "cccc", "dd"], 10)

    assert chunks == [["aaaa", "bbbb"], ["cccc", "dd"]]
    assert ls.chunk_by_size([], 10) == [[]]
    assert ls.chunk_by_size(["x" * 20], 10) == [["x" * 20]]


INCLUDES_BEFORE = '#include "b.h"\n#include "a.h"\n'
INCLUDES_AFTER = '#include "c.h"\n' + INCLUDES_BEFORE


@pytest.mark.skipif(
    shutil.which("clang-format") is None,
    reason="clang-format missing",
)
def test_fix_clang_format_include_sort_never_duplicates(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, ".clang-format", CLANG_STYLE)
    write(repo, "inc.c", INCLUDES_BEFORE)
    commit_all(repo)
    write(repo, "inc.c", INCLUDES_AFTER)
    real = {"LINT_STRICT_CLANG_FORMAT": str(shutil.which("clang-format"))}

    fix(repo, log_dir, extra_env=real)

    text = (repo / "inc.c").read_text()
    assert sorted(text.splitlines()) == sorted(INCLUDES_AFTER.splitlines())
    assert INCLUDES_BEFORE in text


REPEATED_UTC_LINES = (
    "from datetime import datetime, timezone\n"
    "A = datetime.now(tz=timezone.utc)\n"
    "A = datetime.now(tz=timezone.utc)\n"
    "A = datetime.now(tz=timezone.utc)\n"
)


def test_fix_repeated_identical_lines_only_changed_one_fixed(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "rep.py",
        "from datetime import datetime, timezone\n"
        "A = 0\n"
        "A = datetime.now(tz=timezone.utc)\n"
        "A = datetime.now(tz=timezone.utc)\n",
    )
    commit_all(repo)
    write(repo, "rep.py", REPEATED_UTC_LINES)

    fix(repo, log_dir)

    lines = (repo / "rep.py").read_text().splitlines()
    assert [line for line in lines if line.startswith("A =")] == [
        "A = datetime.now(tz=UTC)",
        "A = datetime.now(tz=timezone.utc)",
        "A = datetime.now(tz=timezone.utc)",
    ]


def test_fix_converges_on_lines_its_fixes_touched(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo, "stamp.py", "from datetime import datetime, timezone\n\nA = 0\n"
    )
    commit_all(repo)
    append(repo, "stamp.py", "B = datetime.now(tz=timezone.utc)\n")

    run = fix(repo, log_dir)

    assert (repo / "stamp.py").read_text() == (
        "from datetime import UTC, datetime\n\nA = 0\n"
        "B = datetime.now(tz=UTC)\n"
    ), run.out
    assert not {"I001", "F401"} & rules_at(run, "stamp.py")


PREVIOUS_ARGUMENT_LIMIT = 100_000
FILES_PAST_PREVIOUS_LIMIT = 1300


def test_dup001_single_run_up_to_argv_budget(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    for number in range(FILES_PAST_PREVIOUS_LIMIT):
        write(repo, f"src/module_{number:05d}.py", "VALUE = 1\n")
    fake, env = jscpd_env(repo, tmp_path, current=[], base=[])

    lint(repo, log_dir, "--json", extra_env=env)

    runs = records(fake)
    assert len(runs) == 1
    sent = sum(len(arg) + 1 for arg in runs[0]["files"])
    assert sent > PREVIOUS_ARGUMENT_LIMIT


def test_dup001_new_clone_same_files_same_size_reported(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    write(repo, "src/b.py", clone_source("second"))
    commit_all(repo)
    extra = "".join(f"V{n} = {n}\n" for n in range(30))
    append(repo, "src/b.py", extra)
    old = clone_entry("src/a.py", "src/b.py")
    new = clone_entry("src/a.py", "src/b.py", fragment="def other(): body")
    new["secondFile"] = {"name": "src/b.py", "start": 20, "end": 33}
    _, env = jscpd_env(repo, tmp_path, current=[old, new], base=[old])

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert dup_violations(run) == {("src/b.py", 20)}, run.out


def test_clone_text_digest_ignores_whitespace(ls: ModuleType) -> None:
    spaced = ls.clone_text_digest("def  f():\n    return 1")

    assert spaced == ls.clone_text_digest("def f(): return 1")
    assert spaced != ls.clone_text_digest("def f(): return 2")
    assert ls.clone_text_digest("  \n ") == ""


@pytest.mark.parametrize(
    "case",
    [
        (
            INCLUDES_BEFORE,
            '#include "a.h"\n#include "b.h"\n',
        ),
        ("c\nb\na\n", "a\nb\nc\n"),
    ],
)
def test_splice_keeps_reordered_blocks_atomic(
    ls: ModuleType,
    case: tuple[str, str],
) -> None:
    original, formatted = case

    result = ls.splice_formatting(original, formatted, frozenset({1}))

    assert result.text == original


SPACED_B = '#include "b.h"   \n'
INCLUDE_A = '#include "a.h"\n'


@pytest.mark.skipif(
    shutil.which("clang-format") is None,
    reason="clang-format missing",
)
@pytest.mark.parametrize(
    ("head", "working"),
    [
        (SPACED_B + INCLUDE_A, SPACED_B + INCLUDE_A + INCLUDE_A),
        (SPACED_B, SPACED_B + INCLUDE_A + INCLUDE_A),
    ],
)
def test_fix_single_line_replace_never_pairs_moved_line(
    repo: Path,
    log_dir: Path,
    head: str,
    working: str,
) -> None:
    write(repo, ".clang-format", CLANG_STYLE)
    write(repo, "c.c", head)
    commit_all(repo)
    write(repo, "c.c", working)
    real = {"LINT_STRICT_CLANG_FORMAT": str(shutil.which("clang-format"))}

    run = fix(repo, log_dir, extra_env=real)

    assert (repo / "c.c").read_text() == working
    assert "FMT" in rules_at(run, "c.c")


def test_splice_applies_single_line_quote_normalisation(
    ls: ModuleType,
) -> None:
    result = ls.splice_formatting("x = 'a'\n", 'x = "a"\n', frozenset({1}))

    assert result.text == 'x = "a"\n'


def test_splice_refuses_single_line_replace_by_existing_line(
    ls: ModuleType,
) -> None:
    original = "b   \na\na\n"
    formatted = "a\nb\n"

    result = ls.splice_formatting(original, formatted, frozenset({3}))

    assert result.text == original


COMPARISON_MESSAGE_TWO = (
    "magic number in comparison: 37, 5 — name it as a constant"
)
REPEATED_MESSAGE = (
    "magic number repeated on 3+ lines: 77 — name it as a constant"
)


class HasPath(Protocol):
    path: str


class FakeTextRepo:
    def __init__(self, texts: dict[str, str]) -> None:
        self.texts = texts

    def read_text(self, target: HasPath) -> str:
        return self.texts[target.path]


class MagicOutcome(NamedTuple):
    rows: list[tuple[int, int, str, str, str]]
    tools: tuple[str, ...]
    not_checked: int


def magic_run(
    ls: ModuleType, path: str, language: str, text: str
) -> MagicOutcome:
    target = ls.LintTarget(
        path,
        ls.Language(language),
        frozenset(range(1, 50)),
        ls.TextSource.DISK,
    )
    result = ls.MagicBackend().run(FakeTextRepo({path: text}), [target])
    rows = [
        (v.line, v.column, v.rule, v.message, v.tool)
        for v in result.violations
    ]
    return MagicOutcome(rows, result.tools, len(result.not_checked))


@pytest.mark.parametrize(
    ("path", "language", "text", "expected"),
    [
        (
            "a.c",
            "c",
            "int f(int t)\n{\n    return t > 37 || t < 5;\n}\n",
            [
                (
                    3,
                    16,
                    "MAG001",
                    COMPARISON_MESSAGE_TWO,
                )
            ],
        ),
        (
            "a.ts",
            "ts",
            "const f = (t: number) =>\n  t > 37;\n",
            [
                (
                    2,
                    7,
                    "MAG001",
                    "magic number in comparison: 37 — name it as a constant",
                )
            ],
        ),
        (
            "a.py",
            "python",
            "a = 1 + 77\nb = 2 + 77\nc = 3 + 77\n",
            [
                (
                    n,
                    9,
                    "MAG002",
                    REPEATED_MESSAGE,
                )
                for n in (1, 2, 3)
            ],
        ),
    ],
)
def test_magic_backend_maps_hits_to_violations(
    ls: ModuleType,
    path: str,
    language: str,
    text: str,
    expected: list[tuple[int, int, str, str]],
) -> None:
    result = magic_run(ls, path, language, text)

    assert [row[:4] for row in result.rows] == expected
    assert {row[4] for row in result.rows} == {"magic-numbers"}
    assert result.tools == ("magic-numbers (built-in)",)


def test_magic_backend_skips_unparseable_python(ls: ModuleType) -> None:
    result = magic_run(ls, "a.py", "python", "def f(:\n    x > 37\n")

    assert result.rows == []
    assert result.not_checked == 0


def test_magic_backend_in_fast_backends(ls: ModuleType) -> None:
    names = [backend.name for backend in ls.FAST_BACKENDS]

    assert "magic-numbers" in names
    assert "magic-numbers" in [backend.name for backend in ls.BACKENDS]


def test_jsx_text_number_is_not_a_comparison_integration(
    repo: Path,
    log_dir: Path,
) -> None:
    write(
        repo,
        "src/a.tsx",
        "export const view = <div>37</div>;\n"
        "export const wide = <div>{n > 37}</div>;\n",
    )

    run = lint(repo, log_dir, "--json")

    assert {v for v in violations(run) if v[0] == "src/a.tsx"} == {
        ("src/a.tsx", 2, "MAG001")
    }


def test_python_column_counts_characters_not_bytes_integration(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", "é = x + 77\nb = 77\nc = 77\n")

    run = lint(repo, log_dir, "--json")

    columns = [
        (item["line"], item["column"])
        for item in run.json()["violations"]
        if item["rule"] == "MAG002"
    ]
    assert columns == [(1, 9), (2, 5), (3, 5)]


INVALID_ESCAPE_SOURCE = 'import re\nPATTERN = re.compile("\\d+")\n'


def test_magic_backend_prints_no_syntax_warning(
    ls: ModuleType,
) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        magic_run(ls, "a.py", "python", INVALID_ESCAPE_SOURCE)

    assert [str(item.message) for item in caught] == []


def test_magic_backend_prints_no_syntax_warning_integration(
    repo: Path,
    log_dir: Path,
) -> None:
    write(repo, "a.py", INVALID_ESCAPE_SOURCE)

    run = lint(repo, log_dir, "--json")

    assert run.err.count("SyntaxWarning") == 0


CLOUD_SLUG = "acme/cloud-platform"
DEVICE_SLUG = "acme/device-service"
OTHER_SLUG = "acme/other-service"
SQL_SESSION_CALL = (
    "from sqlalchemy.orm import Session\n\n\n"
    "def save(session: Session, row: object) -> None:\n"
    "    session.add(row)\n"
)
REPOSITORY_SETUP = {"app/repositories/user.py": "VALUE = 1\n"}
ENV_EXAMPLE_SETUP = {".env.example": "KNOWN_NAME=1\n"}
UNRELATED_LINE = "\nUNRELATED = 2\n"


@dataclass(frozen=True)
class HabitCase:
    code: str
    path: str
    bad: str
    good: str
    slug: str | None = None
    setup: dict[str, str] | None = None
    good_path: str | None = None


HAB120 = HabitCase(
    "HAB120",
    "app/colors.py",
    "from enum import StrEnum\n\n\nclass Color(StrEnum):\n    RED = 'red'\n",
    "from enum import StrEnum, auto\n\n\n"
    "class Color(StrEnum):\n    RED = auto()\n",
)
HAB084 = HabitCase(
    "HAB084",
    "app/codes.py",
    "HTTP_NOT_FOUND = 404\n",
    "from http import HTTPStatus\n\nNOT_FOUND = HTTPStatus.NOT_FOUND\n",
)
HAB091 = HabitCase(
    "HAB091",
    "app/models.py",
    "class Post(Base):\n"
    "    owner: Mapped['User'] = relationship('User', back_populates='p')\n",
    "class Post(Base):\n"
    "    owner: Mapped[User] = relationship(User, back_populates='posts')\n",
)
HAB051 = HabitCase(
    "HAB051",
    "tests/test_env.py",
    "import os\n\nos.environ.setdefault('KNOWN_NAME', '1')\n",
    "import os\n\nVALUE = os.environ.get('KNOWN_NAME')\n",
)
HAB106 = HabitCase(
    "HAB106",
    "tests/test_clock.py",
    "from unittest.mock import patch\n\n\n"
    "def test_sleep():\n    with patch('time.sleep'):\n        pass\n",
    "from unittest.mock import patch\n\n\n"
    "def test_sleep():\n    with patch('app.clock.sleep'):\n        pass\n",
)
HAB052 = HabitCase(
    "HAB052",
    "tests/test_shell.py",
    "import subprocess\n\nsubprocess.run(['ls'], check=True)\n",
    "import subprocess\n\nsubprocess.run(['ls'], check=True, timeout=5)\n",
)
HAB118 = HabitCase(
    "HAB118",
    "app/services/users.py",
    SQL_SESSION_CALL,
    SQL_SESSION_CALL,
    setup=REPOSITORY_SETUP,
    good_path="app/repositories/users.py",
)
HAB077 = HabitCase(
    "HAB077",
    "pkg/__init__.py",
    "from pkg.core import run\n\n__all__ = ['run']\n",
    "VERSION = '1'\n",
)
HAB083 = HabitCase(
    "HAB083",
    "app/greeter.py",
    "def greet() -> None:\n    print('hello')\n",
    "def greet() -> str:\n    return 'hello'\n",
)
HAB104 = HabitCase(
    "HAB104",
    "app/uses_tests.py",
    "from common.tests import helper\n",
    "from common import helper\n",
    slug=CLOUD_SLUG,
)
HAB102 = HabitCase(
    "HAB102",
    "app/services/shapes.py",
    "from dataclasses import dataclass\n\n\n@dataclass\nclass Shape:\n"
    "    sides: int\n",
    "from dataclasses import dataclass\n\n\n@dataclass\nclass Shape:\n"
    "    sides: int\n",
    slug=CLOUD_SLUG,
    good_path="app/models/shapes.py",
)
HAB082 = HabitCase(
    "HAB082",
    "app/logic.py",
    "class BrokenError(Exception):\n    pass\n",
    "class BrokenError(Exception):\n    pass\n",
    slug=DEVICE_SLUG,
    good_path="app/errors.py",
)
HAB092 = HabitCase(
    "HAB092",
    "app/settings.py",
    "import os\n\nVALUE = os.environ['MISSING_NAME']\n",
    "import os\n\nVALUE = os.environ['KNOWN_NAME']\n",
    setup=ENV_EXAMPLE_SETUP,
)
HAB070 = HabitCase(
    "HAB070",
    "app/paths.py",
    "ROOT = '__HOME__/project'\n",
    "ROOT = 'project'\n",
)
HAB013_BASE = "VALUE = 1\n" * 999
HAB013_GROWN = "VALUE = 1\n" * 1001

HAB_CASES = [
    HAB120,
    HAB084,
    HAB091,
    HAB051,
    HAB106,
    HAB052,
    HAB118,
    HAB077,
    HAB083,
    HAB104,
    HAB082,
    HAB092,
    HAB070,
]
SCOPED_CASES = [HAB104, HAB102, HAB082]


def habit_rules_at(run: Run, path: str) -> set[str]:
    return {rule for rule in rules_at(run, path) if rule.startswith("HAB")}


def habit_run(
    repo: Path,
    log_dir: Path,
    case: HabitCase,
    text: str,
    *,
    committed: bool = False,
) -> Run:
    if case.slug:
        slug_url = f"git@bitbucket.org:{case.slug}.git"
        git(repo, "remote", "add", "origin", slug_url)
    for name, body in (case.setup or {}).items():
        write(repo, name, body)
    if committed:
        write(repo, case.path, text)
        commit_all(repo)
        append(repo, case.path, UNRELATED_LINE)
    else:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "setup")
        write(repo, case.path, text)
    return lint(repo, log_dir, "--json")


def assert_case_reported(repo: Path, log_dir: Path, case: HabitCase) -> None:
    run = habit_run(repo, log_dir, case, case.bad)

    assert case.code in habit_rules_at(run, case.path)
    assert run.code == EXIT_FAIL


def test_hab120_strenum_literal_equal_to_name_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB120)


def test_hab084_http_status_number_constant_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB084)


def test_hab091_relationship_string_target_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB091)


def test_hab051_environ_setdefault_in_test_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB051)


def test_hab106_patching_time_module_in_test_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB106)


def test_hab052_subprocess_run_without_timeout_in_test_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB052)


def test_hab118_session_call_outside_repositories_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB118)


def test_hab077_init_all_is_reported(repo: Path, log_dir: Path) -> None:
    assert_case_reported(repo, log_dir, HAB077)


def test_hab083_print_in_importable_module_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB083)


def test_hab104_common_tests_import_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB104)


def test_hab102_dataclass_in_services_is_reported(
    repo: Path, log_dir: Path
) -> None:
    run = habit_run(repo, log_dir, HAB102, HAB102.bad)

    assert "HAB102" in habit_rules_at(run, HAB102.path)


def test_hab082_exception_outside_errors_module_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB082)


def test_hab092_undeclared_env_var_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB092)


def test_hab070_home_directory_literal_is_reported(
    repo: Path, log_dir: Path
) -> None:
    assert_case_reported(repo, log_dir, HAB070)


def test_hab013_file_crossing_line_limit_is_reported(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "big.py", HAB013_BASE)
    commit_all(repo)
    write(repo, "big.py", HAB013_GROWN)

    run = lint(repo, log_dir, "--json")

    assert "HAB013" in habit_rules_at(run, "big.py")


def test_hab013_new_file_over_line_limit_is_reported(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "huge.py", HAB013_GROWN)

    run = lint(repo, log_dir, "--json")

    assert "HAB013" in habit_rules_at(run, "huge.py")


def test_hab013_test_file_over_line_limit_is_not_reported(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "tests/test_big.py", HAB013_GROWN)

    run = lint(repo, log_dir, "--json")

    assert "HAB013" not in habit_rules_at(run, "tests/test_big.py")


def test_line_count_already_over_limit_not_reported(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "big.py", HAB013_GROWN)
    commit_all(repo)
    append(repo, "big.py", "VALUE = 2\n")

    run = lint(repo, log_dir, "--json")

    assert "HAB013" not in habit_rules_at(run, "big.py")


@pytest.mark.parametrize("case", [*HAB_CASES, HAB102], ids=lambda c: c.code)
def test_compliant_counterpart_is_not_reported(
    repo: Path, log_dir: Path, case: HabitCase
) -> None:
    path = case.good_path or case.path
    compliant = replace(case, path=path)

    run = habit_run(repo, log_dir, compliant, case.good)

    assert habit_rules_at(run, path) == set()


@pytest.mark.parametrize("case", [*HAB_CASES, HAB102], ids=lambda c: c.code)
def test_unchanged_violation_line_is_not_reported(
    repo: Path, log_dir: Path, case: HabitCase
) -> None:
    run = habit_run(repo, log_dir, case, case.bad, committed=True)

    assert case.code not in habit_rules_at(run, case.path)


@pytest.mark.parametrize("case", SCOPED_CASES, ids=lambda c: c.code)
@pytest.mark.parametrize("slug", [OTHER_SLUG, None], ids=["other", "absent"])
def test_repo_without_origin_skips_repo_rules(
    repo: Path, log_dir: Path, case: HabitCase, slug: str | None
) -> None:
    if slug is None:
        run = habit_run(repo, log_dir, replace(case, slug=None), case.bad)
    else:
        run = habit_run(repo, log_dir, replace(case, slug=slug), case.bad)

    assert case.code not in habit_rules_at(run, case.path)


def test_env_example_absent_skips_env_rule(repo: Path, log_dir: Path) -> None:
    case = replace(HAB092, setup=None)

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB092" not in habit_rules_at(run, case.path)


def test_unparsable_python_reports_not_checked(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "broken.py", "def broken(:\n")

    run = lint(repo, log_dir, "--json")

    assert ("broken.py", "habit-rules") in not_checked_reasons(run)
    assert habit_rules_at(run, "broken.py") == set()


PRIVATE_IMPORT = "from pkg.mod import _private\n"


def test_plc2701_private_import_is_reported(repo: Path, log_dir: Path) -> None:
    write(repo, "app/uses.py", PRIVATE_IMPORT)

    run = lint(repo, log_dir, "--json")

    assert "PLC2701" in rules_at(run, "app/uses.py")


def test_plc2701_ignored_in_test_files(repo: Path, log_dir: Path) -> None:
    write(repo, "tests/test_uses.py", PRIVATE_IMPORT)

    run = lint(repo, log_dir, "--json")

    assert "PLC2701" not in rules_at(run, "tests/test_uses.py")


def test_hab104_common_tests_import_in_test_file_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB104",
        "tests/test_uses.py",
        "from common.tests import helper\n",
        "from common.testing import helper\n",
        slug=CLOUD_SLUG,
    )

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB104" in habit_rules_at(run, case.path)


def test_status_cache_size_constant_is_not_hab084(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase("HAB084", "app/c.py", "STATUS_CACHE_SIZE = 100\n", "")

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB084" not in habit_rules_at(run, case.path)


def test_max_status_history_constant_is_not_hab084(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase("HAB084", "app/h.py", "MAX_STATUS_HISTORY = 200\n", "")

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB084" not in habit_rules_at(run, case.path)


def test_bare_member_name_status_constant_is_hab084(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase("HAB084", "app/n.py", "NOT_FOUND = 404\n", "")

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB084" in habit_rules_at(run, case.path)


def test_renamed_long_file_is_not_hab013(repo: Path, log_dir: Path) -> None:
    write(repo, "big.py", HAB013_GROWN)
    commit_all(repo)
    git(repo, "mv", "big.py", "large.py")
    append(repo, "large.py", "VALUE = 2\n")

    run = lint(repo, log_dir, "--json")

    assert "HAB013" not in habit_rules_at(run, "large.py")


def test_staged_env_example_declaration_is_honoured(
    repo: Path, log_dir: Path
) -> None:
    write(repo, ".env.example", "KNOWN_NAME=1\n")
    commit_all(repo)
    write(repo, ".env.example", "KNOWN_NAME=1\nNEW_NAME=2\n")
    write(repo, "app/settings.py", "import os\n\nV = os.environ['NEW_NAME']\n")
    git(repo, "add", "-A")
    write(repo, ".env.example", "KNOWN_NAME=1\n")

    run = lint(repo, log_dir, "--staged", "--json")

    assert "HAB092" not in habit_rules_at(run, "app/settings.py")


def test_strenum_ignored_name_is_not_hab120(repo: Path, log_dir: Path) -> None:
    text = (
        "from enum import StrEnum\n\n\nclass Color(StrEnum):\n"
        "    _ignore_ = ['scratch']\n    scratch = 'scratch'\n"
    )
    case = HabitCase("HAB120", "app/colors.py", text, text)

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB120" not in habit_rules_at(run, case.path)


def test_renamed_long_file_resolves_its_old_path(ls: ModuleType) -> None:
    entries = [
        ls.DiffEntry("M", "other.py", None, "100644"),
        ls.DiffEntry("R", "large.py", "big.py", "100644"),
    ]

    assert ls.renamed_from(entries, "large.py") == "big.py"
    assert ls.renamed_from(entries, "other.py") is None
    assert ls.renamed_from(entries, "missing.py") is None


def test_strenum_comma_separated_ignore_is_not_hab120(
    repo: Path, log_dir: Path
) -> None:
    text = (
        "from enum import StrEnum\n\n\nclass Color(StrEnum):\n"
        "    _ignore_ = 'scratch, other'\n    scratch = 'scratch'\n"
        "    other = 'other'\n"
    )
    case = HabitCase("HAB120", "app/colors.py", text, text)

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB120" not in habit_rules_at(run, case.path)


UI_SLUG = "acme/web-ui"
CLK_SLUG = "acme/kiosk-ui"
PL_LOCALE = "src/locales/pl/translation.json"
EN_LOCALE = "src/locales/en/translation.json"


def assert_reported(repo: Path, log_dir: Path, case: HabitCase) -> None:
    run = habit_run(repo, log_dir, case, case.bad)

    assert case.code in habit_rules_at(run, case.path)


def test_hab066_then_with_rejection_handler_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB066", "src/api.ts", "load().then(onOk, onFail);\n", ""
    )

    assert_reported(repo, log_dir, case)


def test_hab005_catch_without_binding_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB005", "src/run.ts", "try {\n  go();\n} catch {\n  stop();\n}\n", ""
    )

    assert_reported(repo, log_dir, case)


def test_hab094_api_types_import_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB094",
        "src/view.ts",
        "import { User } from '@/api/types/user';\n",
        "",
        slug=UI_SLUG,
    )

    assert_reported(repo, log_dir, case)


def test_hab058_default_language_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB058",
        "src/lang.ts",
        "const lang = config.default_language;\n",
        "",
        slug=CLK_SLUG,
    )

    assert_reported(repo, log_dir, case)


def test_hab092_ts_undeclared_env_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB092",
        "src/env.ts",
        "export const v = process.env.MISSING_NAME;\n",
        "",
        setup=ENV_EXAMPLE_SETUP,
    )

    assert_reported(repo, log_dir, case)


def test_hab070_ts_home_path_is_reported(repo: Path, log_dir: Path) -> None:
    case = HabitCase(
        "HAB070", "src/paths.ts", "export const root = '/home/sam/app/';\n", ""
    )

    assert_reported(repo, log_dir, case)


def test_hab023_count_key_without_plurals_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB023", EN_LOCALE, '{\n  "items": "{{count}} items"\n}\n', ""
    )

    assert_reported(repo, log_dir, case)


def test_hab023_missing_pl_plural_form_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = (
        '{\n  "item_one": "{{count}} rzecz",\n'
        '  "item_other": "{{count}} rzeczy"\n}\n'
    )
    case = HabitCase("HAB023", PL_LOCALE, text, "")

    assert_reported(repo, log_dir, case)


def test_hab023_key_missing_in_sibling_locale_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB023",
        PL_LOCALE,
        '{\n  "title": "Tytul",\n  "extra": "Dodatek"\n}\n',
        "",
        setup={EN_LOCALE: '{\n  "title": "Title"\n}\n'},
    )

    assert_reported(repo, log_dir, case)


def test_hab057_automat_in_pl_locale_is_reported(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB057",
        PL_LOCALE,
        '{\n  "pick": "Wybierz automat"\n}\n',
        "",
        slug=UI_SLUG,
    )

    assert_reported(repo, log_dir, case)


PL_PLURALS = (
    '{\n  "k_one": "{{count}} a",\n  "k_few": "{{count}} b",\n'
    '  "k_many": "{{count}} c",\n  "k_other": "{{count}} d"\n}\n'
)
EN_PLURALS = '{\n  "k_one": "{{count}} a",\n  "k_other": "{{count}} b"\n}\n'
M2_CASES = [
    HabitCase(
        "HAB066",
        "src/api.ts",
        "load().then(onOk, onFail);\n",
        "load().then(onOk).catch(onFail);\n",
    ),
    HabitCase(
        "HAB005",
        "src/run.ts",
        "try {\n  go();\n} catch {\n  stop();\n}\n",
        "try {\n  go();\n} catch (err) {\n  stop(err);\n}\n",
    ),
    HabitCase(
        "HAB094",
        "src/view.ts",
        "import { User } from '@/api/types/user';\n",
        "import { User } from '@/api/client';\n",
        slug=UI_SLUG,
    ),
    HabitCase(
        "HAB058",
        "src/lang.ts",
        "const lang = config.default_language;\n",
        "const lang = config.language;\n",
        slug=CLK_SLUG,
    ),
    HabitCase(
        "HAB092",
        "src/env.ts",
        "export const v = process.env.MISSING_NAME;\n",
        "export const v = process.env.KNOWN_NAME;\n",
        setup=ENV_EXAMPLE_SETUP,
    ),
    HabitCase(
        "HAB070",
        "src/paths.ts",
        "export const root = '/home/sam/app/';\n",
        "export const root = 'app';\n",
    ),
    HabitCase(
        "HAB023",
        EN_LOCALE,
        '{\n  "items": "{{count}} items"\n}\n',
        EN_PLURALS,
    ),
    HabitCase(
        "HAB057",
        PL_LOCALE,
        '{\n  "pick": "Wybierz automat"\n}\n',
        '{\n  "pick": "Wybierz urzadzenie"\n}\n',
        slug=UI_SLUG,
    ),
]


@pytest.mark.parametrize("case", M2_CASES, ids=lambda c: f"{c.code}-{c.path}")
def test_m2_compliant_counterpart_is_not_reported(
    repo: Path, log_dir: Path, case: HabitCase
) -> None:
    run = habit_run(repo, log_dir, case, case.good)

    assert habit_rules_at(run, case.path) == set()


@pytest.mark.parametrize("case", M2_CASES, ids=lambda c: f"{c.code}-{c.path}")
def test_m2_unchanged_violation_line_is_not_reported(
    repo: Path, log_dir: Path, case: HabitCase
) -> None:
    if case.path.endswith(".json"):
        if case.slug:
            origin = f"git@bitbucket.org:{case.slug}.git"
            git(repo, "remote", "add", "origin", origin)
        write(repo, case.path, case.bad)
        commit_all(repo)
        write(repo, case.path, case.bad.replace("{\n", '{\n  "z": "z",\n', 1))
        run = lint(repo, log_dir, "--json")
    else:
        run = habit_run(repo, log_dir, case, case.bad, committed=True)

    assert case.code not in habit_rules_at(run, case.path)


def test_package_json_is_not_a_target(repo: Path, log_dir: Path) -> None:
    write(repo, "package.json", '{"a": "{{count}} x", "b": "automat"}\n')
    write(repo, "tsconfig.json", "{\n")
    write(repo, "src/data.json", "{\n")

    run = lint(repo, log_dir, "--json")

    names = {item["path"] for item in run.json()["not_checked"]}
    assert not names & {"package.json", "tsconfig.json", "src/data.json"}
    assert habit_rules_at(run, "package.json") == set()


def test_invalid_locale_json_reports_not_checked(
    repo: Path, log_dir: Path
) -> None:
    write(repo, PL_LOCALE, '{\n  "a": \n')

    run = lint(repo, log_dir, "--json")

    assert (PL_LOCALE, "habit-rules") in not_checked_reasons(run)
    assert habit_rules_at(run, PL_LOCALE) == set()


def test_magic_and_clones_skip_locale_targets(
    ls: ModuleType, repo: Path, log_dir: Path
) -> None:
    write(repo, PL_LOCALE, '{\n  "a": 37,\n  "b": 37,\n  "c": 37\n}\n')

    run = lint(repo, log_dir, "--json")

    assert ls.Language.LOCALE not in ls.MagicBackend().languages
    assert ls.Language.LOCALE not in ls.CloneBackend().languages
    assert not rules_at(run, PL_LOCALE) & MAGIC_RULE_NAMES


def test_then_catch_chain_is_not_hab066(repo: Path, log_dir: Path) -> None:
    case = M2_CASES[0]
    text = "load().then(onOk);\nload().catch(onErr);\n"

    run = habit_run(repo, log_dir, case, text)

    assert habit_rules_at(run, case.path) == set()


def test_catch_with_binding_is_not_hab005(repo: Path, log_dir: Path) -> None:
    case = M2_CASES[1]

    run = habit_run(repo, log_dir, case, case.good)

    assert "HAB005" not in habit_rules_at(run, case.path)


def test_hab094_other_repo_is_silent(repo: Path, log_dir: Path) -> None:
    case = replace(M2_CASES[2], slug=OTHER_SLUG)

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB094" not in habit_rules_at(run, case.path)


def test_hab058_other_repo_is_silent(repo: Path, log_dir: Path) -> None:
    case = replace(M2_CASES[3], slug=OTHER_SLUG)

    run = habit_run(repo, log_dir, case, case.bad)

    assert "HAB058" not in habit_rules_at(run, case.path)


@pytest.mark.parametrize(
    ("path", "slug", "text"),
    [
        (PL_LOCALE, UI_SLUG, '{\n  "a": "Zapisz automatycznie"\n}\n'),
        (PL_LOCALE, OTHER_SLUG, '{\n  "a": "Wybierz automat"\n}\n'),
        (EN_LOCALE, UI_SLUG, '{\n  "a": "Pick an automat"\n}\n'),
    ],
    ids=["automatycznie", "other-repo", "en-file"],
)
def test_automat_variants_are_not_hab057(
    repo: Path, log_dir: Path, path: str, slug: str, text: str
) -> None:
    case = HabitCase("HAB057", path, text, text, slug=slug)

    run = habit_run(repo, log_dir, case, text)

    assert "HAB057" not in habit_rules_at(run, path)


def test_complete_plural_family_is_not_hab023(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase(
        "HAB023",
        PL_LOCALE,
        PL_PLURALS,
        PL_PLURALS,
        setup={EN_LOCALE: EN_PLURALS},
    )

    run = habit_run(repo, log_dir, case, PL_PLURALS)

    assert habit_rules_at(run, PL_LOCALE) == set()
    assert habit_rules_at(run, EN_LOCALE) == set()


def test_locale_without_sibling_skips_parity(
    repo: Path, log_dir: Path
) -> None:
    case = HabitCase("HAB023", PL_LOCALE, "{}\n", "{}\n")
    text = '{\n  "title": "Tytul"\n}\n'

    run = habit_run(repo, log_dir, case, text)

    assert habit_rules_at(run, PL_LOCALE) == set()


def test_lone_other_suffix_key_is_not_hab023(
    repo: Path, log_dir: Path
) -> None:
    text = '{\n  "payment_method_other": "Inna metoda"\n}\n'
    case = HabitCase("HAB023", PL_LOCALE, text, text)

    run = habit_run(repo, log_dir, case, text)

    assert "HAB023" not in habit_rules_at(run, PL_LOCALE)


def test_lone_other_suffix_key_parity_uses_full_key(
    repo: Path, log_dir: Path
) -> None:
    text = '{\n  "title": "T",\n  "payment_method_other": "I"\n}\n'
    sibling = '{\n  "title": "T",\n  "payment_method": "M"\n}\n'
    case = HabitCase(
        "HAB023", PL_LOCALE, text, text, setup={EN_LOCALE: sibling}
    )

    run = habit_run(repo, log_dir, case, text)

    assert (PL_LOCALE, 3, "HAB023") in violations(run)


def test_then_with_generic_arguments_is_not_hab066(
    repo: Path, log_dir: Path
) -> None:
    text = "load().then(x => new Map<string, number>());\n"
    case = HabitCase("HAB066", "src/api.ts", text, text)

    run = habit_run(repo, log_dir, case, text)

    assert "HAB066" not in habit_rules_at(run, case.path)


def test_api_typescript_import_is_not_hab094(
    repo: Path, log_dir: Path
) -> None:
    text = "import { U } from '@/api/typescript';\n"
    case = HabitCase("HAB094", "src/view.ts", text, text, slug=UI_SLUG)

    run = habit_run(repo, log_dir, case, text)

    assert "HAB094" not in habit_rules_at(run, case.path)


def test_deeply_nested_locale_reports_not_checked(
    repo: Path, log_dir: Path
) -> None:
    depth = 1200
    write(repo, PL_LOCALE, '{"a":' * depth + "1" + "}" * depth)

    run = lint(repo, log_dir, "--json")

    assert (PL_LOCALE, "habit-rules") in not_checked_reasons(run)


def test_value_on_separate_line_is_hab057(repo: Path, log_dir: Path) -> None:
    before = '{\n  "key":\n    "Wybierz urzadzenie"\n}\n'
    after = '{\n  "key":\n    "Wybierz automat"\n}\n'
    case = HabitCase(
        "HAB057",
        PL_LOCALE,
        after,
        before,
        slug=UI_SLUG,
        setup={PL_LOCALE: before},
    )

    run = habit_run(repo, log_dir, case, after)

    assert (PL_LOCALE, 3, "HAB057") in violations(run)


FAKE_PRETTIER_VERSIONED = FAKE_PRETTIER.replace(
    'print("3.9.9")',
    'print(os.environ.get("FAKE_PRETTIER_VERSION", "3.9.9"))',
)
CHANGED_JS = JS_DEFAULT_STYLE.replace('"x";', "'q';")


def prettier_fixture(repo: Path, tmp_path: Path) -> Path:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER_VERSIONED)
    package = make_package(repo, eslint=False)
    write(package, "a.js", JS_DEFAULT_STYLE)
    commit_all(repo)
    write(package, "a.js", CHANGED_JS)
    return prettier


def test_prettier_fallback_second_run_spawns_no_prettier(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}

    first = lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    second = lint(repo, log_dir, "--json", extra_env=env)

    assert spawned > 0
    assert len(records(prettier)) == spawned
    assert violations(second) == violations(first) != set()


def test_prettier_version_change_is_cache_miss(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}

    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    env["FAKE_PRETTIER_VERSION"] = "3.9.8"
    lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(prettier)) == 2 * spawned


FAKE_TSC_BUILDINFO = """
args = sys.argv[1:]
record({"argv": args})
if "--tsBuildInfoFile" in args:
    target = Path(args[args.index("--tsBuildInfoFile") + 1])
    previous = target.read_text() if target.exists() else ""
    target.write_text(previous + "x")
"""


def tsc_fixture(repo: Path) -> Path:
    package = make_package(repo)
    write(package, "tsconfig.json", "{}\n")
    tsc = make_fake(package / "node_modules/.bin/tsc", FAKE_TSC_BUILDINFO)
    write(package, "src/a.ts", "export const a = 1;\n")
    commit_all(repo)
    write(package, "src/a.ts", "export const a = 2;\n")
    return tsc


def tsc_run_argv(tsc: Path) -> list[str]:
    return next(
        call["argv"] for call in records(tsc) if "--noEmit" in call["argv"]
    )


def test_tsc_runs_incremental_with_buildinfo_in_cache_dir(
    repo: Path,
    log_dir: Path,
) -> None:
    tsc = tsc_fixture(repo)
    cache = cache_path(log_dir)

    lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    argv = tsc_run_argv(tsc)
    assert "--incremental" in argv
    temp = Path(argv[argv.index("--tsBuildInfoFile") + 1])
    assert temp.parent == cache / "tsc"
    finals = list((cache / "tsc").glob("*.tsbuildinfo"))
    assert [f.read_text() for f in finals] == ["x"]
    lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)
    latest = (cache / "tsc").glob("*.tsbuildinfo")
    assert [f.read_text() for f in latest] == ["xx"]


def test_tsc_without_writable_cache_runs_plain(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    tsc = tsc_fixture(repo)
    lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)
    blocker = write(tmp_path, "blocker", "")
    blocked = {**REAL_TS_TOOLS, "LINT_STRICT_CACHE_DIR": str(blocker)}

    run = lint(repo, log_dir, "--json", extra_env=blocked)

    runs = [c["argv"] for c in records(tsc) if "--noEmit" in c["argv"]]
    flags = sorted("--incremental" in argv for argv in runs)
    assert flags == [False, True]
    assert run.code == EXIT_PASS, run.out


TS_FIX_FILES = ("a.ts", "b.ts", "c.ts")
FIX_CONST = json.dumps(
    [
        {
            "ruleId": "prefer-const",
            "severity": 2,
            "message": "use let",
            "line": 1,
            "column": 1,
            "fix": {"range": [0, 5], "text": "let"},
        },
    ],
)
FAKE_ESLINT_BATCH_FAILS = """
if "--stdin" not in sys.argv and "--version" not in sys.argv:
    record({"argv": sys.argv[1:], "stdin": None, "failed": True})
    print("not json")
    raise SystemExit(2)
"""


def ts_fix_package(repo: Path, eslint_body: str = FAKE_ESLINT) -> Path:
    package = make_package(repo)
    make_fake(package / "node_modules/.bin/eslint", eslint_body)
    commit_all(repo)
    for name in TS_FIX_FILES:
        write(package, f"src/{name}", "const a = 1;\n")
    return package


def test_fix_runs_one_eslint_for_all_files(
    repo: Path,
    log_dir: Path,
) -> None:
    package = ts_fix_package(repo)

    fix(repo, log_dir, extra_env={"FAKE_MESSAGES": FIX_CONST})

    calls = records(package / "node_modules/.bin/eslint")
    assert [call["stdin"] for call in calls] == [None, None]
    for call in calls:
        files = [a for a in call["argv"] if a.endswith(".ts")]
        assert sorted(Path(f).name for f in files) == list(TS_FIX_FILES)
    for name in TS_FIX_FILES:
        assert (package / f"src/{name}").read_text() == "let a = 1;\n"


def test_fix_batch_failure_falls_back_per_file(
    repo: Path,
    log_dir: Path,
) -> None:
    package = ts_fix_package(repo, FAKE_ESLINT_BATCH_FAILS + FAKE_ESLINT)

    fix(repo, log_dir, extra_env={"FAKE_MESSAGES": FIX_CONST})

    calls = records(package / "node_modules/.bin/eslint")
    assert len([c for c in calls if c["stdin"] is not None]) == 3
    assert len([c for c in calls if c.get("failed")]) == 2
    for name in TS_FIX_FILES:
        assert (package / f"src/{name}").read_text() == "let a = 1;\n"


def test_jscpd_base_result_cached(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[])

    first = lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(fake))
    second = lint(repo, log_dir, "--json", extra_env=env)

    assert spawned == 2
    assert len(records(fake)) == spawned + 1
    assert dup_violations(first) == dup_violations(second) != set()


HEAVY_HOLD_SECONDS = 1.0


def hold_slot(log_dir: Path, number: int = 0) -> int:
    slots = cache_path(log_dir) / "slots"
    slots.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(slots / f"{number}.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def test_check_mode_waits_for_heavy_slot(
    repo: Path,
    log_dir: Path,
) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "export const a = 1;\n")
    descriptor = hold_slot(log_dir)
    release = threading.Timer(HEAVY_HOLD_SECONDS, os.close, (descriptor,))
    release.start()
    started = time.monotonic()

    run = lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_HEAVY_SLOTS": "1"},
        timeout=60,
    )

    elapsed = time.monotonic() - started
    release.join()
    assert records(package / "node_modules/.bin/eslint")
    assert elapsed >= HEAVY_HOLD_SECONDS, run.out


def test_fix_never_waits_for_heavy_slot(
    repo: Path,
    log_dir: Path,
) -> None:
    package = ts_fix_package(repo)
    descriptor = hold_slot(log_dir)

    run = lint(
        repo,
        log_dir,
        *FIX_FLAGS,
        extra_env={"LINT_STRICT_HEAVY_SLOTS": "1", "FAKE_MESSAGES": FIX_CONST},
        timeout=30,
    )

    os.close(descriptor)
    assert run.json()["fixed_files"]
    for name in TS_FIX_FILES:
        assert (package / f"src/{name}").read_text() == "let a = 1;\n"


def test_corrupt_prettier_cache_is_miss(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}
    first = lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    entries = list((cache_path(log_dir) / "prettier").iterdir())
    for entry in entries:
        entry.write_text('{"stdout": ', encoding="utf-8")
    entries[0].write_bytes(b"\xff\xfe")

    second = lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(prettier)) == 2 * spawned
    assert violations(second) == violations(first) != set()


def test_unwritable_cache_dir_lint_still_passes(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}
    healthy = lint(repo, log_dir, "--json", extra_env=env)
    blocker = write(tmp_path, "blocker", "")
    env["LINT_STRICT_CACHE_DIR"] = str(blocker)

    blocked = lint(repo, log_dir, "--json", extra_env=env)

    assert blocked.code == healthy.code == EXIT_FAIL
    assert violations(blocked) == violations(healthy) != set()
    assert blocked.err == healthy.err


def test_jscpd_base_cache_miss_on_new_base_commit(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[])
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(fake))
    write(repo, "other.txt", "x\n")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-q", "-m", "other")

    lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(fake)) == 2 * spawned


def test_jscpd_base_cache_miss_on_version_change(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[])
    fake.write_text(
        fake.read_text(encoding="utf-8").replace(
            'print("5.4.0")',
            'print(os.environ.get("FAKE_JSCPD_VERSION", "5.4.0"))',
        ),
        encoding="utf-8",
    )
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(fake))

    lint(repo, log_dir, "--json", extra_env={**env, "FAKE_JSCPD_VERSION": "6"})

    assert len(records(fake)) == 2 * spawned


def test_jscpd_cached_base_still_hides_known_clones(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    write(repo, "src/c.py", clone_source("third"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    known = clone_entry("src/a.py", "src/c.py")
    fresh = clone_entry("src/a.py", "src/b.py")
    _, env = jscpd_env(repo, tmp_path, current=[known, fresh], base=[known])

    first = lint(repo, log_dir, "--json", extra_env=env)
    second = lint(repo, log_dir, "--json", extra_env=env)

    assert dup_violations(first) == dup_violations(second)
    assert ("src/b.py", 1) in dup_violations(second)
    assert ("src/c.py", 1) not in dup_violations(second)


def test_jscpd_base_key_without_head(
    log_dir: Path,
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", MAIN)
    write(fresh, "src/a.py", clone_source("first"))
    write(fresh, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    _, env = jscpd_env(fresh, tmp_path, current=[clone], base=[])

    first = lint(fresh, log_dir, "--json", extra_env=env)
    second = lint(fresh, log_dir, "--json", extra_env=env)

    assert dup_violations(first) == dup_violations(second) != set()


def test_cache_key_separates_parts(ls: ModuleType) -> None:
    assert ls.cache_key("a", "bc") != ls.cache_key("ab", "c")
    assert ls.cache_key("a", "bc") == ls.cache_key("a", "bc")


def test_cache_store_replaces_without_leftovers(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "entries"

    ls.cache_store(directory, "key", {"stdout": "one"})
    ls.cache_store(directory, "key", {"stdout": "two"})

    assert ls.cache_load(directory, "key") == {"stdout": "two"}
    assert sorted(entry.name for entry in directory.glob("*.json")) == [
        "key.json",
    ]
    assert not list(directory.glob("*.tmp"))


def test_cache_concurrent_stores_leave_a_valid_entry(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "entries"
    writers = [
        threading.Thread(
            target=ls.cache_store,
            args=(directory, "key", {"stdout": str(n) * 1000}),
        )
        for n in range(8)
    ]

    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join()

    loaded = ls.cache_load(directory, "key")
    assert loaded["stdout"] in {str(n) * 1000 for n in range(8)}
    assert sorted(entry.name for entry in directory.glob("*.json")) == [
        "key.json",
    ]
    assert not list(directory.glob("*.tmp"))


@pytest.mark.parametrize(
    "content",
    [b"", b"{", b"\xff\xfe", b"[1, 2"],
)
def test_cache_load_corrupt_entry_is_miss(
    ls: ModuleType,
    tmp_path: Path,
    content: bytes,
) -> None:
    (tmp_path / "key.json").write_bytes(content)

    assert ls.cache_load(tmp_path, "key") is None
    assert ls.cache_load(tmp_path, "absent") is None


def test_cache_store_unwritable_directory_is_ignored(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    blocker = write(tmp_path, "blocker", "")

    ls.cache_store(blocker / "inside", "key", {"stdout": "x"})

    assert ls.cache_load(blocker / "inside", "key") is None


@pytest.mark.parametrize(
    "document",
    [None, {}, [1], [[["a"], []]], [[[1], 5]], [[["a"]]], "x"],
)
def test_cached_clone_keys_malformed_is_miss(
    ls: ModuleType,
    document: object,
) -> None:
    assert ls.cached_clone_keys(document) is None


def test_cached_clone_keys_round_trip(ls: ModuleType) -> None:
    document = [[["a.py", "b.py"], 184], [["a.py", "c.py"], "digest"]]

    assert ls.cached_clone_keys(document) == {
        (frozenset({"a.py", "b.py"}), 184),
        (frozenset({"a.py", "c.py"}), "digest"),
    }


@pytest.fixture
def slot_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setenv("LINT_STRICT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LINT_STRICT_HEAVY_SLOTS", "1")
    return tmp_path / "cache" / "slots"


def hold_lock(slots: Path) -> int:
    slots.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(slots / "0.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    return descriptor


def test_heavy_slot_wait_timeout_runs_without_slot(
    ls: ModuleType,
    slot_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ls, "HEAVY_SLOT_MAX_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(ls, "HEAVY_SLOT_POLL_SECONDS", 0.05)
    descriptor = hold_lock(slot_env)
    started = time.monotonic()

    with ls.heavy_slot():
        ran = True

    os.close(descriptor)
    assert ran
    assert time.monotonic() - started >= 0.3


def test_heavy_slot_zero_slots_disables(
    ls: ModuleType,
    slot_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINT_STRICT_HEAVY_SLOTS", "0")
    descriptor = hold_lock(slot_env)
    started = time.monotonic()

    with ls.heavy_slot():
        ran = True

    os.close(descriptor)
    assert ran
    assert time.monotonic() - started < 0.2


def test_heavy_slot_is_released_after_the_body(
    ls: ModuleType,
    slot_env: Path,
) -> None:
    with ls.heavy_slot():
        pass

    descriptor = os.open(slot_env / "0.lock", os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(descriptor)


def test_heavy_slot_released_when_body_raises(
    ls: ModuleType,
    slot_env: Path,
) -> None:
    with pytest.raises(RuntimeError), ls.heavy_slot():
        raise RuntimeError

    descriptor = os.open(slot_env / "0.lock", os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(descriptor)


def test_heavy_slot_unwritable_cache_runs_without_slot(
    ls: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = write(tmp_path, "blocker", "")
    monkeypatch.setenv("LINT_STRICT_CACHE_DIR", str(blocker))

    with ls.heavy_slot():
        ran = True

    assert ran


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2", 2), ("0", 0), ("-1", 0), ("many", 3), ("", 3)],
)
def test_heavy_slot_count_parsing(
    ls: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: int,
) -> None:
    monkeypatch.setenv("LINT_STRICT_HEAVY_SLOTS", value)

    assert ls.heavy_slot_count() == expected


def test_heavy_slot_second_slot_is_used_when_first_is_taken(
    ls: ModuleType,
    slot_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINT_STRICT_HEAVY_SLOTS", "2")
    descriptor = hold_lock(slot_env)
    started = time.monotonic()

    with ls.heavy_slot():
        ran = True

    os.close(descriptor)
    assert ran
    assert time.monotonic() - started < 0.2
    assert (slot_env / "1.lock").exists()


def eslint_snapshot(ls: ModuleType, repo: Path, name: str) -> object:
    path = repo / name
    data = path.read_bytes()
    target = ls.LintTarget(
        name,
        ls.Language.TYPESCRIPT,
        frozenset({1}),
        ls.TextSource.DISK,
    )
    return ls.Snapshot(target, data, data.decode("utf-8"))


def test_fix_file_changed_since_snapshot_uses_stdin_path(
    ls: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "const a = 1;\n")
    snapshot = eslint_snapshot(ls, repo, "web/src/a.ts")
    write(package, "src/a.ts", "const a = 2;\n")
    monkeypatch.setenv("FAKE_MESSAGES", FIX_CONST)

    states = ls.eslint_fixed_states(ls.Repo(repo), package, [snapshot])

    calls = records(package / "node_modules/.bin/eslint")
    assert [call["stdin"] for call in calls] == ["const a = 1;\n"]
    assert states["web/src/a.ts"].text == "let a = 1;\n"


def test_fix_file_deleted_since_snapshot_uses_stdin_path(
    ls: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "const a = 1;\n")
    snapshot = eslint_snapshot(ls, repo, "web/src/a.ts")
    (package / "src/a.ts").unlink()
    monkeypatch.setenv("FAKE_MESSAGES", FIX_CONST)

    states = ls.eslint_fixed_states(ls.Repo(repo), package, [snapshot])

    calls = records(package / "node_modules/.bin/eslint")
    assert [call["stdin"] for call in calls] == ["const a = 1;\n"]
    assert states["web/src/a.ts"].text == "let a = 1;\n"


def prettier_cache_name(
    ls: ModuleType,
    repo: Path,
    prettier: Path,
) -> Callable[..., str]:
    package = repo / "web"
    choice = ls.PrettierChoice(str(prettier), own_config=False, cwd=package)
    runner = ls.PrettierRunner(ls.Repo(repo), choice, str(prettier))
    name: Callable[..., str] = runner.cache_name
    return name


@pytest.mark.parametrize("ignore_file", [".prettierignore", ".gitignore"])
def test_prettierignore_change_is_prettier_cache_miss(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
    ignore_file: str,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    write(repo / "web", ignore_file, "a.js\n")

    lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(prettier)) == 2 * spawned


@pytest.mark.parametrize("ignore_file", [".prettierignore", ".gitignore"])
def test_cache_name_follows_ignore_files(
    ls: ModuleType,
    repo: Path,
    tmp_path: Path,
    ignore_file: str,
) -> None:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    write(repo, "web/a.js", "x\n")
    cache_name = prettier_cache_name(ls, repo, prettier)
    sample = ls.Sample("web/a.js", "x\n")
    absent = cache_name((), sample)

    write(repo / "web", ignore_file, "")
    empty = cache_name((), sample)
    write(repo / "web", ignore_file, "a.js\n")
    filled = cache_name((), sample)

    assert len({absent, empty, filled}) == 3


FAKE_TSC_BUILDINFO_FAILS = """
args = sys.argv[1:]
record({"argv": args})
if "--incremental" in args:
    print("error TS5033: Could not write file 'x.tsbuildinfo'.")
    raise SystemExit(2)
"""


def test_tsc_buildinfo_write_failure_retries_plain(
    repo: Path,
    log_dir: Path,
) -> None:
    tsc = tsc_fixture(repo)
    make_fake(tsc, FAKE_TSC_BUILDINFO_FAILS)

    run = lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    runs = [c["argv"] for c in records(tsc) if "--noEmit" in c["argv"]]
    assert sorted("--incremental" in argv for argv in runs) == [False, True]
    assert ("web/src/a.ts", "tsc") not in not_checked_reasons(run)
    assert run.code == EXIT_PASS, run.out


def test_run_tsc_retries_plain_when_buildinfo_cannot_be_written(
    ls: ModuleType,
    repo: Path,
    log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tsc = tsc_fixture(repo)
    make_fake(tsc, FAKE_TSC_BUILDINFO_FAILS)
    monkeypatch.setenv("LINT_STRICT_CACHE_DIR", str(cache_path(log_dir)))

    config = repo / "web/tsconfig.json"

    result = ls.run_tsc(ls.Repo(repo), str(tsc), config, [])

    runs = [c["argv"] for c in records(tsc) if "--noEmit" in c["argv"]]
    assert sorted("--incremental" in argv for argv in runs) == [False, True]
    assert result.not_checked == ()


def test_prettier_cache_surrogate_entry_is_miss(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}
    first = lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    for entry in (cache_path(log_dir) / "prettier").iterdir():
        entry.write_text(json.dumps({"stdout": "\ud800"}), encoding="utf-8")

    second = lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(prettier)) == 2 * spawned
    assert second.code == first.code
    assert violations(second) == violations(first)


def test_cached_stdout_surrogate_is_miss(ls: ModuleType) -> None:
    assert ls.cached_stdout({"stdout": "\ud800"}) is None
    assert ls.cached_stdout({"stdout": "ok\n"}) == b"ok\n"


def spy_git(tmp_path: Path) -> tuple[dict[str, str], Path]:
    log = tmp_path / "git-calls.log"
    shim = tmp_path / "shim/git"
    shim.parent.mkdir()
    shim.write_text(
        f'#!/bin/sh\necho "$@" >> {log}\nexec {shutil.which("git")} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return {"PATH": f"{shim.parent}:{os.environ['PATH']}"}, log


def test_jscpd_base_uses_resolved_sha_for_extraction(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    head = git(repo, "rev-parse", "HEAD").strip()
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    _, env = jscpd_env(repo, tmp_path, current=[clone], base=[])
    spy_env, log = spy_git(tmp_path)

    lint(repo, log_dir, "--json", extra_env={**env, **spy_env})

    calls = log.read_text(encoding="utf-8").splitlines()
    base_calls = [c for c in calls if c.startswith(("ls-tree", "archive"))]
    assert base_calls
    assert all(head in call and "HEAD" not in call for call in base_calls)


def test_base_clone_keys_extract_the_resolved_sha(
    ls: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, ...]] = []

    def git_spy(_self: object, *args: str) -> str:
        seen.append(args)
        return "f" * 40 + "\n" if args[0] == "rev-parse" else "src/a.py\0"

    extracted: list[str] = []
    monkeypatch.setattr(ls.Repo, "git", git_spy)
    monkeypatch.setattr(
        ls,
        "materialize_base",
        lambda _repo, ref, _present, _dest: extracted.append(ref),
    )
    monkeypatch.setattr(ls, "detect_clones", lambda *_args: [])
    monkeypatch.setenv("LINT_STRICT_CACHE_DIR", str(tmp_path / "cache"))
    fake = make_fake(tmp_path / "tools/jscpd", FAKE_JSCPD)

    ls.base_clone_keys(ls.Repo(tmp_path), str(fake), ["src/a.py"], 1e12)

    tree = next(args for args in seen if args[0] == "ls-tree")
    assert tree[-1] == "f" * 40
    assert extracted == ["f" * 40]


def prerelease_prettier(tmp_path: Path) -> Path:
    return make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER_VERSIONED)


def test_prerelease_version_change_is_prettier_cache_miss(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {
        "LINT_STRICT_PRETTIER": str(prettier),
        "FAKE_PRETTIER_VERSION": "3.9.9-alpha.1",
    }
    first = lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    env["FAKE_PRETTIER_VERSION"] = "3.9.9-alpha.2"

    second = lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(prettier)) == 2 * spawned
    assert first.err == second.err


def versioned_jscpd(fake: Path) -> None:
    fake.write_text(
        fake.read_text(encoding="utf-8").replace(
            'print("5.4.0")',
            'print(os.environ.get("FAKE_JSCPD_VERSION", "5.4.0"))',
        ),
        encoding="utf-8",
    )


def test_prerelease_version_change_is_jscpd_cache_miss(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[])
    versioned_jscpd(fake)
    env["FAKE_JSCPD_VERSION"] = "5.4.0-rc.1"
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(fake))
    env["FAKE_JSCPD_VERSION"] = "5.4.0-rc.2"

    lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(fake)) == 2 * spawned


def test_executable_identity_keeps_prerelease_suffix(
    ls: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER_VERSIONED)
    monkeypatch.setenv("FAKE_PRETTIER_VERSION", "3.9.9-alpha.1")

    identity = ls.executable_identity(str(fake), tmp_path)

    assert identity == "3.9.9-alpha.1"
    assert ls.tool_version(str(fake), "prettier", tmp_path) == "prettier 3.9.9"


DAY_SECONDS = 24 * 60 * 60


def age(path: Path, days: float) -> None:
    moment = time.time() - days * DAY_SECONDS
    os.utime(path, (moment, moment))


def test_cache_prune_removes_stale_entries_keeps_fresh(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "cache/tsc"
    directory.mkdir(parents=True)
    names = {
        "old.json": 8,
        "fresh.json": 6,
        "old.uuid.tmp": 2,
        "fresh.uuid.tmp": 0.5,
        "abc.def.tsbuildinfo": 2,
        "abc.fresh.tsbuildinfo": 0.5,
        "abc.tsbuildinfo": 3,
        "stale.tsbuildinfo": 8,
    }
    for name, days in names.items():
        age(write(directory, name, "x"), days)
    slot = write(tmp_path / "cache/slots", "0.lock", "")
    age(slot, 30)

    ls.prune_cache(directory)

    kept = {entry.name for entry in directory.iterdir()} - {".pruned"}
    assert kept == {
        "fresh.json",
        "fresh.uuid.tmp",
        "abc.fresh.tsbuildinfo",
        "abc.tsbuildinfo",
    }
    assert slot.exists()


def test_prune_runs_at_most_once_per_interval(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    ls.prune_cache(tmp_path)
    stale = write(tmp_path, "stale.json", "x")
    age(stale, 8)

    ls.prune_cache(tmp_path)
    assert stale.exists()
    marker = tmp_path / ".pruned"
    moment = time.time() - 2 * 60 * 60
    os.utime(marker, (moment, moment))
    ls.prune_cache(tmp_path)

    assert not stale.exists()


def test_cache_hit_refreshes_mtime(ls: ModuleType, tmp_path: Path) -> None:
    ls.cache_store(tmp_path, "key", {"stdout": "x"})
    entry = tmp_path / "key.json"
    age(entry, 3)

    assert ls.cache_load(tmp_path, "key") == {"stdout": "x"}

    assert time.time() - entry.stat().st_mtime < DAY_SECONDS / 2


def test_lint_prunes_stale_prettier_entries(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    directory = cache_path(log_dir) / "prettier"
    stale = write(directory, "stale.json", "{}")
    age(stale, 8)

    lint(
        repo,
        log_dir,
        "--json",
        extra_env={"LINT_STRICT_PRETTIER": str(prettier)},
    )

    assert not stale.exists()
    assert any(directory.glob("*.json"))


def test_lint_prunes_stray_tsc_temporaries(
    repo: Path,
    log_dir: Path,
) -> None:
    tsc_fixture(repo)
    directory = cache_path(log_dir) / "tsc"
    stray = write(directory, "abc.dead.tsbuildinfo", "x")
    age(stray, 2)

    lint(repo, log_dir, "--json", extra_env=REAL_TS_TOOLS)

    assert not stray.exists()


def test_unreadable_prettierignore_bypasses_prettier_cache(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier)}
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))
    entries = len(list((cache_path(log_dir) / "prettier").glob("*.json")))
    exclude = repo / ".git/info/exclude"
    exclude.write_text("web/.prettierignore\n", encoding="utf-8")
    ignore = write(repo / "web", ".prettierignore", "a.js\n")
    ignore.chmod(0)

    lint(repo, log_dir, "--json", extra_env=env)
    after_second = len(records(prettier))
    lint(repo, log_dir, "--json", extra_env=env)

    ignore.chmod(0o600)
    assert after_second > spawned
    assert len(records(prettier)) - after_second == after_second - spawned
    cached = list((cache_path(log_dir) / "prettier").glob("*.json"))
    assert len(cached) == entries


def test_ignore_content_only_missing_file_is_absent(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    unreadable = write(tmp_path, "unreadable", "x")
    unreadable.chmod(0)

    assert ls.ignore_content(tmp_path / "missing") == ls.IGNORE_ABSENT
    assert ls.ignore_content(unreadable) is None
    assert ls.ignore_content(tmp_path) is None
    unreadable.chmod(0o600)
    assert ls.ignore_content(unreadable) != ls.IGNORE_ABSENT


def test_cache_name_is_none_for_unreadable_ignore_file(
    ls: ModuleType,
    repo: Path,
    tmp_path: Path,
) -> None:
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    write(repo, "web/a.js", "x\n")
    ignore = write(repo / "web", ".gitignore", "a.js\n")
    cache_name = prettier_cache_name(ls, repo, prettier)
    ignore.chmod(0)

    name = cache_name((), ls.Sample("web/a.js", "x\n"))

    ignore.chmod(0o600)
    assert name is None


def test_failed_version_probe_disables_prettier_cache(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    prettier = prettier_fixture(repo, tmp_path)
    env = {"LINT_STRICT_PRETTIER": str(prettier), "FAKE_PRETTIER_VERSION": ""}
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(prettier))

    lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(prettier)) == 2 * spawned
    assert not list((cache_path(log_dir) / "prettier").glob("*.json"))


def test_failed_version_probe_disables_jscpd_base_cache(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    write(repo, "src/a.py", clone_source("first"))
    commit_all(repo)
    write(repo, "src/b.py", clone_source("second"))
    clone = clone_entry("src/a.py", "src/b.py")
    fake, env = jscpd_env(repo, tmp_path, current=[clone], base=[])
    versioned_jscpd(fake)
    env["FAKE_JSCPD_VERSION"] = ""
    lint(repo, log_dir, "--json", extra_env=env)
    spawned = len(records(fake))

    run = lint(repo, log_dir, "--json", extra_env=env)

    assert len(records(fake)) == 2 * spawned
    assert dup_violations(run) != set()


def test_executable_identity_is_empty_when_probe_fails(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    failing = tmp_path / "failing"
    failing.write_text("#!/bin/sh\necho 1.0\nexit 1\n", encoding="utf-8")
    failing.chmod(0o755)
    silent = tmp_path / "silent"
    silent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    silent.chmod(0o755)

    assert ls.executable_identity(str(failing), tmp_path) == ""
    assert ls.executable_identity(str(silent), tmp_path) == ""
    assert ls.executable_identity(str(tmp_path / "absent"), tmp_path) == ""


def test_base_cache_name_is_none_without_identity(
    ls: ModuleType,
    tmp_path: Path,
) -> None:
    silent = tmp_path / "silent"
    silent.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    silent.chmod(0o755)

    name = ls.base_cache_name(ls.Repo(tmp_path), str(silent), "f" * 40, ["a"])

    assert name is None


def test_quick_requires_fix(repo: Path, log_dir: Path) -> None:
    write(repo, "a.py", "x = 1\n")

    alone = lint(repo, log_dir, "--quick")
    json_only = lint(repo, log_dir, "--quick", "--json")

    assert alone.code == json_only.code == EXIT_USAGE
    assert "--quick" in alone.err


def test_quick_overlay_has_no_type_checked_configs(ls: ModuleType) -> None:
    plan = ls.OverlayPlan(
        package=Path("/pkg"),
        config=None,
        recommended=True,
        strict=True,
        type_aware=False,
    )

    source = ls.overlay_source(plan)

    assert "TypeChecked" not in source
    assert "projectService" not in source
    assert "tseslint.configs.strict," in source
    assert "tseslint.configs.stylistic," in source
    assert "explicit-function-return-type" in source
    assert '"max-depth": ["error", 3]' in source


def test_default_overlay_stays_type_aware(ls: ModuleType) -> None:
    plan = ls.OverlayPlan(
        package=Path("/pkg"),
        config=None,
        recommended=True,
        strict=True,
    )

    source = ls.overlay_source(plan)

    assert "strictTypeChecked" in source
    assert '"projectService": true' in source
    assert '"tsconfigRootDir": "/pkg"' in source


def test_quick_fix_still_applies_prettier_and_eslint_fixes(
    repo: Path,
    log_dir: Path,
    tmp_path: Path,
) -> None:
    package = ts_fix_package(repo)
    prettier = make_fake(tmp_path / "tools/prettier", FAKE_PRETTIER)
    env = {
        "FAKE_MESSAGES": FIX_CONST,
        "LINT_STRICT_PRETTIER": str(prettier),
    }

    run = fix(repo, log_dir, "--quick", extra_env=env)

    assert run.code in (EXIT_PASS, EXIT_FAIL), run.err
    for name in TS_FIX_FILES:
        assert (package / f"src/{name}").read_text() == "let a = 1;\n"
    assert records(prettier)
    calls = records(package / "node_modules/.bin/eslint")
    assert calls
    for call in calls:
        assert "TypeChecked" not in call["overlay"]
        assert "projectService" not in call["overlay"]
        assert "tseslint.configs.strict," in call["overlay"]


PYPROJECT_FLOOR = '[project]\nname = "x"\nrequires-python = "{}"\n'
REACT_PACKAGE = '{{"name": "app", "dependencies": {{"react": "{}"}}}}\n'
TSCONFIG_ES2022 = '{"compilerOptions": {"lib": ["ES2022", "DOM"]}}\n'


def python_floor_run(
    repo: Path,
    log_dir: Path,
    requires: str | None,
    path: str,
    text: str,
) -> Run:
    if requires is not None:
        write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(requires))
    write(repo, path, text)
    return lint(repo, log_dir, "--json")


def react_floor_run(
    repo: Path,
    log_dir: Path,
    react: str,
    path: str,
    text: str,
) -> Run:
    write(repo, "package.json", REACT_PACKAGE.format(react))
    write(repo, path, text)
    return lint(repo, log_dir, "--json")


def test_ver002_get_event_loop_in_async_def_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = (
        "import asyncio\n\n\nasync def run():\n    asyncio.get_event_loop()\n"
    )

    run = python_floor_run(repo, log_dir, None, "app/loop.py", text)

    assert ("app/loop.py", 5, "VER002") in violations(run)


def test_ver003_asyncio_iscoroutinefunction_at_py314_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = "import asyncio\n\nVALUE = asyncio.iscoroutinefunction(print)\n"

    run = python_floor_run(repo, log_dir, ">=3.14", "app/check.py", text)

    assert ("app/check.py", 3, "VER003") in violations(run)


def test_ver007_re_match_at_py315_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = "import re\n\nVALUE = re.match('a', 'abc')\n"

    run = python_floor_run(repo, log_dir, ">=3.15", "app/pattern.py", text)

    assert ("app/pattern.py", 3, "VER007") in violations(run)


def test_ver201_forward_ref_at_react19_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = (
        "import { forwardRef } from 'react';\n"
        "export const A = forwardRef(f);\n"
    )

    run = react_floor_run(repo, log_dir, "^19.1.1", "src/A.tsx", text)

    assert ("src/A.tsx", 2, "VER201") in violations(run)


def test_ver202_context_provider_at_react19_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = "export const A = () => <ThemeContext.Provider value={1} />;\n"

    run = react_floor_run(repo, log_dir, "^19.0.0", "src/A.tsx", text)

    assert ("src/A.tsx", 1, "VER202") in violations(run)


def test_ver203_use_form_state_at_react19_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = "import { useFormState } from 'react-dom';\n"

    run = react_floor_run(repo, log_dir, "^19.0.0", "src/A.tsx", text)

    assert ("src/A.tsx", 1, "VER203") in violations(run)


def test_ver204_prop_types_at_react19_is_reported(
    repo: Path, log_dir: Path
) -> None:
    text = "export const A = () => null;\nA.propTypes = {};\n"

    run = react_floor_run(repo, log_dir, "^19.0.0", "src/A.tsx", text)

    assert ("src/A.tsx", 2, "VER204") in violations(run)


def test_prefer_object_has_own_in_overlay_at_es2022(
    repo: Path, log_dir: Path
) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", TSCONFIG_ES2022)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" in overlay


def test_explicit_override_enabled_at_py312(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    mypy = make_fake(
        tmp_path / "tools/mypy", "record({'argv': sys.argv[1:]})\n"
    )
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.12"))
    append(repo, "base.py", DOCUMENTED)

    lint(repo, log_dir, "--json", extra_env={"LINT_STRICT_MYPY": str(mypy)})

    argv = records(mypy)[0]["argv"]
    assert "explicit-override" in argv
    assert argv[argv.index("explicit-override") - 1] == "--enable-error-code"


ISCOROUTINE_TEXT = (
    "import asyncio\n\nVALUE = asyncio.iscoroutinefunction(print)\n"
)


@pytest.mark.parametrize("requires", ["==3.13.*", ">=3.13", "garbage", None])
def test_ver003_below_py314_or_unknown_floor_is_silent(
    repo: Path, log_dir: Path, requires: str | None
) -> None:
    run = python_floor_run(
        repo, log_dir, requires, "app/check.py", ISCOROUTINE_TEXT
    )

    assert "VER003" not in rules_at(run, "app/check.py")


def test_ver003_unchanged_line_is_silent(repo: Path, log_dir: Path) -> None:
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.14"))
    write(repo, "app/check.py", ISCOROUTINE_TEXT)
    commit_all(repo)
    append(repo, "app/check.py", UNRELATED_LINE)

    run = lint(repo, log_dir, "--json")

    assert "VER003" not in rules_at(run, "app/check.py")


def test_unparsable_requires_python_ignores_python_version_file(
    repo: Path, log_dir: Path
) -> None:
    write(repo, ".python-version", "3.14\n")

    run = python_floor_run(
        repo, log_dir, "garbage", "app/check.py", ISCOROUTINE_TEXT
    )

    assert "VER003" not in rules_at(run, "app/check.py")


def test_python_version_file_gives_floor(repo: Path, log_dir: Path) -> None:
    write(repo, ".python-version", "3.14\n")

    run = python_floor_run(
        repo, log_dir, None, "app/check.py", ISCOROUTINE_TEXT
    )

    assert "VER003" in rules_at(run, "app/check.py")


def test_dockerfile_alone_gives_no_floor(repo: Path, log_dir: Path) -> None:
    write(repo, "Dockerfile", "FROM python:3.14\n")

    run = python_floor_run(
        repo, log_dir, None, "app/check.py", ISCOROUTINE_TEXT
    )

    assert "VER003" not in rules_at(run, "app/check.py")


def test_staged_requires_python_is_honoured(repo: Path, log_dir: Path) -> None:
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.14"))
    write(repo, "app/check.py", ISCOROUTINE_TEXT)
    git(repo, "add", "-A")
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.10"))

    run = lint(repo, log_dir, "--staged", "--json")

    assert ("app/check.py", 3, "VER003") in violations(run)


def test_staged_requires_python_below_floor_is_honoured(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.10"))
    write(repo, "app/check.py", ISCOROUTINE_TEXT)
    git(repo, "add", "-A")
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.14"))

    run = lint(repo, log_dir, "--staged", "--json")

    assert "VER003" not in rules_at(run, "app/check.py")


def test_react18_forward_ref_is_silent(repo: Path, log_dir: Path) -> None:
    text = "export const A = forwardRef(f);\n"

    run = react_floor_run(repo, log_dir, "^18.3.1", "src/A.tsx", text)

    assert "VER201" not in rules_at(run, "src/A.tsx")


def test_custom_provider_not_ending_in_context_is_not_ver202(
    repo: Path, log_dir: Path
) -> None:
    text = "export const A = () => <Store.Provider value={1} />;\n"

    run = react_floor_run(repo, log_dir, "^19.0.0", "src/A.tsx", text)

    assert "VER202" not in rules_at(run, "src/A.tsx")


def test_object_has_own_absent_when_tsconfig_min_is_below_es2022(
    repo: Path, log_dir: Path
) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", '{"compilerOptions": {"lib": ["ES2017"]}}')
    write(package, "tsconfig.app.json", TSCONFIG_ES2022)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" not in overlay


def test_object_has_own_absent_without_tsconfig(
    repo: Path, log_dir: Path
) -> None:
    package = make_package(repo)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" not in overlay


def test_explicit_override_off_when_any_target_below_py312(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    mypy = make_fake(
        tmp_path / "tools/mypy", "record({'argv': sys.argv[1:]})\n"
    )
    write(repo, "pyproject.toml", PYPROJECT_FLOOR.format(">=3.12"))
    write(repo, "old/pyproject.toml", PYPROJECT_FLOOR.format(">=3.11"))
    write(repo, "old/mod.py", "X = 1\n")
    append(repo, "base.py", DOCUMENTED)

    lint(repo, log_dir, "--json", extra_env={"LINT_STRICT_MYPY": str(mypy)})

    assert "explicit-override" not in records(mypy)[0]["argv"]


def test_explicit_override_off_without_floor(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    mypy = make_fake(
        tmp_path / "tools/mypy", "record({'argv': sys.argv[1:]})\n"
    )
    append(repo, "base.py", DOCUMENTED)

    lint(repo, log_dir, "--json", extra_env={"LINT_STRICT_MYPY": str(mypy)})

    assert "explicit-override" not in records(mypy)[0]["argv"]


def test_node_modules_tsconfig_is_ignored(repo: Path, log_dir: Path) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", TSCONFIG_ES2022)
    write(
        package,
        "node_modules/dep/tsconfig.json",
        '{"compilerOptions": {"lib": ["ES5"]}}',
    )
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" in overlay


def test_staged_tsconfig_is_honoured_for_overlay(
    repo: Path, log_dir: Path
) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", TSCONFIG_ES2022)
    write(package, "src/a.ts", "const a = 1;\n")
    git(repo, "add", "-A")
    write(package, "tsconfig.json", '{"compilerOptions": {"lib": ["ES2017"]}}')

    lint(repo, log_dir, "--staged", "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" in overlay


def test_react_hook_form_use_form_state_is_not_ver203(
    repo: Path, log_dir: Path
) -> None:
    text = (
        "import { useFormState } from 'react-hook-form';\n"
        "const s = useFormState({ control });\n"
    )

    run = react_floor_run(repo, log_dir, "^19.1.0", "src/A.tsx", text)

    assert "VER203" not in rules_at(run, "src/A.tsx")


def test_tsconfig_without_target_disables_floor(
    repo: Path, log_dir: Path
) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", '{"compilerOptions": {"strict": true}}')
    write(package, "tsconfig.app.json", TSCONFIG_ES2022)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" not in overlay


def test_solution_style_tsconfig_is_skipped(repo: Path, log_dir: Path) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", '{"files": [], "references": []}')
    write(package, "tsconfig.app.json", TSCONFIG_ES2022)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" in overlay


def test_gitignored_tsconfig_is_ignored(repo: Path, log_dir: Path) -> None:
    package = make_package(repo)
    append(repo, ".gitignore", "dist/\n")
    write(package, "tsconfig.json", TSCONFIG_ES2022)
    write(
        package,
        "dist/tsconfig.json",
        '{"compilerOptions": {"lib": ["ES2017"]}}',
    )
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" in overlay


def test_files_empty_with_include_is_not_solution_style(
    repo: Path, log_dir: Path
) -> None:
    package = make_package(repo)
    write(package, "tsconfig.json", '{"files": [], "include": ["src"]}')
    write(package, "tsconfig.app.json", TSCONFIG_ES2022)
    write(package, "src/a.ts", "const a = 1;\n")

    lint(repo, log_dir, "--json")

    overlay = records(package / "node_modules/.bin/eslint")[0]["overlay"]
    assert "prefer-object-has-own" not in overlay


FAKE_MYPY_SUBPROJECT = """
targets = [a for a in sys.argv[1:] if a.endswith(".py")]
record({"argv": sys.argv[1:], "cwd": os.getcwd()})
for target in targets:
    print(f"{target}:1:1: error: boom  [misc]")
"""
SUBPROJECT_PYPROJECT = "[project]\nname = 'sub'\nversion = '0'\n"
SUBPROJECT_MODULE = '"""Module."""\n\nVALUE = 1\n'
EXPLICIT_PACKAGE_BASES = "--explicit-package-bases"


def fake_mypy_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    fake = make_fake(tmp_path / "tools/mypy", FAKE_MYPY_SUBPROJECT)
    return fake, {"LINT_STRICT_MYPY": str(fake)}


def mypy_calls(fake: Path) -> list[tuple[str, list[str]]]:
    return [
        (str(Path(call["cwd"]).resolve()), call["argv"])
        for call in records(fake)
        if "--strict" in call["argv"]
    ]


def test_subproject_target_is_checked_from_its_root(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    write(repo, "tools/sub/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/pkg/b.py", SUBPROJECT_MODULE)
    fake, env = fake_mypy_env(tmp_path)

    lint(repo, log_dir, "--json", extra_env=env)

    (cwd, argv), *_ = mypy_calls(fake)
    assert cwd == str((repo / "tools/sub").resolve())
    assert EXPLICIT_PACKAGE_BASES in argv


def test_repo_root_targets_keep_cwd_and_options(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    append(repo, "base.py", DOCUMENTED)
    fake, env = fake_mypy_env(tmp_path)

    lint(repo, log_dir, "--json", extra_env=env)

    (cwd, argv), *rest = mypy_calls(fake)
    assert not rest
    assert cwd == str(repo.resolve())
    assert EXPLICIT_PACKAGE_BASES not in argv
    assert argv[-1] == str(repo / "base.py")


def test_mixed_targets_run_mypy_once_per_group(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    write(repo, "top.py", SUBPROJECT_MODULE)
    write(repo, "tools/sub/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/pkg/b.py", SUBPROJECT_MODULE)
    fake, env = fake_mypy_env(tmp_path)

    run = lint(repo, log_dir, "--json", extra_env=env)

    cwds = sorted(cwd for cwd, _ in mypy_calls(fake))
    assert cwds == sorted(
        [str(repo.resolve()), str((repo / "tools/sub").resolve())]
    )
    flagged = {
        path for path, _, rule in violations(run) if rule == "mypy:misc"
    }
    assert flagged == {"top.py", "tools/sub/pkg/b.py"}


def test_nearest_pyproject_defines_the_subproject_root(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    write(repo, "tools/sub/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/inner/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/inner/pkg/b.py", SUBPROJECT_MODULE)
    fake, env = fake_mypy_env(tmp_path)

    lint(repo, log_dir, "--json", extra_env=env)

    (cwd, _), *_ = mypy_calls(fake)
    assert cwd == str((repo / "tools/sub/inner").resolve())


def test_root_pyproject_alone_keeps_the_repo_root_group(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    write(repo, "pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "pkg/b.py", SUBPROJECT_MODULE)
    fake, env = fake_mypy_env(tmp_path)

    lint(repo, log_dir, "--json", extra_env=env)

    (cwd, argv), *rest = mypy_calls(fake)
    assert not rest
    assert cwd == str(repo.resolve())
    assert EXPLICIT_PACKAGE_BASES not in argv


def uvx_subproject_run(
    repo: Path, log_dir: Path, tmp_path: Path, *, with_venv: bool
) -> list[str]:
    fake = make_fake(tmp_path / "bin/uvx", FAKE_UVX)
    write(repo, "tools/sub/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/pkg/b.py", SUBPROJECT_MODULE)
    if with_venv:
        make_fake(repo / "tools/sub/.venv/bin/python", "raise SystemExit(1)\n")
    env = {
        "LINT_STRICT_MYPY": "",
        "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
    }

    lint(repo, log_dir, "--json", extra_env=env)

    return next(
        call["argv"] for call in records(fake) if "--strict" in call["argv"]
    )


def test_subproject_venv_python_is_the_checked_interpreter(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    argv = uvx_subproject_run(repo, log_dir, tmp_path, with_venv=True)

    python = argv[argv.index("--python-executable") + 1]
    assert python == str(repo / "tools/sub/.venv/bin/python")


def test_subproject_without_venv_falls_back_to_system_python(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    argv = uvx_subproject_run(repo, log_dir, tmp_path, with_venv=False)

    python = argv[argv.index("--python-executable") + 1]
    assert ".venv" not in python
    assert EXPLICIT_PACKAGE_BASES in argv


def test_mypy_shadows_cover_targets_of_other_groups(
    repo: Path, log_dir: Path, tmp_path: Path
) -> None:
    write(repo, "top.py", SUBPROJECT_MODULE)
    write(repo, "tools/sub/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/pkg/b.py", SUBPROJECT_MODULE)
    git(repo, "add", "-A")
    write(repo, "top.py", SUBPROJECT_MODULE + "OTHER = 2\n")
    fake, env = fake_mypy_env(tmp_path)

    lint(repo, log_dir, "--staged", "--json", extra_env=env)

    sub_root = str((repo / "tools/sub").resolve())
    (argv,) = (a for cwd, a in mypy_calls(fake) if cwd == sub_root)
    shadowed = {
        argv[i + 1] for i, item in enumerate(argv) if item == "--shadow-file"
    }
    assert str(repo / "top.py") in shadowed


def test_relative_lint_strict_mypy_runs_from_subproject_root(
    repo: Path, log_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo, "tools/sub/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "tools/sub/pkg/b.py", SUBPROJECT_MODULE)
    fake, _ = fake_mypy_env(tmp_path)
    monkeypatch.chdir(fake.parent)

    run = lint(
        repo, log_dir, "--json", extra_env={"LINT_STRICT_MYPY": fake.name}
    )

    assert mypy_calls(fake)
    assert ("tools/sub/pkg/b.py", "mypy") not in not_checked_reasons(run)
    assert ("tools/sub/pkg/b.py", 1, "mypy:misc") in violations(run)


WORKSPACE_ROOT_PYPROJECT = (
    "[tool.uv.workspace]\nmembers = ['libs/*', 'services/*']\n"
)
APP_PYPROJECT = (
    "[project]\nname = 'app'\nversion = '0'\n"
    "[tool.uv.sources]\ncommon = { workspace = true }\n"
)
LIB_PYPROJECT = "[project]\nname = '{name}'\nversion = '0'\n"
COMMON_VALUES = '"""Values."""\n\nVALUE: int = 1\n'
APP_MODULE = (
    '"""App."""\n\nfrom common.values import VALUE\n\nx: str = VALUE\n'
)
APP_MODULE_PATH = "services/app/app/mod.py"
ASSIGNMENT_LINE = 5
IMPORT_ERRORS = {"mypy:import-not-found", "mypy:import-untyped"}
TEST_HELPER_IMPORT = '"""Test."""\n\nfrom helper import VALUE\n\nVALUE\n'


def make_workspace(repo: Path) -> None:
    write(repo, "pyproject.toml", WORKSPACE_ROOT_PYPROJECT)
    write(
        repo, "libs/common/pyproject.toml", LIB_PYPROJECT.format(name="common")
    )
    write(repo, "libs/common/common/values.py", COMMON_VALUES)
    write(repo, "services/app/pyproject.toml", APP_PYPROJECT)


@NEEDS_UVX
def test_workspace_source_import_is_type_checked(
    repo: Path, log_dir: Path
) -> None:
    make_workspace(repo)
    write(repo, APP_MODULE_PATH, APP_MODULE)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    found = {item for item in mypy_rules(run) if item[0] == APP_MODULE_PATH}
    assert not {item for item in found if item[2] in IMPORT_ERRORS}, run.out
    assert (APP_MODULE_PATH, ASSIGNMENT_LINE, "mypy:assignment") in found


@NEEDS_UVX
def test_sibling_test_helper_import_resolves(
    repo: Path, log_dir: Path
) -> None:
    make_workspace(repo)
    write(repo, "services/app/tests/helper.py", '"""Helper."""\n\nVALUE = 1\n')
    write(repo, "services/app/tests/test_x.py", TEST_HELPER_IMPORT)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert not {
        item for item in mypy_rules(run) if item[2] in IMPORT_ERRORS
    }, run.out


OTHER_PYPROJECT = "[project]\nname = 'other'\nversion = '0'\n"
PYTEST_PYPROJECT = (
    "[project]\nname = 'app'\nversion = '0'\n"
    "[tool.pytest.ini_options]\npythonpath = ['.', 'extra']\n"
)
MYPYPATH_BEFORE = "/preset/one"


def search_path(
    ls: ModuleType, repo: Path, root: str, *files: str
) -> tuple[Path, ...]:
    targets = [
        ls.LintTarget(
            name, ls.Language.PYTHON, frozenset({1}), ls.TextSource.DISK
        )
        for name in files
    ]
    found: tuple[Path, ...] = ls.mypy_search_path(
        ls.Repo(repo), repo / root, targets
    )
    return found


def test_search_path_skips_undeclared_workspace_members(
    ls: ModuleType, repo: Path
) -> None:
    make_workspace(repo)
    write(repo, "services/other/pyproject.toml", OTHER_PYPROJECT)
    write(repo, "services/other/src/mod.py", "")

    found = search_path(ls, repo, "services/app")

    assert found == (repo / "libs/common",)


def test_search_path_uses_src_layout_of_member(
    ls: ModuleType, repo: Path
) -> None:
    make_workspace(repo)
    write(repo, "libs/lib2/pyproject.toml", LIB_PYPROJECT.format(name="Lib_2"))
    write(repo, "libs/lib2/src/lib2/mod.py", "")
    write(
        repo,
        "services/app/pyproject.toml",
        APP_PYPROJECT + "lib-2 = { workspace = true }\n",
    )

    found = search_path(ls, repo, "services/app")

    assert found == (repo / "libs/common", repo / "libs/lib2/src")


def test_search_path_includes_pytest_pythonpath_except_root(
    ls: ModuleType, repo: Path
) -> None:
    write(repo, "services/app/pyproject.toml", PYTEST_PYPROJECT)

    found = search_path(ls, repo, "services/app")

    assert found == (repo / "services/app/extra",)


def test_search_path_without_pyproject_is_only_target_dirs(
    ls: ModuleType, repo: Path
) -> None:
    write(repo, "pkg/__init__.py", "")
    write(repo, "tests/test_a.py", "")

    found = search_path(
        ls, repo, ".", "tests/test_a.py", "pkg/mod.py", "ns/mod.py", "a.py"
    )

    assert found == (repo / "tests",)


def test_invalid_root_pyproject_does_not_crash_mypy(
    ls: ModuleType, repo: Path
) -> None:
    write(repo, "pyproject.toml", "[tool.uv.workspace\n")
    write(repo, "services/app/pyproject.toml", "= broken")

    found = search_path(ls, repo, "services/app")

    assert found == ()


def test_exclude_glob_drops_member(ls: ModuleType, repo: Path) -> None:
    make_workspace(repo)
    write(
        repo,
        "pyproject.toml",
        WORKSPACE_ROOT_PYPROJECT + "exclude = ['libs/common']\n",
    )

    found = search_path(ls, repo, "services/app")

    assert found == ()


FASTAPI_ROUTE = (
    '"""Api."""\n\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n\n'
    '@app.get("/", response_model=int)\n'
    'def route() -> int:\n    """Return one."""\n    return 1\n'
)
FASTAPI_PYPROJECT = (
    '[project]\nname = "api"\nversion = "0"\nrequires-python = ">=3.13"\n'
)
UNTYPED_LIBRARY = "def deco(function):\n    return function\n\nVALUE = 1\n"
UNTYPED_IMPORT = '"""Use."""\n\nimport untypedlib\n\nuntypedlib.VALUE\n'
UNTYPED_DECORATED = (
    '"""Use."""\n\nimport untypedlib\n\n\n@untypedlib.deco\n'
    'def decorated() -> int:\n    """Return one."""\n    return 1\n'
)
MISSING_IMPORT = (
    '"""Use."""\n\nimport missing_zzz_module\n\nmissing_zzz_module\n'
)


def make_venv(repo: Path) -> Path:
    write(repo, ".gitignore", ".venv/\n")
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(repo / ".venv")],
        check=True,
        timeout=60,
    )
    return next((repo / ".venv/lib").glob("python*/site-packages"))


def make_venv_with_untyped_library(repo: Path) -> None:
    site = make_venv(repo)
    (site / "untypedlib").mkdir()
    (site / "untypedlib/__init__.py").write_text(UNTYPED_LIBRARY)


def test_fastapi_explicit_response_model_is_not_reported(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "pyproject.toml", FASTAPI_PYPROJECT)
    write(repo, "api.py", FASTAPI_ROUTE)

    run = lint(repo, log_dir, "--json")

    assert "FAST001" not in rules_at(run, "api.py"), run.out


DUPLICATE_HELPER = '"""Helper."""\n\nVALUE: int = "x"\n'
DUPLICATE_SIBLING_TEST = '"""Test."""\n\nfrom helper import VALUE\n\nVALUE\n'
DUPLICATE_PACKAGE_TEST = (
    '"""Test."""\n\nfrom tests.x.helper import VALUE\n\nVALUE\n'
)
DUPLICATE_HELPER_PATH = "services/app/tests/x/helper.py"


@NEEDS_UVX
def test_mypy_runs_when_project_dir_has_a_mypy_directory(
    repo: Path, log_dir: Path
) -> None:
    make_venv(repo)
    write(repo, "services/svc/pyproject.toml", SUBPROJECT_PYPROJECT)
    write(repo, "services/svc/mypy/override.ini", "[mypy]\n")
    write(repo, "services/svc/pkg/b.py", '"""B."""\n\nVALUE: int = "x"\n')

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert ("services/svc/pkg/b.py", "mypy") not in not_checked_reasons(run)
    assert ("services/svc/pkg/b.py", 3, "mypy:assignment") in mypy_rules(run)


@NEEDS_UVX
def test_duplicate_module_name_retries_without_sibling_roots(
    repo: Path, log_dir: Path
) -> None:
    make_workspace(repo)
    write(repo, DUPLICATE_HELPER_PATH, DUPLICATE_HELPER)
    write(repo, "services/app/tests/x/test_a.py", DUPLICATE_SIBLING_TEST)
    write(repo, "services/app/tests/test_b.py", DUPLICATE_PACKAGE_TEST)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert (DUPLICATE_HELPER_PATH, "mypy") not in not_checked_reasons(run)
    assert (DUPLICATE_HELPER_PATH, 3, "mypy:assignment") in mypy_rules(run)


@NEEDS_UVX
def test_untyped_third_party_import_is_not_reported(
    repo: Path, log_dir: Path
) -> None:
    make_venv_with_untyped_library(repo)
    write(repo, "use.py", UNTYPED_IMPORT)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert "mypy:import-untyped" not in rules_at(run, "use.py"), run.out


@NEEDS_UVX
def test_missing_module_import_is_still_reported(
    repo: Path, log_dir: Path
) -> None:
    write(repo, "use.py", MISSING_IMPORT)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert "mypy:import-not-found" in rules_at(run, "use.py"), run.out


@NEEDS_UVX
def test_decorator_from_untyped_library_is_not_reported(
    repo: Path, log_dir: Path
) -> None:
    make_venv_with_untyped_library(repo)
    write(repo, "use.py", UNTYPED_DECORATED)

    run = lint(repo, log_dir, "--json", extra_env=REAL_MYPY)

    assert "mypy:untyped-decorator" not in rules_at(run, "use.py"), run.out
    assert not mypy_rules(run), run.out


def test_existing_mypypath_env_is_kept(
    ls: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MYPYPATH", MYPYPATH_BEFORE)

    env = ls.mypy_environment((Path("/ours/a"), Path("/ours/b")))

    assert env is not None
    assert env["MYPYPATH"] == os.pathsep.join(
        ["/ours/a", "/ours/b", MYPYPATH_BEFORE]
    )


def test_c_checks_skip_annex_k_buffer_handling(ls: ModuleType) -> None:
    checks = ls.C_CHECKS.split(",")

    assert (
        "-clang-analyzer-security.insecureAPI.DeprecatedOrUnsafeBufferHandling"
        in checks
    )
