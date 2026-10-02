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

## Workflow v3 in one screen

One TDD pipeline. Claude (the main session, Opus 5.5) writes a plan file (task, architecture, test_plan,
acceptance_criteria, commands, repos, risks) → `codex-runner` gets gpt-6-sol/high to list plan defects
→ Claude fixes the plan → `developer` (Sonnet 5.5, effort medium) implements it test-first: red through
`verify`, green, refactor → `codex-runner` gets gpt-6-sol/high to list code defects → Claude reproduces
each finding, sends the real ones back as one fix round, and runs the unit and integration tests itself.
After a fix round sol re-reviews only the checkpoint diff plus the earlier findings. Fast path: a change of
≤ ~20 lines in ≤ 2 files outside any risk area is done by Claude directly, still test-first, without
Codex reviews or the developer. The relay passes only paths and SHAs; the codex-worker MCP server builds the
prompt and returns `PASS` or one `H:`/`L:` line per defect (H = real defect, L = minor; L never opens a
fix round) under a token header.

Hooks (`claude/hooks/`, registered in `settings.json`): `git-guard.py` (destructive git),
`git-policy.py` (branch rule + commit message format), `verify-guard.py` (bare test/lint/build),
`read-guard.py` (whole-file reads), `delegation-guard.py` (developer and codex-runner need a complete
plan file), `tdd-guard.py` (the developer edits production code only after a test edit and a
`VERIFY FAIL`), `comment-guard.py` (no edit may add a comment to code; directives and one-line
docstrings pass; `--scan [--raw] FILE…` lists findings), `subagent-verify-check.py` (the developer must
verify after its last edit), `lint-guard.py` (an edit may not add a ruff violation, or an eslint one where
the repo has an eslint config; the repo's own config wins, else `~/.claude/lint/ruff.toml`; it fails open),
`bash-write-guard.py` (a Bash command may not write a code file inside a git work tree), plus `repo-facts`
as the SessionStart context. `shell_words.py` is their shared command parser, `code_files.py` their shared
code-file and comment-syntax map, `edit_texts.py` their shared before/after texts of an edit. Each hook
ships with a `*-test.py` matrix; the worker ships with `codex_worker_test.py`.

Skills (`claude/skills/`): `tdd` (red → green → refactor, test_plan design, `tdd_exempt:`), `delegate`
(plan-file template, developer and codex-runner prompts), `review` (checklist, finding adjudication, test
gate, rounds, final report), `repo-standards` (pinned versions, the API oracle, current-vs-legacy idioms),
`commit`, `pr-description`. The developer preloads `tdd` and `repo-standards`.

CLIs (`claude/bin/`): `verify` (runs checks, keeps the log on disk, prints the summary),
`review-checkpoint` (incremental review diffs, new files included, via a temporary index), `repo-facts` (toolchain and pinned-version facts),
`usage-report` (token/context baseline from the local transcripts), `feature-worktree` (`new` / `done` / `list`:
one git worktree per feature branch next to the repo; `done` removes only work that has landed on its base).

## What travels

CLAUDE.md, settings.json (workflow keys, permissions, hooks, output caps), `agents/`, `skills/`,
`templates/` (the `.claude/rules/standards.md` template for projects), `bin/` (verify,
review-checkpoint, repo-facts, usage-report, feature-worktree), `hooks/` (git-guard, git-policy, verify-guard, read-guard,
delegation-guard, tdd-guard, comment-guard, lint-guard, bash-write-guard, subagent-verify-check, shell_words,
code_files, edit_texts + their test matrices), `lint/ruff.toml` (the global ruff config; install.sh never
overwrites an existing one), `retire.json` (what install.sh removes
from an older home), the codex-worker MCP server with its unit test and its registration for Claude and Codex, the
statusline script, Codex `AGENTS.md`.

## After installing

Code review runs on gpt-6-sol, which needs codex-cli 0.157.1 or newer: an older CLI makes the API answer
"The 'gpt-6-sol' model is not supported when using Codex with a ChatGPT account". Check `codex --version`.

```bash
for h in tdd-guard comment-guard lint-guard bash-write-guard git-guard git-policy verify-guard read-guard delegation-guard subagent-verify-check; do
  python3 ~/.claude/hooks/$h-test.py || echo "FAILED: $h"
done
~/.claude/mcp/codex-worker/.venv/bin/python ~/.claude/mcp/codex-worker/codex_worker_test.py
bash ~/.claude/bin/review-checkpoint-test.sh
bash ~/.claude/bin/feature-worktree-test.sh
~/.claude/bin/repo-facts                  # inside a repo: versions, locked vs installed
~/.claude/bin/usage-report --days 30      # token/context baseline
```

install.sh keeps the 5 newest `~/.claude/backups/bundle-*` directories and removes older ones.
`settings.json` sets `autoCompactWindow` to `200k`.

## What stays local on purpose

Logins (`claude login`, `codex login`), `settings.json` → `env` and `autoMode` (machine-specific repo
descriptions), the rest of `~/.codex/config.toml` (partly managed by the ChatGPT desktop app),
Claude auto-memory (`~/.claude/projects/<path>/memory`, keyed by the project path), sessions, caches.
