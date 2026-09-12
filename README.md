# Claude Code + Codex config bundle

Two scripts keep the setup identical on every machine.

- `export.sh [OUT_DIR]` — on the machine that has the current setup. Writes `~/claude-config-bundle/`
  and `~/claude-config-bundle.tar.gz` with home and codex paths replaced by placeholders.
- `install.sh` — on the target machine, from a normal terminal (not from inside a Claude Code session, whose
  classifier blocks writes to `settings.json`). Merges, backs up, and is safe to re-run.

## Moving it

Preferred: keep the exported directory in a private git repository.

The repository already exists: `git@github.com:shrektu/claude-config-bundle.git` (private). To publish
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

## Workflow v2 in one screen

`CLAUDE.md` is the orchestrator core: it classifies the task, delegates, supervises and reviews. Rules
that can be checked mechanically live in hooks; situational knowledge lives in skills that load on demand.

| Class | Definition | Implementer | Codex |
|---|---|---|---|
| S | ≤ ~30 lines, ≤ 2 files, no new module, no risk area | the orchestrator itself | no |
| M | not S, not L, not XL | `implementer` (Sonnet high) | code review at ≥ 200 lines, > 3 files, or on request |
| L | architecture understanding, several modules, hard bug, perf, > ~300 lines | `implementer-hard` (Sonnet xhigh) or `implementer-opus` | code review every round; plan review if an architectural question is open |
| XL | any risk area: migration, concurrency, protocol/firmware, data shape or public API, multi-repo, auth/secrets/PII/payments, data deletion | `implementer-hard` / `implementer-opus` | plan review (`mode=plan`, xhigh), code review every round, final audit |

Hooks (`claude/hooks/`, registered in `settings.json`): `git-guard.py` (destructive git),
`git-policy.py` (branch rule + commit message format), `verify-guard.py` (bare test/lint/build),
`read-guard.py` (whole-file reads), `delegation-guard.py` (implementer prompt fields),
`subagent-verify-check.py` (an implementer must verify after its last edit), plus `repo-facts` as the
SessionStart context. Each one ships with a `*-test.py` matrix.

Skills (`claude/skills/`): `delegate` (prompt templates for the implementers and codex-runner),
`review` (review checklist, finding adjudication, round mechanics, final report), `repo-standards`
(pinned versions, the API oracle, current-vs-legacy idioms — preloaded into every implementer),
`commit`, `pr-description`.

CLIs (`claude/bin/`): `verify` (runs checks, keeps the log on disk, prints the summary),
`review-checkpoint` (incremental review diffs), `repo-facts` (toolchain and pinned-version facts),
`usage-report` (token/context baseline from the local transcripts).

## What travels

CLAUDE.md, settings.json (workflow keys, permissions, hooks, output caps), `agents/`, `skills/`,
`templates/` (the `.claude/rules/standards.md` template for projects), `bin/` (verify,
review-checkpoint, repo-facts, usage-report), `hooks/` (git-guard, git-policy, verify-guard, read-guard,
delegation-guard, subagent-verify-check + their test matrices), `retire.json` (what install.sh removes
from an older home), the codex-worker MCP server and its registration for Claude and Codex, the
statusline script, Codex `AGENTS.md`.

## After installing

```bash
for h in git-guard git-policy verify-guard read-guard delegation-guard subagent-verify-check; do
  python3 ~/.claude/hooks/$h-test.py || echo "FAILED: $h"
done
~/.claude/bin/repo-facts                  # inside a repo: versions, locked vs installed
~/.claude/bin/usage-report --days 30      # token/context baseline
```

## What stays local on purpose

Logins (`claude login`, `codex login`), `settings.json` → `env` and `autoMode` (machine-specific repo
descriptions), the rest of `~/.codex/config.toml` (partly managed by the ChatGPT desktop app),
Claude auto-memory (`~/.claude/projects/<path>/memory`, keyed by the project path), sessions, caches.
