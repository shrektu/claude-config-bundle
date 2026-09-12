# Superworkflow v2 — plan (2026-09-12)

## Objective
One workflow for every project on this machine that hits the sweet spot between token usage and code
quality: deterministic steps enforced by hooks, situational knowledge loaded on demand as skills, the
strongest model/effort used only where risk or difficulty justifies it, and generated code matching the
exact toolchain versions pinned in the repo.

## Hard constraints
- Codex stays review-only (codex-worker MCP, `codex exec --sandbox read-only`). Implementers run inside
  Claude Code (Agent tool) so hooks, live supervision (SendMessage/TaskOutput) and verify apply to them.
- Measured cost structure: orchestrator context = 87 % of spend, subagents 13 %; median context per turn
  was 469k because Fable compacts at ~967k by default. Every change must reduce orchestrator context or
  turns, or raise quality at ~zero token cost.
- Bundle repo (`~/claude-config-bundle`) is the source of truth; files under `claude/` mirror `~/.claude`
  with `__HOME__` / `__CODEX_BIN__` placeholders rendered by `install.sh`. No hardcoded home path.
- Branch rule, commit rules and git-guard stay as they are (only enforced more, not changed).

## 1. Task classes and routing (replaces Tiny/Normal/Hard + S/M/L/XL)
Classified by the orchestrator in the planning turn — no triage model call. Risk beats size.

| Class | Definition | Implementer | Orchestrator effort | Codex plan review | Code review |
|---|---|---|---|---|---|
| S | ≤ ~30 changed lines, ≤ 2 files, no new module/abstraction, no risk area | orchestrator itself | session default (high) | no | own review |
| M | not S, not L, not XL | `implementer` (Sonnet, high) | high | no | own review; Codex (high) only when ≥ 200 lines or > 3 files or user asks |
| L | needs architecture understanding, several modules, hard bug, perf, tricky typing, or > ~300 lines expected | `implementer-hard` (Sonnet, xhigh); `implementer-opus` (Opus 5, high) for long multi-file autonomous work or after one failed Sonnet round | high; user switches `/effort xhigh` for the review turn when asked | only when the plan carries an open architectural question (Codex high) | own + Codex (high) round 1; later rounds review `review-checkpoint diff` only |
| XL | any risk area regardless of size: migrations, concurrency/locking/ISR, protocol/on-wire/firmware/bootloader, data shape/public API, multi-repo, auth/permissions/secrets/PII/payments, data deletion | `implementer-hard` or `implementer-opus` | xhigh (orchestrator asks the user to switch `/effort xhigh` at classification if not already) | mandatory, Codex xhigh, `mode=plan` | own + Codex (high) every round + final audit (Codex xhigh, `mode=final-audit`) after the last fix |

Round limit 3 → escalate (unchanged). Effort is a session-level setting; the orchestrator cannot switch
it, so settings default becomes `high`, xhigh is requested from the user at XL classification, and the
XL final report ends with "switch back: `/effort high`". repo-facts prints the current `effort` at every
session start/compact so drift is visible.

## 2. Hooks (deterministic, every session, every subagent)
Existing: `git-guard.py` (Bash). Already drafted and tested: `verify-guard.py` (Bash), `read-guard.py`
(Read). New:
- `git-policy.py` (PreToolUse Bash): (a) branch rule — on a branch that is not
  `feature/*|bugfix/*|hotfix/*|test/*` (HEAD resolved in the command's effective cwd, honouring `cd …`
  and `git -C`, via `git rev-parse --git-dir` + `symbolic-ref` so linked worktrees work) deny every
  operation that moves or rewrites the branch or its remote — a named table of (subcommand, condition):
  `commit`, `merge`, `rebase`, `cherry-pick`, `revert`, `am`, `reset` in every mode (`--hard` is already
  git-guard's), `push` unless the EFFECTIVE dry-run state is true after git's last-wins option parsing (`-n`/`--dry-run`
  set it, `--no-dry-run` clears it; `--` ends options) — a dry run moves nothing; force variants are
  git-guard's business and stay denied there, `tag` only when creating/deleting (non-option argument,
  `-d`, `-a`, `-s`, `-f`; bare `tag`, `-l/--list`, `-n`, `--contains`, `--points-at`, `--merged` allowed),
  `branch -d/-D/-m/-M/-f/-c/-C` (listing, `-u`, `--show-current` allowed), `update-ref`,
  `symbolic-ref` with a target, `filter-branch`, `filter-repo`, `replace`, `notes add/append/remove`;
  `apply` and `stash` only touch the worktree (allowed here; git-guard covers stash); allow
  `checkout -b`/`switch -c`/`branch <new>` anywhere (creating the work branch). Rebase in progress: the
  git dir has `rebase-merge/` or `rebase-apply/` — read `head-name` from whichever exists; if it names a
  work branch allow `rebase --continue|--abort|--skip|--edit-todo`, `commit`, `commit --amend`; if it
  names a protected branch deny. Detached HEAD outside a rebase → deny mutations; not a git repo → allow.
  Read-only forms of every listed subcommand stay allowed (fixtures for both). (b) commit message rule — `git commit`
  with `-m`: exactly one `-m`, no newline in the message, `-s`/`--signoff` present, no `Co-Authored-By`,
  `Generated with`, `Claude-Session`, no emoji; `--fixup`/`--squash`/`--amend --no-edit`/`-F` allowed
  without checks. Deny reasons name the violated rule and the corrected command.
