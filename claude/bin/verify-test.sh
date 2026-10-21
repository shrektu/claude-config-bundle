#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: verify-test.sh [PATH_TO_VERIFY]
Checks the contract of bin/verify: pipefail in the single-argument form, PASS/FAIL lines, the
deprecation-warning counter on PASS and exit-code propagation.
USAGE
}
set -uo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
VERIFY=${1:-$HERE/verify}
[ -x "$VERIFY" ] || { echo "not executable: $VERIFY"; exit 1; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_VERIFY_LOG_DIR=$TMP/logs
FAILURES=0
CASES=0

expect() {
  local label=$1 want_rc=$2 needle=$3 absent=${4:-}
  CASES=$((CASES + 1))
  if [ "$RC" != "$want_rc" ]; then
    echo "FAIL $label: exit $RC, wanted $want_rc"; FAILURES=$((FAILURES + 1)); return
  fi
  if [ -n "$needle" ] && ! grep -qF -- "$needle" <<<"$OUT"; then
    echo "FAIL $label: missing '$needle' in:"; echo "$OUT"; FAILURES=$((FAILURES + 1)); return
  fi
  if [ -n "$absent" ] && grep -qF -- "$absent" <<<"$OUT"; then
    echo "FAIL $label: unexpected '$absent' in:"; echo "$OUT"; FAILURES=$((FAILURES + 1)); return
  fi
}

run() { OUT=$("$VERIFY" "$@" 2>&1); RC=$?; }

run -- 'false | tail -1'
expect "pipefail: false | tail" 1 "VERIFY FAIL exit=1"

run -- 'echo ok | tail -1'
expect "pass: echo | tail" 0 "VERIFY PASS exit=0"

run -- 'true | false | true'
expect "pipefail: middle failure" 1 "VERIFY FAIL exit=1"

run -- 'printf "app.py:3: DeprecationWarning: old api\n"'
expect "warnings: DeprecationWarning" 0 "warnings: 1 deprecation lines (see log)"

run -- 'printf "PendingDeprecationWarning: later\nthis call is DEPRECATED soon\n"'
expect "warnings: case-insensitive" 0 "warnings: 2 deprecation lines (see log)"

run -- 'echo all good'
expect "warnings: silent when none" 0 "VERIFY PASS exit=0" "warnings:"

run -- 'printf "DeprecationWarning: x\n"; exit 3'
expect "warnings: only on PASS" 3 "VERIFY FAIL exit=3" "warnings:"

run -- 'exit 7'
expect "exit code propagation" 7 "VERIFY FAIL exit=7"

run -- 'echo hi'
expect "single argument form" 0 "cmd: echo hi"

run -- printf 'multi %s\n' args
expect "multi argument form" 0 "VERIFY PASS exit=0"

run -n named -- 'echo hi'
expect "name flag" 0 "-named-"

run -t 5 -- 'exit 1'
expect "tail flag" 1 "VERIFY FAIL exit=1"

LEDGER=$CLAUDE_VERIFY_LOG_DIR/ledger.jsonl
STUBS=$TMP/bin
mkdir -p "$STUBS" "$CLAUDE_VERIFY_LOG_DIR"

cat > "$STUBS/pytest" <<'STUB'
#!/usr/bin/env bash
case ${1:-green} in
  banner) printf '============= 3 failed, 2 passed in 1.23s ==============\n'; exit 1 ;;
  quiet) printf '4 failed, 273 passed, 9 warnings in 1.41s\n'; exit 1 ;;
  collect) printf '1727 passed, 2 warnings, 2 errors in 79.98s\n'; exit 2 ;;
  *) printf '273 passed, 9 warnings in 1.41s\n'; exit 0 ;;
esac
STUB
cat > "$STUBS/vitest" <<'STUB'
#!/usr/bin/env bash
printf ' Test Files  2 failed | 30 passed (32)\n Tests  3 failed | 316 passed (319)\n'
exit 1
STUB
cat > "$STUBS/bun" <<'STUB'
#!/usr/bin/env bash
printf '\n 184 pass\n 0 fail\n 2 expect() calls\n'
exit 1
STUB
chmod +x "$STUBS/pytest" "$STUBS/vitest" "$STUBS/bun"

WORKTREE=$TMP/worktree
mkdir -p "$WORKTREE/.git/objects" "$WORKTREE/.git/refs" "$WORKTREE/src/deep"
printf 'ref: refs/heads/main\n' > "$WORKTREE/.git/HEAD"
WORKTREE_REAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$WORKTREE")
PLAIN=$TMP/plain
mkdir -p "$PLAIN"
PLAIN_REAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PLAIN")

check() {
  local label=$1 got=$2 want=$3
  CASES=$((CASES + 1))
  if [ "$got" != "$want" ]; then
    echo "FAIL $label: got '$got', wanted '$want'"; FAILURES=$((FAILURES + 1))
  fi
}

run_in() { local dir=$1; shift; OUT=$(cd "$dir" && "$VERIFY" "$@" 2>&1); RC=$?; }

