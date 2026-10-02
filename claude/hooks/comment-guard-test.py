#!/usr/bin/env python3
"""Regression matrix for comment-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, os, subprocess, sys, tempfile, time

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "comment-guard.py")
REASON_MARK = "comment-guard: no comments in code"
DEVELOPER = "developer"
MAIN_SESSION = None
PY_KERNEL = {"kernelspec": {"name": "python3", "language": "python", "display_name": "Python 3"},
             "language_info": {"name": "python"}}
R_KERNEL = {"kernelspec": {"name": "ir", "language": "R", "display_name": "R"}, "language_info": {"name": "R"}}


def run(payload, raw=None):
    done = subprocess.run(["python3", hook], input=raw if raw is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=10)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


bad = 0
checks = 0
slowest = 0.0


def expect(label, payload, denied, needles=()):
    global bad, checks, slowest
    checks += 1
    t0 = time.time()
    rc, out, err = run(payload)
    slowest = max(slowest, time.time() - t0)
    ok = rc == 0 and not err and (('"deny"' in out and REASON_MARK in out) if denied else out == "")
    if ok and denied:
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        missing = [needle for needle in needles if needle not in reason]
        if missing:
            ok = False
            print(f"DENY MISSING [{label}] needles={missing} reason={reason[:300]!r}")
            bad += 1
            return
    if not ok:
        bad += 1
        kind = "DENY MISS" if denied else "ALLOW FP "
        print(f"{kind} [{label}] rc={rc} out={out[:200]!r} err={err[-300:]!r}")


def notebook(cells, metadata=PY_KERNEL):
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": metadata, "cells": [
        {"cell_type": kind, "id": cell_id, "metadata": {}, "source": source,
         **({"outputs": [], "execution_count": None} if kind == "code" else {})}
        for cell_id, kind, source in cells]}, indent=1)


with tempfile.TemporaryDirectory() as base:
    def put(name, text):
        path = os.path.join(base, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def payload(tool, data, agent_type=MAIN_SESSION):
        body = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": tool, "tool_input": data,
                "cwd": base}
        if agent_type is not None:
            body["agent_type"] = agent_type
        return body

    def write(label, name, content, denied, existing=None, needles=(), agent_type=MAIN_SESSION):
        path = os.path.join(base, "w", name)
        if existing is not None:
            put(os.path.join("w", name), existing)
        elif os.path.exists(path):
            os.remove(path)
        expect(f"Write {label}", payload("Write", {"file_path": path, "content": content}, agent_type),
               denied, needles)

    def edit(label, name, before, old, new, denied, replace_all=False, needles=(), agent_type=MAIN_SESSION):
        path = put(os.path.join("e", name), before)
        data = {"file_path": path, "old_string": old, "new_string": new}
        if replace_all:
            data["replace_all"] = True
        expect(f"Edit {label}", payload("Edit", data, agent_type), denied, needles)

    def multi(label, name, before, edits, denied):
        path = put(os.path.join("m", name), before)
        expect(f"MultiEdit {label}", payload("MultiEdit", {"file_path": path, "edits": [
            {"old_string": old, "new_string": new} for old, new in edits]}), denied)

    def notebook_edit(label, cells, data, denied, metadata=PY_KERNEL):
        path = put(os.path.join("nb", "n.ipynb"), notebook(cells, metadata))
        expect(f"NotebookEdit {label}", payload("NotebookEdit", {"notebook_path": path, **data}), denied)

    for agent in (MAIN_SESSION, DEVELOPER):
        edit(f"adds # x to .py (agent {agent})", "a.py", "a = 1\nb = 2\n", "b = 2", "b = 2  # x", True,
             needles=("L2:", "# x", "description="), agent_type=agent)
    write("new .py with a comment", "new.py", "# x\nprint(1)\n", True, needles=("L1:",))
    write("// x in .ts", "a.ts", "const a = 1;\n// x\n", True)
    write("/* x */ in .c", "a.c", "int a = 1; /* x */\n", True)
    write("multi-line /** */ in .ts", "doc.ts", "/**\n * Adds.\n * More.\n */\nexport const a = 1;\n", True)
    write("two /// lines in .rs", "doc.rs", "/// Adds.\n/// More.\npub fn a() {}\n", True)
    write("# x in .sh", "a.sh", "echo hi\n# x\n", True)
    write("-- x in .sql", "a.sql", "SELECT 1; -- x\n", True)
    write("<!-- x --> in .vue", "A.vue", "<template>\n  <!-- x -->\n  <div/>\n</template>\n", True)
    write("multi-line docstring", "doc.py", 'def f():\n    """Adds.\n\n    More.\n    """\n    return 1\n', True)
    write("multi-line class docstring", "cls.py", 'class A:\n    """Adds.\n    More."""\n', True)
    write("multi-line module docstring", "mod.py", '"""Adds.\nMore.\n"""\nx = 1\n', True)
    write("bash shebang file comment", "tool", "#!/usr/bin/env bash\necho hi\n# x\n", True)
    write("python shebang file comment", "pytool", "#!/usr/bin/env python3\nprint(1)\n# x\n", True)
    write("python shebang file tokenized as python", "pytool2",
          "#!/usr/bin/env python3\ns = '''\n# not a comment\n'''\n", False)
    write("broken python still denies", "broken.py", "def f(:\n    x = 1  # x\n", True)
    write("unterminated python still denies", "broken2.py", "s = (1,\n# x\n", True)
    write("`// x` inside ${} of a template", "tpl.ts", "const s = `a ${f() // x\n} b`;\n", True)
    write("ruby x = 1# y", "a.rb", "x = 1# y\n", True)
    write("php # x", "a.php", "<?php\n$a = 1; # x\n", True)
    write("lua -- x", "a.lua", "local a = 1 -- x\n", True)
    write("lua --[[ x ]]", "b.lua", "local a = 1 --[[ x ]]\n", True)
    write("go // x", "a.go", "package a\n\nvar s = 1 // x\n", True)
    write("elixir # x", "a.ex", "x = 1 # y\n", True)
    write("comment after rust lifetimes", "life.rs", "fn f<'a>(s: &'a str) -> &'a str { s } // x\n", True)
    write("same comment added twice", "twice.py", "a = 1  # x\nb = 2  # x\n", True, existing="a = 1  # x\nb = 2\n")
    write("reason lists at most three", "many.py", "a = 1  # one\nb = 2  # two\nc = 3  # three\nd = 4  # four\n",
          True, needles=("L1:", "L2:", "L3:"))

    edit("replace_all adds a comment at every match", "ra.py", "s = 1\ns = 1\n", "s = 1", "s = 1  # x", True,
         replace_all=True)
    edit("adds another copy of an existing comment", "copy.py", "a = 1  # x\n", "a = 1  # x",
         "a = 1  # x\nb = 2  # x", True)
    multi("second edit adds a comment", "m.py", "a = 1\nb = 2\n", [("a = 1", "a = 3"), ("b = 2", "b = 2  # x")],
          True)
    multi("edits without comments", "m2.py", "a = 1\nb = 2\n", [("a = 1", "a = 3"), ("b = 2", "b = 4")], False)

    notebook_edit("code cell # x", [("c1", "code", "x = 1\n")],
                  {"cell_id": "c1", "new_source": "x = 1  # x", "edit_mode": "replace"}, True)
    notebook_edit("insert code cell # x", [("c1", "code", "x = 1\n")],
                  {"cell_id": "c1", "new_source": "# x\ny = 2", "cell_type": "code", "edit_mode": "insert"}, True)
    notebook_edit("delete cell", [("c1", "code", "x = 1  # x\n")],
                  {"cell_id": "c1", "new_source": "", "edit_mode": "delete"}, False)
    notebook_edit("markdown cell # Title", [("m1", "markdown", "Intro")],
                  {"cell_id": "m1", "new_source": "# Title", "cell_type": "markdown", "edit_mode": "replace"}, False)
    notebook_edit("existing markdown cell replaced", [("m1", "markdown", "Intro")],
                  {"cell_id": "m1", "new_source": "# Title", "edit_mode": "replace"}, False)
    notebook_edit("R kernel", [("c1", "code", "x <- 1\n")],
                  {"cell_id": "c1", "new_source": "x <- 1  # x", "edit_mode": "replace"}, False, R_KERNEL)
    notebook_edit("cell keeps its comment", [("c1", "code", "x = 1  # x\n")],
                  {"cell_id": "c1", "new_source": "x = 2  # x", "edit_mode": "replace"}, False)

    write("ipynb new code cell # x", "w.ipynb", notebook([("c1", "code", "x = 1\n"), ("c2", "code", "# x\ny = 2\n")]),
          True, existing=notebook([("c1", "code", "x = 1\n")]))
    write("ipynb markdown heading", "w2.ipynb", notebook([("c1", "code", "x = 1\n"), ("m1", "markdown", "# T")]),
          False, existing=notebook([("c1", "code", "x = 1\n")]))
    write("ipynb R kernel", "w3.ipynb", notebook([("c1", "code", "x <- 1  # x\n")], R_KERNEL), False)
    write("ipynb invalid json", "w4.ipynb", "{not json # x", False)

    write("regex classes and escapes in .ts", "re.ts",
          "function f(s) {\n  if (typeof /x\\/\\//.test(s)) return /[//]/;\n  return s;\n}\n", False)
    write("regex literal and division in .ts", "div.ts",
          "const r = s.replace(/\\/\\//g, '');\nconst q = a / b / c;\nconst u = \"http://x\";\n", False)
    write("template literal containing //", "tl.ts", "const u = `http://${host}/a//b`;\nconst v = `//`;\n", False)
    write("strings with # and // in .py", "s.py",
          "s = \"#\"\nu = \"http://x\"\nt = '//'\nf = Field(description=\"a # b\")\n", False)
    write("strings with # and // in .ts", "s.ts", "const s = \"#\";\nconst u = \"http://x\";\nconst t = '//';\n",
          False)
    write("strings and raw strings in .go", "s.go",
          "package a\n\nvar s = \"#\"\nvar u = \"http://x\"\nvar r = `a\n// b\n`\nvar c = '/'\n", False)
    write("shell heredoc", "h.sh", "cat <<EOF\n# line\nEOF\ncat <<-'END'\n\t# other\n\tEND\necho done\n", False)
    write("shell $# and ${#arr[@]}", "n.sh", "echo $#\nn=${#arr[@]}\necho \"a # b\" 'c # d'\n", False)
    write("c++ raw string", "r.cpp", "auto s = R\"(a \" // x)\";\nauto t = R\"d(\n// y\n)d\";\n", False)
    write("c# verbatim string", "v.cs", "var p = @\"C:\\\"; var u = \"http://x\";\n", False)
    write("c# raw string", "raw.cs", "var j = \"\"\"\n// x\n\"\"\";\n", False)
    write("kotlin text block", "k.kt", "val s = \"\"\"\n// x\n\"\"\"\n", False)
    write("java text block", "J.java", "String s = \"\"\"\n// x\n\"\"\";\n", False)
    write("dart raw and triple strings", "d.dart", "var a = r'\\';\nvar b = '''\n// x\n''';\nvar u = 'http://x';\n",
          False)
    write("rust derive and lifetime", "l.rs",
          "#[derive(Debug)]\nstruct S<'a> { s: &'a str }\nconst U: &str = \"http://x\";\nconst C: char = '/';\n",
          False)
    write("rust raw strings", "raw.rs", "const A: &str = r\"a // b\";\nconst B: &str = r#\"c \" // d\"#;\n", False)
    write("#include and #define in .c", "i.c", "#include <stdio.h>\n#define X 1\nint a = X;\n", False)
    write("one-line docstring", "one.py", 'def f():\n    """Adds one."""\n    return 1\n', False)
    write("one-line /** x */", "one.ts", "/** Adds one. */\nexport const a = 1;\n", False)
    write("single ///", "one.rs", "/// Adds one.\npub fn a() {}\n", False)
    write("shebang", "sheb.py", "#!/usr/bin/env python3\nprint(1)\n", False)
    write("coding cookie", "cook.py", "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nprint(1)\n", False)
    write("vue html and script strings", "B.vue",
          "<template>\n  <a href=\"http://x\">Don't</a>\n</template>\n<script setup lang=\"ts\">\n"
          "const u = \"http://x\"\n</script>\n", False)
    write("keeps existing comments", "keep.py", "a = 1  # x\nb = 3\n", False, existing="a = 1  # x\nb = 2\n")
    for name, text in (("R.md", "# Heading\n"), ("c.json", "{\"a\": \"# x\"}\n"), ("c.yaml", "# x\na: 1\n"),
                       ("c.toml", "# x\na = 1\n"), ("plain", "# x\n")):
        write(f"non-code {name}", name, text, False)

    edit("elsewhere in a commented file", "else.py", "a = 1  # x\n# y\nb = 2\n", "b = 2", "b = 3", False)
    edit("comment moved unchanged", "mv.py", "a = 1  # x\nb = 2\n", "a = 1  # x\nb = 2", "a = 1\nb = 2  # x", False)
    edit("comments removed", "rm.py", "a = 1  # x\n# y\n", "a = 1  # x\n# y\n", "a = 1\n", False)
    edit("old_string not found", "nf.py", "a = 1\n", "zzz", "zzz  # x", False)
    expect("Edit missing file", payload("Edit", {"file_path": os.path.join(base, "absent", "gone.py"),
                                                 "old_string": "zzz", "new_string": "# x"}), False)

    edit("shebang removed and comment added", "script", "#!/usr/bin/env bash\necho hi\n",
         "#!/usr/bin/env bash\necho hi", "echo hi\n# x", True)
    edit("syntax fix in a file with a multi-line docstring", "fix.py",
         'def f(:\n    """Adds.\n\n    More.\n    """\n    return 1\n', "def f(:", "def f():", False)
    edit("multi-line docstring added to a parsing file", "adddoc.py", "def f():\n    return 1\n",
         "def f():\n", 'def f():\n    """Adds.\n    More.\n    """\n', True)
    edit("syntax fix plus a new multi-line docstring", "fixdoc.py", "def f(:\n    return 1\n",
         "def f(:\n", 'def f():\n    """Adds.\n    More.\n    """\n', True)
    write("one-line /*! x */ in .ts", "bang.ts", "/*! TODO */\nexport const a = 1;\n", True)
    write("webpack-like prose comment", "wp.js", "/* webpackMigration notes */\nexport const a = 1;\n", True)
    write("css string with /* */ in vue style", "S.vue",
          "<template><div/></template>\n<style>\n.a::before { content: \"/* x */\"; }\n.b { content: '/* y */'; }\n"
          "</style>\n", False)
    write("css comment in vue style", "T.vue", "<template><div/></template>\n<style>\n/* x */\n.a { color: red; }\n"
          "</style>\n", True)
    write("one-line /*! x */ in .rs", "inner.rs", "/*! Crate docs. */\npub fn a() {}\n", False)
    write("multi-line /*! */ in .rs", "inner2.rs", "/*!\n Crate docs.\n More.\n*/\npub fn a() {}\n", True)

    directives = {
        "rb": ["# frozen_string_literal: true", "# encoding: utf-8", "x = 1 # rubocop:disable Style/Foo"],
        "swift": ["// swiftlint:disable line_length"],
        "js": ["import(/* webpackPrefetch: true */ \"./x\");", "import(/* webpackPreload: true */ \"./x\");",
               "import(/* webpackMode: \"lazy\" */ \"./x\");"],
        "py": ["x = f()  # type: ignore[attr-defined]", "import os  # noqa: F401", "x = 1  # pragma: no cover",
               "# fmt: off", "x = 1  # pylint: disable=invalid-name", "# mypy: ignore-errors", "# pyright: basic",
               "# ruff: noqa: E501", "# isort: skip_file"],
        "ts": ["// eslint-disable-next-line no-console", "/* eslint-disable */", "// eslint-enable",
               "// @ts-ignore", "// @ts-expect-error", "// @ts-nocheck", "// @ts-check", "// prettier-ignore",
               "// biome-ignore lint/style/useConst: legacy", "/* istanbul ignore next */", "/* c8 ignore next */",
               "/* v8 ignore next */", "/** @vitest-environment jsdom */", "/** @jest-environment jsdom */",
               "import(/* @vite-ignore */ path);", "import(/* webpackChunkName: \"x\" */ \"./x\");",
               "/// <reference types=\"vite/client\" />"],
        "go": ["//go:build linux", "//go:generate stringer -type=X", "//go:embed static", "// +build linux",
               "f() //nolint:errcheck"],
        "cpp": ["f(); // NOLINT", "// NOLINTNEXTLINE(bugprone-x)", "// clang-format off", "// clang-format on",
                "#include <a.h> // IWYU pragma: keep"],
        "sh": ["# shellcheck disable=SC2086"],
    }
    for suffix, lines in directives.items():
        for number, line in enumerate(lines):
            write(f"directive {line!r}", f"dir{number}.{suffix}", line + "\n", False)
    write("stacked reference directives", "refs.ts",
          "/// <reference types=\"vite/client\" />\n/// <reference path=\"./x.d.ts\" />\n", False)

    garbage = [
        "", "not json", "null", "[]", "5",
        json.dumps({"tool_name": "Edit"}),
        json.dumps({"tool_name": "Edit", "tool_input": None}),
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": 42}}),
        json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "/x.py", "old_string": 1, "new_string": 2}}),
        json.dumps({"tool_name": "MultiEdit", "tool_input": {"file_path": "/x.py", "edits": "nope"}}),
        json.dumps({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "/nope.ipynb",
                                                                "new_source": "# x", "cell_id": "c1"}}),
        json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo '# x' >> a.py"}}),
    ]
    for raw in garbage:
        checks += 1
        rc, out, err = run(None, raw)
        if not (rc == 0 and out == "" and not err):
            bad += 1
            print(f"garbage {raw[:60]!r} -> rc={rc} out={out[:80]!r} err={err[-160:]!r}")

    scan_path = put("scan/s.py", "#!/usr/bin/env python3\nx = 1  # noqa\ny = 2  # real\n")
    for args, wanted, unwanted in (
            (["--scan"], [f"{scan_path}:3: # real"], [":1:", ":2:"]),
            (["--scan", "--raw"], [f"{scan_path}:1:", f"{scan_path}:2:", f"{scan_path}:3:"], [])):
        checks += 1
        done = subprocess.run(["python3", hook, *args, scan_path], capture_output=True, text=True, timeout=10)
        lines = done.stdout.splitlines()
        if done.returncode != 0 or any(not any(line.startswith(w) for line in lines) for w in wanted) \
                or any(u in done.stdout for u in unwanted):
            bad += 1
            print(f"SCAN FAIL {args} -> rc={done.returncode} out={done.stdout[:300]!r} err={done.stderr[-200:]!r}")

print(f"hook: {hook}\nchecks: {checks}, slowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}")
print(("FAIL " if bad else "PASS ") + f"{checks - bad}/{checks}")
sys.exit(1 if bad else 0)
