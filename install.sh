#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: ./install.sh
Applies this bundle to the current machine. Idempotent: unchanged files are skipped, changed files are backed
up to ~/.claude/backups/bundle-<stamp>/ before being replaced. The bundle's own install.sh, export.sh,
README.md and retire.json are copied to ~/.claude/bundle/ verbatim, so their __HOME__ placeholders survive. retire.json is processed first (retired files
and settings entries are backed up and removed). settings.json is MERGED (bundle wins for workflow keys, this
machine keeps env and autoMode, allow/deny lists are unioned, hooks are replaced per event+matcher so a hook
is never registered twice; local-only matchers stay). ~/.claude.json
gets the codex-worker MCP server, ~/.codex/config.toml gets the codex-worker block appended if missing.
Run it from a normal terminal, not from inside a Claude Code session.
USAGE
}
set -euo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=$HOME/.claude/backups/bundle-$STAMP
CODEX_BIN=$(command -v codex || true)
[ -n "$CODEX_BIN" ] || { echo "codex CLI not found on PATH - install it first (https://chatgpt.com/codex/install.sh)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
CHANGED=0

render() { sed -e "s#__CODEX_BIN__#$CODEX_BIN#g" -e "s#__HOME__#$HOME#g" "$1"; }
backup() {
  [ -e "$1" ] || return 0
  mkdir -p "$BACKUP/$(dirname "${1#"$HOME"/}")"
  cp -a "$1" "$BACKUP/${1#"$HOME"/}"
}
install_file() {
  local src=$1 dst=$2 mode=${3:-644} tmp
  tmp=$(mktemp)
  render "$src" > "$tmp"
  if [ -e "$dst" ] && cmp -s "$tmp" "$dst"; then rm -f "$tmp"; return 0; fi
  backup "$dst"
  mkdir -p "$(dirname "$dst")"
  mv "$tmp" "$dst"
  chmod "$mode" "$dst"
  echo "updated: $dst"
  CHANGED=$((CHANGED + 1))
}

install_raw() {
  local src=$1 dst=$2 mode=${3:-644}
  if [ -e "$dst" ] && cmp -s "$src" "$dst"; then return 0; fi
  backup "$dst"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  chmod "$mode" "$dst"
  echo "updated: $dst"
  CHANGED=$((CHANGED + 1))
}

mkdir -p "$HOME/.claude/backups" "$HOME/.codex"
install_file "$HERE/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
install_file "$HERE/claude/statusline-command.sh" "$HOME/.claude/statusline-command.sh" 755
for d in agents skills prompts templates; do
  [ -d "$HERE/claude/$d" ] || continue
  while IFS= read -r -d '' f; do install_file "$f" "$HOME/.claude/$d/${f#"$HERE"/claude/$d/}"; done < <(find "$HERE/claude/$d" -type f -print0)
done
for d in bin hooks; do
  [ -d "$HERE/claude/$d" ] || continue
  while IFS= read -r -d '' f; do install_file "$f" "$HOME/.claude/$d/${f#"$HERE"/claude/$d/}" 755; done < <(find "$HERE/claude/$d" -type f -print0)
done
install_file "$HERE/claude/mcp/codex-worker/codex_worker.py" "$HOME/.claude/mcp/codex-worker/codex_worker.py" 755
install_file "$HERE/claude/mcp/codex-worker/requirements.txt" "$HOME/.claude/mcp/codex-worker/requirements.txt"
printf 'CODEX_BIN=%s\n' "$CODEX_BIN" > "$HOME/.claude/mcp/codex-worker/.env"
install_file "$HERE/codex/AGENTS.md" "$HOME/.codex/AGENTS.md"
for f in export.sh install.sh README.md retire.json; do
  [ -f "$HERE/$f" ] || continue
  install_raw "$HERE/$f" "$HOME/.claude/bundle/$f" "$([ "${f##*.}" = sh ] && echo 755 || echo 644)"
done

RETIRE=$HERE/retire.json
if [ -f "$RETIRE" ]; then
  python3 - "$RETIRE" "$HOME/.claude" "$BACKUP" "$HOME/.claude/settings.json" <<'PY'
import json, os, shutil, sys

spec = json.load(open(sys.argv[1]))
claude_dir, backup, settings_path = sys.argv[2], sys.argv[3], sys.argv[4]
home = os.path.dirname(claude_dir)


def keep_path(path):
    dest = os.path.join(backup, os.path.relpath(path, home))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    return dest


def keep_copy(path):
    dest = keep_path(path)
    if os.path.isdir(path):
        shutil.copytree(path, dest, dirs_exist_ok=True)
    else:
        shutil.copy2(path, dest)


for relative in spec.get("files", []):
    path = os.path.join(claude_dir, relative)
    if not os.path.exists(path):
        continue
    keep_copy(path)
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
    print(f"retired: {path}")

if not os.path.exists(settings_path):
    raise SystemExit(0)
settings = json.load(open(settings_path))
dropped = []
for dotted, names in spec.get("settings", {}).items():
    node = settings
    for part in dotted.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            break
    if isinstance(node, dict):
        for name in names:
            if node.pop(name, None) is not None:
                dropped.append(f"{dotted}.{name}")
    elif isinstance(node, list):
        for name in names:
            while name in node:
                node.remove(name)
                dropped.append(f"{dotted}[{name}]")
if dropped:
    shutil.copy2(settings_path, keep_path(settings_path) + ".pre-retire")
    json.dump(settings, open(settings_path, "w"), indent=2, ensure_ascii=False)
    open(settings_path, "a").write("\n")
    print("retired settings entries: " + ", ".join(dropped))
PY
fi

VENV=$HOME/.claude/mcp/codex-worker/.venv
REQ=$HOME/.claude/mcp/codex-worker/requirements.txt
if [ ! -x "$VENV/bin/python" ] || ! cmp -s "$REQ" "$VENV/.installed-requirements" 2>/dev/null; then
  echo "building venv: $VENV"
  if python3 -m venv "$VENV" 2>/dev/null && "$VENV/bin/pip" install -q -r "$REQ"; then :
  elif command -v uv >/dev/null; then uv venv -q "$VENV" && uv pip install -q --python "$VENV/bin/python" -r "$REQ"
  else echo "could not build the venv (python3 -m venv failed and uv is missing)"; exit 1; fi
  cp "$REQ" "$VENV/.installed-requirements"
fi
"$VENV/bin/python" -c "import mcp" || { echo "venv is missing the mcp package"; exit 1; }

SETTINGS=$HOME/.claude/settings.json
RENDERED_SETTINGS=$(mktemp)
render "$HERE/claude/settings.json" > "$RENDERED_SETTINGS"
python3 - "$SETTINGS" "$RENDERED_SETTINGS" "$BACKUP" <<'PY'
import json, os, shutil, sys
bundle = json.load(open(sys.argv[2]))
path = sys.argv[1]
local = json.load(open(path)) if os.path.exists(path) else {}
merged = dict(local)
for key, value in bundle.items():
    if key == "env":
        merged["env"] = {**value, **local.get("env", {})}
    elif key == "permissions":
        perms = dict(local.get("permissions", {}))
        for lst in ("allow", "deny", "ask"):
            if lst in value or lst in perms:
                perms[lst] = list(dict.fromkeys(list(perms.get(lst, [])) + list(value.get(lst, []))))
        for other in value:
            if other not in ("allow", "deny", "ask"):
                perms[other] = value[other]
        merged["permissions"] = perms
    elif key == "hooks":
        hooks = {k: list(v) for k, v in local.get("hooks", {}).items()}
        for event, entries in value.items():
            taken = {e.get("matcher") for e in entries if isinstance(e, dict)}
            local_only = [e for e in hooks.get(event, [])
                          if not isinstance(e, dict) or e.get("matcher") not in taken]
            hooks[event] = list(entries) + local_only
        merged["hooks"] = hooks
    elif key == "autoMode":
        merged.setdefault("autoMode", value)
    else:
        merged[key] = value
if merged == local:
    print("settings.json: unchanged")
else:
    if os.path.exists(path):
        os.makedirs(os.path.join(sys.argv[3], ".claude"), exist_ok=True)
        shutil.copy2(path, os.path.join(sys.argv[3], ".claude", "settings.json"))
    json.dump(merged, open(path, "w"), indent=2, ensure_ascii=False)
    open(path, "a").write("\n")
    changed = sorted(k for k in set(merged) | set(local) if merged.get(k) != local.get(k))
    print("settings.json: merged, changed keys: " + ", ".join(changed))
PY
rm -f "$RENDERED_SETTINGS"

MCP_JSON=$(render "$HERE/claude/mcp-servers.json" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["mcpServers"]["codex-worker"]))')
CURRENT=$(python3 -c 'import json,os,sys; p=os.path.expanduser("~/.claude.json"); d=json.load(open(p)) if os.path.exists(p) else {}; print(json.dumps(d.get("mcpServers",{}).get("codex-worker")))')
if [ "$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]),sort_keys=True))' "$MCP_JSON")" = "$(python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]),sort_keys=True))' "$CURRENT")" ]; then
  echo "~/.claude.json: codex-worker already registered"
else
  backup "$HOME/.claude.json"
  if command -v claude >/dev/null; then
    claude mcp remove codex-worker -s user >/dev/null 2>&1 || true
    claude mcp add-json codex-worker "$MCP_JSON" -s user
  else
    python3 - "$MCP_JSON" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.claude.json")
d = json.load(open(p)) if os.path.exists(p) else {}
d.setdefault("mcpServers", {})["codex-worker"] = json.loads(sys.argv[1])
json.dump(d, open(p, "w"), indent=2)
print("~/.claude.json: codex-worker registered (python merge; claude CLI not on PATH)")
PY
  fi
fi

CODEX_CFG=$HOME/.codex/config.toml
if [ -e "$CODEX_CFG" ] && grep -q '^\[mcp_servers.codex-worker\]' "$CODEX_CFG"; then
  if grep -q "$HOME/.claude/mcp/codex-worker/codex_worker.py" "$CODEX_CFG"; then echo "~/.codex/config.toml: codex-worker block present"
  else echo "~/.codex/config.toml: codex-worker block present but with different paths - review it by hand"; fi
else
  backup "$CODEX_CFG"
  render "$HERE/codex/config.fragment.toml" >> "$CODEX_CFG"
  echo "updated: $CODEX_CFG (codex-worker block appended)"
fi
python3 -c "import tomllib,sys; tomllib.load(open(sys.argv[1],'rb'))" "$CODEX_CFG" && echo "~/.codex/config.toml: valid TOML"

echo
echo "done. files changed: $CHANGED$( [ -d "$BACKUP" ] && echo "; backups in $BACKUP" )"
echo "next:"
echo "  - restart Claude Code (agents, hooks and MCP servers load at session start)"
echo "  - claude mcp list            -> codex-worker must show Connected"
echo '  - for t in git-guard verify-guard read-guard git-policy delegation-guard subagent-verify-check repo-facts; do python3 ~/.claude/hooks/$t-test.py || break; done'
echo "  - bash ~/.claude/bin/verify-test.sh"
echo "  - ~/.claude/bin/repo-facts            -> toolchain facts of the current repo (also the SessionStart hook)"
echo "  - claude login / codex login if this machine is fresh; set autoMode.environment for this machine's repos"