- `delegation-guard.py` (PreToolUse, matcher `Agent|Task`): when `subagent_type` ∈ {implementer,
  implementer-hard, implementer-opus} the prompt must contain: an acceptance-criteria section, `verify --`,
  at least one absolute path, the git-safety line ("Never revert"), and the repo boundary ("may not touch"
  or "only touch"); deny listing the missing items. `model` given without any `subagent_type` → deny
  ("use implementer/implementer-hard/implementer-opus"). Everything else allowed.
- `repo-facts` — `claude/bin/repo-facts` is a CLI (prints facts for cwd or a given path); the
  SessionStart hook (matchers startup|resume|clear|compact) is a thin registration of the same script;
  implementer agents run it as their first command, so subagents get the same facts without the parent's
  conversation. Plain-stdout context ≤ 40 lines:
  repo root, branch + "NOT a work branch" flag, session `effort` (from hook input), toolchain versions
  from `.python-version`/`pyproject.toml` (requires-python, pinned versions of an allowlist of frameworks
  from `uv.lock`/`poetry.lock`), `package.json` engines + allowlisted deps resolved from the lockfile
  (react, react-dom, typescript, vite, next, vue, svelte, blockly, three, eslint, vitest, jest,
  playwright, tailwindcss) — for each allowlisted package print `locked=X installed=Y` (installed from
  `node_modules/<pkg>/package.json` / `importlib.metadata` in the project venv) and flag `MISMATCH` or
  `not installed`, `Cargo.toml` edition/rust-version plus, for the direct `[dependencies]` (≤ 15), the
  `Cargo.lock` version and source: for `source = "registry+…crates.io-index"` report `installed` only when
  `~/.cargo/registry/src/<registry-dir>/<crate>-<version>/Cargo.toml` exists where `<registry-dir>` is
  the directory of THAT lock entry's registry (crates.io: a name starting with `index.crates.io-` or
  `github.com-`; any other registry URL → `unverified` unless a directory whose name starts with the
  registry host exists); otherwise `not fetched`; for `git+…` sources
  report `git-source (unverified)`; for path dependencies report `path=<dir>` — the oracle rule applies
  only to `installed` registry crates, `go.mod`, `platformio.ini`,
  `CMakeLists.txt` minimum, `.tool-versions`, `.nvmrc`; task entry points: Makefile targets (≤ 20) and
  package.json script names. Silent outside a git repo. Budget ≤ ~400 tokens, < 200 ms.
