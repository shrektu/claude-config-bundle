#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "context-guard.py")
TAIL_BYTES = 512 * 1024
HOOK_TIMEOUT_SECONDS = 15
OVER = 600000
USER_PROMPT = "UserPromptSubmit"
POST_TOOL = "PostToolUse"
USER_TEMPLATE = (
    "Kontekst sesji: {k}k tokenów (próg 500k). Przy najbliższym kamieniu "
    "milowym zrób /compact z fokusem — dalsze tury są coraz droższe i "
    "wolniejsze."
)

BOUNDARY = json.dumps({"type": "system", "subtype": "compact_boundary"})
STOP_SUMMARY = json.dumps({"type": "system", "subtype": "stop_hook_summary"})

Result = tuple[int, str, str]


def entry(cache_read: int, input_tokens: int = 1, creation: int = 2000) -> str:
    usage = {
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": creation,
        "output_tokens": 50,
    }
    return json.dumps({"type": "assistant", "message": {"usage": usage}})


def write_transcript(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


class Sandbox:
    def __init__(self, tmp: Path) -> None:
        self.state_dir = tmp / "state"
        self.main_path = tmp / "projects" / "p" / "session.jsonl"
        self.sub_path = (
            tmp / "projects" / "p" / "subagents" / "agent-abc.jsonl"
        )
        self.sub_path.parent.mkdir(parents=True)

    def run(
        self,
        transcript: Path | None,
        session: str = "s1",
        event: str = USER_PROMPT,
        raw: str | None = None,
        **extra: str,
    ) -> Result:
        payload: dict[str, str] = {
            "session_id": session,
            "hook_event_name": event,
            **extra,
        }
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        environment = dict(os.environ)
        environment.pop("CONTEXT_GUARD_TOKENS", None)
        environment.pop("CONTEXT_GUARD_STEP", None)
        environment["CONTEXT_GUARD_STATE_DIR"] = str(self.state_dir)
        done = subprocess.run(
            ["python3", HOOK],
            input=raw if raw is not None else json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=HOOK_TIMEOUT_SECONDS,
            env=environment,
            check=False,
        )
        return done.returncode, done.stdout.strip(), done.stderr.strip()


class Checks:
    def __init__(self) -> None:
        self.total = 0
        self.failures: list[str] = []

    def check(self, name: str, condition: bool, detail: object = "") -> None:
        self.total += 1
        if not condition:
            self.failures.append(f"{name}: {detail}")

    def silent(self, name: str, result: Result) -> None:
        rc, out, err = result
        self.check(name, rc == 0 and out == "" and not err, result)

    def warns(
        self,
        name: str,
        result: Result,
        event: str = USER_PROMPT,
        kilo: str = "602",
    ) -> None:
        rc, out, err = result
        if rc != 0 or not out or err:
            self.check(name, False, result)
            return
        data = json.loads(out)
        hook_out = data["hookSpecificOutput"]
        model_text = f"Context is {kilo}k tokens (threshold 500k)."
        self.check(name + " event", hook_out["hookEventName"] == event, out)
        self.check(
            name + " user",
            data["systemMessage"] == USER_TEMPLATE.format(k=kilo),
            data["systemMessage"],
        )
        self.check(
            name + " model",
            hook_out["additionalContext"].startswith(model_text),
            hook_out["additionalContext"],
        )


def threshold_scenarios(checks: Checks, sandbox: Sandbox) -> None:
    write_transcript(sandbox.main_path, [entry(OVER)])
    checks.warns(
        "warns_main_session", sandbox.run(sandbox.main_path, session="a")
    )
    post_tool = sandbox.run(sandbox.main_path, session="b", event=POST_TOOL)
    checks.warns("post_tool_event", post_tool, event=POST_TOOL)
    typed = sandbox.run(
        sandbox.main_path, session="c", agent_type="implementer"
    )
    checks.warns("agent_type_without_agent_id_warns", typed)
    checks.silent(
        "agent_id_silent",
        sandbox.run(sandbox.main_path, session="d", agent_id="x1"),
    )
    write_transcript(sandbox.sub_path, [entry(OVER)])
    checks.silent(
        "subagent_transcript_silent",
        sandbox.run(sandbox.sub_path, session="e"),
    )
    write_transcript(sandbox.main_path, [entry(100000)])
    checks.silent(
        "below_threshold", sandbox.run(sandbox.main_path, session="g")
    )
    write_transcript(sandbox.main_path, [entry(300000)])
    checks.silent(
        "between_old_and_new_threshold_silent",
        sandbox.run(sandbox.main_path, session="g2"),
    )


def step_scenarios(checks: Checks, sandbox: Sandbox) -> None:
    write_transcript(sandbox.main_path, [entry(OVER)])
    checks.warns("first_warning", sandbox.run(sandbox.main_path, session="h"))
    checks.silent(
        "not_again_same_size", sandbox.run(sandbox.main_path, session="h")
    )
    write_transcript(sandbox.main_path, [entry(640000)])
    checks.silent(
        "not_again_before_step", sandbox.run(sandbox.main_path, session="h")
    )
    write_transcript(sandbox.main_path, [entry(652000)])
    checks.warns(
        "again_after_step",
        sandbox.run(sandbox.main_path, session="h"),
        kilo="654",
    )


def compact_scenarios(checks: Checks, sandbox: Sandbox) -> None:
    write_transcript(sandbox.main_path, [entry(OVER)])
    checks.warns("compact_first", sandbox.run(sandbox.main_path, session="i"))
    write_transcript(sandbox.main_path, [entry(100000)])
    checks.silent("compact_drop", sandbox.run(sandbox.main_path, session="i"))
    write_transcript(sandbox.main_path, [entry(560000)])
    checks.warns(
        "reset_after_compact",
        sandbox.run(sandbox.main_path, session="i"),
        kilo="562",
    )


def boundary_scenarios(checks: Checks, sandbox: Sandbox) -> None:
    write_transcript(sandbox.main_path, [entry(OVER), BOUNDARY])
    checks.silent(
        "boundary_after_usage_silent",
        sandbox.run(sandbox.main_path, session="p"),
    )
    write_transcript(sandbox.main_path, [entry(OVER), BOUNDARY, entry(OVER)])
    checks.warns(
        "usage_after_boundary_warns",
        sandbox.run(sandbox.main_path, session="q"),
    )
    write_transcript(sandbox.main_path, [entry(OVER), BOUNDARY, entry(100000)])
    checks.silent(
        "low_usage_after_boundary_silent",
        sandbox.run(sandbox.main_path, session="s"),
    )
    write_transcript(sandbox.main_path, [entry(OVER), STOP_SUMMARY])
    checks.warns(
        "other_system_entry_ignored",
        sandbox.run(sandbox.main_path, session="t"),
    )


def recrossing_scenarios(checks: Checks, sandbox: Sandbox) -> None:
    state_file = sandbox.state_dir / "r.json"
    write_transcript(sandbox.main_path, [entry(508000)])
    checks.warns(
        "recross_first",
        sandbox.run(sandbox.main_path, session="r"),
        kilo="510",
    )
    checks.check("recross_state_written", state_file.exists())
    write_transcript(sandbox.main_path, [entry(478000)])
    checks.silent("recross_dip", sandbox.run(sandbox.main_path, session="r"))
    checks.check("recross_state_cleared", not state_file.exists())
    write_transcript(sandbox.main_path, [entry(508000)])
    checks.warns(
        "recross_again",
        sandbox.run(sandbox.main_path, session="r"),
        kilo="510",
    )


def transcript_scenarios(checks: Checks, sandbox: Sandbox) -> None:
    noisy = [entry(OVER), "not json at all", "{broken", entry(10, 5, 5), "[]"]
    write_transcript(sandbox.main_path, noisy)
    checks.silent(
        "garbage_skipped_last_usage_wins",
        sandbox.run(sandbox.main_path, session="j"),
    )
    bare = ["not json", json.dumps({"type": "user"}), "{}"]
    write_transcript(sandbox.main_path, bare)
    checks.silent(
        "no_usage_entry_silent", sandbox.run(sandbox.main_path, session="k")
    )
    usage = {"input_tokens": 1, "cache_read_input_tokens": 900000}
    huge = json.dumps(
        {
            "type": "assistant",
            "message": {"usage": usage, "pad": "x" * (TAIL_BYTES + 1000)},
        }
    )
    write_transcript(sandbox.main_path, [huge, entry(100000)])
    checks.silent(
        "truncated_first_line_skipped",
        sandbox.run(sandbox.main_path, session="l"),
    )
    write_transcript(sandbox.main_path, [huge, entry(OVER)])
    checks.warns(
        "tail_finds_last_entry", sandbox.run(sandbox.main_path, session="m")
    )


def failure_scenarios(checks: Checks, sandbox: Sandbox, tmp: Path) -> None:
    checks.silent(
        "missing_transcript", sandbox.run(tmp / "nope.jsonl", session="n")
    )
    checks.silent(
        "garbage_payload", sandbox.run(sandbox.main_path, raw="not json")
    )
    checks.silent("non_dict_payload", sandbox.run(sandbox.main_path, raw="[]"))
    checks.silent("no_transcript_path", sandbox.run(None, session="o"))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Sandbox(Path(tmp))
        checks = Checks()
        threshold_scenarios(checks, sandbox)
        step_scenarios(checks, sandbox)
        compact_scenarios(checks, sandbox)
        boundary_scenarios(checks, sandbox)
        recrossing_scenarios(checks, sandbox)
        transcript_scenarios(checks, sandbox)
        failure_scenarios(checks, sandbox, Path(tmp))
    print(f"hook: {HOOK}")
    for line in checks.failures:
        print("FAIL " + line)
    passed = checks.total - len(checks.failures)
    print(
        ("FAIL " if checks.failures else "PASS ") + f"{passed}/{checks.total}"
    )
    return 1 if checks.failures else 0


if __name__ == "__main__":
    sys.exit(main())
