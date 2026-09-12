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

LOGS=$(find "$CLAUDE_VERIFY_LOG_DIR" -name '*.log' | wc -l)
CASES=$((CASES + 1))
if [ "$LOGS" -lt 10 ]; then
  echo "FAIL logs: only $LOGS log files written"; FAILURES=$((FAILURES + 1))
fi

echo "verify: $VERIFY"
echo "cases: $CASES, FAILURES: $FAILURES"
[ "$FAILURES" -eq 0 ] && echo "PASS $CASES/$CASES" || echo "FAIL"
exit $((FAILURES > 0))
