from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

Proc = subprocess.CompletedProcess[str]
Case = tuple[str, str, str, str, str]

HOOK = (
    Path(sys.argv[1])
    if __name__ == "__main__" and len(sys.argv) > 1
    else Path(__file__).resolve().parent / "comment-guard.py"
)
DOC_LIMIT = 72
GARBAGE_INPUTS = (
    "",
    "null",
    "[]",
    "{",
    '{"tool_name": 42}',
    '{"tool_name": "Edit"}',
    (
        '{"tool_name": "Edit", "tool_input": {"file_path": "a.py", '
        '"new_string": 7}}'
    ),
)
HATCH = {"CLAUDE_COMMENT_GUARD": "off"}
WORK = tempfile.TemporaryDirectory()

DENY: list[Case] = [
    ("Edit", "a.py", "# load the device groups\nx = 1", "", "python comment"),
    ("Edit", "a.cpp", "// still guarded\nint x;", "", "c++ stays in scope"),
    ("Edit", "a.py", "x = 1  # default timeout", "", "python trailing"),
    (
        "Edit",
        "App.tsx",
        "// ── Load device groups ──────────\nconst a = 1;",
        "",
        "tsx banner",
    ),
    ("Edit", "a.ts", "const a = 1; // narrate", "", "ts trailing comment"),
    (
        "Edit",
        "a.ts",
        "/* multi\n * line\n */\nconst a = 1;",
        "",
        "ts block comment",
    ),
    (
        "Write",
        "a.go",
        "package main\n// why\nfunc main() {}",
        "",
        "Write is checked too",
    ),
    ("Edit", "a.sql", "-- pick the rows\nSELECT 1;", "", "sql comment"),
    ("Edit", "a.py", "# step one\n# step two\nx = 1", "", "several comments"),
    (
        "Edit",
        "a.py",
        "x = 1  # new note",
        "y = 2  # old note",
        "a different trailing comment",
    ),
]
ALLOW: list[Case] = [
    ("Edit", "a.py", "x = 1", "", "plain code"),
    (
        "Edit",
        "a.py",
        'def f():\n    """Do it."""',
        "",
        "docstring is not a comment",
    ),
    ("Edit", "a.py", "url = 'https://x/y'", "", "url inside a string"),
    (
        "Edit",
        "a.ts",
        'const u = "https://example.com//path";',
        "",
        "double slash inside a string",
    ),
    ("Edit", "a.py", "x = 1  # noqa: E501", "", "noqa directive"),
    (
        "Edit",
        "a.py",
        "# type: ignore[arg-type]\nx = 1",
        "",
        "type ignore directive",
    ),
    (
        "Edit",
        "a.ts",
        "// eslint-disable-next-line no-console\nconsole.log(1);",
        "",
        "eslint directive",
    ),
    (
        "Edit",
        "a.ts",
        "// @ts-expect-error legacy shape\nconst a = f();",
        "",
        "ts-expect-error directive",
    ),
    ("Edit", "a.sh", "#!/usr/bin/env bash\nset -e", "", "shebang"),
    (
        "Edit",
        "a.c",
        "#include <stdio.h>\n#pragma once",
        "",
        "preprocessor is not a comment",
    ),
    (
        "Edit",
        "a.c",
        "// SPI needs 2 dummy bytes before the reply\nint x;",
        "",
        "C sources are out of scope",
    ),
    (
        "Edit",
        "regs.h",
        "#ifndef REGS_H\n#define REGS_H\n#endif /* REGS_H */",
        "",
        "include guard in a header",
    ),
    (
        "Edit",
        "regs.h",
        (
            "/* 0x2A: status register, bit 3 latches until read */\n"
            "#define STATUS 0x2A"
        ),
        "",
        "register documentation in a header",
    ),
    (
        "Edit",
        "a.py",
        "# kept from before\nx = 2",
        "# kept from before\nx = 1",
        "comment already in the file",
    ),
    ("Edit", "a.md", "# Heading\ntext", "", "markdown is not code"),
    ("Edit", "a.json", '{"a": 1}', "", "json untouched"),
    ("Edit", "a.txt", "# not code", "", "unknown extension untouched"),
    ("Write", "a.py", "", "", "empty content"),
]
BASH_DENY = [
    (
        "cat > src/api.ts <<'EOF'\n// narrate the call\nconst a = 1;\nEOF",
        "heredoc into a code file",
    ),
    (
        "cd /repo && cat >> src/a.py << 'EOF'\n# appended note\nx = 1\nEOF",
        "appending heredoc",
    ),
    ("tee src/a.py <<EOF\n# note\nx = 1\nEOF", "tee heredoc"),
    (
        (
            "cat > a.ts <<'EOF'\nconst a = 1;\nEOF\n"
            "cat > b.py <<'PY'\n# second heredoc\nx = 1\nPY"
        ),
        "second heredoc in one command",
    ),
]
BASH_ALLOW = [
    ("cat > src/api.ts <<'EOF'\nconst a = 1;\nEOF", "clean heredoc"),
    (
        "python3 - <<'PY'\n# a script, not a written file\nprint(1)\nPY",
        "heredoc with no file target",
    ),
    (
        (
            "cat > firmware/regs.h <<'EOF'\n"
            "/* 0x2A status */\n#define S 0x2A\nEOF"
        ),
        "C header stays exempt",
    ),
    ("cat > notes.md <<'EOF'\n# Heading\nEOF", "markdown is not code"),
    ("~/.claude/bin/verify -- 'pytest -q'", "an ordinary command"),
    ("sed -i 's|//old|/new|' src/a.ts", "sed is not parsed"),
    ("grep -n '# TODO' src/a.py", "reading a comment is not writing one"),
]


