---
name: delegate
description: Szablon promptu dla `implementer` i `implementer-strong`, runda poprawek i eskalacja. Załaduj, gdy spawnujesz implementera i nie napiszesz promptu z pamięci, albo gdy delegation-guard odrzuci spawn.
---

## Before the spawn

For M, L and XL run `~/.claude/bin/repo-facts` before the implementer starts. No test baseline — a test
that fails in the end run is checked on the target branch then (CLAUDE.md, Rules "Test runs").

## Implementer (`implementer`)

Claude Sonnet 5.5 at effort medium, for every task class. Never a bare `model:` Agent call. Fill every
section; delegation-guard denies a spawn that misses one.

```
task
<what to build, in two or three sentences>

plan
<exact files, functions, signatures; what to change and what not to; the data shapes;
 no architecture decisions left to the agent>

class
<S, M, L or XL — it sets the TDD ladder>

acceptance_criteria
<checkable statements, one per line>

paths
/absolute/path/to/repo — the repo root
/absolute/path/to/repo/src/module.py — the file to change

reuse
<the existing helpers, types, constants, components and test fixtures this milestone must build on,
 each with file:line — found by grep or the LSP while planning; or `none — searched: <terms>`.
 delegation-guard denies a new-task spawn without this section; fix rounds do not need it>

tdd_phases
<the ladder for this class from CLAUDE.md, phase by phase, with the acceptance tests named one per
 expected result, the boundaries that get mocks/fakes, and any acceptance test the plan declares
 non-automatable — the agent may not declare that itself. Per phase an `expected_red:` line — the
 assertion that must fail and why ("FAIL: total() returns 0.0 for [] — empty case missing"), so an
 error inside the test is not mistaken for RED. Plus one named test per failure mode the plan lists>

test_command
~/.claude/bin/verify --repo /absolute/path/to/repo -- 'cd /absolute/path/to/repo && <the real test/lint/build command>'

extra_context
<constraints, pinned versions, things that must not regress>

rules
- run `~/.claude/bin/repo-facts` and `~/.claude/bin/habits list --repo <repo> --max-chars 20000` as your first command;
  match the pinned versions and follow every habit it prints
- every changed line meets the language norm; Python docstrings on every class and function except tests,
  each one line, one sentence, at most 72 characters, as short as possible; no module docstrings; no new suppression (noqa, NOLINT, eslint-disable, type: ignore) — report the line instead
- work the phases in `tdd_phases` in order; each one starts with the test, run through
  `~/.claude/bin/verify --repo <repo> -- <test command>` until it is RED, before the production edit
  (tdd-guard denies that edit until the ledger holds the red run; a run that errors out is not red)
- quote the RED verify log path per phase in your report — a declaration without it is not evidence
- before reporting: one run of the tests covering the files you changed plus the acceptance tests, green;
  the repo's own typecheck and lint clean on the changed files, `lint-strict` clean. Never the full suite or
  the build unless this delegation asks for it; no test run at all for a change with no logic (rename,
  annotation, docstring, import)
- zero comments in the code you write
- batch independent tool calls in one message; the round trips cost far more than the commands
- do not create branches, commit, or push (the orchestrator commits after review)

Never revert or discard changes you did not make (checkout/restore/stash/reset/clean are blocked by a hook); if you think a revert is needed, stop and report.

repos
you may only touch <paths>; you may not touch <everything else, named>

report
Under 60 lines: status first (done / done with concerns + each concern / blocked), changed files
(path — what), acceptance criteria met/not met with evidence pointers,
the RED verify log path per phase with the failing assertion it shows, verify summary lines only (VERIFY PASS/FAIL, exit code, log path),
checks NOT run and why, versions/idioms verified against (from repo-facts), gate findings disputed
(id + reason), blocked/questions/deviations or "none". Never paste full logs, diffs or file contents.
```

For L/XL hand over ONE milestone per spawn or SendMessage; a milestone that depends on another waits
until that one has landed. Independent milestones run at the same time, each in its own worktree — skill
`rownolegle` (project path = the worktree, `Repos:` = that worktree only).

## Fix round

SendMessage to the implementer that did the work — its context is intact — with all verified findings of
the round: the defect, file:line, how you reproduced it. Every finding requires its own regression test
named after the bug, unit AND integration against mocks/fakes of the external boundaries, red without
the fix — say so explicitly. Spawn a fresh implementer (with a `findings` section in place of
`tdd_phases`) only when the old one is gone or has drifted.

## Escalation: `implementer-strong`

Three fix rounds without progress on the same finding, before anything is declared **Zablokowane**:
one attempt by `implementer-strong` — Codex gpt-6.1-sol at effort medium, through `codex_implement`
(workspace-write sandbox, no network). Same delegation template and fields (delegation-guard checks
them), plus a `history` section: the finding, the three rounds' attempts and why each failed, the
progress log path. The tool returns a snapshot (HEAD sha + tree sha of the pre-run working tree):
note it in the progress log — `git read-tree` / `git checkout-index` from that tree recovers anything
Codex damaged. Codex's edits bypass the edit-time hooks (comment-guard, tdd-guard), so its round gets
the full review, not a checkpoint diff: comments and docstrings checked by reading, RED logs opened,
lint-strict before the commit as always, and the advisory `ai-review-gate` in your round. Still no progress after it → STOP,
**Zablokowane**, with both implementers' evidence.

## Final check

Once your own review is clean, run the end test run once (CLAUDE.md, Rules "Test runs"): the tests
covering the changed modules, the acceptance tests and lint on the changed files through `verify`; the
full suite and the build only for XL or shared code. A failing test is run once on the target branch
before it counts as a regression. The Codex code gate already ran with review round 1; if later rounds
changed code, its delta run goes in parallel with this end run (CLAUDE.md step 8a).

## review_focus per class (your own review)

| Class | Focus |
|---|---|
| S | the one behaviour that changed, its red test, and whether anything else was touched |
| M | plan conformance, acceptance criteria evidence, meaningful tests, callers and signatures |
| L | module boundaries, integration tests against the fakes, perf and typing claims, regressions in every caller |
| XL | the risk area itself: migration and rollback, on-wire/protocol compatibility, concurrency and ISR paths, auth and tenancy, irreversible steps — plus a final pass asking only what the earlier rounds missed |

## Explore first?

Send `Explore` before the implementer when the repo is unfamiliar or the plan cannot name the files yet
(locating a symbol, a convention, a config across many files) — it returns the conclusion, not the dumps.
Skip it when the plan already names the files: the implementer opens them itself.
