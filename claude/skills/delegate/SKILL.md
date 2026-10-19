---
name: delegate
description: Spawn prompt template for `implementer` and the fix round. Load when you spawn an implementer and cannot write the prompt from memory, or when delegation-guard rejects a spawn.
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
- do not create branches, commit, or push (the orchestrator commits after the final review)

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
until that one has landed. Independent milestones run at the same time, each in its own worktree, with
no limit on their number — skill `parallel` (project path = the worktree, `Repos:` = that worktree only).

## Fix round

All real findings of the trio go back in ONE round, after you committed the milestone. SendMessage to
the implementer that did the work — its context is intact — with all verified findings (Codex, Opus,
Flash): the defect, file:line, how you reproduced it. Every finding requires its own regression test named
after the bug, unit AND integration against mocks/fakes of the external boundaries, red without the fix
— say so explicitly. The implementer leaves the changes uncommitted; you verify them and commit them as
`git commit --fixup=<milestone sha>`. A finding whose fix does not hold (its regression test or the fix
diff shows it) goes back in the next round. Spawn a fresh implementer (with a `findings` section in place
of `tdd_phases`) only when the old one is gone or has drifted. Three rounds without progress on the same
finding end in **Zablokowane**, with the evidence — there is no escalation to another implementer.

## Final check

The end test run (CLAUDE.md, Rules "Test runs") runs in parallel with the final trio and once more on
the fixed state after the fix round: the tests covering the changed modules, the acceptance tests, lint
on the changed files and the acceptance scenario; the full suite and the build only for XL or shared
code. A failing test is run once on the target branch before it counts as a regression. A delta trio
(`diff_base` = the milestone commit) runs only under the conditions in the `review` skill.

## review_focus per class (final trio)

| Class | Focus |
|---|---|
| S | the one behaviour that changed, its red test, and whether anything else was touched |
| M | plan conformance, acceptance criteria evidence, meaningful tests, callers and signatures |
| L | module boundaries, integration tests against the fakes, perf and typing claims, regressions in every caller |
| XL | the risk area itself: migration and rollback, on-wire/protocol compatibility, concurrency and ISR paths, auth and tenancy, irreversible steps |

## Explore first?

Send `Explore` before the implementer when the repo is unfamiliar or the plan cannot name the files yet
(locating a symbol, a convention, a config across many files) — it returns the conclusion, not the dumps.
Skip it when the plan already names the files: the implementer opens them itself.
