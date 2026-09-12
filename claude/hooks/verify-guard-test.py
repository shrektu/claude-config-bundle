#!/usr/bin/env python3
"""Regression matrix for verify-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, subprocess, os, sys

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify-guard.py")
HOME_VERIFY = os.path.expanduser("~/.claude/bin/verify")

deny = [
 "pytest", "pytest -q", "python -m pytest", "python3 -m pytest -q",
 "uv run pytest -q 2>&1 | tail -20", "cd apps/api && pytest", "cd apps/api && pytest -q",
 "npm test", "npm run lint", "pnpm run build", "yarn test", "bun test",
 "make test-api", "make", "make lint", "make check", "make build-all", "make ci",
 "ruff check .", "ruff format . --check", "tsc --noEmit", "eslint src",
 "cargo test", "cargo build", "cargo clippy", "go test ./...", "go build ./...",
 "docker compose build", "docker-compose build", "docker build .",
 "bash -c \"pytest -x\"", "sh -c 'pytest -x'", "FOO=1 pytest", "FOO=1 BAR=2 pytest -q",
 "timeout 300 pytest", "mvn test", "mvnw verify", "gradle build", "gradlew test",
 "vitest run", "jest", "mocha", "ava", "tox", "nox", "mypy .", "pyright",
 "playwright test", "cmake --build build", "pio run", "west build",
 "idf.py build", "alembic upgrade head", "alembic downgrade -1",
 "poetry run pytest", "hatch run pytest -q", "npx jest", "prettier --check .",
 "sudo pytest", "nice pytest -q", "pytest && echo done",
 # round 2: keywords, npm option/bare-script forms, make option values, combined -c shells
 "for f in a b; do pytest $f; done", "while true; do npm test; done", "if pytest -q; then echo ok; fi",
 "npm --prefix apps/web run build", "pnpm -C apps/web run typecheck", "pnpm --filter web run test",
 "pnpm build", "yarn lint", "pnpm typecheck", "bun run lint",
 "make -C apps/api", "make -f other.mk",
 "bash -lc \"pytest -q\"", "sh -ec \"cd x && npm test\"",
 # round 3: the verify exemption is per segment, not per command
 'echo "verify -- pytest"; pytest -q', "~/.claude/bin/verify -- pytest && npm test",
 "verify -- pytest; make test", f"{HOME_VERIFY} -- pytest | tail -5; cargo test",
 "echo verify; pytest -q", "verify -- pytest || ruff check .",
 # round 4: wrapper options that take a value
 "env -u CI pytest", "nice -n 10 pytest -q", "timeout -k 5 60 pytest", "env --unset=CI npm test",
 "sudo -u builder make test", "ionice -c 3 cargo test", "xargs -n 1 pytest",
 # round 5: long wrapper options with a separate value
 "ionice --class 3 pytest", "stdbuf --output L pytest -q", "xargs --max-args 1 pytest",
 "sudo --user builder make test", "ionice --class=3 pytest",
 # round 6: xargs options whose value only exists in the attached form
 "xargs --replace pytest", "xargs --eof pytest", "xargs --max-lines pytest", "xargs -l pytest", "xargs -i pytest", "xargs -e make test",
]
allow = [
 "~/.claude/bin/verify -- 'pytest -q'", "verify -- make test", "$HOME/.claude/bin/verify -- pytest",
 f"{HOME_VERIFY} -- 'npm test'", "pytest --version", "pytest -V",
 "pytest --collect-only -q", "pytest --list-tests", "pytest --dry-run", "pytest --showconfig",
 "make -n test", "make --just-print test", "which pytest", "type pytest", "command -v pytest",
 "git status", "ls", "cat file", "grep -rn pytest .", "echo pytest", "echo 'run pytest later'",
 "echo \"run pytest later\"", "ruff format .", "npm install", "npm run dev", "npm run start",
 "docker compose up -d", "docker compose logs", "cargo fmt", "go fmt ./...", "make ursim-up",
 "make deploy", "python script.py", "python3 -c 'print(1)'", "which python",
 "eslint --version", "tsc --version", "mvn --version", "cmake .", "docker ps",
 # round 2
 "pnpm add x", "yarn dev", "pnpm -C apps/web run dev",
 "make -C apps/api help", "make -C apps/api ursim-up",
 # round 3: wrapped and nested verify invocations stay exempt
 "timeout 300 ~/.claude/bin/verify -- pytest", 'bash -c "verify -- pytest"',
 "verify -- 'cd apps/api && pytest -q'", "verify -n api -t 20 -- 'pytest -q'",
 "~/.claude/bin/verify -- 'pytest -q' | tail -5", "env CI=1 verify -- 'npm test'",
 "verify -- pytest && echo done", "verify -- pytest; git status",
 "env -u CI verify -- pytest", "nice -n 10 verify -- pytest", "timeout -k 5 60 verify -- pytest",
 "env --unset=CI verify -- 'npm test'", "sudo -u builder verify -- 'make test'",
 "ionice --class 3 verify -- pytest", "xargs --max-args 1 verify -- pytest",
 "stdbuf --output L verify -- 'pytest -q'", "sudo --user builder verify -- 'make test'",
 "xargs --replace verify -- pytest", "xargs --eof verify -- pytest", "xargs --max-lines verify -- pytest", "xargs -l verify -- pytest", "xargs -L 1 verify -- pytest", "xargs -I{} verify -- pytest",
 "xargs -I {} verify -- pytest", "xargs --replace=R verify -- pytest",
]
garbage = [
 "", "not json", '{"tool_name":"Bash"}', '{"tool_name":"Edit","tool_input":{"command":"pytest"}}',
 '{"tool_name":"Bash","tool_input":{"command":123}}',
 '{"tool_name":"Bash","tool_input":{"command":"echo \'oops}',
]


def run(cmd):
    p = subprocess.run(["python3", hook], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                        capture_output=True, text=True, timeout=10)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


bad = 0
for c in deny:
    rc, out, err = run(c)
    ok = rc == 0 and '"deny"' in out and not err
    bad += not ok
    if not ok:
        print(f"DENY MISS  {c!r} -> rc={rc} {out[:160]} {err[-160:]}")

for c in allow:
    rc, out, err = run(c)
    ok = rc == 0 and out == "" and not err
    bad += not ok
    if not ok:
        print(f"ALLOW FP   {c!r} -> rc={rc} {out[:160]} {err[-160:]}")

for raw in garbage:
    p = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=10)
    ok = p.returncode == 0 and not p.stderr and p.stdout == ""
    bad += not ok
    if not ok:
        print(f"garbage {raw[:60]!r} -> rc={p.returncode} out={p.stdout.strip()[:60]!r} err={p.stderr[-160:]!r}")

# spot checks from the task's acceptance criteria
rc, out, err = run("cd apps/api && pytest -q")
spot1 = rc == 0 and '"deny"' in out and "~/.claude/bin/verify -- 'cd apps/api && pytest -q'" in out
bad += not spot1
if not spot1:
    print(f"SPOT1 FAIL rc={rc} out={out!r} err={err!r}")

p = subprocess.run(["python3", hook], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": '~/.claude/bin/verify -- "pytest -q"'}}),
                    capture_output=True, text=True, timeout=10)
spot2 = p.returncode == 0 and p.stdout.strip() == "" and not p.stderr
bad += not spot2
if not spot2:
    print(f"SPOT2 FAIL rc={p.returncode} out={p.stdout!r} err={p.stderr!r}")

# round 3: the suggestion drops only a trailing pure display filter
suggestions = [
    ("uv run pytest -q 2>&1 | tail -20", "~/.claude/bin/verify -- 'uv run pytest -q 2>&1'"),
    ("pytest -q | head -5", "~/.claude/bin/verify -- 'pytest -q'"),
    ("make test 2>&1 | tail -n 40", "~/.claude/bin/verify -- 'make test 2>&1'"),
    ("pytest -q | grep FAILED", "~/.claude/bin/verify -- 'pytest -q | grep FAILED'"),
    ("pytest -q | tee out.log", "~/.claude/bin/verify -- 'pytest -q | tee out.log'"),
    ("pytest -q | wc -l", "~/.claude/bin/verify -- 'pytest -q | wc -l'"),
    ("pytest -q 2>&1 | tail -20 | grep x", "~/.claude/bin/verify -- 'pytest -q 2>&1 | tail -20 | grep x'"),
    ("cd apps/api && pytest -q", "~/.claude/bin/verify -- 'cd apps/api && pytest -q'"),
    ("pytest -q | tail -20 || true", "~/.claude/bin/verify -- 'pytest -q | tail -20 || true'"),
]
for cmd, expected in suggestions:
    rc, out, err = run(cmd)
    ok = rc == 0 and '"deny"' in out and expected in out
    bad += not ok
    if not ok:
        print(f"SUGGESTION FAIL {cmd!r} expected {expected!r} -> {out[:300]}")

print(f"hook: {hook}\nsuggestion cases: {len(suggestions)}\ndeny cases: {len(deny)}, allow cases: {len(allow)}, garbage: {len(garbage)}, FAILURES: {bad}")
if bad:
    print(f"FAIL {len(deny) + len(allow) + len(garbage) + 2 - bad}/{len(deny) + len(allow) + len(garbage) + 2}")
else:
    print(f"PASS {len(deny) + len(allow) + len(garbage) + 2}/{len(deny) + len(allow) + len(garbage) + 2}")
sys.exit(1 if bad else 0)
