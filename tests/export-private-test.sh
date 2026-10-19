#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: tests/export-private-test.sh
Runs export.sh on a throwaway HOME with optional exclude.local, scrub.local.sed and leak-check.local
files next to a copy of export.sh, and checks that private content never reaches the exported
directory. Touches nothing outside its temporary directories.
USAGE
}
set -uo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAILURES=0
CHECKS=0
CASE_NO=0
HERE_DIR=
FAKE_HOME=
OUT=
STATUS=0
EXPORT_PATH=$PATH

fail() { echo "FAIL $1"; FAILURES=$((FAILURES + 1)); }
expect() { CHECKS=$((CHECKS + 1)); if [ "$2" != "$3" ]; then fail "$1 (expected $2, got $3)"; fi; }
expect_present() { CHECKS=$((CHECKS + 1)); [ -e "$OUT/$2" ] || fail "$1: missing $2"; }
expect_absent() { CHECKS=$((CHECKS + 1)); [ ! -e "$OUT/$2" ] || fail "$1: still present $2"; }
expect_in_file() { CHECKS=$((CHECKS + 1)); grep -qF -- "$3" "$2" 2>/dev/null || fail "$1: '$3' not in $2"; }
expect_not_in_file() { CHECKS=$((CHECKS + 1)); ! grep -qF -- "$3" "$2" 2>/dev/null || fail "$1: '$3' still in $2"; }

new_case() {
  CASE_NO=$((CASE_NO + 1))
  local base=$WORK/case$CASE_NO
  HERE_DIR=$base/here
  FAKE_HOME=$base/home
  OUT=$base/out
  mkdir -p "$HERE_DIR" "$FAKE_HOME/.claude/mcp/codex-worker" "$FAKE_HOME/.codex"
  cp "$ROOT/export.sh" "$HERE_DIR/export.sh"
  echo "install" > "$HERE_DIR/install.sh"
  echo "readme" > "$HERE_DIR/README.md"
  local c=$FAKE_HOME/.claude
  mkdir -p "$c/agents" "$c/skills/keep" "$c/skills/secret-skill" "$c/bin" "$c/hooks" "$c/lint"
  echo "agent for acmecorp" > "$c/agents/worker.md"
  echo "keep skill" > "$c/skills/keep/SKILL.md"
  echo "secret skill" > "$c/skills/secret-skill/SKILL.md"
  printf '#!/bin/sh\necho acmecorp\n' > "$c/bin/tool"
  echo 'NAME = "acmecorp"' > "$c/hooks/guard.py"
  echo "ruff" > "$c/lint/ruff.toml"
  echo "claude" > "$c/CLAUDE.md"
  echo "status" > "$c/statusline-command.sh"
  echo "worker" > "$c/mcp/codex-worker/codex_worker.py"
  echo "worker test" > "$c/mcp/codex-worker/codex_worker_test.py"
  echo "requests" > "$c/mcp/codex-worker/requirements.txt"
  echo "{}" > "$c/settings.json"
  echo "codex" > "$FAKE_HOME/.codex/AGENTS.md"
}

add_junk() {
  local c=$FAKE_HOME/.claude
  mkdir -p "$c/skills/synced/inner" "$c/hooks/.pytest_cache" "$c/hooks/.ruff_cache" "$c/hooks/__pycache__"
  echo "synced" > "$c/skills/synced/inner/SKILL.md"
  echo "cache" > "$c/hooks/.pytest_cache/state"
  echo "cache" > "$c/hooks/.ruff_cache/state"
  echo "cache" > "$c/hooks/__pycache__/guard.pyc"
  echo "backup" > "$c/bin/tool.bak"
  echo "backup" > "$c/CLAUDE.md.bak-2026-10-15"
}

run_export() {
  env -i HOME="$FAKE_HOME" PATH="$EXPORT_PATH" USER=tester TERM=dumb \
    bash "$HERE_DIR/export.sh" "$OUT" >"$WORK/case$CASE_NO.log" 2>&1
  STATUS=$?
}

