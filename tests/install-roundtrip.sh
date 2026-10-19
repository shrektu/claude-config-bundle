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
check_exec() { CHECKS=$((CHECKS + 1)); [ -x "$1" ] || fail "not executable $1"; }
check_gone() { CHECKS=$((CHECKS + 1)); [ ! -e "$1" ] || fail "still present $1"; }
check_grep() { CHECKS=$((CHECKS + 1)); grep -qF -- "$2" "$1" 2>/dev/null || fail "$3"; }
SYSBIN=$WORK/sysbin
UVBIN=$WORK/uvbin
RUFFBIN=$WORK/ruffbin
run_install() { env -i HOME="$1" PATH="${4:-$FAKEBIN:$SYSBIN}" USER="${USER:-tester}" TERM=dumb \
  bash "$2" >"$3" 2>&1; }

mkdir -p "$FAKEBIN" "$SYSBIN" "$UVBIN" "$RUFFBIN"
for f in /usr/bin/* /bin/*; do
  case ${f##*/} in uv|uvx|ruff|mypy|vulture|pylint) continue ;; esac
  ln -sf "$f" "$SYSBIN/${f##*/}"
done
printf '#!/bin/sh\ncase "$*" in\n  "tool dir --bin") echo "%s/uv-tool-bin" ;;\n  *) echo "$*" >> "%s/uv-called" ;;\nesac\n' \
  "$UVBIN" "$UVBIN" > "$UVBIN/uv"
for tool in ruff mypy vulture pylint; do
  printf '#!/bin/sh\necho "%s 0.0.0-test"\n' "$tool" > "$RUFFBIN/$tool"
  chmod 755 "$RUFFBIN/$tool"
done
chmod 755 "$UVBIN/uv"
printf '#!/bin/sh\necho "codex-cli 0.0.0-test"\n' > "$FAKEBIN/codex"
chmod 755 "$FAKEBIN/codex"

stub_venv() {
  local source=${2:-$ROOT/claude} server venv
  for server in codex-worker agy-worker; do
    venv=$1/.claude/mcp/$server/.venv
    mkdir -p "$venv/bin"
    printf '#!/bin/sh\nexit 0\n' > "$venv/bin/python"
    chmod 755 "$venv/bin/python"
  done
  cp "$source/mcp/codex-worker/requirements.txt" "$1/.claude/mcp/codex-worker/.venv/.installed-requirements"
  cat "$source/mcp/agy-worker/requirements.txt" "$source/mcp/agy-worker/requirements-dev.txt" \
    > "$1/.claude/mcp/agy-worker/.venv/.installed-requirements" 2>/dev/null
}

mkdir -p "$H1/.claude/prompts" "$H1/.claude/skills/orchestrate" "$H1/.claude/agents" "$H2"
RETIRED_AGENTS="implementer-hard implementer-opus commander-opus developer"
for f in prompts/haiku-task.md prompts/codex-review.md skills/orchestrate/SKILL.md \
         agents/sonnet-worker.md agents/claude-reviewer.md agents/haiku-worker.md; do
  echo "old content" > "$H1/.claude/$f"
