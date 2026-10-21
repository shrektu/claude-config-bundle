#!/usr/bin/env python3
"""Regression matrix for tdd-guard.py (the sibling file by default; pass another path as argv[1]).

Builds a throw-away projects root, ledger and transcripts under a temporary directory, feeds JSON
payloads to the hook through subprocess and reports PASS n/total."""
import datetime
import json
import os
import shutil
import subprocess
import time
import sys
import tempfile

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "tdd-guard.py")

SESSION = "session-under-test"
OTHER_SESSION = "some-other-session"
AGENT = "agent-under-test"
LEDGER_NAME = "ledger.jsonl"
SESSIONS_DIR = "sessions"
MARKER_AGE_MINUTES = 10
STALE_RED_AGE_MINUTES = 60

sandbox = tempfile.mkdtemp(prefix="tdd-guard-test-")
projects = os.path.join(sandbox, "projects")
log_dir = os.path.join(sandbox, "logs")
scratch = os.path.join(sandbox, "scratch")
outside = os.path.join(sandbox, "outside")
ledger_path = os.path.join(log_dir, LEDGER_NAME)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def make_repo(name, files):
    root = os.path.join(projects, name)
    os.makedirs(os.path.join(root, ".git"), exist_ok=True)
    for relative, text in files.items():
        write(os.path.join(root, relative), text)
    return root


pyrepo = make_repo("pyrepo", {
    "pyproject.toml": "[project]\nname = 'x'\n\n[tool.pytest.ini_options]\naddopts = '-q'\n",
    "src/app.py": "value = 1\n",
    "src/notes.md": "notes\n",
    "src/config.json": "{}\n",
    "tests/test_app.py": "def test_x():\n    assert True\n",
    "src/app_test.py": "def test_y():\n    assert True\n",
})
tsrepo = make_repo("tsrepo", {
    "package.json": json.dumps({"name": "x", "scripts": {"test": "vitest run"}}) + "\n",
    "src/app.ts": "export const value = 1;\n",
    "src/app.test.ts": "test('x', () => {});\n",
    "src/widget.tsx": "export const W = () => null;\n",
    "__tests__/helper.ts": "export const helper = 1;\n",
})
gorepo = make_repo("gorepo", {
    "go.mod": "module example.com/x\n\ngo 1.22\n",
    "main.go": "package main\n",
    "main_test.go": "package main\n",
})
rsrepo = make_repo("rsrepo", {
    "Cargo.toml": "[package]\nname = 'x'\nversion = '0.1.0'\n",
    "src/lib.rs": "pub fn value() -> u8 { 1 }\n",
    "tests/it.rs": "#[test]\nfn works() {}\n",
})
crepo = make_repo("crepo", {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nenable_testing()\nadd_test(NAME x COMMAND x)\n",
    "src/main.c": "int main(void) { return 0; }\n",
    "tests/test_main.c": "int test_main(void) { return 0; }\n",
})
zephyr = make_repo("zephyr", {
    "tests/CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nenable_testing()\nadd_test(NAME unit COMMAND unit)\n",
    "app/main.c": "int main(void) { return 0; }\n",
    "drivers/spi.h": "void spi_init(void);\n",
})
bare = make_repo("bare", {
    "Makefile": "all:\n\tgcc -o x src/main.c\n",
    "src/app.py": "value = 1\n",
    "src/main.c": "int main(void) { return 0; }\n",
})
write(os.path.join(outside, "app.py"), "value = 1\n")
claude_file = os.path.join(os.path.expanduser("~"), ".claude", "hooks", "tdd-guard.py")
os.makedirs(scratch, exist_ok=True)
os.makedirs(log_dir, exist_ok=True)


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def stamp(delta_minutes=0):
    return (now() + datetime.timedelta(minutes=delta_minutes)).isoformat()


def transcript(messages, name):
    lines = []
    for role, text in messages:
        lines.append(json.dumps({"type": role, "message": {"role": role, "content": text}}))
    return write(os.path.join(sandbox, name), "\n".join(lines) + "\n")


plain_transcript = transcript([("user", "implement the thing"), ("assistant", "ok")], "plain.jsonl")
first_exception = transcript(
    [("user", "TDD-EXCEPTION: spike, no tests"), ("assistant", "ok")], "first-exception.jsonl")
