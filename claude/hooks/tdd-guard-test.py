#!/usr/bin/env python3
"""Regression matrix for tdd-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, os, subprocess, sys, tempfile, time

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "tdd-guard.py")
REASON_MARK = "tdd-guard: RED first"
DEVELOPER = "developer"
PROMPT = "plan_file: /repo/plan.md\nImplement the plan test-first."
EXEMPT_PROMPT = PROMPT + "\ntdd_exempt: pure refactor under existing coverage"
EMPTY_EXEMPT_PROMPT = PROMPT + "\ntdd_exempt:"
QUOTED_EXEMPT_PROMPT = PROMPT + "\n`tdd_exempt: <reason>` in the spawn prompt disables the gate."
SKILL_TEXT = "Base directory for this skill: /x/skills/tdd\n\ntdd_exempt: <reason> in the spawn prompt."
FAIL_LOG = "VERIFY FAIL exit=1 time=2s lines=12 cmd: pytest -q\nlog: /tmp/v.log"
PASS_LOG = "VERIFY PASS exit=0 time=2s lines=12 cmd: pytest -q\nlog: /tmp/v.log"
VERIFY_CMD = "~/.claude/bin/verify -- 'pytest -q'"
SOURCE = "/repo/src/app.py"
TEST_FILE = "/repo/tests/test_app.py"


def prompt(text=PROMPT):
    return {"type": "user", "message": {"role": "user", "content": text}}


def skill(text=SKILL_TEXT):
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def use(name, data, use_id):
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": use_id, "name": name, "input": data}]}}


def result(use_id, content):
    return {"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": use_id, "content": content}]}}


def edit(path, use_id, new_string="x = 1"):
    return [use("Edit", {"file_path": path, "old_string": "a", "new_string": new_string}, use_id),
            result(use_id, "The file has been updated.")]


def bash(command, output, use_id):
    return [use("Bash", {"command": command}, use_id), result(use_id, output)]


def write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return path


def edit_input(path=SOURCE):
    return "Edit", {"file_path": path, "old_string": "a", "new_string": "b"}


def write_input(path, content="print(1)\n"):
    return "Write", {"file_path": path, "content": content}


def multi_input(path=SOURCE):
    return "MultiEdit", {"file_path": path, "edits": [{"old_string": "a", "new_string": "b"}]}


def notebook_input(path):
    return "NotebookEdit", {"notebook_path": path, "new_source": "x = 1", "cell_id": "c1"}


def run(payload, raw=None):
    done = subprocess.run(["python3", hook], input=raw if raw is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=10)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


bad = 0
checks = 0
slowest = 0.0


def expect(label, payload, denied):
    global bad, checks, slowest
    checks += 1
    t0 = time.time()
    rc, out, err = run(payload)
    slowest = max(slowest, time.time() - t0)
    ok = rc == 0 and not err and (('"deny"' in out and REASON_MARK in out) if denied else out == "")
    if not ok:
        bad += 1
        kind = "DENY MISS" if denied else "ALLOW FP "
        print(f"{kind} [{label}] rc={rc} out={out[:160]!r} err={err[-200:]!r}")


with tempfile.TemporaryDirectory() as base:
    def transcript(name, entries):
        return write_jsonl(os.path.join(base, name + ".jsonl"), entries)

    red = [prompt()] + edit(TEST_FILE, "t1") + bash(VERIFY_CMD, FAIL_LOG, "v1")
    transcripts = {
        "empty": transcript("empty", [prompt()]),
        "red": transcript("red", red),
        "only pass": transcript("only-pass", [prompt()] + edit(TEST_FILE, "t1") + bash(VERIFY_CMD, PASS_LOG, "v1")),
        "fail before test": transcript("fail-before", [prompt()] + bash(VERIFY_CMD, FAIL_LOG, "v1")
                                       + edit(TEST_FILE, "t1")),
        "fail via cat": transcript("cat", [prompt()] + edit(TEST_FILE, "t1")
                                   + bash("cat /tmp/verify-logs/last.log", FAIL_LOG, "c1")),
        "fail via grep": transcript("grep", [prompt()] + edit(TEST_FILE, "t1")
                                    + bash("grep -n VERIFY /tmp/verify-logs/last.log", FAIL_LOG, "g1")),
        "fail in non-verify bash": transcript("echo", [prompt()] + edit(TEST_FILE, "t1")
                                              + bash("pytest -q", FAIL_LOG, "p1")),
        "fail not at line start": transcript("inline", [prompt()] + edit(TEST_FILE, "t1")
                                             + bash(VERIFY_CMD, "summary: " + FAIL_LOG, "v1")),
        "fail result for other id": transcript("other-id", [prompt()] + edit(TEST_FILE, "t1")
                                               + [use("Bash", {"command": VERIFY_CMD}, "v1"),
                                                  result("zz", FAIL_LOG), result("v1", PASS_LOG)]),
        "bash -c verify": transcript("bash-c", [prompt()] + edit(TEST_FILE, "t1")
                                     + bash("bash -c \"~/.claude/bin/verify -- pytest -q\"", FAIL_LOG, "v1")),
        "env verify": transcript("env", [prompt()] + edit(TEST_FILE, "t1")
                                 + bash("env PYTHONPATH=src ~/.claude/bin/verify -- pytest -q", FAIL_LOG, "v1")),
        "cd && verify": transcript("cd", [prompt()] + edit(TEST_FILE, "t1")
                                   + bash("cd /repo && ~/.claude/bin/verify -- 'pytest -q'", FAIL_LOG, "v1")),
        "list content": transcript("list", [prompt()] + edit(TEST_FILE, "t1")
                                   + [use("Bash", {"command": VERIFY_CMD}, "v1"),
                                      result("v1", [{"type": "text", "text": FAIL_LOG}])]),
        "write test": transcript("write-test", [prompt(), use("Write", {"file_path": "/repo/src/app.test.ts",
                                                                        "content": "it()"}, "w1"),
                                                result("w1", "File created.")] + bash(VERIFY_CMD, FAIL_LOG, "v1")),
        "rust marker": transcript("rust", [prompt()] + edit("/repo/src/lib.rs", "r1",
                                                            "#[cfg(test)]\nmod tests {\n#[test]\nfn a() {}\n}")
                                  + bash("~/.claude/bin/verify -- cargo test", FAIL_LOG, "v1")),
        "exempt": transcript("exempt", [prompt(EXEMPT_PROMPT)]),
        "exempt after skills": transcript("exempt-skills", [prompt(EXEMPT_PROMPT), skill()]),
        "later exempt": transcript("later-exempt", [prompt(), skill(), prompt("follow-up\ntdd_exempt: sneaky")]),
        "failed test edit": transcript("failed-edit", [
            prompt(), use("Edit", {"file_path": TEST_FILE, "old_string": "a", "new_string": "b"}, "t1"),
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                 "content": "<tool_use_error>String to replace not found in file.</tool_use_error>"}]}}]
            + bash(VERIFY_CMD, FAIL_LOG, "v1")),
        "verify fail flagged is_error": transcript("fail-is-error", [prompt()] + edit(TEST_FILE, "t1") + [
            use("Bash", {"command": VERIFY_CMD}, "v1"),
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "v1", "is_error": True, "content": FAIL_LOG}]}}]),
        "successful test edit": transcript("ok-edit", [
            prompt(), use("Edit", {"file_path": TEST_FILE, "old_string": "a", "new_string": "b"}, "t1"),
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": False,
                 "content": "The file has been updated."}]}}]
            + bash(VERIFY_CMD, FAIL_LOG, "v1")),
        "empty exempt": transcript("empty-exempt", [prompt(EMPTY_EXEMPT_PROMPT)]),
        "quoted exempt": transcript("quoted-exempt", [prompt(QUOTED_EXEMPT_PROMPT)]),
        "skill exempt": transcript("skill-exempt", [prompt(), skill()]),
        "verify issued before test edit": transcript("same-message", [
            prompt(),
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "v1", "name": "Bash", "input": {"command": VERIFY_CMD}},
                {"type": "tool_use", "id": "t1", "name": "Edit",
                 "input": {"file_path": TEST_FILE, "old_string": "a", "new_string": "b"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "v1", "content": FAIL_LOG},
                {"type": "tool_result", "tool_use_id": "t1", "content": "The file has been updated."}]}}]),
    }

    def payload(tool, agent_transcript="empty", agent_type=DEVELOPER, **extra):
        name, data = tool
        body = {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": name, "tool_input": data,
                "agent_id": "a1", "transcript_path": os.path.join(base, "main.jsonl")}
        if agent_type is not None:
            body["agent_type"] = agent_type
        if agent_transcript is not None:
            body["agent_transcript_path"] = transcripts.get(agent_transcript, agent_transcript)
        body.update(extra)
        return body

    for label in ("empty", "only pass", "fail before test", "fail via cat", "fail via grep",
                  "fail in non-verify bash", "fail not at line start", "fail result for other id",
                  "empty exempt", "quoted exempt", "skill exempt", "verify issued before test edit",
                  "later exempt", "failed test edit"):
        expect(f"source edit, transcript {label}", payload(edit_input(), label), True)

    for label in ("red", "bash -c verify", "env verify", "cd && verify", "list content", "write test",
                  "exempt after skills", "successful test edit", "verify fail flagged is_error",
                  "rust marker", "exempt"):
        expect(f"source edit, transcript {label}", payload(edit_input(), label), False)

    for path in ("/repo/src/app.ts", "/repo/cmd/main.go", "/repo/src/Main.java", "/repo/lib/user.rb",
                 "/repo/src/parser.c", "/repo/src/types.pyi", "/repo/src/lib.rs", "/repo/web/App.vue",
                 "/repo/scripts/deploy.sh", "/repo/db/schema.sql", "/repo/fw/main.ino"):
        expect(f"source {path} without red", payload(edit_input(path)), True)
        expect(f"source {path} after red", payload(edit_input(path), "red"), False)

    shebang_path = os.path.join(base, "repo", "bin", "tool")
    os.makedirs(os.path.dirname(shebang_path), exist_ok=True)
    with open(shebang_path, "w", encoding="utf-8") as handle:
        handle.write("#!/usr/bin/env python3\nprint(1)\n")
    plain_path = os.path.join(base, "repo", "LICENSE")
    with open(plain_path, "w", encoding="utf-8") as handle:
        handle.write("MIT License\n")
    expect("extensionless shebang Write", payload(write_input("/repo/bin/run", "#!/bin/sh\necho hi\n")), True)
    expect("extensionless shebang on disk Edit", payload(edit_input(shebang_path)), True)
    expect("extensionless shebang after red", payload(edit_input(shebang_path), "red"), False)
    expect("extensionless plain file", payload(edit_input(plain_path)), False)
    expect("extensionless plain Write", payload(write_input("/repo/Makefile", "all:\n\techo hi\n")), False)

    expect("ipynb outside tests", payload(notebook_input("/repo/analysis.ipynb")), True)
    expect("ipynb outside tests after red", payload(notebook_input("/repo/analysis.ipynb"), "red"), False)
    expect("ipynb inside tests", payload(notebook_input("/repo/tests/explore.ipynb")), False)
    expect("MultiEdit source without red", payload(multi_input()), True)
    expect("MultiEdit source after red", payload(multi_input(), "red"), False)
    expect("Write source without red", payload(write_input(SOURCE)), True)

    for path in ("/repo/tests/test_app.py", "/repo/test/helpers.py", "/repo/testing/util.py",
                 "/repo/src/app_test.py", "/repo/hooks/tdd-guard-test.py", "/repo/src/test_parser.py",
                 "/repo/conftest.py", "/repo/web/__tests__/App.tsx", "/repo/e2e/login.ts",
                 "/repo/spec/models/user.rb", "/repo/specs/api.ts", "/repo/src/app.test.ts",
                 "/repo/src/app.spec.tsx", "/repo/src/util.test.js", "/repo/pkg/app_test.go",
                 "/repo/src/FooTest.java", "/repo/src/FooTests.java", "/repo/src/BarTest.kt",
                 "/repo/src/FooTests.cs", "/repo/lib/user_spec.rb", "/repo/src/test_parser.c",
                 "/repo/src/parser_test.c", "/repo/src/parser_test.cc", "/repo/src/parser_test.cpp"):
        expect(f"test path {path}", payload(edit_input(path)), False)

    for path in ("/repo/README.md", "/repo/package.json", "/repo/config.yaml", "/repo/ci.yml",
                 "/repo/pyproject.toml", "/repo/docs/guide.rst", "/repo/.env.example", "/repo/styles/app.css"):
        expect(f"other path {path}", payload(edit_input(path)), False)

    expect("rust inline test marker edit", payload(("Edit", {"file_path": "/repo/src/lib.rs", "old_string": "a",
                                                            "new_string": "#[test]\nfn parses() {}"})), False)
    expect("rust tokio marker Write", payload(write_input("/repo/src/net.rs",
                                                          "#[tokio::test]\nasync fn t() {}\n")), False)

    for other in ("implementer", "Explore", "general-purpose", "codex-runner"):
        expect(f"agent_type {other} untouched", payload(edit_input(), agent_type=other), False)
    expect("main session untouched", payload(edit_input(), agent_type=None), False)

    derived_dir = os.path.join(base, "main", "subagents")
    write_jsonl(os.path.join(derived_dir, "agent-derived-dirty.jsonl"), [prompt()])
    write_jsonl(os.path.join(derived_dir, "agent-derived-red.jsonl"), red)
    main_path = os.path.join(base, "main.jsonl")
    expect("derived transcript dirty", payload(edit_input(), None, agent_id="derived-dirty",
                                               transcript_path=main_path), True)
    expect("derived transcript red", payload(edit_input(), None, agent_id="derived-red",
                                             transcript_path=main_path), False)
    expect("agent_transcript_path preferred (dirty over red)",
           payload(edit_input(), "empty", agent_id="derived-red", transcript_path=main_path), True)
    expect("agent_transcript_path preferred (red over dirty)",
           payload(edit_input(), "red", agent_id="derived-dirty", transcript_path=main_path), False)
    expect("missing transcript", payload(edit_input(), os.path.join(base, "nope.jsonl"), agent_id="nobody"),
           False)
    expect("no transcript at all", payload(edit_input(), None, agent_id="nobody", transcript_path=None), False)

    def make_dirs(*parts):
        path = os.path.join(base, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    git_repo = make_dirs("test", "app")
    make_dirs("test", "app", ".git")
    expect("repo under a dir named test: src gated",
           payload(edit_input(os.path.join(git_repo, "src", "main.py"))), True)
    expect("repo under a dir named test: tests/ still TEST",
           payload(edit_input(os.path.join(git_repo, "tests", "test_main.py"))), False)
    expect("repo under a dir named test: src after red",
           payload(edit_input(os.path.join(git_repo, "src", "main.py")), "red"), False)
    worktree = make_dirs("spec", "wt")
    with open(os.path.join(worktree, ".git"), "w", encoding="utf-8") as handle:
        handle.write("gitdir: /elsewhere/.git/worktrees/wt\n")
    expect("worktree (.git file) under spec: src gated",
           payload(edit_input(os.path.join(worktree, "lib", "core.py"))), True)
    expect("worktree (.git file) under spec: spec/ inside repo is TEST",
           payload(edit_input(os.path.join(worktree, "spec", "core_behaviour.rb"))), False)
    no_git_cwd = make_dirs("e2e", "proj")
    expect("no .git, under cwd named e2e: src gated",
           payload(edit_input(os.path.join(no_git_cwd, "src", "x.py")), cwd=no_git_cwd), True)
    expect("no .git, under cwd: tests/ is TEST",
           payload(edit_input(os.path.join(no_git_cwd, "tests", "x.py")), cwd=no_git_cwd), False)
    outside = make_dirs("nogit")
    other_cwd = make_dirs("elsewhere")
    expect("no .git, outside cwd: all segments, tests/ is TEST",
           payload(edit_input(os.path.join(outside, "tests", "helper.py")), cwd=other_cwd), False)
    expect("no .git, outside cwd: src gated",
           payload(edit_input(os.path.join(outside, "src", "app.py")), cwd=other_cwd), True)
    repo_red = transcript("repo-red", [prompt()] + edit(os.path.join(git_repo, "tests", "test_main.py"), "t1")
                          + bash(VERIFY_CMD, FAIL_LOG, "v1"))
    repo_not_red = transcript("repo-not-red", [prompt()] + edit(os.path.join(git_repo, "src", "helper.py"), "t1")
                              + bash(VERIFY_CMD, FAIL_LOG, "v1"))
    expect("repo under test: transcript test edit in tests/ opens the gate",
           payload(edit_input(os.path.join(git_repo, "src", "main.py")), repo_red), False)
    expect("repo under test: transcript src edit is not a test edit",
           payload(edit_input(os.path.join(git_repo, "src", "main.py")), repo_not_red), True)

    broken = os.path.join(base, "broken.jsonl")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("not json\n\n[]\n42\n{\"type\":\"assistant\"}\n")
        for entry in red:
            handle.write(json.dumps(entry) + "\n")
    expect("broken lines skipped", payload(edit_input(), broken), False)

    _, spot_out, _ = run(payload(edit_input()))
    checks += 1
    needles = ["verify", "VERIFY FAIL", "tdd_exempt:", "test_plan"]
    missing = [needle for needle in needles if needle not in spot_out]
    if missing:
        bad += 1
        print(f"SPOT FAIL missing={missing} -> {spot_out[:300]}")

    garbage = [
        "", "not json", "null", "[]", "5",
        json.dumps({"tool_name": "Edit", "agent_type": DEVELOPER}),
        json.dumps({"tool_name": "Edit", "agent_type": DEVELOPER, "tool_input": None}),
        json.dumps({"tool_name": "Edit", "agent_type": DEVELOPER, "tool_input": {"file_path": 42}}),
        json.dumps({"tool_name": "Bash", "agent_type": DEVELOPER, "tool_input": {"command": "ls"}}),
        json.dumps({"tool_name": "Edit", "agent_type": DEVELOPER, "tool_input": {"file_path": SOURCE},
                    "agent_transcript_path": 42}),
    ]
    for raw in garbage:
        checks += 1
        rc, out, err = run(None, raw)
        if not (rc == 0 and out == "" and not err):
            bad += 1
            print(f"garbage {raw[:60]!r} -> rc={rc} out={out[:80]!r} err={err[-160:]!r}")

print(f"hook: {hook}\nchecks: {checks}, slowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}")
print(("FAIL " if bad else "PASS ") + f"{checks - bad}/{checks}")
sys.exit(1 if bad else 0)
