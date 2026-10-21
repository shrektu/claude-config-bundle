#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
hook = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "mode-notice.py")
SWITCH_VARS = ("CLAUDE_MODE", "CLAUDE_CODEX", "CLAUDE_CODEX_GATE")
NOTICE = (
    "mode: personal (CLAUDE_MODE=personal) - Codex off: final review = "
    "reviewer-opus + flash-review-runner (S: flash-review-runner alone; "
    "Flash unavailable -> reviewer-opus), plan gate without Codex fallback; "
    "no redakcja, company style guide, glossary or `terms` checks "
    "(writer and ui-writer proofread themselves); "
    "no AI footer on published text.\n"
)
STDINS = (
    "",
    '{"session_id":"s","hook_event_name":"SessionStart"}',
    "not json at all",
    "[]",
    "\x00\xff",
)
PERSONAL_VALUES = ("personal", "PERSONAL", " Personal ", "personal\n")
WORK_VALUES = (None, "", "work", "WORK", "persnal", "off", "1")

bad = 0
checks = 0


def run(
    mode: str | None, stdin: str, extra: dict[str, str] | None = None
) -> tuple[int, str, str]:
    """Run the hook with CLAUDE_MODE set to mode (unset when None)."""
    env = {k: v for k, v in os.environ.items() if k not in SWITCH_VARS}
    if mode is not None:
        env["CLAUDE_MODE"] = mode
    done = subprocess.run(
        [sys.executable, hook],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        env={**env, **(extra or {})},
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


if not Path(hook).is_file():
    print(f"FAIL mode-notice.py exists: {hook}")
    sys.exit(1)

for value in PERSONAL_VALUES:
    for stdin in STDINS:
        rc, out, err = run(value, stdin)
        checks += 1
        if not (rc == 0 and out == NOTICE and not err):
            bad += 1
            print(
                f"PERSONAL FAIL {value!r} {stdin!r} -> rc={rc} {out[:200]!r}"
            )

for work_value in WORK_VALUES:
    for stdin in STDINS:
        rc, out, err = run(work_value, stdin)
        checks += 1
        if not (rc == 0 and out == "" and not err):
            bad += 1
            print(
                f"WORK FAIL {work_value!r} {stdin!r} -> rc={rc} {out[:200]!r}"
            )

rc, out, err = run(None, "", {"CLAUDE_CODEX": "off"})
checks += 1
if not (rc == 0 and out == "" and not err):
    bad += 1
    print(f"LEFTOVER CLAUDE_CODEX FAIL -> rc={rc} {out[:200]!r}")

print(f"hook: {hook}")
print(f"{'FAIL' if bad else 'PASS'} {checks - bad}/{checks}")
sys.exit(1 if bad else 0)