late_exception = transcript(
    [("user", "implement the thing"), ("assistant", "ok"), ("user", "TDD-EXCEPTION: let me through")],
    "late-exception.jsonl")
missing_transcript = os.path.join(sandbox, "there-is-no-such-transcript.jsonl")


def entry(repo, outcome="red", session=SESSION, minutes=0, cmd="uv run pytest -q"):
    return {"schema": 1, "ts": stamp(minutes), "rc": 1, "outcome": outcome, "repo": repo,
            "cmd": cmd, "log": os.path.join(log_dir, "some-run.log"), "session_id": session,
            "slug": "pytest"}


def set_ledger(*entries):
    if entries and entries[0] is None:
        try:
            os.unlink(ledger_path)
        except FileNotFoundError:
            pass
        return
    with open(ledger_path, "w", encoding="utf-8") as handle:
        for item in entries:
            handle.write(item if isinstance(item, str) else json.dumps(item))
            handle.write("\n")


def set_marker(minutes=-MARKER_AGE_MINUTES):
    directory = os.path.join(log_dir, SESSIONS_DIR)
    os.makedirs(directory, exist_ok=True)
    write(os.path.join(directory, SESSION + ".json"),
          json.dumps({"session_id": SESSION, "started_at": stamp(minutes)}))


def reset():
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    set_marker()
    set_ledger(entry(pyrepo, outcome="green"))


def payload(tool, tool_input, cwd=None, transcript_path=None, scratchpad=scratch, session=SESSION):
    body = {"tool_name": tool, "tool_input": tool_input, "session_id": session, "agent_id": AGENT,
            "cwd": cwd or sandbox, "transcript_path": transcript_path or plain_transcript}
    if scratchpad is not None:
        body["scratchpad_dir"] = scratchpad
    return body


def edit(path, tool="Edit", **kwargs):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return payload(tool, {key: path, "new_string": "value = 2\n", "old_string": "value = 1\n"}, **kwargs)


def bash(command, cwd=None, **kwargs):
    return payload("Bash", {"command": command}, cwd=cwd, **kwargs)


def run(body, env=None):
    text = body if isinstance(body, str) else json.dumps(body)
    return subprocess.run([sys.executable, hook], input=text, capture_output=True, text=True,
                          env={**os.environ, "CLAUDE_TDD_PROJECTS_ROOT": projects,
                               "CLAUDE_VERIFY_LOG_DIR": log_dir, **(env or {})})


def denies(proc):
    if '"deny"' not in proc.stdout:
        return False
    block = json.loads(proc.stdout)["hookSpecificOutput"]
    return (block.get("hookEventName") == "PreToolUse"
            and block.get("permissionDecision") == "deny"
            and "tdd-guard" in block.get("permissionDecisionReason", ""))


bad = 0
checks = 0


def expect_deny(body, label, prepare=None):
    global bad, checks
    checks += 1
    reset()
    if prepare:
        prepare()
    proc = run(body() if callable(body) else body)
    if not (proc.returncode == 0 and denies(proc) and proc.stderr == ""):
        bad += 1
        print(f"DENY FAIL ({label}): rc={proc.returncode} out={proc.stdout[:200]!r} err={proc.stderr[:200]!r}")


def expect_allow(body, label, prepare=None):
    global bad, checks
    checks += 1
    reset()
    if prepare:
        prepare()
    proc = run(body() if callable(body) else body)
    if not (proc.returncode == 0 and proc.stdout.strip() == "" and proc.stderr == ""):
        bad += 1
        print(f"ALLOW FAIL ({label}): rc={proc.returncode} out={proc.stdout[:200]!r} err={proc.stderr[:200]!r}")


production = os.path.join(pyrepo, "src/app.py")

expect_deny(edit(production), "first edit of production code without a red run")
expect_deny(edit(production, tool="Write"), "Write is gated too")
expect_deny(edit(os.path.join(tsrepo, "src/app.ts"), tool="Write"), "typescript production file")
expect_deny(edit(os.path.join(gorepo, "main.go")), "go production file")
expect_deny(edit(os.path.join(rsrepo, "src/lib.rs")), "rust production file")
expect_deny(edit(os.path.join(crepo, "src/main.c")), "c file in a repo with enable_testing()")
expect_deny(edit(os.path.join(pyrepo, "src/app.py"), tool="NotebookEdit"), "NotebookEdit is gated too")