- `subagent-verify-check.py` (SubagentStop): only for `agent_type` ∈ implementers (when `agent_type` is
  absent, apply to every subagent whose transcript has code edits); parse `agent_transcript_path` (the
  subagent's own history; fall back to `transcript_path` only if the former is missing); if any
  Edit/Write/NotebookEdit touched a non-doc file (not .md/.txt/.rst) and after the LAST such edit there is
  no Bash tool_use whose command has a segment invoking `verify` (basename `verify` or path ending in
  `/bin/verify`, options before `--` allowed — parsed, not substring-matched; `echo "verify -- x"` does
  not count) WITH a tool_result containing `VERIFY PASS` or `VERIFY FAIL` → exit 2 with the reason on
  stderr ("run the test_command through verify after your last edit, then report"); never block when
  `stop_hook_active` is true or when a block was already issued once for this `agent_id` (state file in
  `scratchpad_dir`, fallback `/tmp`) — no loops. Fixture: distinct parent and agent transcripts.
All hooks: stdlib python3, silent on any parse error, named constants, ≤ 100 ms typical, each with a
`*-test.py` matrix (deny/allow/garbage) in the style of `git-guard-test.py`. Registration in
`claude/settings.json` with `__HOME__` paths. Verify `tool_name` for the Agent tool empirically (matcher
`Agent|Task` covers both names).

## 3. Skills (description in context ≈ 60 tok each; body only when invoked)
- `pr-description` (done), `commit` (trim to branch/split rules; the hook enforces message format).
- `delegate`: prompt templates for implementer / implementer-hard / implementer-opus / codex-runner, the
  class-specific `review_focus`, when to use Explore first. Replaces `prompts/*.md` (deleted).
- `review`: the orchestrator's own review checklist (plan conformance, acceptance criteria, tests, modern
  idioms, regressions, untracked files), finding adjudication (reproduce before sending back; trade-off vs
  bug), Codex modes and severity buckets (BLOCKER/IMPORTANT/OPTIONAL/PASS), the three final statuses.
- `repo-standards`: how to make code match the pinned versions: run `~/.claude/bin/repo-facts` first;
  the installed package source (`node_modules/<pkg>`, `.venv/lib/.../site-packages/<pkg>`,
  `~/.cargo/registry/src/*/<crate>-<version>`) is the API oracle ONLY when repo-facts shows
  `installed == locked`; on `MISMATCH`/`not installed` sync the environment first (`uv sync`, `npm ci`,
  `cargo fetch`) and never trust a stale install; grep the oracle instead of recalling an API; per-stack "current idiom / legacy idiom" checklists
  for the stacks on this machine (Python 3.11–3.14, FastAPI lifespan, SQLAlchemy 2.0 `Mapped`,
  Pydantic v2, Alembic, React 19, TypeScript 5.x, Vite 7, Vitest, Playwright, C11/C17 + CMake ≥ 3.20,
  PlatformIO, Rust 2021/2024, Go 1.22+); treat deprecation warnings as failures where the project allows configuring it
  (`-W error::DeprecationWarning` in pytest config, eslint deprecation rules, `-Werror=deprecated` for C);
  otherwise `verify` prints `warnings: N deprecation lines (log …)` on PASS and the reviewer treats N > 0
  as a finding; when a project has `.claude/rules/standards.md` it wins. Preloaded into every implementer
  agent via `skills:` frontmatter. Also ship `claude/templates/rules-standards.md`, a path-scoped
  `.claude/rules/` template for projects.

## 4. Agents
- `implementer` (Sonnet high), `implementer-hard` (Sonnet xhigh), new `implementer-opus` (Opus 5 high):
  same contract; `skills: [repo-standards]` preloaded; report adds "checks NOT run and why" and
  "versions/idioms verified against". `codex-runner` unchanged except it passes `mode`.

## 5. codex-worker prompt modes
`codex_review_changes(..., mode="code")` with `mode` ∈ {plan, code, final-audit}: plan → contradictions,
missed dependencies, rollout order, data/protocol risks, missing acceptance criteria; code → correctness,
regressions, contract mismatches, missing tests, idioms deprecated for the pinned versions (passed in
`extra_context`); final-audit → "what did the earlier reviews miss" only, no redesign. Output for all
modes: BLOCKER / IMPORTANT / OPTIONAL lists (severity, file:line, trigger conditions, effect, reproduced
yes/no), then "checked and clean", then "could not verify" (distinct from clean), then `PASS` when no
BLOCKER/IMPORTANT. Defaults unchanged (gpt-6-astra, high, service_tier default). `codex/AGENTS.md`
mirrors the contract.

## 6. CLAUDE.md core (≤ 2,100 tokens)
Roles; the class table; non-negotiables (short, each pointing at the hook that enforces it); token
discipline (verify, read slices, checkpoint diffs, one fix task per round, `/compact` at milestones);
code style (unchanged); workflow steps 1–11 compressed; skill pointers (`delegate`, `review`, `commit`,
`pr-description`, `repo-standards`).