last_field() {
  python3 - "$LEDGER" "$1" <<'PY'
import json, os, sys
ledger, key = sys.argv[1], sys.argv[2]
if not os.path.isfile(ledger):
    print("no ledger file")
    raise SystemExit(0)
lines = [line for line in open(ledger, encoding="utf-8") if line.strip()]
value = json.loads(lines[-1]).get(key) if lines else "empty ledger"
print("" if value is None else value)
PY
}

valid_lines() {
  python3 - "$LEDGER" <<'PY'
import json, os, sys
good = 0
if not os.path.isfile(sys.argv[1]):
    print(0)
    raise SystemExit(0)
for line in open(sys.argv[1], encoding="utf-8"):
    if not line.strip():
        continue
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    if isinstance(entry, dict) and entry.get("schema") == 1 and "outcome" in entry:
        good += 1
print(good)
PY
}

canon() {
  local text
  text=$(cat)
  text=${text//"$CLAUDE_VERIFY_LOG_DIR"/LOGDIR}
  text=${text//"$STUBS"/STUBS}
  sed -E 's|[0-9]{8}-[0-9]{6}-|TS-|g; s|-[0-9]+\.log|-PID.log|g; s|time=[0-9]+s|time=Ts|g; s|(log: LOGDIR/TS-)_[^ ]*(-PID\.log)|\1_SLUG\2|' <<<"$text"
}

GREEN_GOLDEN=$'VERIFY PASS exit=0 time=Ts lines=2 cmd: printf "one\\ntwo\\n"\nlog: LOGDIR/TS-printf__one_ntwo_n_-PID.log'
RED_GOLDEN=$'VERIFY FAIL exit=1 time=Ts lines=1 cmd: STUBS/pytest quiet\nlog: LOGDIR/TS-_SLUG-PID.log\n--- last 1 lines\n4 failed, 273 passed, 9 warnings in 1.41s'

outcome_of() {
  rm -f "$LEDGER"
  run_in "$PLAIN" -- "$1" >/dev/null 2>&1
  last_field outcome
}

export CLAUDE_CODE_SESSION_ID=session-under-test

rm -f "$LEDGER"
run_in "$PLAIN" -- 'echo hi'
check "ledger: one record per run" "$(grep -c . "$LEDGER" 2>/dev/null || echo 0)" 1
check "ledger: rc" "$(last_field rc)" 0
check "ledger: cmd" "$(last_field cmd)" "echo hi"
check "ledger: session_id" "$(last_field session_id)" "session-under-test"
check "ledger: repo falls back to cwd" "$(last_field repo)" "$PLAIN_REAL"
check "ledger: schema" "$(last_field schema)" 1
LEDGER_LOG=$(last_field log)
check "ledger: log path is the printed one" "log: $LEDGER_LOG" "$(grep '^log: ' <<<"$OUT")"
CASES=$((CASES + 1))
[ -f "$LEDGER_LOG" ] || { echo "FAIL ledger: log file missing"; FAILURES=$((FAILURES + 1)); }

rm -f "$LEDGER"
run_in "$PLAIN" -- 'exit 9'
check "ledger: failing rc recorded" "$(last_field rc)" 9
check "ledger: exit code still the command's" "$RC" 9

check "outcome: green suite" "$(outcome_of "$STUBS/pytest green")" green
check "outcome: pytest banner form" "$(outcome_of "$STUBS/pytest banner")" red
check "outcome: pytest quiet form" "$(outcome_of "$STUBS/pytest quiet")" red
check "outcome: vitest 4 form" "$(outcome_of "$STUBS/vitest run")" red
check "outcome: bun 0 fail is not red" "$(outcome_of "$STUBS/bun test")" error
check "outcome: false" "$(outcome_of 'false')" error
check "outcome: nonexistent command" "$(outcome_of 'definitely-not-a-command-xyz')" error
check "outcome: pytest collection error" "$(outcome_of "$STUBS/pytest collect")" error
check "outcome: FAILED without a runner" "$(outcome_of 'printf "FAILED x\n"; exit 1')" error

rm -f "$LEDGER"
run_in "$PLAIN" --repo "$WORKTREE/src/deep" -- 'echo hi'
check "repo: --repo normalized to worktree root" "$(last_field repo)" "$WORKTREE_REAL"

rm -f "$LEDGER"
run_in "$PLAIN" -- "cd $WORKTREE/src/deep && echo hi"
check "repo: leading cd normalized to worktree root" "$(last_field repo)" "$WORKTREE_REAL"

GREEN_NEW=$(cd "$PLAIN" && "$VERIFY" -- 'printf "one\ntwo\n"' 2>&1 | canon)
check "byte-for-byte: green run" "$GREEN_NEW" "$GREEN_GOLDEN"
RED_NEW=$(cd "$PLAIN" && "$VERIFY" -- "$STUBS/pytest quiet" 2>&1 | canon)
check "byte-for-byte: failing run" "$RED_NEW" "$RED_GOLDEN"

rm -f "$LEDGER"
for index in 1 2 3 4 5 6 7 8; do (cd "$PLAIN" && "$VERIFY" -- "echo parallel $index" >/dev/null 2>&1) & done
wait
check "concurrency: one line per run" "$(grep -c . "$LEDGER" 2>/dev/null || echo 0)" 8
check "concurrency: every line well formed" "$(valid_lines)" 8

python3 - "$LEDGER" "$CLAUDE_VERIFY_LOG_DIR" <<'PY'
import datetime, json, os, sys
ledger, log_dir = sys.argv[1], sys.argv[2]
now = datetime.datetime.now(datetime.timezone.utc)
def stamp(days):
    return (now - datetime.timedelta(days=days)).isoformat()
rows = [
    {"schema": 1, "ts": stamp(40), "rc": 1, "outcome": "red", "repo": "/x", "cmd": "pytest",
     "log": os.path.join(log_dir, "expired-red.log"), "session_id": "old", "slug": "pytest"},
    {"schema": 1, "ts": stamp(3), "rc": 1, "outcome": "red", "repo": "/x", "cmd": "pytest",
     "log": os.path.join(log_dir, "kept-red.log"), "session_id": "fresh", "slug": "pytest"},
    {"schema": 1, "ts": stamp(2), "rc": 0, "outcome": "green", "repo": "/x", "cmd": "pytest",
     "log": os.path.join(log_dir, "kept-green.log"), "session_id": "fresh", "slug": "pytest"},
]
with open(ledger, "w", encoding="utf-8") as handle:
    handle.write(json.dumps(rows[0]) + "\n")
    handle.write("{not json at all\n")
    handle.write(json.dumps(rows[1]) + "\n")
    handle.write(json.dumps(rows[2]) + "\n")
PY
for stale in expired-red kept-red kept-green unreferenced; do
  printf 'old output\n' > "$CLAUDE_VERIFY_LOG_DIR/$stale.log"
  touch -d '10 days ago' "$CLAUDE_VERIFY_LOG_DIR/$stale.log"
done
run_in "$PLAIN" -- 'echo prune'
check "prune: expired entry dropped, fresh kept, new appended" "$(valid_lines)" 3
check "prune: corrupt line dropped without crashing" "$(grep -c 'not json at all' "$LEDGER" 2>/dev/null || true)" 0
check "prune: newest entry is the fresh run" "$(last_field cmd)" "echo prune"
CASES=$((CASES + 1))
[ -f "$CLAUDE_VERIFY_LOG_DIR/kept-red.log" ] || {
  echo "FAIL rotation: log of a retained red entry was deleted"; FAILURES=$((FAILURES + 1)); }
CASES=$((CASES + 1))
[ -f "$CLAUDE_VERIFY_LOG_DIR/unreferenced.log" ] && {
  echo "FAIL rotation: stale unreferenced log survived"; FAILURES=$((FAILURES + 1)); }
CASES=$((CASES + 1))
[ -f "$CLAUDE_VERIFY_LOG_DIR/expired-red.log" ] && {
  echo "FAIL rotation: log of an expired red entry survived"; FAILURES=$((FAILURES + 1)); }

ledger_eval() {
  python3 - "$VERIFY" "$1" <<'PY'
import sys
source = open(sys.argv[1], encoding="utf-8").read()
body = source.split("<<'LEDGER_PY'\n", 1)[1].split("\nLEDGER_PY\n", 1)[0]
module = {"__name__": "ledger_under_test"}
exec(compile(body, "ledger", "exec"), module)
print(eval(sys.argv[2], module))
PY
}

ledger_script() {
  python3 - "$VERIFY" "$1" <<'PY'
import sys
source = open(sys.argv[1], encoding="utf-8").read()
body = source.split("<<'LEDGER_PY'\n", 1)[1].split("\nLEDGER_PY\n", 1)[0]
module = {"__name__": "ledger_under_test"}
exec(compile(body, "ledger", "exec"), module)
exec(compile(open(sys.argv[2], encoding="utf-8").read(), sys.argv[2], "exec"), module)
PY
}

cat > "$STUBS/twister" <<'STUB'
#!/usr/bin/env bash
case ${1:-zero} in
  zero) printf 'INFO    - 0 of 10 test configurations failed\n' ;;
  *) printf 'INFO    - 3 of 10 test configurations failed\n' ;;