expect_deny(bash("sed -i 's/1/2/' src/app.py", cwd=pyrepo), "sed -i")
expect_deny(bash("sed --in-place 's/1/2/' src/app.py", cwd=pyrepo), "sed --in-place")
expect_deny(bash("perl -i -pe 's/1/2/' src/app.py", cwd=pyrepo), "perl -i")
expect_deny(bash("echo value = 2 | tee src/app.py", cwd=pyrepo), "tee")
expect_deny(bash("echo value = 2 | tee -a src/app.py", cwd=pyrepo), "tee -a")
expect_deny(bash("echo value = 2 > src/app.py", cwd=pyrepo), "redirect")
expect_deny(bash("echo value = 2 >> src/app.py", cwd=pyrepo), "appending redirect")
expect_deny(bash("cat > src/app.py <<'EOF'\nvalue = 2\nEOF", cwd=pyrepo), "heredoc")
expect_deny(bash("cp /etc/hostname src/app.py", cwd=pyrepo), "cp")
expect_deny(bash("mv /etc/hostname src/app.py", cwd=pyrepo), "mv")
expect_deny(bash("install -m 644 /etc/hostname src/app.py", cwd=pyrepo), "install")
expect_deny(bash("dd if=/dev/null of=src/app.py", cwd=pyrepo), "dd of=")
expect_deny(bash("truncate -s 0 src/app.py", cwd=pyrepo), "truncate")
expect_deny(bash("python3 -c \"open('src/app.py','w').write('value = 2')\"", cwd=pyrepo),
            "python3 -c with open for writing")
expect_deny(bash(f"cd {pyrepo} && echo value = 2 > src/app.py"), "leading cd sets the base directory")

patch_file = write(os.path.join(pyrepo, "changes.patch"),
                   "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n")
expect_deny(bash(f"patch -p1 -i {patch_file}", cwd=pyrepo), "patch -i")
expect_deny(bash(f"patch -p1 < {patch_file}", cwd=pyrepo), "patch with a redirected patch file")

expect_deny(edit(production), "red run recorded for another repo",
            prepare=lambda: set_ledger(entry(tsrepo)))
expect_deny(edit(production), "red run recorded for another session",
            prepare=lambda: set_ledger(entry(pyrepo, session=OTHER_SESSION)))
expect_deny(edit(production), "verify -- false classified as error",
            prepare=lambda: set_ledger(entry(pyrepo, outcome="error", cmd="false")))
expect_deny(edit(production), "unknown command classified as error",
            prepare=lambda: set_ledger(entry(pyrepo, outcome="error", cmd="pytst -q")))
expect_deny(edit(production), "pytest collection error classified as error",
            prepare=lambda: set_ledger(entry(pyrepo, outcome="error", cmd="uv run pytest -q")))
expect_deny(edit(production), "green run does not unlock",
            prepare=lambda: set_ledger(entry(pyrepo, outcome="green")))
expect_deny(edit(production), "red run older than the session marker",
            prepare=lambda: set_ledger(entry(pyrepo, minutes=-STALE_RED_AGE_MINUTES)))
expect_deny(edit(production), "no ledger file at all", prepare=lambda: set_ledger(None))
expect_deny(edit(production, transcript_path=late_exception),
            "TDD-EXCEPTION outside the first user message")

expect_allow(edit(os.path.join(pyrepo, "tests/test_app.py")), "python test under tests/")
expect_allow(edit(os.path.join(pyrepo, "src/app_test.py")), "python test by name")
expect_allow(edit(os.path.join(tsrepo, "src/app.test.ts")), "typescript test by name")
expect_allow(edit(os.path.join(tsrepo, "__tests__/helper.ts")), "typescript test directory")
expect_allow(edit(os.path.join(gorepo, "main_test.go")), "go test file")
expect_allow(edit(os.path.join(rsrepo, "tests/it.rs")), "rust integration test")
expect_allow(edit(os.path.join(crepo, "tests/test_main.c")), "c test file")
expect_allow(edit(os.path.join(pyrepo, "src/notes.md")), "markdown is not code")
expect_allow(edit(os.path.join(pyrepo, "src/config.json")), "json is not code")
expect_allow(edit(os.path.join(outside, "app.py")), "path outside the projects root")
expect_allow(edit(claude_file), "path under ~/.claude")
expect_allow(edit(os.path.join(bare, "src/app.py")), "repo with no detectable harness")
expect_allow(edit(os.path.join(bare, "src/main.c")), "c file in a repo with no harness")
expect_allow(edit(production, transcript_path=first_exception),
             "TDD-EXCEPTION in the first user message")
