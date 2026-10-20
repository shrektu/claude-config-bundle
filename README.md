# Claude Code + Codex config bundle

Two scripts keep the setup identical on every machine.

- `export.sh [OUT_DIR]` — on the machine that has the current setup. Writes `~/claude-config-bundle/`
  and `~/claude-config-bundle.tar.gz` with home and codex paths replaced by placeholders.
- `install.sh` — on the target machine, from a normal terminal (not from inside a Claude Code session, whose
  classifier blocks writes to `settings.json`). Merges, backs up, and is safe to re-run.

## Moving it

Preferred: keep the exported directory in a git repository.

The repository already exists: `git@github.com:shrektu/claude-config-bundle.git`. To publish changes made on
this machine, export to a temporary directory, copy the result into a clone of the repository (keeping its
`tests/`), and open a pull request from a work branch:

```bash
~/.claude/bundle/export.sh /tmp/claude-config-bundle-export
git clone git@github.com:shrektu/claude-config-bundle.git ~/claude-config-bundle   # or git pull when it exists
cd ~/claude-config-bundle && git switch -c feature/update-config
rsync -a --delete --exclude .git --exclude tests /tmp/claude-config-bundle-export/ ./
git add -A && git commit -m "Update config" && git push -u origin HEAD
```

Commit without `-s` and without trailers. On the other machine:

```bash
git clone git@github.com:shrektu/claude-config-bundle.git ~/claude-config-bundle   # or git pull when it exists
~/claude-config-bundle/install.sh
```

Alternative without git: copy the tarball (scp, USB, cloud drive), `tar -xzf`, run `install.sh`.

After changing anything in `~/.claude` on either machine, run `export.sh` there, publish as above, and
`install.sh` on the other one. The repository is the source of truth; last export wins.

## Workflow in one screen

One orchestrator session plans, delegates, supervises from evidence, reviews and commits; everything else is
a specialist behind a thin relay.

- Orchestrator (the main session, Opus 5.5): classifies the task S/M/L/XL, writes a short plan (objective,
  constraints, files, reuse, tests, risks, failure modes, open questions), delegates to one implementer,
  supervises it by evidence only during a milestone (`git status`, the diff stat, the RED and verify logs
  it names; "tests pass" without a log path counts for nothing), adjudicates the final review, runs the end
  tests and commits.
- `implementer` (Claude Sonnet 5.5, effort medium): the one implementer. Edits files, runs tests through
  `verify`, fixes its own failures. It makes no architecture decisions and has no iteration limit.
- Plan gate: `plan-gate-runner` relays the plan to Gemini 3.8 Flash (`agy_plan_review`); when Gemini is
  unavailable it falls back to Codex (`codex-runner`, gpt-6.1-sol, reasoning effort high). Findings are input
  to the orchestrator's adjudication, never orders.
- Final review (the trio): `codex-runner` (gpt-6.1-sol, effort medium, bugs only), `reviewer-opus` (Claude
  Opus 5.5, read-only) and `flash-review-runner` (Gemini 3.8 Flash, low) review the diff in parallel
  once per milestone (once per task with one milestone). After adjudication the milestone is committed and
  the fix round lands as a `--fixup` commit, verified by its tests and by reading the fix diff. A delta trio
  runs only for fixes over about 100 lines or in a risk area. The fixups are autosquashed before the report.
- `writer` (Claude Haiku 5.5): Gemini Flash drafts every text the customer never sees (PR descriptions,
  Jira comments, Bitbucket review comments and replies) and Haiku checks it; `ui-writer` (Claude Sonnet
  5.5) does the same for UI text shown on the frontend, with no footer. Everything published on
  Sebastian's behalf ends with the footer `🤖 Wygenerowane przez <model>`.
- Argon (`agy-worker`): reads datasheet PDFs and answers hard debugging questions (`agy_debug_consult`).

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

Skills (`claude/skills/`): `task` (a ticket from start to an open PR), `epic` (a whole epic), `qa`
(end-to-end scenarios), `delegate` (spawn prompts), `review` (a review round and the final report),
`parallel` (independent milestones in parallel worktrees), `commit`, `pr-description`, `bb` (Bitbucket
review), `datasheet` (claims checked against chip PDFs through Argon), `ui-texts` (UI texts and translations)
and `repo-standards` (pinned versions and idioms).

CLIs (`claude/bin/`): `verify`, `repo-facts` (toolchain and pinned-version facts), `lint-strict` (the
commit-gate linters), `habits` (rules learned from reviews), `usage-report` (token and context baseline
from local transcripts) and `bb-sweep`.

## agy-worker (Argon)

`claude/mcp/agy-worker/` is an MCP server that drives the Antigravity CLI (`agy`) for the plan gate, the
Flash code review, the writer, datasheet PDFs and `agy_debug_consult`. Every call runs `agy` inside a
bubblewrap sandbox (`/usr/bin/bwrap`, with `/usr/bin/xdg-dbus-proxy` for the session bus) on a throwaway
workspace, so the model can read what it is handed and nothing else. `allowed-remotes.txt` is the allowlist of
git remotes (one glob per line, for example `github.com/*`) the sandboxed run may fetch; install.sh installs
it only when the machine has none, so a machine's own allowlist is never overwritten (a note says when it
differs from the bundle's).

Prerequisites, all warnings and never failures at install time: `agy` on PATH (Antigravity CLI:
`curl -fsSL https://antigravity.google/cli/install.sh | bash`, then run `agy` once interactively to sign in),
`bubblewrap`, `xdg-dbus-proxy` and `poppler-utils` (`pdfinfo`, `pdfseparate`, `pdfunite`) from apt, and
python3 3.12 or newer (older python skips the agy-worker venv and registration). The exported registration
carries `__AGY_BIN__`; install.sh renders it from `command -v agy`, or `~/.local/bin/agy` with a warning.
The venv gets `requirements-dev.txt` too, so the worker's tests run:

```bash
cd ~/.claude/mcp/agy-worker && .venv/bin/python -m pytest -q
```

## What travels

CLAUDE.md, settings.json (workflow keys, permissions, hooks, output caps), `agents/`, `skills/`, `templates/`,
`bin/`, `hooks/` (with their test matrices), `retire.json` (what install.sh removes from an older home),
the codex-worker MCP server with its registration for Claude and Codex (its unit test `test_codex_worker.py`
when it exists on the exporting machine), the agy-worker MCP server (python files and tests,
`requirements*.txt`, `pyproject.toml`, `allowed-remotes.txt`; never `.venv` or caches) with its registration, the statusline script, Codex `AGENTS.md`.

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
