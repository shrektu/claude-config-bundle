#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: tests/install-roundtrip.sh
Installs the bundle on a throwaway HOME that still carries the retired files, the old union-style hook
block and the stale allow rules, then checks the result, idempotence, the export and a second install
from that export. Touches nothing outside its temporary directories.
USAGE
}
set -uo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
H1=$WORK/home1
H2=$WORK/home2
FAKEBIN=$WORK/bin
EXPORTED=$WORK/exported
FAILURES=0
CHECKS=0

fail() { echo "FAIL $1"; FAILURES=$((FAILURES + 1)); }
check() { CHECKS=$((CHECKS + 1)); if [ "$2" != 0 ]; then fail "$1"; fi; }
check_file() { CHECKS=$((CHECKS + 1)); [ -e "$1" ] || fail "missing $1"; }
check_gone() { CHECKS=$((CHECKS + 1)); [ ! -e "$1" ] || fail "still present $1"; }
check_grep() { CHECKS=$((CHECKS + 1)); grep -qF -- "$2" "$1" 2>/dev/null || fail "$3"; }
run_install() { env -i HOME="$1" PATH="$FAKEBIN:/usr/bin:/bin" USER="${USER:-tester}" TERM=dumb \
  bash "$2" >"$3" 2>&1; }

mkdir -p "$FAKEBIN"
printf '#!/bin/sh\necho "codex-cli 0.0.0-test"\n' > "$FAKEBIN/codex"
chmod 755 "$FAKEBIN/codex"

stub_venv() {
  local venv=$1/.claude/mcp/codex-worker/.venv
  mkdir -p "$venv/bin"
  printf '#!/bin/sh\nexit 0\n' > "$venv/bin/python"
  chmod 755 "$venv/bin/python"
  cp "$ROOT/claude/mcp/codex-worker/requirements.txt" "$venv/.installed-requirements"
}

mkdir -p "$H1/.claude/prompts" "$H1/.claude/skills/orchestrate" "$H1/.claude/agents" "$H2"
for f in prompts/haiku-task.md prompts/codex-review.md skills/orchestrate/SKILL.md \
         agents/sonnet-worker.md agents/claude-reviewer.md agents/haiku-worker.md; do
  echo "old content" > "$H1/.claude/$f"
done
cat > "$H1/.claude/settings.json" <<'JSON'
{
  "env": { "MAX_MCP_OUTPUT_TOKENS": "1000000", "LOCAL_ONLY": "keep-me" },
  "permissions": {
    "allow": ["mcp__codex__*", "Agent(haiku-worker)", "Agent(claude-reviewer)", "Bash(ls*)"],
    "defaultMode": "auto"
  },
  "effortLevel": "xhigh",
  "autoMode": { "environment": "local" },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "python3 /old/path/git-guard.py" } ] },
      { "matcher": "Grep", "hooks": [ { "type": "command", "command": "python3 /old/path/grep-hook.py" } ] }
    ]
  }
}
JSON
stub_venv "$H1"
stub_venv "$H2"

run_install "$H1" "$ROOT/install.sh" "$WORK/install1.log"
check "install.sh exit status (see $WORK/install1.log)" $?
if [ "$FAILURES" != 0 ]; then tail -20 "$WORK/install1.log"; fi

