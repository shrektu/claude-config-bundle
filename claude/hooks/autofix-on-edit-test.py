#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "autofix-on-edit.py")
FAKE_SOURCE = """#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["FAKE_ARGV"], "w") as handle:
    json.dump(sys.argv[1:], handle)
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
with open(os.environ["FAKE_STDOUT"]) as handle:
    sys.stdout.write(handle.read())
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
REPORT_HEADER = (
    "autofix: 3 changed lines fixed in src/a.py; "
    "re-read the file before the next edit."
)
HOOK_TIMEOUT_SECONDS = 30
FAKE_SLOW_SECONDS = 6
HOOK_SHORT_TIMEOUT = 1
LISTED_LIMIT = 15
MANY_VIOLATIONS = 20

Result = tuple[int, str, str]


def violation(index: int) -> dict[str, object]:
    return {
        "path": "src/a.py",
        "line": index,
        "column": 1,
        "rule": f"R{index}",
        "message": f"problem {index}",
        "url": "",
        "tool": "ruff",
    }


def report(fixed_lines: int, count: int) -> str:
    return json.dumps(
        {
            "violations": [violation(i) for i in range(1, count + 1)],
            "not_checked": [],
            "suppressions": [],
            "passed": count == 0,
            "fixed_lines": fixed_lines,
            "fixed_files": ["src/a.py"] if fixed_lines else [],
        }
    )


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = (root / "repo").resolve()
        (self.repo / "src").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.fake = root / "fake-lint-strict"
        self.fake.write_text(FAKE_SOURCE)
        self.fake.chmod(0o755)
        self.argv_file = root / "argv.json"
        self.stdout_file = root / "stdout.txt"
        self.log_dir = root / "logs"
        self.target = self.repo / "src" / "a.py"
        self.target.write_text("x = 1\n")

    def set_output(self, text: str) -> None:
        self.stdout_file.write_text(text)

    def error_lines(self) -> list[str]:
        path = self.log_dir / "errors.log"
        if not path.exists():
            return []
        return [line for line in path.read_text().splitlines() if line]

    def argv(self) -> list[str]:
        return list(json.loads(self.argv_file.read_text()))

    def run(
        self,
        file_path: Path | None = None,
        tool: str | list[str] = "Edit",
        **env: str | int,
    ) -> Result:
        payload = {
            "tool_name": tool,
            "tool_input": {"file_path": str(file_path or self.target)},
            "hook_event_name": "PostToolUse",
        }
        environment = dict(os.environ)
        environment.pop("CLAUDE_AUTOFIX", None)
        environment.update(
            {
                "AUTOFIX_LINT_STRICT": str(self.fake),
                "AUTOFIX_LOG_DIR": str(self.log_dir),
                "FAKE_ARGV": str(self.argv_file),
                "FAKE_STDOUT": str(self.stdout_file),
            }
        )
        environment.update({key: str(value) for key, value in env.items()})
        done = subprocess.run(
            ["python3", HOOK],
            input=json.dumps(payload),
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

    def silent(
        self, name: str, result: Result, box: Sandbox, logged: int
    ) -> None:
        rc, out, err = result
        self.check(name + " exit0", rc == 0, f"rc={rc} err={err}")
        self.check(name + " silent", out == "" and not err, f"{out!r} {err!r}")
        lines = box.error_lines()
        self.check(name + " log", len(lines) == logged, lines)


def context_of(out: str) -> str:
    if not out:
        return ""
    return str(json.loads(out)["hookSpecificOutput"]["additionalContext"])


def event_of(out: str) -> str:
    if not out:
        return ""
    return str(json.loads(out)["hookSpecificOutput"]["hookEventName"])


Fresh = Callable[[str], Sandbox]


def output_scenarios(checks: Checks, fresh: Fresh) -> None:
    box = fresh("report")
    box.set_output(report(3, 2))
    rc, out, err = box.run()
    text = context_of(out)
    checks.check("reports exit0", rc == 0 and not err, f"rc={rc} {err}")
    checks.check("reports event", event_of(out) == "PostToolUse", out)
    checks.check("reports header", text.startswith(REPORT_HEADER), text)
    checks.check(
        "reports violations",
        "lint-strict on changed lines:" in text
        and "src/a.py:1 R1 problem 1" in text
        and "src/a.py:2 R2 problem 2" in text,
        text,
    )
    checks.check("reports no more", "...and" not in text, text)
    expected_argv = [
        "--repo",
        str(box.repo),
        "--fix",
        "--quick",
        "--paths",
        "src/a.py",
        "--json",
    ]
    checks.check("argv", box.argv() == expected_argv, box.argv())

    box = fresh("violations-only")
    box.set_output(report(0, 1))
    text = context_of(box.run(tool="Write")[1])
    checks.check(
        "violations-only",
        "autofix:" not in text and "src/a.py:1 R1 problem 1" in text,
        text,
    )

    box = fresh("clean")
    box.set_output(report(0, 0))
    checks.silent("clean", box.run(), box, 0)

    box = fresh("many")
    box.set_output(report(0, MANY_VIOLATIONS))
    text = context_of(box.run(FAKE_EXIT=1)[1])
    listed = [line for line in text.splitlines() if line.startswith("src/")]
    checks.check("many listed", len(listed) == LISTED_LIMIT, text)
    checks.check("many last", listed[-1] == "src/a.py:15 R15 problem 15", text)
    checks.check("many tail", text.endswith("...and 5 more"), text)


def failure_scenarios(checks: Checks, fresh: Fresh, tmp: str) -> None:
    box = fresh("timeout")
    box.set_output(report(3, 2))
    slow = box.run(
        AUTOFIX_TIMEOUT=HOOK_SHORT_TIMEOUT, FAKE_SLEEP=FAKE_SLOW_SECONDS
    )
    checks.silent("timeout", slow, box, 1)

    box = fresh("nonjson")
    box.set_output("this is not json")
    checks.silent("nonjson", box.run(), box, 1)

    box = fresh("exit2")
    box.set_output(report(3, 2))
    checks.silent("exit2", box.run(FAKE_EXIT=2), box, 1)

    box = fresh("missing-tool")
    box.set_output(report(3, 2))
    absent = Path(tmp) / "nope"
    checks.silent(
        "missing-tool", box.run(AUTOFIX_LINT_STRICT=str(absent)), box, 1
    )


def skip_scenarios(checks: Checks, fresh: Fresh, tmp: str) -> None:
    box = fresh("list-tool")
    box.set_output(report(3, 2))
    checks.silent("non_string_tool_name", box.run(tool=["Edit"]), box, 0)

    box = fresh("suffix")
    box.set_output(report(3, 2))
    notes = box.repo / "notes.txt"
    notes.write_text("x")
    checks.silent("suffix", box.run(file_path=notes), box, 0)

    box = fresh("missing-file")
    box.set_output(report(3, 2))
    gone = box.repo / "src" / "gone.py"
    checks.silent("missing-file", box.run(file_path=gone), box, 0)

    box = fresh("outside")
    box.set_output(report(3, 2))
    stray = Path(tmp) / "stray.py"
    stray.write_text("x = 1\n")
    checks.silent("outside", box.run(file_path=stray), box, 0)

    box = fresh("off")
    box.set_output(report(3, 2))
    for value in ("off", "0", "false", "no"):
        checks.silent("off-" + value, box.run(CLAUDE_AUTOFIX=value), box, 0)

    box = fresh("tool")
    box.set_output(report(3, 2))
    checks.silent("other-tool", box.run(tool="Bash"), box, 0)

    box = fresh("gitdir")
    box.set_output(report(3, 2))
    inside = box.repo / ".git" / "hook.py"
    inside.write_text("x = 1\n")
    checks.silent("inside-git", box.run(file_path=inside), box, 0)


def main() -> int:
    checks = Checks()
    with tempfile.TemporaryDirectory() as tmp:

        def fresh(label: str) -> Sandbox:
            return Sandbox(Path(tempfile.mkdtemp(dir=tmp, prefix=label)))

        output_scenarios(checks, fresh)
        failure_scenarios(checks, fresh, tmp)
        skip_scenarios(checks, fresh, tmp)

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