esac
exit 1
STUB
mkdir -p "$TMP/pytest-tools"
cat > "$TMP/pytest-tools/run.sh" <<'STUB'
#!/usr/bin/env bash
printf 'FAILED x\n'
exit 1
STUB
chmod +x "$STUBS/twister" "$TMP/pytest-tools/run.sh"

check "verify-twister-zero-count-red: zero configurations failed" \
  "$(outcome_of "$STUBS/twister zero")" error
check "verify-twister-zero-count-red: three configurations failed" \
  "$(outcome_of "$STUBS/twister three")" red
check "verify-twister-zero-count-red: unit, zero count" \
  "$(ledger_eval 'bool(RUNNER_FAILURE.search("INFO    - 0 of 10 test configurations failed"))')" False
check "verify-twister-zero-count-red: unit, non-zero count" \
  "$(ledger_eval 'bool(RUNNER_FAILURE.search("INFO    - 3 of 10 test configurations failed"))')" True

check "verify-runner-name-in-comment: runner named only in a comment" \
  "$(outcome_of 'printf "FAILED x\n"; exit 1 # pytest')" error
check "verify-runner-name-in-comment: runner name only in a directory" \
  "$(outcome_of "$TMP/pytest-tools/run.sh")" error

cat > "$TMP/unit-runner.py" <<'UNIT'
CASES = (
    ('printf "FAILED x\n"; exit 1 # pytest', False),
    ("uv run pytest -q", True),
    ("/opt/pytest-tools/run.sh", False),
    ("echo 'run the pytest suite later'", False),
    ("npm run test", True),
    ("npm test", True),
    ("cargo +nightly test", True),
    ("go test ./...", True),
    ("ruff check src", False),
)
print(sum(1 for command, want in CASES if names_known_runner(command) == want), len(CASES))
UNIT
check "verify-runner-name-in-comment: unit, runner as a command token" \
  "$(ledger_script "$TMP/unit-runner.py" 2>&1)" "9 9"