expect_allow(bash("grep -n value src/app.py", cwd=pyrepo), "reading is not writing")
expect_allow(bash("python3 -m pytest -q src/app.py", cwd=pyrepo), "an unrecognised bash form")
expect_allow(bash("cat src/app.py | wc -l", cwd=pyrepo), "a pipeline that writes nothing")
expect_allow(bash('sed -i \'s/1/2/\' "$TARGET_FILE"', cwd=pyrepo), "unexpanded variable in sed")
expect_allow(bash('cp /etc/hostname "$DEST/app.py"', cwd=pyrepo), "unexpanded variable in cp")
expect_allow(bash("echo hi > /dev/null", cwd=pyrepo), "redirect to a file outside the projects root")
expect_allow(edit(production), "a red run in this session unlocks the repo",
             prepare=lambda: set_ledger(entry(pyrepo)))
expect_allow(edit(os.path.join(pyrepo, "src/other.py")),
             "a red run also covers a corrupt ledger line",
             prepare=lambda: set_ledger("{broken json", entry(pyrepo)))
expect_allow(edit(production, transcript_path=missing_transcript), "unreadable transcript fails open")
expect_deny(edit(production, scratchpad=None),
            "tdd-guard-missing-scratchpad-disables-gate: no scratchpad_dir still denies",
            prepare=lambda: set_ledger(None))
expect_allow(edit(production, scratchpad=None),
             "tdd-guard-missing-scratchpad-disables-gate: no scratchpad_dir still honours a red run",
             prepare=lambda: set_ledger(entry(pyrepo)))


checks += 1
reset()
proc = run(edit(production))
reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if proc.stdout else ""
if pyrepo not in reason or "verify" not in reason:
    bad += 1
    print(f"REASON FAIL: {reason[:300]!r}")

RELATIVE_CD_FORMS = (
    ("echo value = 2 > src/app.py", "redirect"),
    ("echo value = 2 >> src/app.py", "appending redirect"),
    ("cat > src/app.py <<'EOF'\nvalue = 2\nEOF", "heredoc"),
    ("sed -i 's/1/2/' src/app.py", "sed -i"),
    ("perl -i -pe 's/1/2/' src/app.py", "perl -i"),
    ("echo value = 2 | tee src/app.py", "tee"),
    ("cp /etc/hostname src/app.py", "cp"),
    ("mv /etc/hostname src/app.py", "mv"),
    ("install -m 644 /etc/hostname src/app.py", "install"),
    ("dd if=/dev/null of=src/app.py", "dd of="),
    ("truncate -s 0 src/app.py", "truncate"),
    ("patch -p1 -i changes.patch", "patch"),
    ("python3 -c \"open('src/app.py','w').write('value = 2')\"", "python3 -c open for writing"),
)
for command, form in RELATIVE_CD_FORMS:
    expect_deny(bash(f"cd pyrepo && {command}", cwd=projects),
                f"tdd-guard-relative-cd-bypass: {form}")

expect_deny(edit(os.path.join(zephyr, "app/main.c")),
            "tdd-guard-tests-lookaside: c under app/ in a zephyr layout")
expect_deny(edit(os.path.join(zephyr, "drivers/spi.h")),
            "tdd-guard-tests-lookaside: header beside the sources")
expect_allow(edit(os.path.join(zephyr, "tests/main_test.c")),
             "tdd-guard-tests-lookaside: the test itself stays open")
expect_allow(edit(os.path.join(bare, "src/main.c")),
             "tdd-guard-tests-lookaside: no marker anywhere is still not gated")

REAL_PROBE_CANDIDATES = ("device-sw1191/app.py", "device-sw86/app.py", "device-dispense/app.py",
                         "device-rs485/app.py")
