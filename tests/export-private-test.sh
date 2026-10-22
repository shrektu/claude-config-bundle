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
  echo "worker test" > "$c/mcp/codex-worker/test_codex_worker.py"
  echo "requests" > "$c/mcp/codex-worker/requirements.txt"
  echo "{}" > "$c/settings.json"
  echo "codex" > "$FAKE_HOME/.codex/AGENTS.md"
  add_agy_worker
}

add_agy_worker() {
  local a=$FAKE_HOME/.claude/mcp/agy-worker
  mkdir -p "$a/.venv/bin" "$a/__pycache__" "$a/.pytest_cache" "$a/.hypothesis"
  for f in agy_worker.py agy_runner.py test_agy_worker.py conftest.py helpers_test.py; do
    echo "# $f" > "$a/$f"
  done
  echo "mcp==1.27.0" > "$a/requirements.txt"
  echo "pytest" > "$a/requirements-dev.txt"
  echo "[tool.pytest.ini_options]" > "$a/pyproject.toml"
  echo "github.com/*" > "$a/allowed-remotes.txt"
  echo "venv python" > "$a/.venv/bin/python"
  echo "cache" > "$a/__pycache__/agy_worker.pyc"
  echo "cache" > "$a/.pytest_cache/state"
  echo "cache" > "$a/.hypothesis/state"
  echo "scratch" > "$a/scratch.log"
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
./claude/mcp/agy-worker/agy_runner.py
./claude/mcp/agy-worker/agy_worker.py
./claude/mcp/agy-worker/allowed-remotes.txt
./claude/mcp/agy-worker/conftest.py
./claude/mcp/agy-worker/helpers_test.py
./claude/mcp/agy-worker/pyproject.toml
./claude/mcp/agy-worker/requirements-dev.txt
./claude/mcp/agy-worker/requirements.txt
./claude/mcp/agy-worker/test_agy_worker.py
./claude/mcp/codex-worker/codex_worker.py
./claude/mcp/codex-worker/requirements.txt
./claude/mcp/codex-worker/test_codex_worker.py
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
rm -rf "$FAKE_HOME/.claude/lint" "$FAKE_HOME/.claude/mcp/codex-worker/test_codex_worker.py"
run_export
expect "missing optional sources still export: exit (see $WORK/case$CASE_NO.log)" 0 "$STATUS"
expect_present "missing optional sources still export" claude/mcp/codex-worker/codex_worker.py
expect_present "missing optional sources still export" claude/mcp/codex-worker/requirements.txt
expect_absent "missing optional sources still export" claude/lint
expect_absent "missing optional sources still export" claude/mcp/codex-worker/test_codex_worker.py
expect_absent "missing optional sources still export" claude/mcp/codex-worker/codex_worker_test.py

new_case
cp "$FAKE_HOME/.claude/mcp/codex-worker/test_codex_worker.py" "$FAKE_HOME/.claude/mcp/codex-worker/codex_worker_test.py"
run_export
expect "legacy codex-worker test name is not exported: exit" 0 "$STATUS"
expect_present "current codex-worker test name exported" claude/mcp/codex-worker/test_codex_worker.py
expect_absent "legacy codex-worker test name is not exported" claude/mcp/codex-worker/codex_worker_test.py

new_case
rm -rf "$FAKE_HOME/.claude/mcp/agy-worker"
run_export
expect "export without agy-worker: exit (see $WORK/case$CASE_NO.log)" 0 "$STATUS"
CHECKS=$((CHECKS + 1))
[ -f "$OUT.tar.gz" ] || fail "export without agy-worker writes no tarball"
expect_absent "export without agy-worker" claude/mcp/agy-worker
expect_present "export without agy-worker keeps codex-worker" claude/mcp/codex-worker/codex_worker.py
expect_in_file "export without agy-worker keeps the codex entry" "$OUT/claude/mcp-servers.json" '"codex-worker"'
expect_not_in_file "export without agy-worker drops the mcp entry" "$OUT/claude/mcp-servers.json" agy-worker

new_case
run_export
expect "agy-worker export: exit (see $WORK/case$CASE_NO.log)" 0 "$STATUS"
for f in agy_worker.py agy_runner.py test_agy_worker.py conftest.py helpers_test.py requirements.txt \
         requirements-dev.txt pyproject.toml allowed-remotes.txt; do
  expect_present "agy-worker export" "claude/mcp/agy-worker/$f"
done
expect_present "codex-worker test under its current name" claude/mcp/codex-worker/test_codex_worker.py
for junk in .venv __pycache__ .pytest_cache .hypothesis scratch.log; do
  expect_absent "agy-worker export leaves out $junk" "claude/mcp/agy-worker/$junk"
done
CHECKS=$((CHECKS + 1))
python3 - "$OUT/claude/mcp-servers.json" <<'PY' || fail "mcp-servers.json agy-worker entry"
import json, sys
servers = json.load(open(sys.argv[1]))["mcpServers"]
wanted = {
    "type": "stdio",
    "command": "__HOME__/.claude/mcp/agy-worker/.venv/bin/python",
    "args": ["__HOME__/.claude/mcp/agy-worker/agy_worker.py"],
    "env": {"AGY_BIN": "__AGY_BIN__"},
    "timeout": 5400000,
}
if servers.get("agy-worker") != wanted:
    print("  agy-worker entry:", servers.get("agy-worker"))
    sys.exit(1)
if "codex-worker" not in servers:
    print("  codex-worker entry lost")
    sys.exit(1)
PY

new_case
echo 'acmecorp' > "$FAKE_HOME/.claude/mcp/agy-worker/agy_runner.py"
echo 'acmecorp' > "$HERE_DIR/leak-check.local"
run_export
expect "leak inside agy-worker aborts with exit 3" 3 "$STATUS"
expect_in_file "leak inside agy-worker names the file" "$WORK/case$CASE_NO.log" "agy-worker/agy_runner.py:1"

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
rm -f "$FAKE_HOME/.claude/mcp/codex-worker/test_codex_worker.py"
run_export
expect "install works without test_codex_worker.py: export exit" 0 "$STATUS"
INSTALL_HOME=$WORK/install-home
mkdir -p "$INSTALL_HOME/.claude/mcp/codex-worker/.venv/bin" "$INSTALL_HOME/.claude/mcp/agy-worker/.venv/bin" "$WORK/installbin"
for server in codex-worker agy-worker; do
  printf '#!/bin/sh\nexit 0\n' > "$INSTALL_HOME/.claude/mcp/$server/.venv/bin/python"
  chmod 755 "$INSTALL_HOME/.claude/mcp/$server/.venv/bin/python"
done
cp "$OUT/claude/mcp/codex-worker/requirements.txt" "$INSTALL_HOME/.claude/mcp/codex-worker/.venv/.installed-requirements"
cat "$OUT/claude/mcp/agy-worker/requirements.txt" "$OUT/claude/mcp/agy-worker/requirements-dev.txt" \
  > "$INSTALL_HOME/.claude/mcp/agy-worker/.venv/.installed-requirements"
printf '#!/bin/sh\necho "codex-cli 0.0.0-test"\n' > "$WORK/installbin/codex"
chmod 755 "$WORK/installbin/codex"
env -i HOME="$INSTALL_HOME" PATH="$WORK/installbin:/usr/bin:/bin" USER=tester TERM=dumb \
  bash "$OUT/install.sh" >"$WORK/install-case.log" 2>&1
expect "install works without test_codex_worker.py: install exit (see $WORK/install-case.log)" 0 "$?"
CHECKS=$((CHECKS + 1))
[ -f "$INSTALL_HOME/.claude/mcp/codex-worker/codex_worker.py" ] || fail "install works without test_codex_worker.py: worker missing"
CHECKS=$((CHECKS + 1))
[ -f "$INSTALL_HOME/.claude/mcp/agy-worker/agy_worker.py" ] || fail "install of an export: agy-worker missing"

install_export() {
  local home=$1 log=$2 server
  mkdir -p "$home/.claude/mcp/codex-worker/.venv/bin" "$WORK/installbin"
  printf '#!/bin/sh\nexit 0\n' > "$home/.claude/mcp/codex-worker/.venv/bin/python"
  chmod 755 "$home/.claude/mcp/codex-worker/.venv/bin/python"
  cp "$OUT/claude/mcp/codex-worker/requirements.txt" "$home/.claude/mcp/codex-worker/.venv/.installed-requirements"
  if [ -d "$OUT/claude/mcp/agy-worker" ]; then
    server=agy-worker
    mkdir -p "$home/.claude/mcp/$server/.venv/bin"
    printf '#!/bin/sh\nexit 0\n' > "$home/.claude/mcp/$server/.venv/bin/python"
    chmod 755 "$home/.claude/mcp/$server/.venv/bin/python"
    cat "$OUT/claude/mcp/agy-worker/requirements.txt" "$OUT/claude/mcp/agy-worker/requirements-dev.txt" \
      > "$home/.claude/mcp/$server/.venv/.installed-requirements"
  fi
  env -i HOME="$home" PATH="$WORK/installbin:/usr/bin:/bin" USER=tester TERM=dumb \
    bash "$OUT/install.sh" >"$log" 2>&1
}

new_case
cp "$ROOT/install.sh" "$HERE_DIR/install.sh"
cp "$ROOT/retire.json" "$HERE_DIR/retire.json"
rm -rf "$FAKE_HOME/.claude/lint"
cp "$FAKE_HOME/.claude/mcp/codex-worker/test_codex_worker.py" "$FAKE_HOME/.claude/mcp/codex-worker/codex_worker_test.py"
run_export
expect "second install of an export reaches zero changes: export exit" 0 "$STATUS"
REPEAT_HOME=$WORK/repeat-home
install_export "$REPEAT_HOME" "$WORK/repeat-1.log"
expect "second install of an export reaches zero changes: first install (see $WORK/repeat-1.log)" 0 "$?"
install_export "$REPEAT_HOME" "$WORK/repeat-2.log"
expect "second install of an export reaches zero changes: second install (see $WORK/repeat-2.log)" 0 "$?"
expect_in_file "second install of an export reaches zero changes" "$WORK/repeat-2.log" "files changed: 0"

new_case
cp "$ROOT/install.sh" "$HERE_DIR/install.sh"
rm -rf "$FAKE_HOME/.claude/mcp/agy-worker"
run_export
expect "install of an export without agy-worker: export exit" 0 "$STATUS"
install_export "$WORK/no-agy-home" "$WORK/no-agy.log"
expect "install of an export without agy-worker: install exit (see $WORK/no-agy.log)" 0 "$?"
CHECKS=$((CHECKS + 1))
[ ! -e "$WORK/no-agy-home/.claude/mcp/agy-worker" ] || fail "install of an export without agy-worker invented the directory"

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

new_case
echo '{"env": {"CLAUDE_MODE": "personal", "CLAUDE_CODEX": "off", "OTHER": "x"}, "autoMode": {"environment": "local"}}' \
  > "$FAKE_HOME/.claude/settings.json"
run_export
expect "machine mode never exported: exit" 0 "$STATUS"
expect_not_in_file "machine mode never exported" "$OUT/claude/settings.json" CLAUDE_MODE
expect_not_in_file "retired Codex switch never exported" "$OUT/claude/settings.json" CLAUDE_CODEX
expect_in_file "other env entries kept" "$OUT/claude/settings.json" '"OTHER": "x"'
expect_not_in_file "autoMode still dropped" "$OUT/claude/settings.json" autoMode

echo "checks: $CHECKS, FAILURES: $FAILURES"
if [ "$FAILURES" != 0 ]; then
  echo "logs kept in $WORK"
  trap - EXIT
  echo "FAIL"
  exit 1
fi
echo "PASS $CHECKS/$CHECKS"
