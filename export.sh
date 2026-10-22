#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: export.sh [OUT_DIR]      (default: ~/claude-config-bundle; also writes OUT_DIR.tar.gz)
Packs the portable Claude Code + Codex setup of this machine: CLAUDE.md, settings.json (without autoMode and the machine mode),
agents, skills, prompts, templates, bin, hooks, lint (ruff.toml), the codex-worker and agy-worker MCP servers, statusline, Codex AGENTS.md and the
MCP entries for ~/.claude.json and ~/.codex/config.toml, plus retire.json so the retirement
list travels with the bundle. Paths are replaced by __HOME__, __CODEX_BIN__ and
__AGY_BIN__ so install.sh can render them on any machine. Credentials, sessions, memory and caches stay out.
USAGE
}
set -euo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
OUT=${1:-$HOME/claude-config-bundle}
HERE=$(cd "$(dirname "$0")" && pwd)
CODEX_BIN=$(command -v codex || true)
config_lines() {
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(printf '%s' "$line" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
    case $line in ''|'#'*) continue ;; esac
    printf '%s\n' "$line"
  done < "$1"
}
text_files() {
  find "$OUT" -type f \( -name '*.md' -o -name '*.json' -o -name '*.sh' -o -name '*.py' -o -name '*.toml' -o -name '*.txt' -o -path '*/bin/*' \) -print0
}
drop_private() {
  find "$OUT" \( -name '*.bak*' -o -name .pytest_cache -o -name .ruff_cache -o -name __pycache__ \) \
    -prune -exec rm -rf {} +
  rm -rf "$OUT/claude/skills/synced"
  [ -f "$HERE/exclude.local" ] || return 0
  local entry parent root
  root=$(realpath -- "$OUT")
  while IFS= read -r entry; do
    case $entry in
      /*|*..*|.) echo "export: refusing exclude entry: $entry" >&2; exit 2 ;;
    esac
    parent=$(realpath -m -- "$OUT/$(dirname -- "$entry")")
    case $parent in
      "$root"|"$root"/*) ;;
      *) echo "export: refusing exclude entry: $entry" >&2; exit 2 ;;
    esac
    rm -rf "${OUT:?}/$entry"
  done < <(config_lines "$HERE/exclude.local")
}
scrub_private() {
  [ -f "$HERE/scrub.local.sed" ] || return 0
  { grep -rIlZ --exclude-dir=.git '' "$OUT" || true; } | xargs -0 -r sed -E -i -f "$HERE/scrub.local.sed"
}
check_leaks() {
  [ -f "$HERE/leak-check.local" ] || return 0
  local re found status hits=
  while IFS= read -r re; do
    status=0
    found=$(grep -rainE --exclude-dir=.git -- "$re" "$OUT") || status=$?
    if [ "$status" -ge 2 ]; then
      rm -f "$OUT/manifest.txt"
      echo "export: invalid leak pattern: $re" >&2
      exit 3
    fi
    hits+=$found$'\n'
  done < <(config_lines "$HERE/leak-check.local")
  [ -n "${hits//$'\n'/}" ] || return 0
  rm -f "$OUT/manifest.txt"
  { echo "export: private content found:"; printf '%s' "$hits"; } >&2
  exit 3
}
check_shebangs() {
  [ -d "$OUT/claude" ] || return 0
  local pinned
  pinned=$(find "$OUT/claude" -type f -exec awk 'FNR == 1 { if (/^#!__HOME__\//) print FILENAME; nextfile }' {} + | sed "s#^$OUT/##" | sort)
  [ -n "$pinned" ] || return 0
  rm -f "$OUT/manifest.txt"
  { echo "export: machine-specific interpreter in shebang:"; echo "$pinned"; } >&2
  exit 3
}
mkdir -p "$OUT"
rm -f "$OUT.tar.gz"
find "$OUT" -mindepth 1 -maxdepth 1 ! -name .git ! -name .gitignore -exec rm -rf {} +
mkdir -p "$OUT/claude/mcp/codex-worker" "$OUT/codex"
for d in agents skills prompts templates bin hooks lint; do
  [ -d "$HOME/.claude/$d" ] && cp -a "$HOME/.claude/$d" "$OUT/claude/"
done
cp "$HOME/.claude/CLAUDE.md" "$HOME/.claude/statusline-command.sh" "$OUT/claude/"
cp "$HOME/.claude/mcp/codex-worker/codex_worker.py" "$HOME/.claude/mcp/codex-worker/requirements.txt" \
  "$OUT/claude/mcp/codex-worker/"
[ ! -f "$HOME/.claude/mcp/codex-worker/test_codex_worker.py" ] \
  || cp "$HOME/.claude/mcp/codex-worker/test_codex_worker.py" "$OUT/claude/mcp/codex-worker/"
if [ -d "$HOME/.claude/mcp/agy-worker" ]; then
  mkdir -p "$OUT/claude/mcp/agy-worker"
  find "$HOME/.claude/mcp/agy-worker" -maxdepth 1 -type f \
    \( -name '*.py' -o -name 'requirements*.txt' -o -name pyproject.toml -o -name allowed-remotes.txt \) \
    -exec cp {} "$OUT/claude/mcp/agy-worker/" \;
fi
cp "$HOME/.codex/AGENTS.md" "$OUT/codex/AGENTS.md"
python3 - "$HOME/.claude/settings.json" "$OUT/claude/settings.json" <<'PY'
import json, sys
settings = json.load(open(sys.argv[1]))
settings.pop("autoMode", None)
for machine_key in ("CLAUDE_MODE", "CLAUDE_CODEX"):
    settings.get("env", {}).pop(machine_key, None)
json.dump(settings, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
open(sys.argv[2], "a").write("\n")
PY
cat > "$OUT/claude/mcp-servers.json" <<'JSON'
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
[ -d "$HOME/.claude/mcp/agy-worker" ] || python3 - "$OUT/claude/mcp-servers.json" <<'PY'
import json, sys

path = sys.argv[1]
data = json.load(open(path))
del data["mcpServers"]["agy-worker"]
json.dump(data, open(path, "w"), indent=2)
open(path, "a").write("\n")
PY
cat > "$OUT/codex/config.fragment.toml" <<'TOML'

[mcp_servers.codex-worker]
command = "env"
args = [
    "CODEX_BIN=__CODEX_BIN__",
    "__HOME__/.claude/mcp/codex-worker/.venv/bin/python",
    "__HOME__/.claude/mcp/codex-worker/codex_worker.py",
]
TOML
drop_private
text_files | xargs -0 -r sed -i -e "s#${CODEX_BIN:-/nonexistent}#__CODEX_BIN__#g" -e "s#$HOME#__HOME__#g"
scrub_private
cp "$HERE/install.sh" "$HERE/export.sh" "$HERE/README.md" "$OUT/"
if [ -f "$HERE/retire.json" ]; then cp "$HERE/retire.json" "$OUT/"; fi
{
  echo "exported: $(date -Is) on $(hostname) by $USER"
  echo "claude: $(claude --version 2>/dev/null || echo unknown)"
  echo "codex:  $(codex --version 2>/dev/null || echo unknown)"
  echo "files:"; (cd "$OUT" && find . -path ./.git -prune -o -type f -print | sort | sed 's/^/  /')
} > "$OUT/manifest.txt"
check_leaks
check_shebangs
if grep -rIl "$HOME" "$OUT" >/dev/null 2>&1; then echo "WARNING: unrendered home paths remain:"; grep -rIl "$HOME" "$OUT"; fi
tar --exclude=.git -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
echo "bundle: $OUT"
echo "tarball: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1))"