DEFAULT_PROJECTS_ROOT = "__HOME__/projects"
real_probe = next((os.path.join(DEFAULT_PROJECTS_ROOT, candidate) for candidate in REAL_PROBE_CANDIDATES
                   if os.path.isfile(os.path.join(DEFAULT_PROJECTS_ROOT, candidate))), None)
if real_probe is None:
    print("PROBE SKIP: no known gated repository under the projects root")
else:
    checks += 1
    reset()
    set_ledger(None)
    default_root = run(edit(real_probe), env={"CLAUDE_TDD_PROJECTS_ROOT": DEFAULT_PROJECTS_ROOT})
    stale_root = run(edit(real_probe), env={"CLAUDE_TDD_PROJECTS_ROOT": "/nonexistent-projects-root-xyz"})
    if not (denies(default_root) and denies(stale_root)):
        bad += 1
        print("ROOT FALLBACK FAIL (tdd-guard-unvalidated-projects-root): "
              f"default={default_root.stdout[:120]!r} stale={stale_root.stdout[:120]!r}")

import importlib.util

spec = importlib.util.spec_from_file_location("tdd_guard_under_test", hook)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
os.environ["CLAUDE_TDD_PROJECTS_ROOT"] = projects
os.environ["CLAUDE_VERIFY_LOG_DIR"] = log_dir


def unit(label, call, want):
    global bad, checks
    checks += 1
    try:
        got = call()
    except Exception as error:
        got = f"{type(error).__name__}: {error}"
    if got != want:
        bad += 1
        print(f"UNIT FAIL ({label}): got {got!r}, wanted {want!r}")


def with_root(root, call):
    def run_with_root():
        os.environ["CLAUDE_TDD_PROJECTS_ROOT"] = root
        try:
            return call()
        finally:
            os.environ["CLAUDE_TDD_PROJECTS_ROOT"] = projects
    return run_with_root


unit("tdd-guard-missing-scratchpad-disables-gate: unit, no key",
     lambda: guard.state_directory({}), guard.FALLBACK_STATE_DIR)
unit("tdd-guard-missing-scratchpad-disables-gate: unit, empty key",
     lambda: guard.state_directory({"scratchpad_dir": ""}), guard.FALLBACK_STATE_DIR)
unit("tdd-guard-missing-scratchpad-disables-gate: unit, usable key",
     lambda: guard.state_directory({"scratchpad_dir": scratch}), scratch)
for command, form in RELATIVE_CD_FORMS:
    unit(f"tdd-guard-relative-cd-bypass: unit, {form}",
         lambda command=command: guard.bash_targets(f"cd pyrepo && {command}", projects),
         [os.path.join(projects, "pyrepo", "src/app.py")])
unit("tdd-guard-unvalidated-projects-root: unit, stale value falls back",
     with_root("/nonexistent-projects-root-xyz", guard.projects_root),
     os.path.realpath(DEFAULT_PROJECTS_ROOT))
unit("tdd-guard-unvalidated-projects-root: unit, usable value is honoured",
     guard.projects_root, os.path.realpath(projects))
unit("tdd-guard-tests-lookaside: unit, zephyr layout is gated",
     lambda: guard.gated_repo(os.path.join(zephyr, "app/main.c")), zephyr)
unit("tdd-guard-tests-lookaside: unit, no marker anywhere",
     lambda: guard.gated_repo(os.path.join(bare, "src/main.c")), None)

STALE_MARKER_AGE_SECONDS = 60 * 60 * 24 * 30
OLD_MARKER_MINUTES = -60


def marker_path(session=SESSION, repo=None):
    return guard.state_path(scratch, {"agent_id": AGENT, "session_id": session}, repo or pyrepo)


def put_marker(content, session=SESSION, repo=None):
    write(marker_path(session, repo), content)


def valid_marker(repo=None, minutes=0):
    return json.dumps({"session_id": SESSION, "repo": repo or pyrepo, "created_at": stamp(minutes)})


expect_deny(edit(production, session=OTHER_SESSION),
            "tdd-guard-marker-crosses-sessions: another session sharing the agent id",
            prepare=lambda: (put_marker(valid_marker()), set_ledger(None)))
expect_deny(edit(production),
            "tdd-guard-marker-crosses-sessions: a marker created before the session start",
            prepare=lambda: (put_marker(valid_marker(minutes=OLD_MARKER_MINUTES)), set_ledger(None)))
