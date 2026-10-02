#!/usr/bin/env python3
"""Regression matrix for lint-guard.py (the sibling file by default; pass another path as argv[1])."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "lint-guard.py")
BUNDLE_RUFF_CONFIG = HERE.parent / "lint" / "ruff.toml"
REASON_MARK = "lint-guard"
FIX_HINT = "ruff check --fix"
MAX_LISTED = 5
TIMEOUT_BUDGET_S = 9.5
SLEEPING_RUFF = "#!/bin/sh\nexec sleep 30\n"
ESLINT_ARGS_FILE = "eslint-args.txt"
ESLINT_VIOLATION = [{"filePath": "x.ts", "messages": [
    {"ruleId": "no-unused-vars", "message": "'unusedVar' is defined but never used.", "line": 3}]}]
FAKE_ESLINT = (
    "#!/bin/sh\n"
    'printf "%s\\n" "$*" > "{args}"\n'
    "if grep -q unusedVar; then\n"
    "  cat <<'JSON'\n{violation}\nJSON\n"
    "else\n  echo '[{{\"filePath\": \"x.ts\", \"messages\": []}}]'\nfi\n"
)

state = {"bad": 0, "checks": 0}
RUFF_ON_PATH = shutil.which("ruff")
PYTHON = sys.executable
BASE_ENV = {"HOME": os.environ.get("HOME", "/"), "PATH": os.environ.get("PATH", "")}


def run(payload, env, raw=None):
    done = subprocess.run([PYTHON, HOOK], input=raw if raw is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=15, env=env, check=False)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def expect(label, payload, denied, env=None, needles=(), raw=None):
    state["checks"] += 1
    started = time.monotonic()
    rc, out, err = run(payload, env or BASE_ENV, raw)
    elapsed = time.monotonic() - started
    ok = rc == 0 and not err and (('"deny"' in out and REASON_MARK in out) if denied else out == "")
    reason = ""
    if ok and denied:
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        missing = [needle for needle in needles if needle not in reason]
        if missing:
            ok = False
            print(f"DENY MISSING [{label}] needles={missing} reason={reason[:400]!r}")
            state["bad"] += 1
            return reason
    if elapsed > TIMEOUT_BUDGET_S:
        ok = False
        print(f"SLOW [{label}] {elapsed:.1f}s")
    if not ok:
        state["bad"] += 1
        kind = "DENY MISS" if denied else "ALLOW FP "
        print(f"{kind} [{label}] rc={rc} out={out[:300]!r} err={err[-300:]!r}")
    return reason


def edit(path, old, new, tool="Edit"):
    return {"tool_name": tool, "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}


def write(path, content):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def put(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_repo(base, name):
    root = Path(base) / name
    (root / ".git").mkdir(parents=True)
    return root


def make_executable(path, text):
    put(path, text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def env_with(path_dirs, **extra):
    return {"HOME": BASE_ENV["HOME"], "PATH": os.pathsep.join(str(d) for d in path_dirs), **extra}


def test_file_block(repo, env):
    code = "def check(value):\n    assert value == 3\n"
    for relative in ("tests/test_x.py", "src/x_test.py", "src/x-test.py", "conftest.py"):
        expect(f"ALLOW magic value in {relative}", write(repo / relative, code), False, env)
    expect("DENY the same magic value in a source file", write(repo / "src" / "x.py", code), True, env,
           needles=("PLR2004",))


def ruff_block(base):
    env = {**BASE_ENV, "LINT_GUARD_RUFF_CONFIG": str(BUNDLE_RUFF_CONFIG)}
    plain = make_repo(base, "plain")
    legacy_old = "x = 1\n"
    legacy_new = "from typing import List\n\nx: List[int] = []\n"
    target = put(plain / "src" / "a.py", legacy_old)
    expect("DENY Edit adding typing.List", edit(target, legacy_old, legacy_new), True, env,
           needles=("UP006", "L3", FIX_HINT))
    many = "from typing import List\n" + "".join(f"v{index}: List[int] = []\n" for index in range(9))
    reason = expect("DENY caps the listed violations", write(plain / "src" / "many.py", many), True, env,
                    needles=("more.",))
    state["checks"] += 1
    listed = [line for line in reason.splitlines() if line.startswith("L") and line[1:2].isdigit()]
    if len(listed) != MAX_LISTED:
        state["bad"] += 1
        print(f"CAP wrong: {reason!r}")
    expect("DENY Write of a new file with == True", write(plain / "src" / "new.py",
                                                         "x = 1\nif x == True:\n    pass\n"), True, env,
           needles=("E712",))
    expect("DENY MultiEdit adding typing.List",
           {"tool_name": "MultiEdit", "tool_input": {"file_path": str(target), "edits": [
               {"old_string": legacy_old, "new_string": legacy_new}]}}, True, env, needles=("UP006",))
    expect("DENY Write into a directory that does not exist yet",
           write(plain / "fresh" / "deep" / "b.py", legacy_new), True, env, needles=("UP006",))

    messy = put(plain / "src" / "messy.py", "from typing import List\n\nx: List[int] = []\ny = 1\n")
    expect("ALLOW edit elsewhere in a file with existing violations", edit(messy, "y = 1", "y = 2"),
           False, env)
    clean = put(plain / "src" / "clean.py", "x = 1\n")
    expect("ALLOW clean edit", edit(clean, "x = 1", "x = 2"), False, env)
    expect("ALLOW non-code file", write(plain / "README.md", "if x == True:\n"), False, env)
    expect("ALLOW json file", write(plain / "data.json", "{}"), False, env)
    expect("ALLOW notebook edit payload",
           {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(plain / "n.ipynb"),
                                                        "new_source": "x: List[int] = []"}}, False, env)

    selecting = make_repo(base, "selecting")
    put(selecting / "pyproject.toml", '[tool.ruff.lint]\nselect = ["D100"]\n')
    nested = selecting / "pkg" / "inner"
    expect("DENY honours the repo pyproject [tool.ruff] from a nested dir",
           write(nested / "m.py", "x = 1\n"), True, env, needles=("D100",))
    expect("ALLOW the repo config replaces the global one",
           write(nested / "n.py", '"""Doc."""\n' + legacy_new), False, env)

    ruff_toml = make_repo(base, "ruff-toml")
    put(ruff_toml / "ruff.toml", '[lint]\nselect = ["D100"]\n')
    expect("DENY honours ruff.toml", write(ruff_toml / "m.py", "x = 1\n"), True, env, needles=("D100",))

    test_file_block(plain, env)

    unrelated = make_repo(base, "unrelated-pyproject")
    put(unrelated / "pyproject.toml", '[project]\nname = "x"\n')
    expect("DENY a pyproject without [tool.ruff] does not count as config",
           write(unrelated / "m.py", legacy_new), True, env, needles=("UP006",))

    absent_config = {**BASE_ENV, "LINT_GUARD_RUFF_CONFIG": str(Path(base) / "missing.toml")}
    expect("ALLOW fails open when the global config is unreadable", write(plain / "z.py", legacy_new), False,
           absent_config)

    bare = Path(base) / "no-ruff-bin"
    bare.mkdir()
    expect("ALLOW ruff missing from PATH", write(plain / "q.py", legacy_new), False,
           env_with([bare], LINT_GUARD_RUFF_CONFIG=str(BUNDLE_RUFF_CONFIG)))

    slow = Path(base) / "slow-bin"
    make_executable(slow / "ruff", SLEEPING_RUFF)
    expect("ALLOW ruff timeout", write(plain / "r.py", legacy_new), False,
           env_with([slow], LINT_GUARD_RUFF_CONFIG=str(BUNDLE_RUFF_CONFIG)))

    garbage = Path(base) / "garbage-bin"
    make_executable(garbage / "ruff", "#!/bin/sh\necho not json\n")
    expect("ALLOW non-JSON ruff output", write(plain / "s.py", legacy_new), False,
           env_with([garbage], LINT_GUARD_RUFF_CONFIG=str(BUNDLE_RUFF_CONFIG)))


def eslint_block(base):
    repo = make_repo(base, "web")
    put(repo / "eslint.config.js", "export default [];\n")
    args_file = Path(base) / ESLINT_ARGS_FILE
    make_executable(repo / "node_modules" / ".bin" / "eslint",
                    FAKE_ESLINT.format(args=args_file, violation=json.dumps(ESLINT_VIOLATION)))
    source = put(repo / "src" / "a.ts", "const used = 1;\nexport default used;\n")
    bad_new = "const used = 1;\nconst unusedVar = 2;\nexport default used;\n"
    added_line = "const used = 1;\nconst unusedVar = 2;\n"
    expect("DENY eslint violation added", edit(source, "const used = 1;\n", added_line), True,
           needles=("no-unused-vars", "unusedVar"))
    state["checks"] += 1
    recorded = args_file.read_text() if args_file.exists() else ""
    for needle in ("--format json", "--stdin", "--stdin-filename"):
        if needle not in recorded:
            state["bad"] += 1
            print(f"ESLINT ARGS missing {needle!r}: {recorded!r}")
    messy = put(repo / "src" / "b.tsx", "const unusedVar = 1;\nexport default 2;\n")
    expect("ALLOW eslint violation that already existed",
           edit(messy, "export default 2;", "export default 3;"), False)

    no_config = make_repo(base, "no-config")
    make_executable(no_config / "node_modules" / ".bin" / "eslint",
                    FAKE_ESLINT.format(args=args_file, violation=json.dumps(ESLINT_VIOLATION)))
    expect("ALLOW .ts without an eslint config", write(no_config / "a.ts", bad_new), False)

    no_binary = make_repo(base, "no-binary")
    put(no_binary / "eslint.config.js", "export default [];\n")
    expect("ALLOW .ts with a config but no eslint binary", write(no_binary / "a.ts", bad_new), False)

    broken = make_repo(base, "broken-eslint")
    put(broken / ".eslintrc.json", "{}")
    make_executable(broken / "node_modules" / ".bin" / "eslint", "#!/bin/sh\necho oops\nexit 2\n")
    expect("ALLOW non-JSON eslint output", write(broken / "a.ts", bad_new), False)


def main():
    with tempfile.TemporaryDirectory() as base:
        if RUFF_ON_PATH:
            ruff_block(base)
        else:
            state["bad"] += 1
            print("FAIL ruff is not on PATH: install ruff: uv tool install ruff")
        eslint_block(base)
        expect("ALLOW malformed JSON", None, False, raw="{not json")
        expect("ALLOW payload without tool_input", {"tool_name": "Edit"}, False)
        expect("ALLOW payload that is a list", None, False, raw="[]")
        expect("ALLOW edit whose old_string is absent", edit(put(Path(base) / "w" / "a.py", "x = 1\n"),
                                                             "nope", "x: List[int] = []"), False)
    print(f"lint-guard matrix: {state['checks']} checks, {state['bad']} failed")
    sys.exit(1 if state["bad"] else 0)


if __name__ == "__main__":
    main()