cat > "$STUBS/failing-runner" <<'STUB'
#!/usr/bin/env bash
printf '4 failed, 273 passed, 9 warnings in 1.41s\n'
exit 1
STUB
chmod +x "$STUBS/failing-runner"
for LAUNCHER in uv uvx npx bunx cargo pnpm python3; do
  cp "$STUBS/failing-runner" "$STUBS/$LAUNCHER"
done

check "verify-runner-not-command-word: comment glued to a semicolon" \
  "$(outcome_of 'printf "FAILED x\n"; exit 1;# pytest')" error
check "verify-runner-not-command-word: runner name as an argument" \
  "$(outcome_of 'echo pytest; printf "FAILED x\n"; exit 1')" error
check "verify-runner-not-command-word: uv run pytest stays red" \
  "$(outcome_of "$STUBS/uv run pytest")" red
check "verify-runner-not-command-word: python -m pytest stays red" \
  "$(outcome_of "$STUBS/python3 -m pytest")" red
check "verify-runner-not-command-word: npx vitest stays red" \
  "$(outcome_of "$STUBS/npx vitest")" red
check "verify-runner-not-command-word: timeout wraps the runner" \
  "$(outcome_of "timeout 60 $STUBS/pytest quiet")" red
check "verify-runner-not-command-word: cargo test stays red" \
  "$(outcome_of "$STUBS/cargo test")" red
check "verify-runner-not-command-word: pnpm exec vitest stays red" \
  "$(outcome_of "$STUBS/pnpm exec vitest")" red

cat > "$STUBS/systemd-run" <<'STUB'
#!/usr/bin/env bash
while [[ ${1:-} == -* ]]; do
  case $1 in
    -p|-E|-u|--property|--setenv|--unit|--expand-environment) shift 2 ;;
    *) shift ;;
  esac
done
exec "$@"
STUB
chmod +x "$STUBS/systemd-run"
SCOPE="$STUBS/systemd-run --user --scope --quiet -p MemoryMax=3G -p MemorySwapMax=0"
check "verify-systemd-run-wrapper: failing pytest is red" \
  "$(outcome_of "$SCOPE $STUBS/pytest quiet")" red
check "verify-systemd-run-wrapper: passing pytest is green" \
  "$(outcome_of "$SCOPE $STUBS/pytest green")" green
check "verify-systemd-run-wrapper: collection error stays error" \
  "$(outcome_of "$SCOPE $STUBS/pytest collect")" error
check "verify-systemd-run-wrapper: reported uv run shape is red" \
  "$(outcome_of "cd $PLAIN && $SCOPE $STUBS/uv run --frozen --with=httpx pytest -q -p no:cacheprovider tests/")" red
check "verify-systemd-run-expand-environment-value: failing pytest is red" \
  "$(outcome_of "$STUBS/systemd-run --user --scope --expand-environment false $STUBS/pytest quiet")" red
check "verify-systemd-run-wrapper: env failing pytest is red" \
  "$(outcome_of "env FOO=1 $STUBS/pytest quiet")" red
check "verify-systemd-run-wrapper: env collection error stays error" \
  "$(outcome_of "env FOO=1 $STUBS/pytest collect")" error
check "verify-systemd-run-wrapper: nice failing pytest is red" \
  "$(outcome_of "nice -n 5 $STUBS/pytest quiet")" red
check "verify-systemd-run-wrapper: nice passing pytest is green" \
  "$(outcome_of "nice -n 5 $STUBS/pytest green")" green
check "verify-systemd-run-wrapper: timeout passing pytest is green" \
  "$(outcome_of "timeout 60 $STUBS/pytest green")" green