while IFS= read -r -d '' file; do
  rel=${file#"$ROOT"/claude/}
  [ "$rel" = "mcp-servers.json" ] && continue
  check_file "$H1/.claude/$rel"
done < <(find "$ROOT/claude" -path '*/__pycache__' -prune -o -type f -print0)
check_file "$H1/.claude/bundle/retire.json"
check_file "$H1/.claude/bundle/install.sh"
check_file "$H1/.codex/AGENTS.md"
check_file "$H1/.claude/bin/repo-facts"
check_file "$H1/.claude/hooks/git-policy.py"
check_file "$H1/.claude/hooks/delegation-guard.py"
check_file "$H1/.claude/hooks/subagent-verify-check.py"

for f in prompts/haiku-task.md prompts/codex-review.md skills/orchestrate agents/sonnet-worker.md \
         agents/claude-reviewer.md agents/haiku-worker.md; do
  check_gone "$H1/.claude/$f"
done

CHECKS=$((CHECKS + 1))
LEFTOVER=$(grep -rl "__HOME__" "$H1/.claude" 2>/dev/null | grep -v "/\.claude/bundle/" | grep -v "/backups/" || true)
[ -z "$LEFTOVER" ] || fail "unrendered __HOME__ in: $LEFTOVER"

check_grep "$H1/.claude/settings.json" "$H1/.claude/hooks/git-policy.py" "settings.json: rendered hook path"
CHECKS=$((CHECKS + 1))
[ -x "$H1/.claude/statusline-command.sh" ] || fail "statusline-command.sh is not executable"
CHECKS=$((CHECKS + 1))
grep -qF "__HOME__" "$H1/.claude/bundle/export.sh" || fail "installed export.sh lost its __HOME__ placeholders"
check_grep "$H1/.claude.json" "$H1/.claude/mcp/codex-worker/codex_worker.py" ".claude.json: rendered mcp path"
check_grep "$H1/.codex/config.toml" "$H1/.claude/mcp/codex-worker/codex_worker.py" "codex config: rendered path"
check_grep "$WORK/install1.log" "retired: $H1/.claude/skills/orchestrate" "install log: retirement of the old skill"
check_grep "$WORK/install1.log" "retired settings entries" "install log: retirement of stale settings"

CHECKS=$((CHECKS + 1))
python3 - "$H1/.claude/settings.json" <<'PY' || fail "settings.json content"
import json, sys
settings = json.load(open(sys.argv[1]))
problems = []
if settings.get("effortLevel") != "high":
    problems.append(f"effortLevel={settings.get('effortLevel')!r}")
if settings.get("autoCompactWindow") != "300k":
    problems.append("autoCompactWindow missing")
if settings.get("bashOutputMaxChars") != 12000:
    problems.append("bashOutputMaxChars missing")
for model, config in settings.get("modelSettings", {}).items():
    if config.get("effortLevel") != "high":
        problems.append(f"modelSettings.{model}={config}")
env = settings.get("env", {})
if "MAX_MCP_OUTPUT_TOKENS" in env:
    problems.append("env.MAX_MCP_OUTPUT_TOKENS still set")
if env.get("LOCAL_ONLY") != "keep-me":
    problems.append("local env entry lost")
allow = settings.get("permissions", {}).get("allow", [])
for stale in ("mcp__codex__*", "Agent(haiku-worker)", "Agent(claude-reviewer)"):
    if stale in allow:
        problems.append(f"stale allow {stale}")
for wanted in ("Agent(implementer-opus)", "Agent(implementer)", "Bash(ls*)", "mcp__codex-worker__*"):
    if wanted not in allow:
        problems.append(f"missing allow {wanted}")
if settings.get("autoMode", {}).get("environment") != "local":
    problems.append("autoMode lost")
hooks = settings.get("hooks", {})
for event in ("PreToolUse", "SessionStart", "SubagentStop"):
    if not hooks.get(event):
        problems.append(f"hook event {event} missing")
groups = {(event, entry.get("matcher")): entry for event, entries in hooks.items() for entry in entries}
expected = [("PreToolUse", "Bash"), ("PreToolUse", "Read"), ("PreToolUse", "Agent|Task"),
            ("SessionStart", "startup|resume|clear|compact"), ("SubagentStop", None)]
for key in expected:
    if key not in groups:
        problems.append(f"hook group {key} missing")
if len(groups) != len(expected) + 1:
    problems.append(f"{len(groups)} hook groups, wanted {len(expected) + 1} (bundle groups + the local Grep one)")
if ("PreToolUse", "Grep") not in groups:
    problems.append("local-only Grep matcher dropped")
bash_group = groups.get(("PreToolUse", "Bash"), {}).get("hooks", [])
if len(bash_group) != 3:
    problems.append(f"Bash group has {len(bash_group)} hook commands, wanted 3")
names = [h.get("command", "").rsplit("/", 1)[-1] for h in bash_group]
if names != ["git-guard.py", "verify-guard.py", "git-policy.py"]:
    problems.append(f"Bash hook order {names}")
if any("/old/path/git-guard.py" in h.get("command", "") for h in bash_group):
    problems.append("old union-style Bash hook still registered")
for problem in problems:
    print("  settings problem:", problem)
sys.exit(1 if problems else 0)
PY

run_install "$H1" "$ROOT/install.sh" "$WORK/install2.log"
check "second install exit status (see $WORK/install2.log)" $?
check_grep "$WORK/install2.log" "files changed: 0" "second install: no file changes"
check_grep "$WORK/install2.log" "settings.json: unchanged" "second install: settings unchanged"
CHECKS=$((CHECKS + 1))
if grep -q "^retired:" "$WORK/install2.log"; then fail "second install retired files again"; fi

env -i HOME="$H1" PATH="$FAKEBIN:/usr/bin:/bin" USER="${USER:-tester}" TERM=dumb \
  bash "$H1/.claude/bundle/export.sh" "$EXPORTED" >"$WORK/export.log" 2>&1
check "installed export.sh exit status (see $WORK/export.log)" $?
check_file "$EXPORTED/retire.json"
check_file "$EXPORTED/claude/hooks/git-policy.py"
check_file "$EXPORTED/claude/bin/repo-facts"
check_file "$EXPORTED/manifest.txt"
CHECKS=$((CHECKS + 1))
if grep -q "\./\.git/" "$EXPORTED/manifest.txt"; then fail "manifest lists .git entries"; fi
check_grep "$EXPORTED/manifest.txt" "./retire.json" "manifest lists retire.json"
check_grep "$EXPORTED/claude/settings.json" "__HOME__/.claude/hooks/git-policy.py" "export: home path replaced"

check_file "$EXPORTED/claude/templates/rules-standards.md"

run_install "$H2" "$EXPORTED/install.sh" "$WORK/install3.log"
check "install from export exit status (see $WORK/install3.log)" $?
while IFS= read -r -d '' file; do
  rel=${file#"$EXPORTED"/claude/}
  [ "$rel" = "mcp-servers.json" ] && continue
  check_file "$H2/.claude/$rel"
done < <(find "$EXPORTED/claude" -path '*/__pycache__' -prune -o -type f -print0)
check_file "$H2/.claude/templates/rules-standards.md"
check_file "$H2/.claude/hooks/git-policy.py"
check_file "$H2/.claude/bundle/retire.json"
check_grep "$H2/.claude/settings.json" "$H2/.claude/hooks/delegation-guard.py" "second home: rendered path"

echo "checks: $CHECKS, FAILURES: $FAILURES"
if [ "$FAILURES" != 0 ]; then
  echo "logs kept in $WORK"
  trap - EXIT
  echo "FAIL"
  exit 1
fi
echo "PASS $CHECKS/$CHECKS"
