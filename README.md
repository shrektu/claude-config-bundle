# Claude Code + Codex config bundle

Two scripts keep the setup identical on every machine.

- `export.sh [OUT_DIR]` — on the machine that has the current setup. Writes `~/claude-config-bundle/`
  and `~/claude-config-bundle.tar.gz` with home and codex paths replaced by placeholders.
- `install.sh` — on the target machine, from a normal terminal (not from inside a Claude Code session, whose
  classifier blocks writes to `settings.json`). Merges, backs up, and is safe to re-run.

## Moving it

Preferred: keep the exported directory in a private git repository.

```bash
~/.claude/bundle/export.sh
cd ~/claude-config-bundle && git init -q && git add -A && git commit -qm "config $(date +%F)"
git remote add origin <private-repo-url> && git push -u origin HEAD
```

On the other machine:

```bash
git clone <private-repo-url> ~/claude-config-bundle   # or git pull when it exists
~/claude-config-bundle/install.sh
```

Alternative without git: copy the tarball (scp, USB, cloud drive), `tar -xzf`, run `install.sh`.

After changing anything in `~/.claude` on either machine, run `export.sh` there, commit, push, and
`install.sh` on the other one. The repository is the source of truth; last export wins.

## What travels

CLAUDE.md, settings.json (workflow keys, permissions, hooks, output caps), agents, skills, prompts,
`bin/` (verify, review-checkpoint), `hooks/` (git-guard + its test matrix), the codex-worker MCP server
and its registration for Claude and Codex, the statusline script, Codex `AGENTS.md`.

## What stays local on purpose

Logins (`claude login`, `codex login`), `settings.json` → `env` and `autoMode` (machine-specific repo
descriptions), the rest of `~/.codex/config.toml` (partly managed by the ChatGPT desktop app),
Claude auto-memory (`~/.claude/projects/<path>/memory`, keyed by the project path), sessions, caches.
