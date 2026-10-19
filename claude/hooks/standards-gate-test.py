#!/usr/bin/env python3
"""Regression matrix for standards-gate.py (sibling file or argv[1])."""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HOOK = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(__file__).resolve().with_name("standards-gate.py")
)
HOOK_TIMEOUT = 60
EXECUTABLE_MODE = 0o755
READ_ONLY_MODE = 0o500
FAKE_REPORT = "a.py:3: E501 line too long\nLINT-STRICT FAIL (1)\n"
FIX_MARK = "standards-gate: fix every violation on the changed lines"
INTERACTIVE_MARK = "an interactive commit cannot be checked"
UNAVAILABLE_MARK = "standards-gate: lint-strict unavailable"
NUDGE_MARK = (
    "standards-gate: lint-strict found norm violations in the uncommitted"
    " changes of these repos. Fix every one in a file you created or"
    " changed; for a violation in a file you did not touch, do not edit"
    " it — list it in your report."
)
STATE_PREFIX = "standards-gate-"
MAX_BLOCKS = 3
REAL_LINT_STRICT = (
    Path(__file__).resolve().parents[2] / "stage-lint" / "bin" / "lint-strict"
)
BAD_SOURCE = "def f(a): return a\n"
BLOCK_EXIT = 2
INCLUDE_RUNS = 2
CAP_LINES = 60
LONG_REPORT_LINES = 100
FAKE_SOURCE = """
import json, os, sys, time
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
sys.stdout.write(os.environ.get("FAKE_STDOUT", ""))
sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
AI_FAKE_SOURCE = FAKE_SOURCE.replace("FAKE_", "AI_FAKE_")
AI_REPORT = "a.py:3 [naming] Rename x to retries. (id 0123456789)\n"


@dataclass(frozen=True)
class Outcome:
    rc: int
    stdout: str
    stderr: str
    calls: list[list[str]]
    ai_calls: list[list[str]]

    def reason(self) -> str:
        try:
            output = json.loads(self.stdout)
            specific = output["hookSpecificOutput"]
        except ValueError, KeyError, TypeError:
            return ""
        if specific.get("permissionDecision") != "deny":
            return ""
        return specific.get("permissionDecisionReason", "")

    def system_message(self) -> str:
        try:
            return json.loads(self.stdout).get("systemMessage", "")
        except ValueError, AttributeError:
            return ""


@dataclass
class Env:
    base: Path
    fake: Path
    log: Path
    ai_fake: Path
    ai_log: Path
    repo: Path
    sub: Path
    other: Path
    verify_repo: Path
    failures: list[str] = field(default_factory=list)
    total: int = 0

    def run(self, payload: object, **fake: str) -> Outcome:
        self.log.unlink(missing_ok=True)
        self.ai_log.unlink(missing_ok=True)
        env = dict(os.environ)
        env["LINT_STRICT_BIN"] = str(self.fake)
        env["FAKE_LOG"] = str(self.log)
        env["AI_REVIEW_GATE_BIN"] = str(self.ai_fake)
        env["AI_FAKE_LOG"] = str(self.ai_log)
        env.update(fake)
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        done = subprocess.run(
            [sys.executable, str(HOOK)],
            input=raw,
            capture_output=True,
            text=True,
            timeout=HOOK_TIMEOUT,
            env=env,
            check=False,
        )
        return Outcome(
            done.returncode,
            done.stdout,
            done.stderr,
            read_calls(self.log),
            read_calls(self.ai_log),
        )

    def check(self, name: str, condition: bool, detail: object = "") -> None:
        self.total += 1
        if not condition:
            self.failures.append(f"{name}: {detail}")


def read_calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
    ]


def write_fake(path: Path, source: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(EXECUTABLE_MODE)
    return path


def git_init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", str(path)], check=True, capture_output=True
    )
    return path.resolve()


def make_env(base: Path) -> Env:
    repo = git_init(base / "r")
    (repo / "pkg").mkdir()
    return Env(
        base=base,
        fake=write_fake(base / "fake-lint-strict", FAKE_SOURCE),
        log=base / "calls.jsonl",
        ai_fake=write_fake(base / "fake-ai-review-gate", AI_FAKE_SOURCE),
        ai_log=base / "ai-calls.jsonl",
        repo=repo,
        sub=git_init(repo / "sub"),
        other=git_init(base / "other"),
        verify_repo=git_init(base / "s"),
    )


def bash_payload(command: str, cwd: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
        "session_id": "sess",
        "transcript_path": "/nonexistent/t.jsonl",
    }


def staged(repo: Path) -> list[str]:
    return ["--repo", str(repo), "--staged"]


def tracked(repo: Path, *paths: str) -> list[str]:
    run = ["--repo", str(repo), "--tracked"]
    return [*run, "--paths", *paths] if paths else run


def argv_cases(env: Env) -> list[tuple[str, str, list[list[str]]]]:
    r = env.repo
    return [
        ("plain", 'git commit -m "x"', [staged(r)]),
        ("amend", "git commit --amend --no-edit", [staged(r)]),
        ("fixup sep", "git commit --fixup abc123", [staged(r)]),
        ("fixup eq", "git commit --fixup=abc123", [staged(r)]),
        ("signoff", 'git commit -s -m "a b"', [staged(r)]),
        ("all short", "git commit -a", [tracked(r)]),
        ("all combined", 'git commit -am "m"', [tracked(r)]),
        ("all long", "git commit --all -m m", [tracked(r)]),
        ("sam", "git commit -sam m", [tracked(r)]),
        ("asm", "git commit -asm m", [tracked(r)]),
        (
            "dashdash",
            "git commit -m m -- a.py b.py",
            [tracked(r, "a.py", "b.py")],
        ),
        ("positional", "git commit a.py", [tracked(r, "a.py")]),
        ("only", "git commit -m m -o a.py", [tracked(r, "a.py")]),
        ("only long", "git commit --only a.py -m m", [tracked(r, "a.py")]),
        (
            "include",
            "git commit -i a.py -m m",
            [staged(r), tracked(r, "a.py")],
        ),
        ("value F", "git commit -F msg.txt", [staged(r)]),
        ("value C", "git commit -C HEAD", [staged(r)]),
        ("value c", "git commit -c HEAD", [staged(r)]),
        ("value t", "git commit -t tmpl.txt", [staged(r)]),
        ("attached m", "git commit -mfoo", [staged(r)]),
        ("value author", 'git commit --author "A <a@b>" -m x', [staged(r)]),
        ("value date", "git commit --date now -m x", [staged(r)]),
        ("value cleanup", "git commit --cleanup strip -m x", [staged(r)]),
        ("value trailer", 'git commit --trailer "k: v" -m x', [staged(r)]),
        ("value squash", "git commit --squash abc", [staged(r)]),
        ("value file", "git commit --file msg.txt", [staged(r)]),
        ("value message", "git commit --message hello", [staged(r)]),
        ("reuse message", "git commit --reuse-message HEAD", [staged(r)]),
        ("reedit message", "git commit --reedit-message HEAD", [staged(r)]),
        ("template", "git commit --template t.txt", [staged(r)]),
        ("gpg attached", "git commit -Skey -m x", [staged(r)]),
        ("gpg eq", "git commit --gpg-sign=key -m x", [staged(r)]),
        ("absolute git", "/usr/bin/git commit -m x", [staged(r)]),
    ]


def segment_cases(env: Env) -> list[tuple[str, str, list[list[str]]]]:
    r = env.repo
    return [
        ("semicolon", "true; git commit -m x", [staged(r)]),
        ("and", "make && git commit -m x", [staged(r)]),
        ("or", "false || git commit -m x", [staged(r)]),
        ("pipe", "echo msg | git commit -F -", [staged(r)]),
        ("newline", "ls\ngit commit -m x", [staged(r)]),
        ("subshell", "(git commit -m x)", [staged(r)]),
        ("env wrapper", "env A=1 git commit -m x", [staged(r)]),
        ("nice wrapper", "nice -n 5 git commit -m x", [staged(r)]),
        ("timeout wrapper", "timeout 60 git commit -m x", [staged(r)]),
        ("bash -c", "bash -c 'git commit -m x'", [staged(r)]),
        ("config option", "git -c user.name=x commit -m y", [staged(r)]),
        ("env assignment", "GIT_DIR=x git commit -m y", [staged(r)]),
        ("no pager", "git --no-pager -P commit -m y", [staged(r)]),
        ("git dir eq", "git --git-dir=.git commit -m y", [staged(r)]),
        ("sudo wrapper", "sudo -u me git commit -m x", [staged(r)]),
        ("timeout signal", "timeout -s KILL 60 git commit -m x", [staged(r)]),
        ("quoted separator", 'git commit -m "a; git commit -p"', [staged(r)]),
        ("herestring", 'git commit -F - <<< "msg"', [staged(r)]),
        (
            "after heredoc",
            "cat <<EOF\nbody\nEOF\ngit commit -m x",
            [staged(r)],
        ),
        ("redirect out", "git commit -m x > out.txt", [staged(r)]),
        ("redirect attached", "git commit -m x >>log.txt", [staged(r)]),
        ("redirect stderr", "git commit -m x 2>/dev/null", [staged(r)]),
        ("redirect dup", "git commit -m x 2>&1 | tee log", [staged(r)]),
        ("herestring then heredoc", "git commit -F - <<< m\nls", [staged(r)]),
        ("empty dashdash", "git commit -m x --", [staged(r)]),
        ("no verify", "git commit --no-verify -m x", [staged(r)]),
        (
            "pathspec file eq",
            "git commit --pathspec-from-file=list.txt",
            [tracked(r)],
        ),
        (
            "pathspec file sep",
            "git commit --pathspec-from-file list.txt",
            [tracked(r)],
        ),
        (
            "pathspec file nul",
            "git commit --pathspec-from-file list.txt --pathspec-file-nul",
            [tracked(r)],
        ),
        (
            "pathspec file with message",
            "git commit -m msg --pathspec-from-file list.txt",
            [tracked(r)],
        ),
        (
            "pathspec file eq with message",
            "git commit --pathspec-from-file=list.txt -m msg",
            [tracked(r)],
        ),
        (
            "two commits",
            "git commit -m a; git commit -a",
            [staged(r), tracked(r)],
        ),
    ]


def repo_cases(env: Env) -> list[tuple[str, str, list[list[str]]]]:
    sub = env.sub
    other = env.other
    return [
        ("dash C relative", "git -C sub commit -m x", [staged(sub)]),
        ("dash C absolute", f"git -C {other} commit -m x", [staged(other)]),
        ("cd absolute", f"cd {other} && git commit -m x", [staged(other)]),
        ("cd relative", "cd sub && git commit -m x", [staged(sub)]),
        (
            "cd then dash C",
            f"cd {sub} && git -C ../../other commit -m x",
            [staged(other)],
        ),
        ("dash C parent", "git -C ../other commit -m x", [staged(other)]),
        ("last cd wins", f"cd sub; cd {other}; git commit", [staged(other)]),
        ("chained dash C", "git -C sub -C .. commit", [staged(env.repo)]),
        ("subshell cd", "(cd sub && git commit -m x)", [staged(sub)]),
        ("bash -c cd", "bash -c 'cd sub && git commit -m x'", [staged(sub)]),
        ("home dash C", "git -C ~ commit -m x", [staged(Path.home())]),
    ]


def default(repo: Path, *paths: str) -> list[str]:
    run = ["--repo", str(repo)]
    return [*run, "--paths", *paths] if paths else run


def add_cases(env: Env) -> list[tuple[str, str, list[list[str]]]]:
    r = env.repo
    return [
        (
            "add path",
            "git add bad.py && git commit -m x",
            [staged(r), default(r, "bad.py")],
        ),
        ("add all", "git add -A && git commit -m x", [staged(r), default(r)]),
        (
            "add all long",
            "git add --all && git commit -m x",
            [staged(r), default(r)],
        ),
        ("add dot", "git add . && git commit -m x", [staged(r), default(r)]),
        ("add root", "git add :/ && git commit -m x", [staged(r), default(r)]),
        (
            "add patch",
            "git add -p && git commit -m x",
            [staged(r), default(r)],
        ),
        ("add bare", "git add && git commit -m x", [staged(r), default(r)]),
        (
            "add pathspec file",
            "git add --pathspec-from-file list.txt && git commit -m x",
            [staged(r), default(r)],
        ),
        (
            "add update",
            "git add -u && git commit -m x",
            [staged(r), tracked(r)],
        ),
        (
            "add update paths",
            "git add --update a.py && git commit -m x",
            [staged(r), tracked(r, "a.py")],
        ),
        (
            "add in cd",
            "cd sub && git add x.py && git commit -m x",
            [staged(env.sub), default(env.sub, "x.py")],
        ),
        (
            "add other repo",
            "git -C ../other add y.py && git commit -m x",
            [staged(r)],
        ),
        (
            "add in subdir of same repo",
            "cd pkg && git add x.py && cd .. && git commit -m x",
            [staged(r), default(r / "pkg", "x.py")],
        ),
        (
            "add with unresolvable root",
            "git -C nowhere add z.py && git commit -m x",
            [staged(r), default(r / "nowhere", "z.py")],
        ),
        ("add after commit", "git commit -m x; git add later.py", [staged(r)]),
        (
            "add chmod",
            "git add --chmod=+x run.sh && git commit -m x",
            [staged(r), default(r, "run.sh")],
        ),
        (
            "add twice deduped",
            "git add a.py; git add a.py; git commit -am x",
            [tracked(r), default(r, "a.py")],
        ),
    ]


NOT_COMMITS = (
    "git commit-tree HEAD^{tree} -m x",
    "git commit-graph write",
    "git log --grep commit",
    'echo "git commit"',
    "echo git commit",
    'grep -r "git commit" .',
    "ls",
    "cat <<EOF\ngit commit -m x\nEOF",
    "cat <<-'END' > f.txt\n\tgit commit -a\n\tEND\necho done",
    "git status",
    'git commit -m "unbalanced',
    "python3 -c 'print(1)'",
    "git commit-msg",
    "cat <<'X'\ngit commit -a\nX",
    "echo '$(git commit)'",
)


def check_commit_matrix(env: Env) -> None:
    cases = [
        *argv_cases(env),
        *segment_cases(env),
        *repo_cases(env),
        *add_cases(env),
    ]
    for name, command, expected in cases:
        out = env.run(bash_payload(command, env.repo))
        env.check(
            f"argv {name}",
            out.rc == 0
            and out.stdout == ""
            and out.calls == expected
            and out.ai_calls == [],
            f"rc={out.rc} out={out.stdout[:80]!r} calls={out.calls}"
            f" ai={out.ai_calls}",
        )


def check_interactive(env: Env) -> None:
    for flag in ("-p", "--patch", "--interactive", "-sp"):
        out = env.run(bash_payload(f"git commit {flag}", env.repo))
        env.check(
            f"interactive {flag}",
            out.rc == 0 and INTERACTIVE_MARK in out.reason() and not out.calls,
            f"rc={out.rc} out={out.stdout[:120]!r} calls={out.calls}",
        )


def check_not_commits(env: Env) -> None:
    for command in NOT_COMMITS:
        out = env.run(bash_payload(command, env.repo), FAKE_EXIT="1")
        env.check(
            f"not commit {command!r}",
            out.rc == 0 and out.stdout == "" and not out.calls,
            f"rc={out.rc} out={out.stdout[:80]!r} calls={out.calls}",
        )
    out = env.run(bash_payload("echo hi", env.repo), LINT_STRICT_BIN="/x")
    env.check("fast path", out.rc == 0 and not out.stdout, out.stdout)


def check_deny_and_pass(env: Env) -> None:
    payload = bash_payload('git commit -m "x"', env.repo)
    out = env.run(payload, FAKE_EXIT="1", FAKE_STDOUT=FAKE_REPORT)
    reason = out.reason()
    env.check(
        "deny on violations",
        out.rc == 0 and FAKE_REPORT.rstrip() in reason and FIX_MARK in reason,
        f"rc={out.rc} out={out.stdout[:200]!r}",
    )
    out = env.run(payload, FAKE_EXIT="0", FAKE_STDOUT="clean\n")
    env.check(
        "pass silently",
        out.rc == 0 and out.stdout == "" and out.calls == [staged(env.repo)],
        f"rc={out.rc} out={out.stdout[:80]!r} calls={out.calls}",
    )
    include = bash_payload("git commit -i a.py -m m", env.repo)
    out = env.run(include, FAKE_EXIT="1", FAKE_STDOUT=FAKE_REPORT)
    env.check(
        "include deny runs both",
        FIX_MARK in out.reason() and len(out.calls) == INCLUDE_RUNS,
        f"out={out.stdout[:80]!r} calls={out.calls}",
    )


def check_fail_open(env: Env) -> None:
    payload = bash_payload("git commit -m x", env.repo)
    variants = {
        "exit 2": {"FAKE_EXIT": "2"},
        "timeout": {"FAKE_SLEEP": "5", "LINT_STRICT_TIMEOUT": "0.5"},
        "missing binary": {"LINT_STRICT_BIN": str(env.base / "nope")},
    }
    for name, extra in variants.items():
        out = env.run(payload, **extra)
        env.check(
            f"fail open {name}",
            out.rc == 0 and UNAVAILABLE_MARK in out.system_message(),
            f"rc={out.rc} out={out.stdout[:120]!r} err={out.stderr[-200:]!r}",
        )
    for raw in ("", "not json", "null", "[]", "17", '{"tool_name": "Bash"}'):
        out = env.run(raw)
        env.check(
            f"garbage {raw!r}",
            out.rc == 0 and not out.stdout and not out.calls,
            f"rc={out.rc} out={out.stdout[:80]!r} err={out.stderr[-120:]!r}",
        )
    other_tool = bash_payload("git commit -m x", env.repo)
    other_tool["tool_name"] = "Edit"
    out = env.run(other_tool, FAKE_EXIT="1")
    env.check("non-Bash tool ignored", out.rc == 0 and not out.calls)
    other_event = bash_payload("git commit -m x", env.repo)
    other_event["hook_event_name"] = "PostToolUse"
    out = env.run(other_event, FAKE_EXIT="1")
    env.check("other event ignored", out.rc == 0 and not out.calls)


def check_subagent_stop_skips_ai_gate(env: Env) -> None:
    for lint_exit in ("0", "1"):
        out = env.run(
            stop_payload(env, f"agent-ai-{lint_exit}"),
            FAKE_EXIT=lint_exit,
            AI_FAKE_EXIT="1",
        )
        env.check(
            f"subagent stop skips ai gate (lint exit {lint_exit})",
            out.calls and not out.ai_calls,
            f"calls={out.calls} ai={out.ai_calls}",
        )


def check_commit_clean_lint_passes_without_ai_gate(env: Env) -> None:
    payload = bash_payload('git commit -m "x"', env.repo)
    failing_ai = {
        "failing report": {"AI_FAKE_EXIT": "1", "AI_FAKE_STDOUT": AI_REPORT},
        "timeout": {"AI_FAKE_SLEEP": "5", "AI_REVIEW_GATE_TIMEOUT": "0.5"},
    }
    for name, extra in failing_ai.items():
        out = env.run(payload, **extra)
        env.check(
            f"commit_clean_lint_passes_without_ai_gate {name}",
            out.rc == 0
            and out.stdout == ""
            and out.calls == [staged(env.repo)]
            and out.ai_calls == [],
            f"rc={out.rc} out={out.stdout[:200]!r} ai={out.ai_calls}",
        )


def tool_use(name: str, data: dict[str, object]) -> str:
    block = {"type": "tool_use", "id": "u1", "name": name, "input": data}
    entry = {"type": "assistant", "message": {"content": [block]}}
    return json.dumps(entry)


def write_transcript(env: Env, name: str) -> Path:
    lines = [
        "this line is not json",
        tool_use("Edit", {"file_path": str(env.repo / "new" / "deep.py")}),
        tool_use(
            "Bash",
            {
                "command": (
                    f"~/.claude/bin/verify --repo {env.verify_repo}"
                    " -- 'pytest -q'"
                ),
            },
        ),
        "[]",
    ]
    path = env.base / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def stop_payload(
    env: Env, agent_id: str, **extra: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": "SubagentStop",
        "agent_type": "implementer",
        "agent_id": agent_id,
        "agent_transcript_path": str(write_transcript(env, "t.jsonl")),
        "transcript_path": "/nonexistent/main.jsonl",
        "cwd": str(env.other),
        "session_id": "sess",
        "scratchpad_dir": str(env.base),
    }
    payload.update(extra)
    return payload


def expected_stop_calls(env: Env) -> list[list[str]]:
    repos = (env.repo, env.verify_repo, env.other)
    return sorted(["--repo", str(repo)] for repo in repos)


def check_stop_blocks(env: Env) -> None:
    payload = stop_payload(env, "agent-a")
    for attempt in range(1, MAX_BLOCKS + 1):
        out = env.run(payload, FAKE_EXIT="1", FAKE_STDOUT=FAKE_REPORT)
        env.check(
            f"stop block {attempt}",
            out.rc == BLOCK_EXIT
            and NUDGE_MARK in out.stderr
            and FAKE_REPORT.rstrip() in out.stderr
            and sorted(out.calls) == expected_stop_calls(env),
            f"rc={out.rc} err={out.stderr[:160]!r} calls={out.calls}",
        )
    out = env.run(payload, FAKE_EXIT="1", FAKE_STDOUT=FAKE_REPORT)
    env.check(
        "stop after max blocks",
        out.rc == 0 and not out.calls and not out.stderr,
        f"rc={out.rc} calls={out.calls} err={out.stderr[:80]!r}",
    )


def check_stop_variants(env: Env) -> None:
    out = env.run(
        stop_payload(env, "agent-e", agent_type="Explore"), FAKE_EXIT="1"
    )
    env.check("explore ignored", out.rc == 0 and not out.calls, out.calls)
    out = env.run(stop_payload(env, "agent-c"), FAKE_EXIT="0")
    env.check(
        "clean stop",
        out.rc == 0
        and not out.stderr
        and sorted(out.calls) == expected_stop_calls(env),
        f"rc={out.rc} calls={out.calls}",
    )
    missing_type = stop_payload(env, "agent-m")
    del missing_type["agent_type"]
    out = env.run(missing_type, FAKE_EXIT="1", FAKE_STDOUT=FAKE_REPORT)
    env.check("missing agent_type blocks", out.rc == BLOCK_EXIT, out.rc)
    fallback = stop_payload(env, "agent-t", agent_transcript_path=None)
    fallback["transcript_path"] = str(write_transcript(env, "main.jsonl"))
    out = env.run(fallback, FAKE_EXIT="1")
    env.check(
        "transcript_path fallback",
        sorted(out.calls) == expected_stop_calls(env),
        out.calls,
    )
    long_report = "".join(f"v{n}\n" for n in range(1, LONG_REPORT_LINES + 1))
    out = env.run(
        stop_payload(env, "agent-l"), FAKE_EXIT="1", FAKE_STDOUT=long_report
    )
    env.check(
        "output capped",
        f"v{CAP_LINES}\n" in out.stderr
        and f"v{CAP_LINES + 1}\n" not in out.stderr,
        out.stderr[-120:],
    )


def check_stop_edges(env: Env) -> None:
    corrupt = env.base / f"{STATE_PREFIX}agent-g"
    corrupt.write_text("garbage", encoding="utf-8")
    out = env.run(stop_payload(env, "agent-g"), FAKE_EXIT="1")
    env.check("corrupt state counts as zero", out.rc == BLOCK_EXIT, out.rc)
    out = env.run(stop_payload(env, "agent-n", agent_type=42), FAKE_EXIT="1")
    env.check("non-string agent_type ignored", out.rc == 0 and not out.calls)
    out = env.run(stop_payload(env, "agent-u"), FAKE_EXIT="2")
    env.check("stop lint exit 2 allows", out.rc == 0 and not out.stderr)
    lines = [
        tool_use("NotebookEdit", {"notebook_path": str(env.sub / "n.ipynb")}),
        tool_use("Bash", {"command": "verify --repo=../s -- make"}),
        tool_use("Bash", {"command": "cd sub && ~/.claude/bin/verify -- x"}),
    ]
    path = env.base / "t-edge.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = stop_payload(env, "agent-x", cwd=str(env.repo))
    payload["agent_transcript_path"] = str(path)
    out = env.run(payload, FAKE_EXIT="0")
    expected = sorted(
        ["--repo", str(repo)] for repo in (env.sub, env.verify_repo, env.repo)
    )
    env.check(
        "notebook, repo= and relative repo",
        sorted(out.calls) == expected,
        out.calls,
    )


def check_real_lint_strict(env: Env) -> None:
    if not REAL_LINT_STRICT.is_file():
        print(f"SKIP real lint-strict: {REAL_LINT_STRICT} absent")
        return
    repo = git_init(env.base / "e2e")
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )
    (repo / "bad.py").write_text(BAD_SOURCE, encoding="utf-8")
    command = "git add bad.py && git commit -s -m change"
    payload = bash_payload(command, repo)
    out = env.run(payload, LINT_STRICT_BIN=str(REAL_LINT_STRICT))
    env.check(
        "real lint-strict denies add then commit",
        FIX_MARK in out.reason() and "bad.py" in out.reason(),
        f"rc={out.rc} out={out.stdout[:300]!r} err={out.stderr[-200:]!r}",
    )


def check_real_lint_strict_stop_mid_merge(env: Env) -> None:
    if not REAL_LINT_STRICT.is_file():
        print(f"SKIP real lint-strict mid-merge: {REAL_LINT_STRICT} absent")
        return
    repo = git_init(env.base / "e2e-merge")

    def git(*arguments: str) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.com",
                *arguments,
            ],
            check=True,
            capture_output=True,
        )

    (repo / "base.py").write_text("X = 1\n", encoding="utf-8")
    git("add", "base.py")
    git("commit", "-q", "-m", "init")
    git("switch", "-q", "-c", "incoming")
    (repo / "bad.py").write_text(BAD_SOURCE, encoding="utf-8")
    git("add", "bad.py")
    git("commit", "-q", "-m", "incoming")
    git("switch", "-q", "-")
    (repo / "ours.py").write_text("Y = 2\n", encoding="utf-8")
    git("add", "ours.py")
    git("commit", "-q", "-m", "ours")
    git("merge", "-q", "--no-commit", "--no-ff", "incoming")
    payload = stop_payload(env, f"agent-merge-{os.getpid()}", cwd=str(repo))
    out = env.run(payload, LINT_STRICT_BIN=str(REAL_LINT_STRICT))
    env.check(
        "real lint-strict stop does not block mid-merge",
        out.rc == 0,
        f"rc={out.rc} out={out.stdout[:300]!r} err={out.stderr[-200:]!r}",
    )


def check_stop_state_fallback(env: Env) -> None:
    locked = env.base / "locked"
    locked.mkdir()
    locked.chmod(READ_ONLY_MODE)
    agent_id = f"agent-ro-{os.getpid()}"
    marker = Path(tempfile.gettempdir()) / f"{STATE_PREFIX}{agent_id}"
    try:
        payload = stop_payload(env, agent_id, scratchpad_dir=str(locked))
        out = env.run(payload, FAKE_EXIT="1")
        env.check(
            "unwritable state dir falls back",
            out.rc == BLOCK_EXIT and marker.exists(),
            f"rc={out.rc} marker={marker.exists()}",
        )
    finally:
        marker.unlink(missing_ok=True)
        locked.chmod(EXECUTABLE_MODE)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw_base:
        env = make_env(Path(raw_base).resolve())
        check_commit_matrix(env)
        check_interactive(env)
        check_not_commits(env)
        check_deny_and_pass(env)
        check_fail_open(env)
        check_subagent_stop_skips_ai_gate(env)
        check_commit_clean_lint_passes_without_ai_gate(env)
        check_stop_blocks(env)
        check_stop_variants(env)
        check_stop_edges(env)
        check_real_lint_strict(env)
        check_real_lint_strict_stop_mid_merge(env)
        check_stop_state_fallback(env)
    for failure in env.failures:
        print(f"FAIL {failure}")
    if env.failures:
        print(f"FAIL {len(env.failures)}/{env.total}")
        return 1
    print(f"{env.total}/{env.total} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