## 7. settings.json (bundle) and machine-local retirement
`effortLevel: high` (+ `modelSettings`), `autoCompactWindow: "300k"`, `bashOutputMaxChars: 12000`,
hooks for all events above, allow `Agent(implementer-opus)`, statusline with context %/cost/model.
New `retire.json` (repo root; installed into `~/.claude/bundle/` next to install.sh and copied back by
`export.sh`, so it travels) consumed by `install.sh`: delete `~/.claude/prompts/haiku-task.md`,
`~/.claude/prompts/codex-review.md`, `~/.claude/skills/orchestrate/`, `~/.claude/agents/{sonnet-worker,
claude-reviewer,haiku-worker}.md`; drop `env.MAX_MCP_OUTPUT_TOKENS`; drop allow rules `mcp__codex__*`,
`Agent(haiku-worker)`, `Agent(claude-reviewer)`. Test: install → export → install round trip on a temp
HOME keeps retire.json and is idempotent; an old-home fixture with the orchestrate skill loses it. `install.sh` hook merge becomes "replace per
(event, matcher), bundle wins, local-only matchers kept" instead of union (union would run git-guard
twice). `export.sh` manifest excludes `.git`.

## 8. Measurement
`claude/bin/usage-report [--days N] [--project PATH]`: from `~/.claude/projects/**.jsonl` prints ≤ 40
lines: tokens main vs subagent (read/create/output, input-equivalent share), median/p90 context per turn,
turns > 200k, tool-result tokens by tool, raw vs verify test runs, Read calls without limit > 3k tok,
Agent spawns by type, codex review calls. Baseline now, re-run after 10 tasks.

## Files (repo `__HOME__/claude-config-bundle`, branch `feature/superworkflow`)
claude/hooks/{git-policy,delegation-guard,repo-facts,subagent-verify-check}.py + `*-test.py`;
claude/hooks/verify-guard.py (remove hardcoded home; the suggested rewrite drops ONLY a trailing pure
display filter — a final segment whose command is `tail` or `head` — so the verify log keeps the full
output; `grep`, `wc`, `tee` and every other segment stay, because they may be assertions and pipefail
makes their status count); claude/bin/verify (child shell runs with
`-o pipefail`; `warnings:` line on PASS counting `DeprecationWarning|deprecated` lines); claude/skills/{delegate,review,repo-standards,
commit,pr-description}/SKILL.md; claude/agents/{implementer,implementer-hard,implementer-opus,codex-runner}.md;
claude/mcp/codex-worker/codex_worker.py; codex/AGENTS.md; claude/CLAUDE.md; claude/settings.json;
claude/templates/rules-standards.md; claude/bin/usage-report; retire.json; install.sh; export.sh; README.md.

## Acceptance criteria
0. No hook denies a read-only git command (`status`, `log`, `diff`, `tag -l`, `branch --list`, `push -n`
   without force) — the one existing exception is git-guard's unconditional force-push denial
   (`push -f/--force`, also with `-n`), which is unchanged by design.
1. Every hook matrix passes via `~/.claude/bin/verify`; each hook < 100 ms on a typical input; garbage input silent.
2. `grep -rn "/home/<user>" claude/ codex/ install.sh export.sh` → empty.
3. `HOME=$(mktemp -d) ./install.sh` on a fresh temp home installs every file, renders paths, writes a valid
   settings.json with all hook events; re-running is a no-op; on a home that has the old settings it
   removes the retired entries and does not duplicate the Bash hook group.
4. `claude/CLAUDE.md` ≤ 8,400 bytes; each SKILL.md description ≤ 1,024 chars; all JSON valid; `bash -n` on scripts.
5. `usage-report` runs on this machine's transcripts in < 30 s and prints the baseline.
6. codex_worker.py: `mode` validated, unknown mode → error string; prompt text per mode contains the
   severity buckets and the PASS rule.

## Risks / open questions for the plan review
- SubagentStop blocking: loop safety relies on `stop_hook_active` + one-shot state; is exit 2 the right
  mechanism for SubagentStop in current docs? Does `agent_type` arrive for custom agents?