check "verify-systemd-run-wrapper: timeout collection error stays error" \
  "$(outcome_of "timeout 60 $STUBS/pytest collect")" error

cat > "$TMP/unit-runner-word.py" <<'UNIT'
CASES = (
    ('printf "FAILED x\n"; exit 1;# pytest', False),
    ("echo pytest; printf 'FAILED x'; exit 1", False),
    ("echo 'pytest'", False),
    ("git commit -m 'pytest fixes'", False),
    ("ruff check src", False),
    ("uv run pytest", True),
    ("uvx pytest", True),
    ("python -m pytest", True),
    ("python3 -m pytest -q", True),
    ("npx vitest run", True),
    ("bunx vitest", True),
    ("poetry run pytest", True),
    ("pdm run pytest", True),
    ("hatch run pytest", True),
    ("pnpm exec vitest", True),
    ("pnpm dlx vitest", True),
    ("yarn dlx vitest", True),
    ("timeout 60 pytest", True),
    ("env FOO=1 pytest -q", True),
    ("nice -n 5 pytest", True),
    ("cargo test", True),
    ("cargo +nightly test", True),
    ("go test ./...", True),
    ("npm test", True),
    ("npm run test", True),
    ("systemd-run --user --scope --quiet -p MemoryMax=3G -p MemorySwapMax=0 uv run --frozen --with=httpx pytest -q -p no:cacheprovider tests/", True),
    ("systemd-run --user --scope -- pytest -q", True),
    ("systemd-run --unit=device-tests -p MemoryMax=3G pytest", True),
    ("systemd-run -u device-tests pytest", True),
    ("systemd-run --description 'unit tests' --user --scope pytest", True),
    ("systemd-run --user --scope -E FOO=1 pytest", True),
    ("/usr/bin/systemd-run --user --scope pytest", True),
    ("systemd-run --user --scope nice -n 5 timeout 60 env FOO=1 pytest", True),
    ("systemd-run --user --scope --expand-environment false pytest", True),
    ("systemd-run --user --scope ruff check src", False),
    ("systemd-run --user --scope echo pytest", False),
)
print(sum(1 for command, want in CASES if names_known_runner(command) == want), len(CASES))
UNIT
check "verify-runner-not-command-word: unit, runner is the command word or a launcher target" \
  "$(ledger_script "$TMP/unit-runner-word.py" 2>&1)" "36 36"

cat > "$TMP/unit-comments.py" <<'UNIT'
CASES = (
    ('printf "x"; exit 1;# pytest', 'printf "x"; exit 1;'),
    ("true |# pytest", "true |"),
    ("true &&# pytest", "true &&"),
    ("(# pytest", "("),
    ("printf x # pytest", "printf x "),
    ("echo a#b", "echo a#b"),
    ("echo '# not a comment'", "echo '# not a comment'"),
)
print(sum(1 for text, want in CASES if strip_comments(text) == want), len(CASES))
UNIT
check "verify-runner-not-command-word: unit, a comment may start right after a separator" \
  "$(ledger_script "$TMP/unit-comments.py" 2>&1)" "7 7"



cat > "$TMP/unit-lock.py" <<'UNIT'
import datetime
import json
import os
import subprocess
import sys
import time

HOLDER = ("import fcntl,sys,time\n"
          "handle = open(sys.argv[1], 'a')\n"
          "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
          "print('held', flush=True)\n"
          "time.sleep(60)\n")
EXPIRED_AGE_DAYS = 40
directory = os.environ["UNIT_LOCK_DIR"]
os.makedirs(directory, exist_ok=True)
ledger = os.path.join(directory, LEDGER_NAME)
expired = {"schema": SCHEMA_VERSION,
           "ts": (now() - datetime.timedelta(days=EXPIRED_AGE_DAYS)).isoformat(),
           "rc": 1, "outcome": OUTCOME_ERROR, "repo": "/tmp", "cmd": "pytest",
           "log": "/tmp/expired.log", "session_id": None, "slug": "pytest"}
with open(ledger, "w", encoding="utf-8") as handle:
    handle.write(json.dumps(expired) + "\n")
