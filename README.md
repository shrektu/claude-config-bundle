# Claude Code + Codex config bundle

Two scripts keep the setup identical on every machine.

- `export.sh [OUT_DIR]` — on the machine that has the current setup. Writes `~/claude-config-bundle/`
  and `~/claude-config-bundle.tar.gz` with home and codex paths replaced by placeholders.
- `install.sh` — on the target machine, from a normal terminal (not from inside a Claude Code session, whose
  classifier blocks writes to `settings.json`). Merges, backs up, and is safe to re-run.

## Moving it

Preferred: keep the exported directory in a git repository.

The repository already exists: `git@github.com:shrektu/claude-config-bundle.git`. To publish
changes made on this machine:

```bash
~/.claude/bundle/export.sh
cd ~/claude-config-bundle && git add -A && git commit -s -m "Update config $(date +%F)" && git push
```

On the other machine:

```bash
git clone git@github.com:shrektu/claude-config-bundle.git ~/claude-config-bundle   # or git pull when it exists
~/claude-config-bundle/install.sh
```

Alternative without git: copy the tarball (scp, USB, cloud drive), `tar -xzf`, run `install.sh`.

After changing anything in `~/.claude` on either machine, run `export.sh` there, commit, push, and
`install.sh` on the other one. The repository is the source of truth; last export wins.

## Workflow in one screen

One orchestrator session plans, delegates, reviews and commits; everything else is a specialist.

- Orchestrator (the main session, Opus 5.5): classifies the task, writes a short plan (objective,
  constraints, files, reuse, tests, risks, failure modes, open questions), delegates, reviews every round
  itself, runs the end tests and commits.
- `implementer` (Claude Sonnet 5.5, effort medium): edits files, runs tests through `verify`, fixes its own
  failures. It makes no architecture decisions.
- `implementer-strong` (Codex gpt-6.1-sol, effort medium, through `codex_implement`): one escalation attempt
  after three fix rounds without progress.
- `writer` (Sonnet 5.5, read-only): drafts the prose the orchestrator publishes (PR descriptions,
  ticket comments, longer replies).
- `codex-runner` (gpt-6.1-sol, reasoning effort high): the plan gate critiques every M/L/XL plan before the
  implementer starts; the code gate reviews the diff for bugs before every commit. Its findings are input
  to the orchestrator's adjudication, never orders.

Task classes: S (about 30 lines, at most 2 files, no risk area), M, L (architecture-level, several modules
or more than about 300 lines), XL (any risk area: migration, concurrency, protocol, public API, auth,
data deletion). The TDD ladder grows with the class: S one red test then the fix; M acceptance, implementation,
unit, edge cases, refactor under green; L adds integration-level acceptance tests against fakes; XL adds a
migration or protocol scenario and a verify run after the refactor. Every phase starts with a failing test run
through `verify`.

`verify` (`claude/bin/verify`) runs every test, lint and build, keeps the full log on disk and prints a
summary. It runs inside a systemd user scope (MemoryMax 6G, swap 1G, CPUQuota 600%, CPUWeight 30, nice 10);
`VERIFY_MEMORY_MAX`, `VERIFY_SWAP_MAX`, `VERIFY_CPU_QUOTA`, `VERIFY_CPU_WEIGHT` and `VERIFY_NICE` override
the limits and `VERIFY_NO_LIMITS=1` disables them.

Hooks (`claude/hooks/`, registered in `settings.json`): `git-guard` (destructive git), `git-policy` (branch
rule and commit message format), `verify-guard` (bare test, lint and build commands), `read-guard` (whole-file
reads), `delegation-guard` (a delegation must carry its required fields), `tdd-guard` (production edits only
after a red run), `comment-guard` (no comments in code), `standards-gate` (lint on every commit and at
subagent stop), `subagent-verify-check` (an implementer must verify after its last edit), `codex-gate`,
`autofix-on-edit`, `context-guard`, `session-start-marker` and `payload-probe`; `repo-facts` is the
SessionStart context. Each hook ships with a `*-test.py` matrix.

Skills (`claude/skills/`): `task` (a ticket from start to an open PR), `epik` (a whole epic), `qa` (end-to-end
scenarios), `delegate` (spawn prompts and escalation), `review` (a review round and the final report),
`rownolegle` (independent milestones in parallel worktrees), `commit`, `pr-description`, `bb` (Bitbucket
review) and `repo-standards` (pinned versions and idioms).

CLIs (`claude/bin/`): `verify`, `review-checkpoint` (incremental review diffs), `repo-facts` (toolchain and
pinned-version facts), `lint-strict` (the commit-gate linters), `habits` (rules learned from reviews),
`ai-review-gate`, `usage-report` (token and context baseline from local transcripts) and `bb-sweep`.

## What travels

CLAUDE.md, settings.json (workflow keys, permissions, hooks, output caps), `agents/`, `skills/`, `templates/`,
`bin/`, `hooks/` (with their test matrices), `retire.json` (what install.sh removes from an older home),
the codex-worker MCP server with its registration for Claude and Codex (the worker's unit test only when
it exists on the exporting machine), the statusline script, Codex `AGENTS.md`.

## After installing

Code review runs on gpt-6.1-sol, which needs a recent codex-cli. Check `codex --version`.

```bash
for h in autofix-on-edit codex-gate comment-guard context-guard delegation-guard git-guard git-policy payload-probe read-guard repo-facts standards-gate subagent-verify-check tdd-guard verify-guard; do
  python3 ~/.claude/hooks/$h-test.py || echo "FAILED: $h"
done
bash ~/.claude/bin/verify-test.sh
~/.claude/bin/repo-facts                  # inside a repo: versions, locked vs installed
~/.claude/bin/usage-report --days 30      # token/context baseline
```

install.sh keeps the 5 newest `~/.claude/backups/bundle-*` directories and removes older ones.

## What stays local on purpose

Logins (`claude login`, `codex login`), `settings.json` → `env` and `autoMode` (machine-specific repo
descriptions), the rest of `~/.codex/config.toml` (partly managed by the ChatGPT desktop app),
Claude auto-memory (`~/.claude/projects/<path>/memory`, keyed by the project path), sessions, caches.

## Private content

When the exported directory goes to a public repository, three optional files placed next to `export.sh`
keep company-specific content out. They are never exported themselves.

- `exclude.local` — one path per line, relative to the export directory (for example
  `claude/skills/acme-internal`). Empty lines and lines starting with `#` are ignored. Absolute paths and
  paths containing `..` abort the export with exit 2.
- `scrub.local.sed` — a `sed -E` script applied to every exported text file (for example
  `s/acmecorp/example/g`).
- `leak-check.local` — one extended regex per line (for example `acme(corp)?\.example\.com`). It is
  checked case-insensitively against everything exported, binaries and `manifest.txt` included. Any hit
  prints the `file:line` matches, writes no manifest and no tarball, and exits 3.

Independent of these files, `*.bak*` files, `.pytest_cache`, `.ruff_cache`, `__pycache__` and
`claude/skills/synced` are never exported.