done
for a in implementer $RETIRED_AGENTS; do echo "old agent" > "$H1/.claude/agents/$a.md"; done
cat > "$H1/.claude/settings.json" <<'JSON'
{
  "env": { "MAX_MCP_OUTPUT_TOKENS": "1000000", "LOCAL_ONLY": "keep-me" },
  "permissions": {
    "allow": ["mcp__codex__*", "Agent(haiku-worker)", "Agent(claude-reviewer)", "Bash(ls*)",
              "Agent(implementer)", "Agent(implementer-hard)", "Agent(implementer-opus)", "Agent(commander-opus)",
              "Agent(implementer-strong)", "Write(/__H1__/.claude/hooks/**)"],
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
sed -i "s#/__H1__#/$H1#" "$H1/.claude/settings.json"
RETIRED_HOME_ENTRIES="audit-2026-09-12 settings.json.bak-manual settings.json.bak-manual2 \
  skills/rownolegle skills/epik skills/teksty-ui"
mkdir -p "$H1/.claude/audit-2026-09-12" "$H1/.claude/lint" "$H1/.claude/backups/unrelated"
echo "old audit" > "$H1/.claude/audit-2026-09-12/report.md"
echo "{}" > "$H1/.claude/settings.json.bak-manual"
echo "{}" > "$H1/.claude/settings.json.bak-manual2"
CUSTOM_RUFF='line-length = 77'
echo "$CUSTOM_RUFF" > "$H1/.claude/lint/ruff.toml"
RETIRED_HOME_FILES="bin/feature-worktree bin/feature-worktree-test.sh bin/quality-gate bin/quality-gate-test.sh \
  bin/review-checkpoint-test.sh hooks/bash-write-guard.py hooks/bash-write-guard-test.py hooks/code_files.py \
  hooks/edit_texts.py hooks/lint-guard.py hooks/lint-guard-test.py hooks/shell_words.py \
  mcp/codex-worker/codex_worker_test.py skills/quality-bar/SKILL.md skills/tdd/SKILL.md \
  agents/implementer-strong.md skills/rownolegle/SKILL.md skills/epik/SKILL.md skills/teksty-ui/SKILL.md \
  skills/qa/references/scenariusze.md"
for f in $RETIRED_HOME_FILES; do
  mkdir -p "$(dirname "$H1/.claude/$f")"
  echo "retired content" > "$H1/.claude/$f"
done
FAKE_BACKUPS="20200101-000001 20200101-000002 20200101-000003 20200101-000004 20200101-000005 20200101-000006 20200101-000007"
for stamp in $FAKE_BACKUPS; do mkdir -p "$H1/.claude/backups/bundle-$stamp"; done
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
for tool in ai-review-gate habits lint-strict review-checkpoint usage-report verify; do
  check_exec "$H1/.claude/bin/$tool"
done
check_file "$H1/.claude/agents/implementer.md"
CHECKS=$((CHECKS + 1))
if grep -qF "old agent" "$H1/.claude/agents/implementer.md"; then fail "implementer.md was not replaced by the bundle version"; fi
for hook in git-guard verify-guard read-guard codex-gate standards-gate autofix-on-edit context-guard session-start-marker; do
  check_file "$H1/.claude/hooks/$hook.py"
done
check_file "$H1/.claude/hooks/git-policy.py"
check_file "$H1/.claude/hooks/delegation-guard.py"
check_file "$H1/.claude/hooks/subagent-verify-check.py"
check_file "$H1/.claude/hooks/tdd-guard.py"
check_file "$H1/.claude/hooks/tdd-guard-test.py"
check_file "$H1/.claude/hooks/comment-guard.py"
check_file "$H1/.claude/hooks/comment-guard-test.py"
for f in $RETIRED_HOME_FILES; do
  check_gone "$H1/.claude/$f"
  CHECKS=$((CHECKS + 1))
  compgen -G "$H1/.claude/backups/bundle-2*/.claude/$f" >/dev/null || fail "no backup of retired $f"
done
check_gone "$H1/.claude/lint"
CHECKS=$((CHECKS + 1))
grep -qF -- "$CUSTOM_RUFF" "$H1"/.claude/backups/bundle-2*/.claude/lint/ruff.toml 2>/dev/null \
  || fail "the retired ruff.toml was not backed up"
for entry in $RETIRED_HOME_ENTRIES prompts; do
  check_gone "$H1/.claude/$entry"
  CHECKS=$((CHECKS + 1))
  compgen -G "$H1/.claude/backups/bundle-2*/.claude/$entry" >/dev/null || fail "no backup of retired $entry"
done
CHECKS=$((CHECKS + 1))
BACKUPS_LEFT=$(cd "$H1/.claude/backups" && ls -d bundle-* | wc -l | tr -d ' ')
[ "$BACKUPS_LEFT" = 5 ] || fail "backup rotation kept $BACKUPS_LEFT bundle-* dirs, wanted 5"
check_gone "$H1/.claude/backups/bundle-20200101-000001"
check_gone "$H1/.claude/backups/bundle-20200101-000003"
check_file "$H1/.claude/backups/bundle-20200101-000007"
check_file "$H1/.claude/backups/unrelated"
for a in $RETIRED_AGENTS; do
  check_gone "$H1/.claude/agents/$a.md"
  CHECKS=$((CHECKS + 1))
  compgen -G "$H1/.claude/backups/bundle-*/.claude/agents/$a.md" >/dev/null || fail "no backup of retired agents/$a.md"
done
CHECKS=$((CHECKS + 1))
AGENTS_LEFT=$(cd "$H1/.claude/agents" && ls | LC_ALL=C sort | tr '\n' ' ')
[ "$AGENTS_LEFT" = "codex-runner.md flash-review-runner.md implementer.md plan-gate-runner.md reviewer-opus.md writer.md " ] || fail "agents left after install: $AGENTS_LEFT"
check_grep "$WORK/install1.log" "for t in tdd-guard " "install log: post-install hint runs the tdd-guard matrix"
check_grep "$WORK/install1.log" " comment-guard " "install log: post-install hint runs the comment-guard matrix"
check_grep "$WORK/install1.log" "test_codex_worker.py" "install log: post-install hint names the worker test"
check_grep "$WORK/install1.log" "and agy-worker must show Connected" "install log: checklist asks for agy-worker Connected"
check_grep "$WORK/install1.log" "agy-worker/.venv/bin/python -m pytest" "install log: checklist runs the agy-worker tests"
check_file "$ROOT/claude/mcp/agy-worker/agy_worker.py"
check_file "$H1/.claude/mcp/agy-worker/agy_worker.py"
check_file "$H1/.claude/mcp/agy-worker/requirements-dev.txt"
check_file "$H1/.claude/mcp/agy-worker/allowed-remotes.txt"
for skill in parallel epic ui-texts; do check_file "$H1/.claude/skills/$skill/SKILL.md"; done

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
check_grep "$H1/.claude.json" "$H1/.claude/mcp/agy-worker/agy_worker.py" ".claude.json: agy-worker not registered"
check_grep "$H1/.claude.json" "$H1/.local/bin/agy" ".claude.json: AGY_BIN not rendered"
check_grep "$H1/.codex/config.toml" "$H1/.claude/mcp/codex-worker/codex_worker.py" "codex config: rendered path"
check_grep "$WORK/install1.log" "retired: $H1/.claude/skills/orchestrate" "install log: retirement of the old skill"
check_grep "$WORK/install1.log" "retired settings entries" "install log: retirement of stale settings"

CHECKS=$((CHECKS + 1))
python3 - "$H1/.claude/settings.json" "$ROOT/claude/settings.json" "$H1" <<'PY' || fail "settings.json content"
import json, re, sys
settings = json.load(open(sys.argv[1]))
bundle = json.load(open(sys.argv[2]))
home = sys.argv[3]
problems = []
if settings.get("model") != "opus[1m]":
    problems.append(f"model={settings.get('model')!r}")
if settings.get("effortLevel") != "high":
    problems.append(f"effortLevel={settings.get('effortLevel')!r}")
if settings.get("bashOutputMaxChars") != 12000:
    problems.append("bashOutputMaxChars missing")
if settings.get("modelSettings") != bundle["modelSettings"]:
    problems.append(f"modelSettings={settings.get('modelSettings')}")
env = settings.get("env", {})
if "MAX_MCP_OUTPUT_TOKENS" in env:
    problems.append("env.MAX_MCP_OUTPUT_TOKENS still set")
if env.get("LOCAL_ONLY") != "keep-me":
    problems.append("local env entry lost")
allow = settings.get("permissions", {}).get("allow", [])
for stale in ("mcp__codex__*", "Agent(haiku-worker)", "Agent(claude-reviewer)",
              "Agent(implementer-hard)", "Agent(implementer-opus)", "Agent(commander-opus)"):
    if stale in allow:
        problems.append(f"stale allow {stale}")
for stale in ("Agent(implementer-strong)", f"Write(/{home}/.claude/hooks/**)"):
    if stale in allow:
        problems.append(f"stale allow {stale}")
for wanted in ("Agent(implementer)", "Agent(codex-runner)", "Bash(ls*)",
               "mcp__codex-worker__*", "mcp__agy-worker__*"):
    if wanted not in allow:
        problems.append(f"missing allow {wanted}")
if settings.get("autoMode", {}).get("environment") != "local":
    problems.append("autoMode lost")
hooks = settings.get("hooks", {})
wanted_count = 1
for event, entries in bundle["hooks"].items():
    wanted_count += len(entries)
    for entry in entries:
        rendered = json.loads(json.dumps(entry).replace("__HOME__", home))
        if rendered not in hooks.get(event, []):
            problems.append(f"hook entry missing: {event} {entry.get('matcher')}")
if sum(len(entries) for entries in hooks.values()) != wanted_count:
    problems.append("hook entry count differs from bundle entries plus the local Grep one")
if not any(e.get("matcher") == "Grep" for e in hooks.get("PreToolUse", [])):
    problems.append("local-only Grep matcher dropped")
if any("/old/path/git-guard.py" in h.get("command", "") for e in hooks.get("PreToolUse", []) for h in e["hooks"]):
    problems.append("old union-style Bash hook still registered")
for problem in problems:
    print("  settings problem:", problem)
sys.exit(1 if problems else 0)
PY

CHECKS=$((CHECKS + 1))
python3 - "$H1/.claude/settings.json" "$H1" <<'PY' || fail "a hook command references a file that does not exist"
import json, os, re, sys
settings = json.load(open(sys.argv[1]))
home = sys.argv[2]
pattern = re.compile(re.escape(home) + r"/\.claude/[^\s'\";)]+")
missing = []
for entries in settings["hooks"].values():
    for entry in entries:
        for hook in entry["hooks"]:
            missing += [p for p in pattern.findall(hook["command"]) if not os.path.exists(p)]
for path in missing:
    print("  hook references missing file:", path)
sys.exit(1 if missing else 0)
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
for tool in ai-review-gate habits lint-strict review-checkpoint verify; do
  check_exec "$EXPORTED/claude/bin/$tool"
done
check_file "$EXPORTED/claude/hooks/tdd-guard.py"
check_file "$EXPORTED/claude/hooks/comment-guard.py"
check_gone "$EXPORTED/claude/lint"
check_gone "$EXPORTED/claude/mcp/codex-worker/codex_worker_test.py"
check_file "$EXPORTED/claude/mcp/agy-worker/agy_worker.py"
check_file "$EXPORTED/claude/mcp/agy-worker/allowed-remotes.txt"
check_gone "$EXPORTED/claude/mcp/agy-worker/.venv"
check_file "$EXPORTED/manifest.txt"
CHECKS=$((CHECKS + 1))
if grep -q "\./\.git/" "$EXPORTED/manifest.txt"; then fail "manifest lists .git entries"; fi
check_grep "$EXPORTED/manifest.txt" "./retire.json" "manifest lists retire.json"
check_grep "$EXPORTED/claude/settings.json" "__HOME__/.claude/hooks/git-policy.py" "export: home path replaced"

check_file "$EXPORTED/claude/templates/rules-standards.md"

mkdir -p "$EXPORTED/claude/bin/__pycache__" "$EXPORTED/claude/hooks/__pycache__"
printf 'stale' > "$EXPORTED/claude/bin/__pycache__/probe.cpython-314.pyc"
printf 'stale' > "$EXPORTED/claude/hooks/stray.pyc"
run_install "$H2" "$EXPORTED/install.sh" "$WORK/install3.log"
check "install from export exit status (see $WORK/install3.log)" $?
check_gone "$H2/.claude/bin/__pycache__/probe.cpython-314.pyc"
check_gone "$H2/.claude/hooks/stray.pyc"
while IFS= read -r -d '' file; do
  rel=${file#"$EXPORTED"/claude/}
  [ "$rel" = "mcp-servers.json" ] && continue
  check_file "$H2/.claude/$rel"
done < <(find "$EXPORTED/claude" -path '*/__pycache__' -prune -o -type f ! -name '*.pyc' -print0)
check_file "$H2/.claude/templates/rules-standards.md"
check_file "$H2/.claude/hooks/git-policy.py"
check_file "$H2/.claude/bundle/retire.json"
check_file "$H2/.claude/hooks/tdd-guard.py"
check_grep "$H2/.claude/settings.json" "$H2/.claude/hooks/delegation-guard.py" "second home: rendered path"

mkdir -p "$WORK/home-uv" "$WORK/home-none" "$WORK/home-ruff"
for home in home-uv home-none home-ruff; do stub_venv "$WORK/$home"; done
run_install "$WORK/home-uv" "$ROOT/install.sh" "$WORK/install-uv.log" "$UVBIN:$FAKEBIN:$SYSBIN"
check "install without ruff but with uv, exit status" $?
for tool in ruff mypy vulture pylint; do
  check_grep "$UVBIN/uv-called" "tool install $tool" "uv was not asked to install $tool"
  check_grep "$WORK/install-uv.log" "$tool is not installed" "no warning although $tool is still off PATH after uv"
done
check_grep "$WORK/install-uv.log" "lint-guard is inactive" "no warning although ruff is still off PATH after uv"
check_grep "$WORK/install-uv.log" "$UVBIN/uv-tool-bin" "warning does not say where uv put ruff"
rm -f "$UVBIN/uv-called"
run_install "$WORK/home-none" "$ROOT/install.sh" "$WORK/install-none.log"
check "install without ruff and uv, exit status" $?
check_grep "$WORK/install-none.log" "lint-guard is inactive" "no warning that lint-guard is inactive"
for tool in mypy vulture pylint; do
  check_grep "$WORK/install-none.log" "$tool is not installed" "no warning that $tool is missing"
done
run_install "$WORK/home-ruff" "$ROOT/install.sh" "$WORK/install-ruff.log" "$RUFFBIN:$UVBIN:$FAKEBIN:$SYSBIN"
check "install with ruff present, exit status" $?
check_gone "$UVBIN/uv-called"
CHECKS=$((CHECKS + 1))
if grep -q "is not installed" "$WORK/install-ruff.log"; then fail "warned about a tool that is installed"; fi

BUNDLE=$WORK/bundle
FAKEMCP=$WORK/fakemcp
FAKECLAUDE=$WORK/claudebin
NOPDFBIN=$WORK/nopdfbin
AGYBIN=$WORK/agybin
H3=$WORK/home3
H4=$WORK/home4
LOCAL_ALLOWLIST='local.example/*'
BUNDLE_ALLOWLIST='github.com/*'
RUNTIME_REQUIREMENTS='--prefer-binary'
DEV_REQUIREMENTS='--pre'
mkdir -p "$BUNDLE" "$FAKEMCP/mcp" "$FAKECLAUDE" "$NOPDFBIN" "$AGYBIN" "$H3" "$H4"
touch "$FAKEMCP/mcp/__init__.py"
for f in /usr/bin/* /bin/*; do
  name=$(basename "$f")
  case $name in uv|uvx|ruff|mypy|vulture|pylint|pdf*) continue ;; esac
  ln -sf "$f" "$NOPDFBIN/$name"
done
printf '#!/bin/sh\nexit 0\n' > "$AGYBIN/agy"
chmod 755 "$AGYBIN/agy"
cat > "$FAKECLAUDE/claude" <<'SH'
#!/usr/bin/env python3
import json, os, sys
home = os.environ["HOME"]
with open(os.path.join(home, "claude-calls.log"), "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
path = os.path.join(home, ".claude.json")
data = json.load(open(path)) if os.path.exists(path) else {}
servers = data.setdefault("mcpServers", {})
if sys.argv[1:3] == ["mcp", "remove"]:
    servers.pop(sys.argv[3], None)
elif sys.argv[1:3] == ["mcp", "add-json"]:
    servers[sys.argv[3]] = json.loads(sys.argv[4])
json.dump(data, open(path, "w"), indent=2)
SH
chmod 755 "$FAKECLAUDE/claude"
cp -a "$ROOT/install.sh" "$ROOT/export.sh" "$ROOT/retire.json" "$ROOT/README.md" "$ROOT/codex" "$ROOT/claude" "$BUNDLE/"
rm -rf "$BUNDLE/claude/mcp/agy-worker"
mkdir -p "$BUNDLE/claude/mcp/agy-worker"
for f in agy_worker.py test_agy_worker.py; do echo "pass" > "$BUNDLE/claude/mcp/agy-worker/$f"; done
echo "$RUNTIME_REQUIREMENTS" > "$BUNDLE/claude/mcp/agy-worker/requirements.txt"
echo "$DEV_REQUIREMENTS" > "$BUNDLE/claude/mcp/agy-worker/requirements-dev.txt"
echo "[tool.pytest.ini_options]" > "$BUNDLE/claude/mcp/agy-worker/pyproject.toml"
echo "$BUNDLE_ALLOWLIST" > "$BUNDLE/claude/mcp/agy-worker/allowed-remotes.txt"
echo "$RUNTIME_REQUIREMENTS" > "$BUNDLE/claude/mcp/codex-worker/requirements.txt"
echo "pass" > "$BUNDLE/claude/mcp/codex-worker/test_codex_worker.py"
cat > "$BUNDLE/claude/mcp-servers.json" <<'JSON'
{
  "mcpServers": {
    "codex-worker": {
      "type": "stdio",
      "command": "env",
      "args": [
        "CODEX_BIN=__CODEX_BIN__",
        "__HOME__/.claude/mcp/codex-worker/.venv/bin/python",
        "__HOME__/.claude/mcp/codex-worker/codex_worker.py"
      ],
      "env": {},
      "timeout": 5400000
    },
    "agy-worker": {
      "type": "stdio",
      "command": "__HOME__/.claude/mcp/agy-worker/.venv/bin/python",
      "args": ["__HOME__/.claude/mcp/agy-worker/agy_worker.py"],
      "env": {"AGY_BIN": "__AGY_BIN__"},
      "timeout": 5400000
    }
  }
}
JSON
MISSING_INTERPRETER=/nonexistent/pyenv/bin/python3
MISSING_INTERPRETER_HOOK=standards-gate.py
python3 - "$BUNDLE/claude/settings.json" "$MISSING_INTERPRETER" "$MISSING_INTERPRETER_HOOK" <<'PY'
import json, sys
MISSING_INTERPRETER, MISSING_INTERPRETER_HOOK = sys.argv[2], sys.argv[3]
settings = json.load(open(sys.argv[1]))
allow = settings["permissions"]["allow"]
settings["permissions"]["allow"] = [
    e for e in allow if e != "Agent(implementer-strong)" and not e.startswith("Write(/__HOME__/.claude/hooks")
]
settings["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [
    {"type": "command", "command": f"{MISSING_INTERPRETER} __HOME__/.claude/hooks/{MISSING_INTERPRETER_HOOK}"}]})
json.dump(settings, open(sys.argv[1], "w"), indent=2)
PY

run_bundle_install() { env -i HOME="$1" PATH="$2" PYTHONPATH="$FAKEMCP" USER="${USER:-tester}" TERM=dumb \
  bash "$BUNDLE/install.sh" >"$3" 2>&1; }

mkdir -p "$H3/.claude/mcp/agy-worker" "$H3/.claude/agents" "$H3/.claude/skills/rownolegle" \
  "$H3/.claude/skills/epik" "$H3/.claude/skills/teksty-ui" "$H3/.claude/skills/qa/references"
echo "$LOCAL_ALLOWLIST" > "$H3/.claude/mcp/agy-worker/allowed-remotes.txt"
echo '{"userMarker": 1}' > "$H3/.claude.json"
V1_RETIRED="agents/implementer-strong.md skills/rownolegle/SKILL.md skills/epik/SKILL.md skills/teksty-ui/SKILL.md \
  skills/qa/references/scenariusze.md"
for f in $V1_RETIRED; do echo "v1 content" > "$H3/.claude/$f"; done
cat > "$H3/.claude/settings.json" <<JSON
{
  "permissions": {
    "allow": ["Bash(ls*)", "Agent(implementer-strong)", "Write(/$H3/.claude/hooks/**)", "Agent(implementer)"]
  }
}
JSON

run_bundle_install "$H3" "$FAKECLAUDE:$FAKEBIN:$NOPDFBIN" "$WORK/install-v2a.log"
check "v2 install on a home with v1 leftovers, exit status (see $WORK/install-v2a.log)" $?
for f in agy_worker.py test_agy_worker.py pyproject.toml requirements.txt requirements-dev.txt; do
  check_file "$H3/.claude/mcp/agy-worker/$f"
done
CHECKS=$((CHECKS + 1))
[ "$(cat "$H3/.claude/mcp/agy-worker/allowed-remotes.txt" 2>/dev/null)" = "$LOCAL_ALLOWLIST" ] \
  || fail "a machine's own allowed-remotes.txt was overwritten"
check_grep "$WORK/install-v2a.log" "allowed-remotes.txt differs" "no note that the local allowlist differs from the bundle's"
for server in codex-worker agy-worker; do
  check_exec "$H3/.claude/mcp/$server/.venv/bin/python"
  check_grep "$WORK/install-v2a.log" "building venv: $H3/.claude/mcp/$server/.venv" "$server venv was not built"
  check_grep "$H3/claude-calls.log" "mcp add-json $server " "claude mcp add-json was not called for $server"
  check_grep "$H3/.claude.json" "$H3/.claude/mcp/$server/" "$server registration lacks its rendered path"
done
CHECKS=$((CHECKS + 1))
[ "$(cat "$H3/.claude/mcp/agy-worker/.venv/.installed-requirements" 2>/dev/null)" = "$(printf '%s\n%s' "$RUNTIME_REQUIREMENTS" "$DEV_REQUIREMENTS")" ] \
  || fail "agy-worker venv marker is not requirements.txt followed by requirements-dev.txt"
check_grep "$H3/.claude.json" "$H3/.local/bin/agy" "AGY_BIN did not fall back to ~/.local/bin/agy"
check_grep "$WORK/install-v2a.log" "falling back to $H3/.local/bin/agy" "no note about the AGY_BIN fallback"
check_file "$H3/.claude/mcp/codex-worker/test_codex_worker.py"
check_grep "$WORK/install-v2a.log" "WARNING: hook interpreter $MISSING_INTERPRETER does not exist ($MISSING_INTERPRETER_HOOK)" "no warning about a hook interpreter missing on this machine"
CLAUDE_JSON_BACKUP=$(compgen -G "$H3/.claude/backups/bundle-*/.claude.json" | head -1)
check_grep "$CLAUDE_JSON_BACKUP" "userMarker" "the .claude.json backup lost the original content"
CHECKS=$((CHECKS + 1))
if grep -qF "worker" "$CLAUDE_JSON_BACKUP" 2>/dev/null; then fail ".claude.json was backed up after a server was already registered"; fi
for f in $V1_RETIRED; do
  check_gone "$H3/.claude/$f"
  CHECKS=$((CHECKS + 1))
  compgen -G "$H3/.claude/backups/bundle-*/.claude/$f" >/dev/null || fail "no backup of retired $f"
done
for dir in skills/rownolegle skills/epik skills/teksty-ui; do check_gone "$H3/.claude/$dir"; done
check_grep "$WORK/install-v2a.log" "retired settings entries" "no retirement of the v1 settings entries"
CHECKS=$((CHECKS + 1))
python3 - "$H3/.claude/settings.json" "$H3" <<'PY' || fail "settings entries of v1 were not retired"
import json, sys
allow = json.load(open(sys.argv[1]))["permissions"]["allow"]
problems = [e for e in ("Agent(implementer-strong)", f"Write(/{sys.argv[2]}/.claude/hooks/**)") if e in allow]
problems += [f"lost {e}" for e in ("Bash(ls*)", "Agent(implementer)") if e not in allow]
for problem in problems:
    print("  settings problem:", problem)
sys.exit(1 if problems else 0)
PY
check_grep "$WORK/install-v2a.log" "WARNING: agy is not on PATH" "no warning about the missing agy"
check_grep "$WORK/install-v2a.log" "antigravity.google/cli/install.sh" "no install hint for agy"
check_grep "$WORK/install-v2a.log" "WARNING: pdfinfo, pdfseparate or pdfunite not found" "no warning about missing poppler"
check_grep "$WORK/install-v2a.log" "poppler-utils" "no install hint for poppler"
for sandbox_tool in bwrap xdg-dbus-proxy; do
  CHECKS=$((CHECKS + 1))
  if [ -e "/usr/bin/$sandbox_tool" ]; then
    if grep -qF "WARNING: /usr/bin/$sandbox_tool not found" "$WORK/install-v2a.log"; then
      fail "warned about /usr/bin/$sandbox_tool although it exists"
    fi
  else
    grep -qF "WARNING: /usr/bin/$sandbox_tool not found" "$WORK/install-v2a.log" \
      || fail "no warning about the missing /usr/bin/$sandbox_tool"
  fi
done

CALLS_BEFORE=$(wc -l < "$H3/claude-calls.log")
run_bundle_install "$H3" "$FAKECLAUDE:$FAKEBIN:$NOPDFBIN" "$WORK/install-v2b.log"
check "second v2 install exit status (see $WORK/install-v2b.log)" $?
check_grep "$WORK/install-v2b.log" "files changed: 0" "second v2 install: files changed"
check_grep "$WORK/install-v2b.log" "agy-worker already registered" "second v2 install: agy-worker registered again"
check_grep "$WORK/install-v2b.log" "codex-worker already registered" "second v2 install: codex-worker registered again"
CHECKS=$((CHECKS + 1))
[ "$(wc -l < "$H3/claude-calls.log")" = "$CALLS_BEFORE" ] || fail "second v2 install called claude mcp again"
CHECKS=$((CHECKS + 1))
[ "$(cat "$H3/.claude/mcp/agy-worker/allowed-remotes.txt")" = "$LOCAL_ALLOWLIST" ] \
  || fail "second v2 install overwrote the local allowlist"

python3 - "$H3/.claude.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
data["mcpServers"]["agy-worker"]["env"]["AGY_BIN"] = "/stale/agy"
json.dump(data, open(sys.argv[1], "w"))
PY
run_bundle_install "$H3" "$FAKECLAUDE:$FAKEBIN:$NOPDFBIN" "$WORK/install-v2c.log"
check "install over a changed registration exit status (see $WORK/install-v2c.log)" $?
check_grep "$H3/claude-calls.log" "mcp remove agy-worker" "a changed agy-worker registration was not removed first"
check_grep "$H3/.claude.json" "$H3/.local/bin/agy" "a changed agy-worker registration was not rewritten"
CHECKS=$((CHECKS + 1))
if grep -qF "/stale/agy" "$H3/.claude.json"; then fail "stale AGY_BIN survived the re-registration"; fi
check_grep "$WORK/install-v2c.log" "codex-worker already registered" "the unchanged codex-worker was re-registered"

stub_venv "$H4" "$BUNDLE/claude"
run_bundle_install "$H4" "$AGYBIN:$FAKEBIN:$SYSBIN" "$WORK/install-v2d.log"
check "v2 install on a fresh home with agy, exit status (see $WORK/install-v2d.log)" $?
CHECKS=$((CHECKS + 1))
[ "$(cat "$H4/.claude/mcp/agy-worker/allowed-remotes.txt" 2>/dev/null)" = "$BUNDLE_ALLOWLIST" ] \
  || fail "the bundle's allowed-remotes.txt was not installed on a fresh home"
CHECKS=$((CHECKS + 1))
if grep -qF "WARNING: agy is not on PATH" "$WORK/install-v2d.log"; then fail "warned about agy although it is on PATH"; fi
check_grep "$WORK/install-v2d.log" "agy-worker registered (python merge" "no python-merge registration of agy-worker"
check_grep "$H4/.claude.json" "$H4/.claude/mcp/agy-worker/agy_worker.py" "fresh home: agy-worker not in .claude.json"
check_grep "$H4/.claude.json" "$AGYBIN/agy" "AGY_BIN is not the agy found on PATH"

SPECIAL_AGY_DIR="$WORK/cli&tools$(printf '\043')bin"
SPECIAL_AGY=$SPECIAL_AGY_DIR/agy
H6=$WORK/home6
mkdir -p "$SPECIAL_AGY_DIR" "$H6"
cp "$AGYBIN/agy" "$SPECIAL_AGY"
stub_venv "$H6" "$BUNDLE/claude"
run_bundle_install "$H6" "$SPECIAL_AGY_DIR:$FAKEBIN:$SYSBIN" "$WORK/install-v2f.log"
check "install with agy under a path with & and the hash sign, exit status (see $WORK/install-v2f.log)" $?
CHECKS=$((CHECKS + 1))
python3 - "$H6/.claude.json" "$SPECIAL_AGY" <<'PY' || fail "AGY_BIN with special characters was corrupted by the renderer"
import json, sys
registered = json.load(open(sys.argv[1]))["mcpServers"]["agy-worker"]["env"]["AGY_BIN"]
if registered != sys.argv[2]:
    print("  registered AGY_BIN:", registered)
    sys.exit(1)
PY

BUNDLE_WITHOUT_AGY=$WORK/bundle-without-agy
H7=$WORK/home7
mkdir -p "$H7"
cp -a "$BUNDLE" "$BUNDLE_WITHOUT_AGY"
rm -rf "$BUNDLE_WITHOUT_AGY/claude/mcp/agy-worker"
python3 - "$BUNDLE_WITHOUT_AGY/claude/mcp-servers.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
del data["mcpServers"]["agy-worker"]
json.dump(data, open(sys.argv[1], "w"), indent=2)
PY
stub_venv "$H7" "$BUNDLE_WITHOUT_AGY/claude"
env -i HOME="$H7" PATH="$FAKEBIN:$SYSBIN" PYTHONPATH="$FAKEMCP" USER="${USER:-tester}" TERM=dumb \
  bash "$BUNDLE_WITHOUT_AGY/install.sh" >"$WORK/install-v2g.log" 2>&1
check "install of a bundle without agy-worker, exit status (see $WORK/install-v2g.log)" $?
check_grep "$H7/.claude.json" "codex-worker" "bundle without agy-worker: codex-worker not registered"
CHECKS=$((CHECKS + 1))
if grep -qF "agy-worker" "$H7/.claude.json"; then fail "bundle without agy-worker registered it anyway"; fi

OLD_PYTHON_BIN=$WORK/oldpython
H5=$WORK/home5
mkdir -p "$OLD_PYTHON_BIN" "$H5"
printf '#!/bin/sh\ncase "$2" in *"version_info < (3, 12)"*) exit 1 ;; esac\nexec /usr/bin/python3 "$@"\n' > "$OLD_PYTHON_BIN/python3"
chmod 755 "$OLD_PYTHON_BIN/python3"
run_bundle_install "$H5" "$OLD_PYTHON_BIN:$AGYBIN:$FAKECLAUDE:$FAKEBIN:$SYSBIN" "$WORK/install-v2e.log"
check "install with python below 3.12, exit status (see $WORK/install-v2e.log)" $?
check_grep "$WORK/install-v2e.log" "WARNING: python3 is older than 3.12, skipping agy-worker" "no warning that agy-worker needs python 3.12"
check_gone "$H5/.claude/mcp/agy-worker/.venv"
check_grep "$H5/.claude.json" "codex-worker" "codex-worker must still be registered with an old python"
CHECKS=$((CHECKS + 1))
if grep -qF "agy-worker" "$H5/.claude.json"; then fail "agy-worker registered although its venv was skipped"; fi

CHECKS=$((CHECKS + 1))
python3 - "$ROOT/retire.json" <<'PY' || fail "retire.json lacks the v2 entries"
import json, sys
spec = json.load(open(sys.argv[1]))
files = ("agents/implementer-strong.md", "skills/rownolegle", "skills/epik", "skills/teksty-ui",
         "skills/qa/references/scenariusze.md")
allow = ("Agent(implementer-strong)", "Write(/__HOME__/.claude/hooks/**)")
problems = [f"file {f}" for f in files if f not in spec["files"]]
problems += [f"allow {e}" for e in allow if e not in spec["settings"]["permissions.allow"]]
for problem in problems:
    print("  retire.json is missing", problem)
sys.exit(1 if problems else 0)
PY

echo "checks: $CHECKS, FAILURES: $FAILURES"
if [ "$FAILURES" != 0 ]; then
  echo "logs kept in $WORK"
  trap - EXIT
  echo "FAIL"
  exit 1
fi
echo "PASS $CHECKS/$CHECKS"
