---
name: parallel
description: Independent milestones of an L/XL task in parallel — a separate implementer in a separate worktree, the final trio review and a commit per milestone, landing by rebase + ff in dependency order. Load when an L/XL plan has at least two milestones with no edge between them.
---

Why: the implementer is the biggest time cost in this workflow (median run 11 min, p90 33 min), and
milestones run one after another wait for each other for no reason. Independent milestones go at once,
each on its own worktree and its own local sub-branch; dependent ones still go in order. The rules for the
graph and for resources are the same as in the `epic` skill (§2 edges, §4 resources), only at the level
of the milestones of one task. There is no limit on the number of parallel implementers; only shared
resources (§3) serialise work.

## 1. The milestone graph — in the plan, before the plan gate

Each milestone lists the files it creates or edits, tests included. An edge (A before B) exists when:

- **same file** — B edits a file that A edits, other than by appending at the end (below);
- **contract** — B uses a type, schema, endpoint, constant, component or fixture that A creates or
  changes. A shared contract goes into a sequential M0 that lands before the rest fork;
- **resources and data** — a migration, lockfile, build configuration, a shared conftest/fixture;
- **deployment order** — the producer before the consumer, as in `epic`.

**Shared files** (a constants module, translation files, an import registry): the plan declares them
explicitly as shared. Parallel milestones may only **append** to them — a new constant, a new key, a new
import; any other change to such a file is an edge. An uncertain edge is an edge. The plan gate
(`plan-gate-runner`, Gemini Flash with a Codex fallback) receives the graph together with the plan.

## 2. Forking

A milestone starts when **all its predecessors have landed** on the task branch (§5) — the predecessor's
commit on its sub-branch alone is not enough, because the worktree forks from the task branch.

    git -C <task branch checkout> worktree add \
      __HOME__/projects/.worktrees/<repo>-<ID>-m<N> -b <task-branch>-m<N> <task-branch>

The sub-branch carries the task branch's prefix (`feature/…-m2`), so a commit and a rebase on it pass
through git-policy. It is local only — it never goes to the remote. Write the fork SHA (`git rev-parse
<task-branch>`) in the log: it is the `diff_base` of the code reviewers and the review base of this
milestone.

## 3. Delegation

One `implementer` per worktree, the ordinary `delegate` template, with two differences: the project path
is the worktree, and `Repos:` allows only that worktree. tdd-guard and verify count everything from the
worktree root, so every milestone has its own RED.

In parallel worktrees the implementer runs only targeted tests and lint of its own files. Anything that
touches a shared resource — the docker stack, a database, a fixed port, a device, a serial port, a flashed
board, a full firmware build or twister — does not go in parallel: it belongs to the integration step
(§6) and you run it, one after another. Say so in the delegation's `extra_context`.

## 4. No barrier

While a milestone is being built you do not review it: you check only evidence — `git status --short`
and `git diff <fork SHA> --stat` in its worktree, and the RED and verify logs the implementer's report
names. When the milestone reports done, its one final review runs on its worktree: the trio
(`codex-runner` in mode `code` with `diff_base` = the fork SHA, `reviewer-opus` and `flash-review-runner`)
in parallel (`review_focus` and `acceptance_criteria` as text, never as paths outside the repo). You
reproduce and adjudicate every finding, commit the milestone on its sub-branch (the standards gate works
as always), and all the real findings go back in ONE SendMessage to that implementer, each with its
regression tests. The fix round lands as `git commit --fixup=<milestone sha>`; a finding whose fix does
not hold goes back in the next round. A delta trio, `diff_base` = the milestone commit, runs only when
the fixes are more than ~100 lines or touch a risk area; otherwise you verify the fix round by its tests
and by reading the fix diff. After the fix round you run the milestone's end test run again, autosquash,
and land it at once (§5). Then you recompute what got unblocked and launch the next — you
do not wait for the rest of its peers.

## 5. Landing, in dependency order

    git -C <worktree> rebase <task-branch>
    git -C <task branch checkout> merge --ff-only <task-branch>-m<N>

The history stays linear, one commit per milestone, its message unchanged. When the rebase stops on a
conflict:

- **An append in a shared file** (two constants, two keys, two imports) — you merge it yourself, like the
  trivial fix in CLAUDE.md.
- **Anything else** — an edge was missing. Record it in the log, leave the conflict markers and send the
  files to resolve in its worktree to that milestone's implementer (SendMessage; when it is gone, a fresh
  spawn with the list of files).

In both cases the resolution passes through the gates before it lands: run the milestone's tests through
verify, then `git -C <worktree> add <files>` and `git -C <worktree> commit --no-edit` — an ordinary
commit, so the standards gate checks the resolved state — and only then `git -C <worktree> rebase
--continue`. A bare `rebase --continue` after a conflict bypasses the gate, so you do not use it.

Mechanics that cost attempts in a trial run:

- Write paths in git commands literally. Hooks read the command text and do not expand shell variables,
  so `git -C $W commit` ends in a gate error ("could not run").
- The commit gate runs before the whole Bash call, and a rejection cancels it entirely. So `git add` and
  `git commit` go in separate calls — an `add` glued to a rejected commit will not run.

After landing you clean up: `git -C <checkout> worktree remove <worktree>` (it refuses on a dirty tree —
then you first check `status --short`; you remove only test and build products, e.g. `__pycache__`, and
never use `--force`) and `git -C <checkout> branch -d <task-branch>-m<N>` (it refuses when the
sub-branch is not merged).

## 6. Integration — after the last landing

Step 8 of CLAUDE.md on the task branch: tests of the modules changed by all the milestones, lint of the
changed files (the full suite and the build only for XL or shared code), and in addition everything you
deferred in §3 on shared resources — one after another, plus the acceptance scenario on the landed
branch. There is no further review of the whole: each milestone already had its trio. Only when landing
needed conflict resolutions in code does a delta trio run, on those resolutions only. A regression from
this step is fixed by the implementer in the task branch's checkout
(SendMessage with the new path, or a fresh spawn), now sequentially, with a regression test like every
finding.

## 7. Log

One log per task branch, a section per milestone: the fork SHA, the worktree path, the review and fix
rounds, RED log paths, findings, the SHA after landing, edges added after a conflict and who found them.
