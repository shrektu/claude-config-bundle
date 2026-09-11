#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: export.sh [OUT_DIR]      (default: ~/claude-config-bundle; also writes OUT_DIR.tar.gz)
Packs the portable Claude Code + Codex setup of this machine: CLAUDE.md, settings.json (without autoMode),
agents, skills, prompts, bin, hooks, the codex-worker MCP server, statusline, Codex AGENTS.md and the
codex-worker entries for ~/.claude.json and ~/.codex/config.toml. Paths are replaced by __HOME__ and
__CODEX_BIN__ so install.sh can render them on any machine. Credentials, sessions, memory and caches stay out.
USAGE
}
set -euo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
OUT=${1:-$HOME/claude-config-bundle}
HERE=$(cd "$(dirname "$0")" && pwd)
CODEX_BIN=$(command -v codex || true)
mkdir -p "$OUT"
find "$OUT" -mindepth 1 -maxdepth 1 ! -name .git ! -name .gitignore -exec rm -rf {} +
mkdir -p "$OUT/claude/mcp/codex-worker" "$OUT/codex"
for d in agents skills prompts bin hooks; do
  [ -d "$HOME/.claude/$d" ] && cp -a "$HOME/.claude/$d" "$OUT/claude/"
done
cp "$HOME/.claude/CLAUDE.md" "$HOME/.claude/statusline-command.sh" "$OUT/claude/"
cp "$HOME/.claude/mcp/codex-worker/codex_worker.py" "$HOME/.claude/mcp/codex-worker/requirements.txt" "$OUT/claude/mcp/codex-worker/"
cp "$HOME/.codex/AGENTS.md" "$OUT/codex/AGENTS.md"
python3 - "$HOME/.claude/settings.json" "$OUT/claude/settings.json" <<'PY'
import json, sys
settings = json.load(open(sys.argv[1]))
settings.pop("autoMode", None)
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
    }
  }
}
JSON
cat > "$OUT/codex/config.fragment.toml" <<'TOML'

[mcp_servers.codex-worker]
command = "env"
args = [
    "CODEX_BIN=__CODEX_BIN__",
    "__HOME__/.claude/mcp/codex-worker/.venv/bin/python",
    "__HOME__/.claude/mcp/codex-worker/codex_worker.py",
]
TOML
find "$OUT" -type f \( -name '*.md' -o -name '*.json' -o -name '*.sh' -o -name '*.py' -o -name '*.toml' -o -name '*.txt' -o -path '*/bin/*' \) -print0 \
  | xargs -0 sed -i -e "s#${CODEX_BIN:-/nonexistent}#__CODEX_BIN__#g" -e "s#$HOME#__HOME__#g"
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} +
cp "$HERE/install.sh" "$HERE/export.sh" "$HERE/README.md" "$OUT/"
{
  echo "exported: $(date -Is) on $(hostname) by $USER"
  echo "claude: $(claude --version 2>/dev/null || echo unknown)"
  echo "codex:  $(codex --version 2>/dev/null || echo unknown)"
  echo "files:"; (cd "$OUT" && find . -type f | sort | sed 's/^/  /')
} > "$OUT/manifest.txt"
if grep -rIl "$HOME" "$OUT" >/dev/null 2>&1; then echo "WARNING: unrendered home paths remain:"; grep -rIl "$HOME" "$OUT"; fi
tar --exclude=.git -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
echo "bundle: $OUT"
echo "tarball: $OUT.tar.gz ($(du -h "$OUT.tar.gz" | cut -f1))"