new_case
echo "claude/skills/secret-skill" > "$HERE_DIR/exclude.local"
run_export
expect "exclude.local removes listed path: exit" 0 "$STATUS"
expect_absent "exclude.local removes listed path" claude/skills/secret-skill
expect_present "exclude.local removes listed path: sibling kept" claude/skills/keep/SKILL.md

new_case
add_junk
run_export
expect "junk always dropped: exit" 0 "$STATUS"
expect_absent "junk always dropped" claude/bin/tool.bak
expect_absent "junk always dropped" claude/CLAUDE.md.bak-2026-10-15
expect_absent "junk always dropped" claude/hooks/.pytest_cache
expect_absent "junk always dropped" claude/hooks/.ruff_cache
expect_absent "junk always dropped" claude/hooks/__pycache__
expect_absent "junk always dropped" claude/skills/synced
expect_present "junk always dropped: real files kept" claude/bin/tool

new_case
echo 's/acmecorp/example/g' > "$HERE_DIR/scrub.local.sed"
run_export
expect "scrub applied to md/py/bin: exit" 0 "$STATUS"
expect_in_file "scrub applied to md" "$OUT/claude/agents/worker.md" "agent for example"
expect_in_file "scrub applied to py" "$OUT/claude/hooks/guard.py" 'NAME = "example"'
expect_in_file "scrub applied to bin" "$OUT/claude/bin/tool" "echo example"
expect_not_in_file "scrub applied to md" "$OUT/claude/agents/worker.md" acmecorp
expect_not_in_file "scrub applied to py" "$OUT/claude/hooks/guard.py" acmecorp
expect_not_in_file "scrub applied to bin" "$OUT/claude/bin/tool" acmecorp

new_case
echo 'acmecorp' > "$HERE_DIR/leak-check.local"
run_export
expect "leak hit aborts with exit 3" 3 "$STATUS"
expect_in_file "leak hit reported" "$WORK/case$CASE_NO.log" "export: private content found:"
expect_in_file "leak hit names file and line" "$WORK/case$CASE_NO.log" "agents/worker.md:1"
expect_absent "leak hit writes no manifest" manifest.txt
CHECKS=$((CHECKS + 1)); [ ! -e "$OUT.tar.gz" ] || fail "leak hit writes no tarball"

for bad in /etc ../x; do
  new_case
  echo "$bad" > "$HERE_DIR/exclude.local"
  run_export
  expect "unsafe exclude entry $bad exits 2" 2 "$STATUS"
  expect_in_file "unsafe exclude entry $bad message" "$WORK/case$CASE_NO.log" "refusing exclude entry"
done

new_case
echo "claude/skills/secret-skill" > "$HERE_DIR/exclude.local"
echo 's/acmecorp/example/g' > "$HERE_DIR/scrub.local.sed"
echo 'zzz-no-match' > "$HERE_DIR/leak-check.local"
run_export
expect "local files never exported: exit" 0 "$STATUS"
CHECKS=$((CHECKS + 1))
if [ -n "$(find "$OUT" -name '*.local*' -print)" ]; then fail "local files never exported"; fi

new_case
add_junk
run_export
expect "no local files keeps file set: exit" 0 "$STATUS"
EXPECTED_FILES="./README.md
./claude/CLAUDE.md
./claude/agents/worker.md
./claude/bin/tool
./claude/hooks/guard.py
./claude/lint/ruff.toml
./claude/mcp-servers.json
./claude/mcp/codex-worker/codex_worker.py
./claude/mcp/codex-worker/codex_worker_test.py
./claude/mcp/codex-worker/requirements.txt
./claude/settings.json
./claude/skills/keep/SKILL.md
./claude/skills/secret-skill/SKILL.md
./claude/statusline-command.sh
./codex/AGENTS.md
./codex/config.fragment.toml
./export.sh
./install.sh
./manifest.txt"
ACTUAL_FILES=$(cd "$OUT" && find . -type f | LC_ALL=C sort)
CHECKS=$((CHECKS + 1))
if [ "$ACTUAL_FILES" != "$EXPECTED_FILES" ]; then
  fail "no local files keeps file set"
  diff <(echo "$EXPECTED_FILES") <(echo "$ACTUAL_FILES")
