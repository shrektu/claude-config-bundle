#!/usr/bin/env python3
"""Regression matrix for subagent-verify-check.py (the sibling file by default; pass another path as argv[1])."""
import json, os, subprocess, sys, tempfile, time

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "subagent-verify-check.py")
REASON_MARK = "subagent-verify-check:"


def use(name, data, use_id):
    return {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "tool_use", "id": use_id, "name": name, "input": data}]}}


def result(use_id, text):
    return {"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": use_id, "content": text}]}}


def edit(path, use_id="e1"):
    return [use("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}, use_id),
            result(use_id, "The file has been updated.")]


def write_tool(path, use_id="w1"):
    return [use("Write", {"file_path": path, "content": "x"}, use_id), result(use_id, "File created.")]


def notebook(path, use_id="n1"):
    return [use("NotebookEdit", {"notebook_path": path, "new_source": "x"}, use_id), result(use_id, "Updated.")]


def bash(command, output, use_id="b1"):
    return [use("Bash", {"command": command}, use_id), result(use_id, output)]


def transcript(base, name, entries):
    path = os.path.join(base, name)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return path


PASS_LOG = "VERIFY PASS exit=0 time=3s lines=20 cmd: pytest -q\nlog: /tmp/x.log"
FAIL_LOG = "VERIFY FAIL exit=1 time=3s lines=20 cmd: pytest -q\nlog: /tmp/x.log"
VERIFY_CMD = "~/.claude/bin/verify -- 'pytest -q'"

bad = 0


def check(label, condition, detail=""):
    global bad
    if not condition:
        bad += 1
        print(f"FAIL {label} {detail}")


def run(payload, timeout=30):
    done = subprocess.run(["python3", hook], input=json.dumps(payload), capture_output=True, text=True,
                          timeout=timeout)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def payload_for(base, path, **extra):
    data = {"hook_event_name": "SubagentStop", "session_id": "sess-1", "cwd": base,
            "scratchpad_dir": base, "agent_id": extra.pop("agent_id", "agent-" + os.path.basename(path)),
            "agent_type": "implementer", "agent_transcript_path": path}
    data.update(extra)
    return data


slowest = 0.0
with tempfile.TemporaryDirectory() as base:
    parent_clean = transcript(base, "parent-clean.jsonl", bash(VERIFY_CMD, PASS_LOG, "pb1"))
    parent_dirty = transcript(base, "parent-dirty.jsonl", edit("/repo/app.py", "pe1"))

    block_cases = {
        "verify then edit": transcript(base, "t-verify-then-edit.jsonl",
                                       bash(VERIFY_CMD, PASS_LOG, "b1") + edit("/repo/app.py", "e1")),
        "edit without verify": transcript(base, "t-edit-only.jsonl", edit("/repo/app.py", "e1")),
        "echoed verify": transcript(base, "t-echo.jsonl",
                                    edit("/repo/app.py", "e1") + bash('echo "verify -- pytest"', "verify -- pytest", "b1")),
        "verify without result": transcript(base, "t-no-result.jsonl",
                                            edit("/repo/app.py", "e1") + bash(VERIFY_CMD, "pytest ran fine", "b1")),
        "notebook edit": transcript(base, "t-notebook.jsonl", notebook("/repo/study.ipynb", "n1")),
        "write then doc verify": transcript(base, "t-write.jsonl",
                                            write_tool("/repo/new.py", "w1") + bash("pytest -q", "2 passed", "b1")),
        "missing agent_type": transcript(base, "t-no-type.jsonl", edit("/repo/app.py", "e1")),
        "agent transcript dirty": transcript(base, "t-agent-dirty.jsonl", edit("/repo/app.py", "e1")),
        "notebook_path only": transcript(base, "t-notebook-key.jsonl",
                                         notebook("/repo/study.ipynb", "n1")
                                         + bash("pytest -q", "2 passed", "b1")),
        "doc notebook then code write": transcript(base, "t-doc-then-code.jsonl",
                                                   notebook("/repo/notes.md", "n1")
                                                   + write_tool("/repo/app.py", "w1")),
        "xargs --eof hides no verify": transcript(base, "t-xargs-eof.jsonl",
                                                  edit("/repo/app.py", "e1")
                                                  + bash("xargs --eof pytest", "2 passed", "b1")),
        "second edit after verify": transcript(base, "t-second-edit.jsonl",
                                               edit("/repo/a.py", "e1") + bash(VERIFY_CMD, PASS_LOG, "b1")
                                               + edit("/repo/b.py", "e2")),
    }
    allow_cases = {
        "edit then verify": transcript(base, "a-edit-then-verify.jsonl",
                                       edit("/repo/app.py", "e1") + bash(VERIFY_CMD, PASS_LOG, "b1")),
        "edit then failing verify": transcript(base, "a-edit-then-fail.jsonl",
                                               edit("/repo/app.py", "e1") + bash(VERIFY_CMD, FAIL_LOG, "b1")),
        "bare verify name": transcript(base, "a-bare-verify.jsonl",
                                       edit("/repo/app.py", "e1") + bash("verify -- make test", PASS_LOG, "b1")),
        "verify inside bash -c": transcript(base, "a-bash-c.jsonl",
                                            edit("/repo/app.py", "e1")
                                            + bash('bash -c "verify -- pytest"', PASS_LOG, "b1")),
        "verify after chained cd": transcript(base, "a-chain.jsonl",
                                              edit("/repo/app.py", "e1")
                                              + bash("cd /repo && $HOME/.claude/bin/verify -- 'pytest -q'",
                                                     PASS_LOG, "b1")),
        "doc only edits": transcript(base, "a-docs.jsonl",
                                     edit("/repo/README.md", "e1") + write_tool("/repo/notes.txt", "w1")
                                     + edit("/repo/doc.rst", "e2")),
        "no edits at all": transcript(base, "a-noedit.jsonl", bash("git status", "clean", "b1")),
        "timeout wrapped verify": transcript(base, "a-timeout.jsonl",
                                             edit("/repo/app.py", "e1")
                                             + bash("timeout 60 ~/.claude/bin/verify -- pytest", PASS_LOG, "b1")),
        "env wrapped verify": transcript(base, "a-env.jsonl",
                                         edit("/repo/app.py", "e1")
                                         + bash("env CI=1 ~/.claude/bin/verify -- pytest", PASS_LOG, "b1")),
        "shell option before -c": transcript(base, "a-shell-opt.jsonl",
                                             edit("/repo/app.py", "e1")
                                             + bash('bash -o pipefail -c "verify -- pytest"', PASS_LOG, "b1")),
        "env -u wrapped verify": transcript(base, "a-env-unset.jsonl",
                                            edit("/repo/app.py", "e1")
                                            + bash("env -u CI ~/.claude/bin/verify -- pytest", PASS_LOG, "b1")),
        "nice -n wrapped verify": transcript(base, "a-nice.jsonl",
                                             edit("/repo/app.py", "e1")
                                             + bash("nice -n 10 ~/.claude/bin/verify -- pytest", PASS_LOG, "b1")),
        "timeout -k wrapped verify": transcript(base, "a-timeout-kill.jsonl",
                                                edit("/repo/app.py", "e1")
                                                + bash("timeout -k 5 60 verify -- pytest", PASS_LOG, "b1")),
        "long option value form": transcript(base, "a-long-opt.jsonl",
                                             edit("/repo/app.py", "e1")
                                             + bash("env --unset=CI verify -- pytest", PASS_LOG, "b1")),
        "sudo -u wrapped verify": transcript(base, "a-sudo.jsonl",
                                             edit("/repo/app.py", "e1")
                                             + bash("sudo -u builder verify -- 'make test'", PASS_LOG, "b1")),
        "ionice --class wrapped verify": transcript(base, "a-ionice.jsonl",
                                                    edit("/repo/app.py", "e1")
                                                    + bash("ionice --class 3 verify -- pytest", PASS_LOG, "b1")),
        "xargs --max-args wrapped verify": transcript(base, "a-xargs.jsonl",
                                                      edit("/repo/app.py", "e1")
                                                      + bash("xargs --max-args 1 verify -- pytest", PASS_LOG, "b1")),
        "stdbuf --output wrapped verify": transcript(base, "a-stdbuf.jsonl",
                                                     edit("/repo/app.py", "e1")
                                                     + bash("stdbuf --output L verify -- 'pytest -q'", PASS_LOG, "b1")),
        "xargs --replace wrapped verify": transcript(base, "a-xargs-replace.jsonl",
                                                     edit("/repo/app.py", "e1")
                                                     + bash("xargs --replace verify -- pytest", PASS_LOG, "b1")),
        "xargs --max-lines wrapped verify": transcript(base, "a-xargs-maxlines.jsonl",
                                                     edit("/repo/app.py", "e1")
                                                     + bash("xargs --max-lines verify -- pytest", PASS_LOG, "b1")),
        "xargs -I{} wrapped verify": transcript(base, "a-xargs-i.jsonl",
                                                edit("/repo/app.py", "e1")
                                                + bash("xargs -I{} verify -- pytest", PASS_LOG, "b1")),
        "notebook then verify": transcript(base, "a-notebook-verify.jsonl",
                                           notebook("/repo/study.ipynb", "n1")
                                           + bash(VERIFY_CMD, PASS_LOG, "b1")),
        "empty transcript": transcript(base, "a-empty.jsonl", []),
    }

    for label, path in block_cases.items():
        extra = {}
        if label == "missing agent_type":
            extra["agent_type"] = None
        if label == "agent transcript dirty":
            extra["transcript_path"] = parent_clean
        t0 = time.time()
        rc, out, err = run(payload_for(base, path, **extra))
        slowest = max(slowest, time.time() - t0)
        check(f"block[{label}]", rc == 2 and REASON_MARK in err and out == "",
              f"rc={rc} out={out[:80]!r} err={err[:160]!r}")

    for label, path in allow_cases.items():
        extra = {"transcript_path": parent_dirty} if label == "edit then verify" else {}
        t0 = time.time()
        rc, out, err = run(payload_for(base, path, **extra))
        slowest = max(slowest, time.time() - t0)
        check(f"allow[{label}]", rc == 0 and not out and not err, f"rc={rc} out={out[:80]!r} err={err[:160]!r}")

    dirty = block_cases["edit without verify"]
    rc1, _, err1 = run(payload_for(base, dirty, agent_id="once-agent"))
    rc2, _, err2 = run(payload_for(base, dirty, agent_id="once-agent"))
    check("one block per agent_id", rc1 == 2 and rc2 == 0 and not err2, f"rc1={rc1} rc2={rc2} err2={err2[:120]!r}")
    check("state file written", os.path.exists(os.path.join(base, "subagent-verify-check-once-agent")))

    rc, out, err = run(payload_for(base, dirty, agent_id="loop-agent", stop_hook_active=True))
    check("stop_hook_active", rc == 0 and not out and not err, f"rc={rc} err={err[:120]!r}")

    for other in ("Explore", "codex-runner", "general-purpose"):
        rc, out, err = run(payload_for(base, dirty, agent_id=f"other-{other}", agent_type=other))
        check(f"other agent_type[{other}]", rc == 0 and not out and not err, f"rc={rc} err={err[:120]!r}")

    rc, out, err = run(payload_for(base, dirty, agent_id="fallback-agent", scratchpad_dir="/nonexistent-dir-xyz"))
    check("missing scratchpad_dir still blocks once", rc == 2 and REASON_MARK in err, f"rc={rc} err={err[:120]!r}")
    try:
        os.remove(os.path.join("/tmp", "subagent-verify-check-fallback-agent"))
    except OSError:
        pass

    broken = os.path.join(base, "broken.jsonl")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("not json\n\n{\"type\":\"assistant\"}\n[]\n42\n")
        handle.write(json.dumps(use("Edit", {"file_path": "/repo/app.py"}, "e9")) + "\n")
    rc, out, err = run(payload_for(base, broken, agent_id="broken-agent"))
    check("broken lines still parsed", rc == 2 and REASON_MARK in err, f"rc={rc} err={err[:120]!r}")

    garbage = [
        "", "not json", "null", "[]", "17",
        json.dumps({"hook_event_name": "SubagentStop"}),
        json.dumps({"hook_event_name": "SubagentStop", "agent_transcript_path": "/nope/missing.jsonl",
                    "agent_type": "implementer"}),
        json.dumps({"hook_event_name": "SubagentStop", "agent_transcript_path": 42, "agent_type": 42}),
        json.dumps({"agent_transcript_path": os.path.join(base, "t-edit-only.jsonl"), "agent_type": "Explore"}),
    ]
    for raw in garbage:
        done = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=30)
        check("garbage", done.returncode == 0 and not done.stdout and not done.stderr,
              f"{raw[:50]!r} -> rc={done.returncode} out={done.stdout[:60]!r} err={done.stderr[-120:]!r}")

total = len(block_cases) + len(allow_cases) + len(garbage) + 9
print(f"hook: {hook}\nblock cases: {len(block_cases)}, allow cases: {len(allow_cases)}, "
      f"garbage: {len(garbage)}, slowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}")
print("FAIL" if bad else f"PASS {total}/{total}")
sys.exit(1 if bad else 0)
