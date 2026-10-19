#!/usr/bin/env python3
"""Regression matrix for payload-probe.py (the sibling file by default; pass another path as argv[1])."""
import json, subprocess, os, sys, tempfile

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload-probe.py")
CODEX = "mcp__codex-worker__codex_review_changes"


def run(raw, log):
    proc = subprocess.run([sys.executable, hook], input=raw, capture_output=True, text=True,
                          env={**os.environ, "PROBE_LOG": log})
    lines = []
    if os.path.exists(log):
        lines = [json.loads(line) for line in open(log) if line.strip()]
    return proc, lines


bad = 0
with tempfile.TemporaryDirectory() as tmp:
    log = os.path.join(tmp, "nested", "payload.log")

    payload = {"hook_event_name": "PreToolUse", "tool_name": CODEX, "agent_type": "codex-runner",
               "agent_id": "a41b0d4bd296103f3", "transcript_path": "/p/s.jsonl",
               "tool_input": {"command": "secret --token abc123"}}
    proc, lines = run(json.dumps(payload), log)
    if proc.returncode != 0 or proc.stdout != "" or proc.stderr != "":
        bad += 1
        print(f"SILENCE FAIL: rc={proc.returncode} out={proc.stdout[:120]!r} err={proc.stderr[:120]!r}")
    if len(lines) != 1:
        bad += 1
        print(f"RECORD FAIL: expected 1 record, got {len(lines)}")
    else:
        rec = lines[0]
        for field in ("hook_event_name", "tool_name", "agent_type", "agent_id", "transcript_path"):
            if rec.get(field) != payload[field]:
                bad += 1
                print(f"FIELD FAIL {field}: {rec.get(field)!r}")
        if "tool_input" in rec or "tool_input" in rec.get("keys", []):
            bad += 1
            print("LEAK FAIL: tool_input reached the log")
        if "secret" in json.dumps(rec) or "abc123" in json.dumps(rec):
            bad += 1
            print("LEAK FAIL: tool input content reached the log")
        if rec.get("keys") != sorted(k for k in payload if k != "tool_input"):
            bad += 1
            print(f"KEYS FAIL: {rec.get('keys')!r}")

    proc, lines = run(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash"}), log)
    if proc.returncode != 0 or len(lines) != 2:
        bad += 1
        print(f"APPEND FAIL: rc={proc.returncode} records={len(lines)}")

    for raw in ("", "null", "[]", "{", '{"tool_name": 42}', "not json at all"):
        proc, _ = run(raw, log)
        if proc.returncode != 0 or proc.stdout != "" or proc.stderr != "":
            bad += 1
            print(f"GARBAGE FAIL {raw!r}: rc={proc.returncode} out={proc.stdout[:100]!r} err={proc.stderr[:100]!r}")

    unwritable = "/proc/cannot/write/here.log"
    proc, _ = run(json.dumps({"tool_name": "Bash"}), unwritable)
    if proc.returncode != 0 or proc.stdout != "" or proc.stderr != "":
        bad += 1
        print(f"UNWRITABLE FAIL: rc={proc.returncode} out={proc.stdout[:100]!r} err={proc.stderr[:100]!r}")

print(f"hook: {hook}")
print(f"{'FAIL' if bad else 'PASS'} — {bad} failure(s)")
sys.exit(1 if bad else 0)