fi

new_case
rm -rf "$FAKE_HOME/.claude/lint" "$FAKE_HOME/.claude/mcp/codex-worker/codex_worker_test.py"
run_export
expect "missing optional sources still export: exit (see $WORK/case$CASE_NO.log)" 0 "$STATUS"
expect_present "missing optional sources still export" claude/mcp/codex-worker/codex_worker.py
expect_present "missing optional sources still export" claude/mcp/codex-worker/requirements.txt
expect_absent "missing optional sources still export" claude/lint
expect_absent "missing optional sources still export" claude/mcp/codex-worker/codex_worker_test.py

new_case
mkdir -p "$WORK/fakebin"
printf '#!/bin/sh\necho acmehost\n' > "$WORK/fakebin/hostname"
chmod 755 "$WORK/fakebin/hostname"
EXPORT_PATH=$WORK/fakebin:$PATH
echo 'acmehost' > "$HERE_DIR/leak-check.local"
run_export
EXPORT_PATH=$PATH
expect "leak in manifest metadata aborts with exit 3" 3 "$STATUS"
expect_in_file "leak in manifest metadata reported" "$WORK/case$CASE_NO.log" "manifest.txt"
expect_absent "leak in manifest metadata leaves no manifest" manifest.txt
CHECKS=$((CHECKS + 1)); [ ! -e "$OUT.tar.gz" ] || fail "leak in manifest metadata writes no tarball"

new_case
printf 'head\0acmecorp\0tail\n' > "$FAKE_HOME/.claude/bin/blob"
echo 'acmecorp' > "$HERE_DIR/leak-check.local"
run_export
expect "leak inside a binary file aborts with exit 3" 3 "$STATUS"
expect_in_file "leak inside a binary file reported" "$WORK/case$CASE_NO.log" "bin/blob"
expect_absent "leak inside a binary file leaves no manifest" manifest.txt

new_case
cp "$ROOT/install.sh" "$HERE_DIR/install.sh"
rm -f "$FAKE_HOME/.claude/mcp/codex-worker/codex_worker_test.py"
run_export
expect "install works without codex_worker_test.py: export exit" 0 "$STATUS"
INSTALL_HOME=$WORK/install-home
mkdir -p "$INSTALL_HOME/.claude/mcp/codex-worker/.venv/bin" "$WORK/installbin"
printf '#!/bin/sh\nexit 0\n' > "$INSTALL_HOME/.claude/mcp/codex-worker/.venv/bin/python"
chmod 755 "$INSTALL_HOME/.claude/mcp/codex-worker/.venv/bin/python"
cp "$OUT/claude/mcp/codex-worker/requirements.txt" "$INSTALL_HOME/.claude/mcp/codex-worker/.venv/.installed-requirements"
printf '#!/bin/sh\necho "codex-cli 0.0.0-test"\n' > "$WORK/installbin/codex"
chmod 755 "$WORK/installbin/codex"
env -i HOME="$INSTALL_HOME" PATH="$WORK/installbin:/usr/bin:/bin" USER=tester TERM=dumb \
  bash "$OUT/install.sh" >"$WORK/install-case.log" 2>&1
expect "install works without codex_worker_test.py: install exit (see $WORK/install-case.log)" 0 "$?"
CHECKS=$((CHECKS + 1))
[ -f "$INSTALL_HOME/.claude/mcp/codex-worker/codex_worker.py" ] || fail "install works without codex_worker_test.py: worker missing"