expect_deny(edit(production),
            "tdd-guard-marker-crosses-sessions: a marker naming another repo",
            prepare=lambda: (put_marker(valid_marker(repo=tsrepo)), set_ledger(None)))
expect_deny(edit(production),
            "tdd-guard-marker-crosses-sessions: a corrupt marker denies instead of failing open",
            prepare=lambda: (put_marker("not json at all"), set_ledger(None)))
expect_allow(edit(production),
             "tdd-guard-marker-crosses-sessions: a valid marker unlocks without the ledger",
             prepare=lambda: (put_marker(valid_marker()), set_ledger(None)))

checks += 1
reset()
ancient = write(os.path.join(scratch, "tdd-guard-ancient-marker"), valid_marker())
recent = write(os.path.join(scratch, "tdd-guard-recent-marker"), valid_marker())
os.utime(ancient, (0, time.time() - STALE_MARKER_AGE_SECONDS))
set_ledger(entry(pyrepo))
run(edit(production))
if os.path.exists(ancient) or not os.path.exists(recent):
    bad += 1
    print("MARKER RETENTION FAIL (tdd-guard-marker-crosses-sessions): "
          f"ancient={os.path.exists(ancient)} recent={os.path.exists(recent)}")

unit("tdd-guard-marker-crosses-sessions: unit, the name carries both identities",
     lambda: (AGENT in os.path.basename(marker_path()),
              SESSION in os.path.basename(marker_path())), (True, True))
unit("tdd-guard-marker-crosses-sessions: unit, a corrupt marker is not a marker",
     lambda: guard.read_marker(write(os.path.join(sandbox, "corrupt-marker"), "{nope")), None)
unit("tdd-guard-marker-crosses-sessions: unit, another repo is rejected",
     lambda: guard.marker_accepted(
         write(os.path.join(sandbox, "other-repo-marker"), valid_marker(repo=tsrepo)),
         SESSION, pyrepo, guard.EPOCH), False)
unit("tdd-guard-marker-crosses-sessions: unit, another session is rejected",
     lambda: guard.marker_accepted(
         write(os.path.join(sandbox, "other-session-marker"), valid_marker()),
         OTHER_SESSION, pyrepo, guard.EPOCH), False)
unit("tdd-guard-marker-crosses-sessions: unit, a marker older than the session start is rejected",
     lambda: guard.marker_accepted(
         write(os.path.join(sandbox, "old-marker"), valid_marker(minutes=OLD_MARKER_MINUTES)),
         SESSION, pyrepo, guard.parse_timestamp(stamp(-MARKER_AGE_MINUTES))), False)
unit("tdd-guard-marker-crosses-sessions: unit, a current marker is accepted",
     lambda: guard.marker_accepted(
         write(os.path.join(sandbox, "good-marker"), valid_marker()),
         SESSION, pyrepo, guard.parse_timestamp(stamp(-MARKER_AGE_MINUTES))), True)

checks += 1
reset()
set_ledger(entry(pyrepo))
first = run(edit(production))
set_ledger(None)
second = run(edit(production))
if not (first.stdout.strip() == "" and second.stdout.strip() == ""):
    bad += 1
    print("UNLOCK STATE FAIL (tdd-guard-marker-crosses-sessions: the second edit reuses the marker): "
          f"first={first.stdout[:160]!r} second={second.stdout[:160]!r}")

for raw in ("", "null", "[]", "{", '{"tool_name": 42}', '{"tool_name": "Edit"}',
            '{"tool_name": "Edit", "tool_input": {"file_path": 7}}',
            '{"tool_name": "Bash", "tool_input": {"command": null}}'):
    checks += 1
    proc = run(raw)
    if not (proc.returncode == 0 and proc.stdout.strip() == "" and proc.stderr == ""):
        bad += 1
        print(f"GARBAGE FAIL {raw!r}: rc={proc.returncode} out={proc.stdout[:150]!r} err={proc.stderr[:150]!r}")

shutil.rmtree(sandbox, ignore_errors=True)
print(f"hook: {hook}\nchecks: {checks}")
print(f"{'FAIL' if bad else 'PASS'} {checks - bad}/{checks}")
sys.exit(1 if bad else 0)