holder = subprocess.Popen([sys.executable, "-c", HOLDER, os.path.join(directory, LOCK_NAME)],
                          stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
record = LedgerRecord(schema=SCHEMA_VERSION, ts=now().isoformat(), rc=1, outcome=OUTCOME_ERROR,
                      repo="/tmp", cmd="pytest", log="/tmp/none.log", session_id=None, slug="pytest")
start = time.monotonic()
store(directory, record)
elapsed = time.monotonic() - start
holder.kill()
holder.wait()
written = len(open(ledger, encoding="utf-8").read().splitlines())
print(elapsed < LOCK_WAIT_BUDGET_SECONDS + 1, written)
UNIT
check "verify-lost-record-under-lock: unit, a held lock keeps the record and skips the prune" \
  "$(UNIT_LOCK_DIR=$TMP/lock-unit ledger_script "$TMP/unit-lock.py" 2>&1)" "True 2"

cat > "$TMP/release-on-line-holder.py" <<'HOLD'
import fcntl
import sys

handle = open(sys.argv[1], "a")
fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
print("held", flush=True)
sys.stdin.readline()
HOLD

cat > "$TMP/unit-append-waits.py" <<'UNIT'
import os
import subprocess
import sys
import threading
import time

PROBE_SECONDS = 0.2
directory = os.environ["UNIT_APPEND_DIR"]
os.makedirs(directory, exist_ok=True)
ledger = os.path.join(directory, LEDGER_NAME)
open(ledger, "w", encoding="utf-8").close()
holder = subprocess.Popen([sys.executable, os.environ["UNIT_HOLDER"], os.path.join(directory, LOCK_NAME)],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
writer = threading.Thread(target=append_line, args=(directory, "appended-line"))
writer.start()
time.sleep(PROBE_SECONDS)
written_while_held = os.path.getsize(ledger) > 0
still_waiting = writer.is_alive()
holder.stdin.write("\n")
holder.stdin.flush()
writer.join()
holder.wait()
written_after = open(ledger, encoding="utf-8").read().splitlines()
print(written_while_held, still_waiting, written_after)
UNIT
check "ledger: append waits for the prune lock" \
  "$(UNIT_HOLDER=$TMP/release-on-line-holder.py UNIT_APPEND_DIR=$TMP/append-waits ledger_script "$TMP/unit-append-waits.py" 2>&1)" \
  "False True ['appended-line']"

cat > "$TMP/unit-append-stuck.py" <<'UNIT'
import os
import subprocess
import sys
import time

MARGIN_SECONDS = 0.5
directory = os.environ["UNIT_APPEND_DIR"]
os.makedirs(directory, exist_ok=True)
ledger = os.path.join(directory, LEDGER_NAME)
holder = subprocess.Popen([sys.executable, os.environ["UNIT_HOLDER"], os.path.join(directory, LOCK_NAME)],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
holder.stdout.readline()
start = time.monotonic()
append_line(directory, "appended-line")
elapsed = time.monotonic() - start
holder.kill()
holder.wait()
written = open(ledger, encoding="utf-8").read().splitlines()
print(elapsed < LOCK_WAIT_BUDGET_SECONDS + MARGIN_SECONDS, written)
UNIT
check "ledger: append proceeds when the lock is stuck" \
  "$(UNIT_HOLDER=$TMP/release-on-line-holder.py UNIT_APPEND_DIR=$TMP/append-stuck ledger_script "$TMP/unit-append-stuck.py" 2>&1)" \
  "True ['appended-line']"

STUCK_RUN_MARGIN_SECONDS=0.25
STUCK_DIR=$TMP/stuck-run
mkdir -p "$STUCK_DIR" "$TMP/free-run"
elapsed_since() { python3 -c "print(round($(date +%s.%N) - $1, 3))"; }
FREE_START=$(date +%s.%N)
CLAUDE_VERIFY_LOG_DIR=$TMP/free-run "$VERIFY" -- 'true' >/dev/null 2>&1
FREE_ELAPSED=$(elapsed_since "$FREE_START")
mkfifo "$TMP/release-stuck"
python3 "$TMP/release-on-line-holder.py" "$STUCK_DIR/ledger.lock" < "$TMP/release-stuck" > "$TMP/stuck-holder.out" &
STUCK_PID=$!
exec 8> "$TMP/release-stuck"
HOLDER_READY_TRIES=200
for _ in $(seq "$HOLDER_READY_TRIES"); do [ -s "$TMP/stuck-holder.out" ] && break; sleep 0.05; done
STUCK_START=$(date +%s.%N)
CLAUDE_VERIFY_LOG_DIR=$STUCK_DIR "$VERIFY" -- 'true' >/dev/null 2>&1
STUCK_ELAPSED=$(elapsed_since "$STUCK_START")
echo >&8
exec 8>&-
wait "$STUCK_PID" 2>/dev/null
STUCK_BUDGET=$(ledger_eval LOCK_WAIT_BUDGET_SECONDS)
STUCK_EXTRA=$(python3 -c "print($STUCK_ELAPSED - $FREE_ELAPSED)")
check "ledger: stuck lock costs one budget" \
  "$(python3 -c "print($STUCK_BUDGET - $STUCK_RUN_MARGIN_SECONDS <= $STUCK_EXTRA <= $STUCK_BUDGET + $STUCK_RUN_MARGIN_SECONDS)")" True
check "ledger: stuck lock still records" "$(grep -c . "$STUCK_DIR/ledger.jsonl")" 1

if [ "$(id -u)" -ne 0 ]; then
  NOLOCK_DIR=$TMP/unwritable-lock
  mkdir -p "$NOLOCK_DIR"
  : > "$NOLOCK_DIR/ledger.lock"
  chmod 000 "$NOLOCK_DIR/ledger.lock"
  CLAUDE_VERIFY_LOG_DIR=$NOLOCK_DIR "$VERIFY" -- 'true' >/dev/null 2>&1
  check "ledger: unwritable lock file still records" "$(grep -c . "$NOLOCK_DIR/ledger.jsonl" 2>/dev/null || echo 0)" 1
  chmod 644 "$NOLOCK_DIR/ledger.lock"
fi

cat > "$TMP/unit-truncate.py" <<'UNIT'
OVERSIZED_CMD_CHARS = 9000
record = LedgerRecord(schema=SCHEMA_VERSION, ts=now().isoformat(), rc=1, outcome=OUTCOME_ERROR,
                      repo="/repo", cmd="z" * OVERSIZED_CMD_CHARS, log="/l.log",
                      session_id="s", slug="slug")
line = serialise(record)
parsed = json.loads(line)
print(len(line.encode("utf-8")) <= RECORD_MAX_BYTES, parsed["cmd"].endswith(TRUNCATED_CMD_SUFFIX),
      parsed["log"])
UNIT
check "verify-torn-record: unit, an over-long cmd is truncated, never dropped" \
  "$(ledger_script "$TMP/unit-truncate.py" 2>&1)" "True True /l.log"

rm -f "$LEDGER"
LONG_CMD="true $(python3 -c 'print("z" * 6000)')"
run_in "$PLAIN" -- "$LONG_CMD"
check "verify-torn-record: exit code with an over-long command" "$RC" 0
check "verify-torn-record: the record fits the atomic write bound" \
  "$(python3 - "$LEDGER" "$VERIFY" <<'PY'
import json, os, re, sys
lines = [line for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
source = open(sys.argv[2], encoding="utf-8").read()
bound = int(re.search(r"^RECORD_MAX_BYTES = (\d+)", source, re.M).group(1))
entry = json.loads(lines[-1])
print(len(lines), len(lines[-1].encode("utf-8")) <= bound, entry["outcome"])
PY
)" "1 True green"

cat > "$TMP/hold-lock.py" <<'HOLD'
import fcntl
import sys
import time

handle = open(sys.argv[1], "a")
fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
print("held", flush=True)
time.sleep(60)
HOLD
rm -f "$LEDGER"
printf 'stale\n' > "$CLAUDE_VERIFY_LOG_DIR/stale-under-lock.log"
touch -d '10 days ago' "$CLAUDE_VERIFY_LOG_DIR/stale-under-lock.log"
: > "$TMP/holder.out"
python3 "$TMP/hold-lock.py" "$CLAUDE_VERIFY_LOG_DIR/ledger.lock" > "$TMP/holder.out" 2>&1 &
HOLDER_PID=$!
WAITED=0
while ! grep -q held "$TMP/holder.out" 2>/dev/null; do
  sleep 0.05
  WAITED=$((WAITED + 1))
  [ "$WAITED" -gt 100 ] && break
done
LOCK_START=$(date +%s)
run_in "$PLAIN" -- 'exit 5'
check "verify-lost-record-under-lock: exit code under a held lock" "$RC" 5
expect "verify-lost-record-under-lock: normal output under a held lock" 5 "VERIFY FAIL exit=5"
run_in "$PLAIN" -- 'echo second under the lock'
run_in "$PLAIN" -- 'echo third under the lock'
LOCK_ELAPSED=$(( $(date +%s) - LOCK_START ))
kill "$HOLDER_PID" 2>/dev/null
wait "$HOLDER_PID" 2>/dev/null
check "verify-lost-record-under-lock: three runs under a held lock write three records" \
  "$(valid_lines)" 3
CASES=$((CASES + 1))
if [ -f "$CLAUDE_VERIFY_LOG_DIR/stale-under-lock.log" ]; then
  echo "FAIL verify-lost-record-under-lock: rotation did not run while the lock was held"
  FAILURES=$((FAILURES + 1))
fi
CASES=$((CASES + 1))
if [ "$LOCK_ELAPSED" -gt 5 ]; then
  echo "FAIL verify-lost-record-under-lock: three runs waited ${LOCK_ELAPSED}s on a held lock"
  FAILURES=$((FAILURES + 1))
fi

REL_OUT=$TMP/relative.out
(cd "$TMP" && CLAUDE_VERIFY_LOG_DIR=rel-logs "$VERIFY" -- 'echo relative log dir') > "$REL_OUT" 2>&1
REL_LOG=$(python3 - "$TMP/rel-logs/ledger.jsonl" <<'PY'
import json, os, sys
if not os.path.isfile(sys.argv[1]):
    print("no ledger file")
    raise SystemExit(0)
lines = [line for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
print(json.loads(lines[-1]).get("log", "") if lines else "empty ledger")
PY
)
check "verify-relative-log-dir: ledger log field is absolute" "${REL_LOG:0:1}" "/"
check "verify-relative-log-dir: printed log path is absolute" \
  "$(grep -c '^log: /' "$REL_OUT")" 1
check "verify-relative-log-dir: unit, a relative path is made absolute" \
  "$(ledger_eval 'absolute_path("rel/x.log") == os.path.join(os.getcwd(), "rel/x.log")')" True
check "verify-relative-log-dir: unit, an absolute path is left alone" \
  "$(ledger_eval 'absolute_path("/var/tmp/x.log")')" "/var/tmp/x.log"

LOGS=$(find "$CLAUDE_VERIFY_LOG_DIR" -name '*.log' | wc -l)
CASES=$((CASES + 1))
if [ "$LOGS" -lt 10 ]; then
  echo "FAIL logs: only $LOGS log files written"; FAILURES=$((FAILURES + 1))
fi

broken_ledger_is_silent() {
  local label=$1
  local out err rc
  out=$(cd "$PLAIN" && "$VERIFY" -- 'printf "one\ntwo\n"' 2>"$TMP/stderr"); rc=$?
  err=$(cat "$TMP/stderr")
  check "$label: exit code" "$rc" 0
  check "$label: nothing on stderr" "$err" ""
  check "$label: stdout unchanged" "$(canon <<<"$out")" "$GREEN_GOLDEN"
}

rm -rf "$LEDGER"
mkdir -p "$LEDGER"
broken_ledger_is_silent "ledger is a directory"
rmdir "$LEDGER"
printf '' > "$LEDGER"
chmod 000 "$LEDGER"
broken_ledger_is_silent "ledger is unwritable"
chmod 644 "$LEDGER"

USER_BUS=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bus
CGROUP_PROBE='cg=$(sed "s|^0::||" /proc/self/cgroup); echo "cgroup=$cg"; echo "cpu.max=$(cat /sys/fs/cgroup$cg/cpu.max)"; echo "memory.max=$(cat /sys/fs/cgroup$cg/memory.max)"; echo "markers=${VERIFY_LIMITED:-} ${BUN_MEMORY_LIMITED:-}"'
ALLOCATE_256M='python3 -c "b = b\"x\" * (256 * 1024 * 1024); print(len(b))"'

run_unlimited_env() { OUT=$(env -u VERIFY_LIMITED -u VERIFY_NO_LIMITS "$@" 2>&1); RC=$?; }
log_as_out() { OUT=$(cat "$(sed -n 's/^log: //p' <<<"$OUT")"); }
skip_without_bus() {
  [ -S "$USER_BUS" ] && return 1
  echo "SKIP $1"
  return 0
}

if ! skip_without_bus "limits: scope cpu.max and memory.max"; then
  run_unlimited_env "$VERIFY" -- "$CGROUP_PROBE"
  log_as_out
  expect "limits: scope cpu.max and memory.max" 0 "cpu.max=600000 100000"
  expect "limits: scope memory.max" 0 "memory.max=6442450944"
  expect "limits: runs in a transient scope" 0 "/run-"
fi

if ! skip_without_bus "limits: env markers exported"; then
  run_unlimited_env "$VERIFY" -- "$CGROUP_PROBE"
  log_as_out
  expect "limits: env markers exported" 0 "markers=1 1"
fi

if ! skip_without_bus "limits: memory cap kills with hint"; then
  run_unlimited_env env VERIFY_MEMORY_MAX=64M VERIFY_SWAP_MAX=0 "$VERIFY" -- "$ALLOCATE_256M"
  expect "limits: memory cap kills with hint" 137 "limits: exit 137"
  expect "limits: hint names the limit and the lifts" 137 "VERIFY_MEMORY_MAX=... or VERIFY_NO_LIMITS=1 lifts it"
  expect "limits: hint names the memory limit" 137 "64M"
fi

OWN_CGROUP=$(sed "s|^0::||" /proc/self/cgroup)
run_unlimited_env env VERIFY_NO_LIMITS=1 "$VERIFY" -- "$CGROUP_PROBE"
log_as_out
expect "limits: opt-out has no scope" 0 "cgroup=$OWN_CGROUP"
expect "limits: opt-out still exports markers" 0 "markers=1 1"
run_unlimited_env env VERIFY_NO_LIMITS=1 "$VERIFY" -- 'exit 137'
expect "limits: opt-out prints no hint" 137 "VERIFY FAIL exit=137" "limits: exit 137"

if ! skip_without_bus "limits: nested verify opens no second scope"; then
  run_unlimited_env "$VERIFY" -- "$VERIFY -- 'sed \"s|^0::||\" /proc/self/cgroup >$TMP/inner' >/dev/null; sed 's|^0::||' /proc/self/cgroup >$TMP/outer"
  inner=$(cat "$TMP/inner" 2>/dev/null)
  outer=$(cat "$TMP/outer" 2>/dev/null)
  CASES=$((CASES + 1))
  [ -n "$inner" ] && [ "$inner" = "$outer" ] || { echo "FAIL limits: nested verify opens no second scope: $inner vs $outer"; FAILURES=$((FAILURES + 1)); }
fi

echo "verify: $VERIFY"
echo "cases: $CASES, FAILURES: $FAILURES"
[ "$FAILURES" -eq 0 ] && echo "PASS $CASES/$CASES" || echo "FAIL"
exit $((FAILURES > 0))