new_case
printf '# private skills\n\n  claude/skills/secret-skill  \nclaude/skills/missing\n' > "$HERE_DIR/exclude.local"
run_export
expect "exclude.local comments, blanks, spaces and missing path: exit" 0 "$STATUS"
expect_absent "exclude.local trailing spaces trimmed" claude/skills/secret-skill
expect_present "exclude.local comment line not treated as path" claude/skills/keep/SKILL.md

new_case
: > "$HERE_DIR/scrub.local.sed"
run_export
expect "empty scrub file is a no-op: exit" 0 "$STATUS"
expect_in_file "empty scrub file is a no-op" "$OUT/claude/agents/worker.md" "agent for acmecorp"

new_case
printf '# regexes\n\nacme(corp|host)\\.example\\.com\n' > "$HERE_DIR/leak-check.local"
echo "see https://acmecorp.example.com/x" > "$HERE_DIR/README.md"
run_export
expect "leak regex with special characters in README from here: exit" 3 "$STATUS"
expect_in_file "leak regex with special characters names README" "$WORK/case$CASE_NO.log" "README.md:1"

new_case
echo "acmecorp" > "$HERE_DIR/install.sh"
echo 'acmecorp' > "$HERE_DIR/leak-check.local"
run_export
expect "leak in install.sh copied from here is caught" 3 "$STATUS"
expect_in_file "leak in install.sh reported" "$WORK/case$CASE_NO.log" "install.sh:1"

new_case
mkdir -p "$WORK/outside"
echo "keep me" > "$WORK/outside/sentinel"
ln -s "$WORK/outside" "$FAKE_HOME/.claude/skills/link"
echo "claude/skills/link/sentinel" > "$HERE_DIR/exclude.local"
run_export
expect "exclude through symlink outside OUT is refused: exit" 2 "$STATUS"
expect_in_file "exclude through symlink outside OUT message" "$WORK/case$CASE_NO.log" "refusing exclude entry"
CHECKS=$((CHECKS + 1)); [ -e "$WORK/outside/sentinel" ] || fail "exclude through symlink deleted a file outside OUT"

new_case
printf 'owner: acmecorp\n' > "$FAKE_HOME/.claude/skills/keep/meta.yaml"
printf 'notes for acmecorp\n' > "$FAKE_HOME/.claude/skills/keep/NOTES"
echo 's/acmecorp/example/g' > "$HERE_DIR/scrub.local.sed"
run_export
expect "scrub covers yaml and extensionless files: exit" 0 "$STATUS"
expect_in_file "scrub covers yaml" "$OUT/claude/skills/keep/meta.yaml" "owner: example"
expect_in_file "scrub covers extensionless" "$OUT/claude/skills/keep/NOTES" "notes for example"

new_case
echo "stale" > "$OUT.tar.gz"
echo 'acmecorp' > "$HERE_DIR/leak-check.local"
run_export
expect "leak abort leaves no stale tarball: exit" 3 "$STATUS"
CHECKS=$((CHECKS + 1)); [ ! -e "$OUT.tar.gz" ] || fail "leak abort leaves a stale tarball"

new_case
echo 'acme(' > "$HERE_DIR/leak-check.local"
run_export
expect "invalid leak regex aborts: exit" 3 "$STATUS"
expect_in_file "invalid leak regex message" "$WORK/case$CASE_NO.log" "export: invalid leak pattern: acme("
expect_absent "invalid leak regex leaves no manifest" manifest.txt

new_case
printf 'claude\ncodex\n' > "$HERE_DIR/exclude.local"
run_export
expect "export with every text file excluded still succeeds: exit" 0 "$STATUS"

echo "checks: $CHECKS, FAILURES: $FAILURES"
if [ "$FAILURES" != 0 ]; then
  echo "logs kept in $WORK"
  trap - EXIT
  echo "FAIL"
  exit 1
fi
echo "PASS $CHECKS/$CHECKS"