def launch(payload: str, env: dict[str, str] | None = None) -> Proc:
    """Run the hook with the raw stdin text."""
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


def run(
    tool: str,
    path: str,
    new: str,
    old: str = "",
    env: dict[str, str] | None = None,
) -> Proc:
    """Run the hook on an Edit or Write payload."""
    tool_input = {"file_path": path}
    if tool == "Write":
        tool_input["content"] = new
    else:
        tool_input["new_string"] = new
        tool_input["old_string"] = old
    payload = {"tool_name": tool, "tool_input": tool_input}
    return launch(json.dumps(payload), env)


def run_bash(command: str, env: dict[str, str] | None = None) -> Proc:
    """Run the hook on a Bash payload."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return launch(json.dumps(payload), env)


def run_edit(
    path: Path,
    old: str,
    new: str,
    replace_all: bool = False,
    env: dict[str, str] | None = None,
) -> Proc:
    """Run the hook on an Edit payload for a file that exists."""
    tool_input: dict[str, object] = {
        "file_path": str(path),
        "old_string": old,
        "new_string": new,
    }
    if replace_all:
        tool_input["replace_all"] = True
    payload = {"tool_name": "Edit", "tool_input": tool_input}
    return launch(json.dumps(payload), env)


def denies(proc: Proc) -> bool:
    """Tell whether the hook output is a comment-guard deny."""
    if '"deny"' not in proc.stdout:
        return False
    block = json.loads(proc.stdout)["hookSpecificOutput"]
    return (
        block.get("hookEventName") == "PreToolUse"
        and block.get("permissionDecision") == "deny"
        and "comment-guard" in block.get("permissionDecisionReason", "")
    )


def is_silent(proc: Proc) -> bool:
    """Tell whether the hook allowed the call without any output."""
    return (
        proc.returncode == 0
        and proc.stdout.strip() == ""
        and proc.stderr == ""
    )


def reason_of(proc: Proc) -> str:
    """Return the deny reason of a hook result."""
    return str(
        json.loads(proc.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ],
    )


def path_in_work(name: str, text: str | None = None) -> Path:
    """Return a path in the scratch directory, creating the file if given."""
    path = Path(WORK.name) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return path


def docstring_of(length: int) -> str:
    """Return a one-line docstring literal of the given text length."""
    return '"""' + "x" * (length - 1) + '."""'


def edit_adding_docstring(
    doc_source: str,
    name: str = "f.py",
    header: str = "def f():\n    ",
) -> Proc:
    """Run an Edit that inserts a docstring into a one-function file."""
    path = path_in_work(name, header + "pass\n")
    return run_edit(path, header + "pass", header + doc_source + "\n    pass")


def test_denies_module_docstring() -> None:
    proc = run(
        "Write",
        str(path_in_work("new_module.py")),
        '"""Does a thing."""\nx = 1\n',
    )
    assert denies(proc), proc.stdout
    assert "module docstring" in reason_of(proc)


def repo_requiring_module_docstrings(name: str) -> Path:
    """Return a file path in a git repo whose ruff config selects D."""
    root = path_in_work(name)
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "ruff.toml").write_text(
        '[lint]\nselect = ["D", "I"]\n', encoding="utf-8"
    )
    return root / "pkg" / "mod.py"


def test_module_docstring_allowed_when_repo_ruff_requires_it() -> None:
    target = repo_requiring_module_docstrings("ruffrepo")
    proc = run("Write", str(target), '"""Does a thing."""\nx = 1\n')
    assert is_silent(proc), proc.stdout


def test_module_docstring_allowed_in_heredoc_when_repo_requires_it() -> None:
    target = repo_requiring_module_docstrings("ruffheredoc")
    proc = run_bash(f"cat > {target} <<'EOF'\n" + '"""Module."""\nx = 1\nEOF')
    assert is_silent(proc), proc.stdout


def test_module_docstring_denied_when_repo_ignores_d100() -> None:
    target = repo_requiring_module_docstrings("ruffignore")
    (target.parents[1] / "ruff.toml").write_text(
        '[lint]\nselect = ["D"]\nignore = ["D100"]\n', encoding="utf-8"
    )
    proc = run("Write", str(target), '"""Does a thing."""\nx = 1\n')
    assert denies(proc), proc.stdout
    assert "module docstring" in reason_of(proc)


def test_module_docstring_still_denied_without_repo_config() -> None:
    root = path_in_work("plainrepo")
    (root / ".git").mkdir(parents=True, exist_ok=True)
    proc = run("Write", str(root / "mod.py"), '"""Does a thing."""\nx = 1\n')
    assert denies(proc), proc.stdout
    assert "module docstring" in reason_of(proc)


def test_denies_multi_sentence_docstring() -> None:
    proc = edit_adding_docstring('"""Do one. Do two."""')
    assert denies(proc), proc.stdout
    assert "one sentence" in reason_of(proc)
    assert "`f`" in reason_of(proc)


def test_denies_multiline_docstring() -> None:
    proc = edit_adding_docstring('"""Do one.\n\n    More detail.\n    """')
    assert denies(proc), proc.stdout
    assert "one line" in reason_of(proc)


def test_denies_docstring_over_72() -> None:
    proc = edit_adding_docstring(docstring_of(DOC_LIMIT + 1))
    assert denies(proc), proc.stdout
    assert "72" in reason_of(proc)


def test_allows_docstring_at_72() -> None:
    assert is_silent(edit_adding_docstring(docstring_of(DOC_LIMIT)))


def test_allows_carried_legacy_docstring() -> None:
    legacy = (
        'def f():\n    """Do one.\n\n    Do two. Do three.\n    """\n'
        "    return 1\n"
    )
    path = path_in_work("legacy.py", legacy)
    assert is_silent(run_edit(path, "return 1", "return 2"))


def test_allows_write_with_short_docstrings() -> None:
    text = (
        'class A:\n    """Hold a value."""\n\n'
        '    def get(self):\n        """Return it."""\n'
    )
    proc = run("Write", str(path_in_work("short.py")), text)
    assert is_silent(proc)


def test_ignores_pyi_files() -> None:
    text = '"""Stub module."""\ndef f() -> int: ...\n'
    proc = run("Write", str(path_in_work("stub.pyi")), text)
    assert is_silent(proc)


def test_heredoc_module_docstring_denied() -> None:
    target = path_in_work("viaheredoc.py")
    proc = run_bash(f"cat > {target} <<'EOF'\n" + '"""Module."""\nx = 1\nEOF')
    assert denies(proc), proc.stdout
    assert "module docstring" in reason_of(proc)


def test_heredoc_short_docstrings_allowed() -> None:
    target = path_in_work("okheredoc.py")
    body = 'def f():\n    """Do it."""\nEOF'
    assert is_silent(run_bash(f"cat > {target} <<'EOF'\n" + body))


def test_abbreviations_are_not_sentence_ends() -> None:
    doc = '"""Return a value, e.g. an int or i.e. a str."""'
    assert is_silent(edit_adding_docstring(doc))


def test_question_and_exclamation_end_sentences() -> None:
    assert denies(edit_adding_docstring('"""Is it? Yes."""', name="q.py"))
    assert denies(edit_adding_docstring('"""Stop! Go."""', name="e.py"))


def test_replace_all_judges_every_added_docstring() -> None:
    path = path_in_work(
        "many.py",
        "def a():\n    pass\n\n\ndef b():\n    pass\n",
    )
    proc = run_edit(
        path,
        "    pass",
        '    """One. Two."""\n    pass',
        replace_all=True,
    )
    assert denies(proc), proc.stdout
    assert "`a`" in reason_of(proc)
    assert "`b`" in reason_of(proc)


def test_edit_without_replace_all_touches_first_occurrence_only() -> None:
    path = path_in_work(
        "first.py",
        "def a():\n    pass\n\n\ndef b():\n    pass\n",
    )
    proc = run_edit(path, "    pass", '    """One. Two."""\n    pass')
    assert denies(proc), proc.stdout
    assert "`a`" in reason_of(proc)
    assert "`b`" not in reason_of(proc)


def test_unreadable_file_skips_docstring_check() -> None:
    missing = Path(WORK.name) / "absent" / "nothing.py"
    assert is_silent(run_edit(missing, "x", '"""Two. Sentences."""\nx'))


def test_syntax_error_in_new_text_is_not_denied() -> None:
    path = path_in_work("broken.py", "def f():\n    pass\n")
    assert is_silent(run_edit(path, "pass", '"""One. Two."""\n    def ('))


def test_async_def_is_judged() -> None:
    proc = edit_adding_docstring(
        '"""One. Two."""',
        name="a.py",
        header="async def f():\n    ",
    )
    assert denies(proc), proc.stdout


def test_nested_class_is_judged() -> None:
    path = path_in_work("nested.py", "class A:\n    class B:\n        pass\n")
    proc = run_edit(path, "        pass", '        """One. Two."""')
    assert denies(proc), proc.stdout
    assert "`B`" in reason_of(proc)


def test_overload_stubs_without_docstrings_pass() -> None:
    text = (
        "from typing import overload\n\n\n"
        "@overload\ndef f(a: int) -> int: ...\n"
        "@overload\ndef f(a: str) -> str: ...\n"
    )
    assert is_silent(run("Write", str(path_in_work("over.py")), text))


def test_docstring_escape_hatch() -> None:
    path = path_in_work("hatch.py", "def f():\n    pass\n")
    proc = run_edit(path, "pass", '"""One. Two."""', env=HATCH)
    assert is_silent(proc)


def test_sample_cap_applies_to_docstring_violations() -> None:
    body = "".join(f"def f{i}():\n    '''One. Two.'''\n" for i in range(6))
    proc = run("Write", str(path_in_work("capped.py")), body)
    assert denies(proc), proc.stdout
    assert "and 2 more" in reason_of(proc)


def table_failures() -> int:
    """Run the Edit and Write tables and return the failure count."""
    bad = 0
    for tool, path, new, old, label in DENY:
        proc = run(tool, path, new, old)
        if not (proc.returncode == 0 and denies(proc) and proc.stderr == ""):
            bad += 1
            print(f"DENY FAIL ({label}): out={proc.stdout[:160]!r}")
    for tool, path, new, old, label in ALLOW:
        if not is_silent(run(tool, path, new, old)):
            bad += 1
            print(f"ALLOW FAIL ({label})")
    return bad


def payload_failures() -> int:
    """Run the garbage, escape hatch and sample cap checks."""
    bad = 0
    for raw in GARBAGE_INPUTS:
        if not is_silent(launch(raw)):
            bad += 1
            print(f"GARBAGE FAIL {raw!r}")
    if not is_silent(run("Edit", "a.py", "# narrate\nx = 1", env=HATCH)):
        bad += 1
        print("ESCAPE HATCH FAIL")
    cap = run("Edit", "a.py", "# 1\n# 2\n# 3\n# 4\n# 5\n# 6\nx = 1")
    if "and 2 more" not in cap.stdout:
        bad += 1
        print(f"SAMPLE CAP FAIL: {cap.stdout[:300]!r}")
    return bad


def bash_failures() -> int:
    """Run the heredoc tables and the shell escape hatch."""
    bad = 0
    for command, label in BASH_DENY:
        proc = run_bash(command)
        if not (proc.returncode == 0 and denies(proc) and proc.stderr == ""):
            bad += 1
            print(f"BASH DENY FAIL ({label}): out={proc.stdout[:160]!r}")
    for command, label in BASH_ALLOW:
        if not is_silent(run_bash(command)):
            bad += 1
            print(f"BASH ALLOW FAIL ({label})")
    hatch = "cat > a.py <<'EOF'\n# narrate\nx = 1\nEOF"
    if not is_silent(run_bash(hatch, env=HATCH)):
        bad += 1
        print("BASH HATCH FAIL")
    return bad


def docstring_failures(checks: list[Callable[[], None]]) -> int:
    """Run the docstring checks and return the failure count."""
    bad = 0
    for check in checks:
        try:
            check()
        except AssertionError as error:
            bad += 1
            print(f"DOC FAIL {check.__name__}: {error}")
    return bad


def doc_checks() -> list[Callable[[], None]]:
    """Return every docstring check defined in this file."""
    return [
        value
        for key, value in sorted(globals().items())
        if key.startswith("test_")
    ]


def main() -> int:
    """Run the matrix, print the summary and return the exit code."""
    checks = doc_checks()
    bad = (
        table_failures()
        + payload_failures()
        + bash_failures()
        + docstring_failures(checks)
    )
    docs = len(checks)
    total = (
        len(DENY)
        + len(ALLOW)
        + len(GARBAGE_INPUTS)
        + 2
        + len(BASH_DENY)
        + len(BASH_ALLOW)
        + 1
        + docs
    )
    print(f"hook: {HOOK}")
    print(
        f"deny: {len(DENY)}, allow: {len(ALLOW)}, "
        f"garbage: {len(GARBAGE_INPUTS)}, hatch+cap: 2, "
        f"bash deny: {len(BASH_DENY)}, bash allow: {len(BASH_ALLOW)}, "
        f"bash hatch: 1, docstring: {docs}",
    )
    print(f"{'FAIL' if bad else 'PASS'} {total - bad}/{total}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
