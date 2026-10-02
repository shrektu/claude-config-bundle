#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: quality-gate-test.sh [PATH_TO_QUALITY_GATE]
Checks the contract of bin/quality-gate on throwaway git repos: findings only on changed lines, base
resolution, skipped and failed tools, repo type config, and the TypeScript branch with fake tsc/jscpd.
USAGE
}
set -uo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
GATE=${1:-$HERE/quality-gate}
[ -x "$GATE" ] || { echo "not executable: $GATE"; exit 1; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILURES=0
CASES=0
REPO=
GATE_PATH=$PATH
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

OK_PY=$'def add(left: int, right: int) -> int:\n    return left + right\n'
BAD_PY=$'\n\ndef bad() -> int:\n    return "text"\n\n\nprint(bad())\n'
BLOCK_PY=$'def work(items: list[int]) -> int:\n    total = 0\n    for item in items:\n        total += item * 2\n        if total > 100:\n            total -= 3\n    result = total + 1\n    return result\n'
TSC_ERROR="src/a.ts(2,7): error TS2322: Type 'string' is not assignable to type 'number'."

expect() {
  local label=$1 want_rc=$2 needle=$3 absent=${4:-}
  CASES=$((CASES + 1))
  if [ "$RC" != "$want_rc" ]; then
    echo "FAIL $label: exit $RC, wanted $want_rc"; echo "$OUT"; FAILURES=$((FAILURES + 1)); return
  fi
  if [ -n "$needle" ] && ! grep -qF -- "$needle" <<<"$OUT"; then
    echo "FAIL $label: missing '$needle' in:"; echo "$OUT"; FAILURES=$((FAILURES + 1)); return
  fi
  if [ -n "$absent" ] && grep -qF -- "$absent" <<<"$OUT"; then
    echo "FAIL $label: unexpected '$absent' in:"; echo "$OUT"; FAILURES=$((FAILURES + 1)); return
  fi
}

gate() { OUT=$(cd "$REPO" && PATH=$GATE_PATH "$GATE" "$@" 2>&1); RC=$?; }

new_repo() {
  REPO=$TMP/$1
  mkdir -p "$REPO"
  git -C "$REPO" init -q -b main
  git -C "$REPO" config user.email test@example.com
  git -C "$REPO" config user.name test
  git -C "$REPO" config commit.gpgsign false
}

commit_all() {
  git -C "$REPO" add -A
  git -C "$REPO" commit -q -m "$1"
}

put() { mkdir -p "$(dirname "$REPO/$1")"; printf '%s' "$2" >"$REPO/$1"; }
append() { printf '%s' "$2" >>"$REPO/$1"; }

fake_tool() {
  mkdir -p "$1"
  printf '%s\n' "#!/bin/sh" "$3" >"$1/$2"
  chmod +x "$1/$2"
}

new_repo typed
put pkg/ok.py "$OK_PY"
commit_all base
append pkg/ok.py "$BAD_PY"
gate
expect "mypy error on a changed line" 1 "pkg/ok.py:6 mypy:"
expect "mypy count line" 1 "quality-gate: 1 findings"

commit_all "bad on base"
append pkg/ok.py $'\n\ndef good() -> int:\n    return 1\n\n\nprint(good())\n'
gate
expect "same error on an unchanged line" 0 "quality-gate: 0 findings" "mypy:"

gate --base HEAD~1
expect "--base reaches back to the bad commit" 1 "pkg/ok.py:6 mypy:"

new_repo clean
put pkg/ok.py "$OK_PY"
commit_all base
gate
expect "no changes" 0 "quality-gate: 0 findings"

put pkg/dead.py $'import os\n'
gate
expect "untracked file with an unused import" 1 "pkg/dead.py:1 vulture:"

new_repo duplicates
put pkg/a.py "$BLOCK_PY"
commit_all base
put pkg/b.py "$BLOCK_PY"
gate
expect "duplicated block next to an existing one" 1 "pkg/b.py:2 pylint:" "pkg/a.py:"

new_repo missing
put pkg/ok.py "$OK_PY"
commit_all base
put pkg/new.py "$OK_PY"
NOVULTURE=$TMP/no-vulture-bin
mkdir -p "$NOVULTURE"
for tool in git python3 mypy pylint; do ln -s "$(command -v $tool)" "$NOVULTURE/$tool"; done
GATE_PATH=$NOVULTURE
gate
expect "missing vulture is skipped" 0 "skipped: vulture (install: uv tool install vulture)"
GATE_PATH=$PATH

CRASH_BIN=$TMP/crash-bin
fake_tool "$CRASH_BIN" mypy 'echo boom >&2; exit 2'
GATE_PATH=$CRASH_BIN:$PATH
gate
expect "crashing mypy fails the gate" 2 "failed: mypy (boom)"

GARBAGE_BIN=$TMP/garbage-bin
fake_tool "$GARBAGE_BIN" mypy 'echo "not a diagnostic"; exit 1'
GATE_PATH=$GARBAGE_BIN:$PATH
gate
expect "unparseable mypy output fails the gate" 2 "failed: mypy"

SLOW_BIN=$TMP/slow-bin
fake_tool "$SLOW_BIN" mypy 'sleep 5'
GATE_PATH=$SLOW_BIN:$PATH
OUT=$(cd "$REPO" && QUALITY_TOOL_TIMEOUT_S=1 PATH=$GATE_PATH "$GATE" 2>&1); RC=$?
expect "mypy timeout fails the gate" 2 "failed: mypy (timeout)"
GATE_PATH=$PATH

new_repo upstream
put pkg/ok.py "$OK_PY"
commit_all base
git clone -q "$TMP/upstream" "$TMP/downstream"
REPO=$TMP/downstream
git -C "$REPO" config user.email test@example.com
git -C "$REPO" config user.name test
git -C "$REPO" config commit.gpgsign false
git -C "$REPO" checkout -q -b feature
append pkg/ok.py "$BAD_PY"
commit_all "feature work"
gate
expect "default base is the merge-base with origin/HEAD" 1 "pkg/ok.py:6 mypy:"
gate --base HEAD
expect "explicit --base HEAD hides committed work" 0 "quality-gate: 0 findings"

new_repo loose
put mypy.ini $'[mypy]\n'
put pkg/ok.py "$OK_PY"
commit_all base
append pkg/ok.py $'\n\ndef loose(value):\n    return value\n\n\nprint(loose(1))\n'
gate
expect "repo mypy config replaces --strict" 0 "quality-gate: 0 findings"

new_repo strict
put pkg/ok.py "$OK_PY"
commit_all base
append pkg/ok.py $'\n\ndef loose(value):\n    return value\n'
gate
expect "no repo config means mypy --strict" 1 "mypy:"

new_repo pyrighted
put pyrightconfig.json '{}'
put pkg/ok.py "$OK_PY"
commit_all base
append pkg/ok.py $'\n\ndef later() -> int:\n    return 1\n'
PYRIGHT_BIN=$TMP/pyright-bin
fake_tool "$PYRIGHT_BIN" pyright "cat <<JSON
{\"generalDiagnostics\": [
 {\"file\": \"$REPO/pkg/ok.py\", \"severity\": \"error\", \"message\": \"changed line problem\", \"range\": {\"start\": {\"line\": 4, \"character\": 0}}},
 {\"file\": \"$REPO/pkg/ok.py\", \"severity\": \"error\", \"message\": \"old line problem\", \"range\": {\"start\": {\"line\": 0, \"character\": 0}}}
]}
JSON
exit 1"
GATE_PATH=$PYRIGHT_BIN:$PATH
gate
expect "pyright reports changed lines" 1 "pkg/ok.py:5 pyright: changed line problem" "old line problem"
GATE_PATH=$PATH

API_PY=$'from collections.abc import Callable\nfrom typing import TypeVar\n\nHandler = TypeVar("Handler", bound=Callable[[], int])\n\n\nclass Router:\n    def get(self, handler: Handler) -> Handler:\n        return handler\n\n    def fixture(self, handler: Handler) -> Handler:\n        return handler\n\n\nrouter = Router()\n\n\n@router.get\ndef read_value() -> int:\n    return 1\n\n\n@router.fixture\ndef make_value() -> int:\n    return 2\n'
HELPER_PY=$'def helper() -> int:\n    return 1\n'

new_repo deadcode
put pkg/ok.py "$OK_PY"
commit_all base
put pkg/dead.py "$HELPER_PY"
gate
expect "unused function on a changed line" 1 "pkg/dead.py:1 vulture:"

new_repo usedcode
put pkg/user.py $'from pkg.dead import helper\n\nprint(helper())\n'
commit_all base
put pkg/dead.py "$HELPER_PY"
gate
expect "function used from another tracked file" 0 "quality-gate: 0 findings"

new_repo registered
put pkg/ok.py "$OK_PY"
commit_all base
put pkg/api.py "$API_PY"
gate
expect "framework-registered handlers are not dead code" 0 "quality-gate: 0 findings"

new_repo crossdir
put alpha/a.py "$BLOCK_PY"
commit_all base
put beta/b.py "$BLOCK_PY"
gate
expect "duplicate across top-level directories" 1 "beta/b.py:2 pylint:"

new_repo localpyright
put pyrightconfig.json '{}'
put pkg/ok.py "$OK_PY"
commit_all base
append pkg/ok.py $'\n\ndef later() -> int:\n    return 1\n\n\nprint(later())\n'
fake_tool "$REPO/node_modules/.bin" pyright "cat <<JSON
{\"generalDiagnostics\": [
 {\"file\": \"$REPO/pkg/ok.py\", \"severity\": \"error\", \"message\": \"local binary problem\", \"range\": {\"start\": {\"line\": 4, \"character\": 0}}}
]}
JSON
exit 1"
gate
expect "repo-local pyright is preferred over PATH" 1 "pkg/ok.py:5 pyright: local binary problem"

new_repo web
put .gitignore $'node_modules\n'
put web/tsconfig.json '{}'
put web/src/b.ts $'export const b = 1;\nexport const c = 2;\nexport const d = 3;\n'
commit_all base
put web/src/a.ts $'export const a = 1;\nexport const e: number = "x";\nexport const f = 3;\n'
gate
expect "ts project without tsc is skipped" 0 "skipped: tsc"

fake_tool "$REPO/web/node_modules/.bin" tsc "cat <<'OUT'
$TSC_ERROR
src/b.ts(1,1): error TS1000: old problem
OUT
exit 2"
gate
expect "tsc error on a changed line" 1 "web/src/a.ts:2 tsc:" "old problem"

fake_tool "$REPO/web/node_modules/.bin" jscpd 'out=
while [ $# -gt 0 ]; do case $1 in --output) out=$2; shift ;; esac; shift; done
cat >"$out/jscpd-report.json" <<'"'"'JSON'"'"'
{"duplicates": [{"format": "typescript", "lines": 3,
  "firstFile": {"name": "web/src/a.ts", "start": 1, "end": 3},
  "secondFile": {"name": "web/src/b.ts", "start": 1, "end": 3}}]}
JSON'
gate
expect "jscpd clone touching a changed file" 1 "web/src/a.ts:1 jscpd:" "web/src/b.ts:1 jscpd:"
expect "tsc and jscpd both counted" 1 "quality-gate: 2 findings"

echo "quality-gate matrix: $CASES checks, $FAILURES failed"
[ "$FAILURES" -eq 0 ]