- delegation-guard false denies (prompt phrasing drift) — mitigated by keyword sets, but is the field list right?
- git-policy during interactive-less rebase/fixup flows (`rebase -i --autosquash` needs GIT_SEQUENCE_EDITOR).
- 300k auto-compact for XL tasks: the user can raise it per session with `/autocompact`.
- Is Opus 5 high the right third implementer, or Sonnet xhigh enough? No local data; kept optional.
- Effort switching stays manual (session setting) — acceptable?

## Out of scope
Project-specific rules content (robotics-scratch CLAUDE.md cleanup), Codex as implementer, changing
git-guard semantics, pricing claims.

## Plan review round 1 (Codex, xhigh) — resolutions
Accepted and folded in above: (1) SubagentStop reads `agent_transcript_path`; (2) `verify` child shell
gets `-o pipefail` and verify-guard strips trailing `| tail/head` from its suggestion; (3) git-policy
uses a mutation table incl. `reset` in all modes, read-only `tag`/`branch` forms allowed; (4) rebase
detection via `git rev-parse --git-dir` + both `rebase-merge` and `rebase-apply`; (5) verify evidence is
parsed (command segment + `VERIFY PASS|FAIL` in the result), not substring-matched; (6) retire.json
travels through install/export and retires the old orchestrate skill and agents; (7) repo-facts is a CLI
run by implementers; (8) verify reports deprecation counts on PASS, projects configure warnings-as-errors
where possible; (9) installed source is the oracle only when it matches the lockfile; (10) XL reports end
with the effort switch-back reminder.
Deliberate trade-off kept against the reviewer's advice: read-guard stays (49 reads cost 334k tokens and
each dump persists for every later turn; the denial costs ~300 tokens). `usage-report` measures it; if
targeted re-reads cost more than the dumps after 10 tasks, raise `READ_GUARD_MAX_BYTES` or drop the hook.

## Plan review round 2 (Codex, high) — resolutions
(1) verify-guard's suggestion drops only a trailing `tail`/`head` segment; `grep`/`wc`/`tee` are kept as
possible assertions (pipefail makes their status count). (2) No dry-run exception in git-policy's push
rule; git-guard's force-push denial stays, stated as the one exception in acceptance criterion 0.
(3) repo-facts reports Cargo.lock versions for direct dependencies and whether the crate source is fetched,
so the repo-standards oracle rule (`installed == locked`) has evidence for Rust too.

## Plan review round 3 (Codex, high) — resolutions
(1) `push -n/--dry-run` is allowed by git-policy on every branch (criterion 0 holds); force variants remain
git-guard's unconditional denial. (2) repo-facts reads Cargo.lock `source`: registry crates are
`installed` only when the exact `<crate>-<version>/Cargo.toml` exists in the registry source cache; git
and path sources are reported as unverified/path and never authorise the registry cache as oracle.
Round 4 reviews only these two lines; everything else was CLEAN in round 3.

## Plan review round 4 (Codex, high) — resolutions and closure
(1) git-policy computes the effective dry-run state with last-wins negation (`--no-dry-run` clears it).
(2) repo-facts matches the registry directory to the lock entry's registry (crates.io dirs only for
crates.io sources; other registries by host prefix, else `unverified`).
Codex's own verdict: "both blockers are in the implementation details of parsing, not architecture".
Plan stage closed after 4 rounds (16 findings, all accepted); remaining parsing detail is covered by the
hook test matrices and by the code review rounds, where Codex reviews the real parser.

## v2.1 — command handoff (2026-09-12)
Class S/M is now handed over end to end to a new `commander-opus` agent (Opus, xhigh) after the
orchestrator writes the plan: it implements S itself, delegates M to `implementer`, verifies, reviews,
runs the Codex gate via `codex-runner`, commits on the work branch and reports. The orchestrator only
relays that report — no second review — because commander-opus's own verify/review pass plus the
git-policy and subagent-verify-check hooks are already the evidence. L/XL are unaffected: the
orchestrator stays in command as before.
A session-model switch (`set_session_model` to Opus for the S/M portion, back to Fable after) was
rejected: the app refuses `set_session_model` for the session's own current turn, so Fable cannot hand
its own turn to Opus mid-task and reclaim it later. A subagent avoids that restriction — Claude Code
allows three layers of subagent spawning, so `commander-opus` → `implementer` → `Explore` stays in
bounds, and `delegation-guard`/`subagent-verify-check` already gate implementer-shaped agents generically.
