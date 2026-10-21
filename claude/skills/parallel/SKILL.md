---
name: parallel
description: Independent milestones of an L/XL task in parallel — a separate implementer in a separate worktree, the final review and a commit per milestone, landing by rebase + ff in dependency order. Load when an L/XL plan has at least two milestones with no edge between them.
---

Independent milestones of one task run at once, each in its own worktree and local sub-branch; dependent
ones run in order. Only shared resources (§3 below) serialise work.

## 1. The milestone graph — in the plan, before the plan gate

Each milestone lists the files it creates or edits, tests included. Edge A → B when:

- **same file** — B edits a file A edits, other than appending to a shared file;
- **contract** — B uses a type, schema, endpoint, constant, component or fixture A creates or changes (a
  shared contract goes into a sequential M0 that lands before the fork);
- **resources and data** — a migration, lockfile, build configuration, shared conftest/fixture;
- **deployment order** — producer before consumer.

**Shared files** (a constants module, translation files, an import registry) are declared in the plan;
parallel milestones only append to them (a constant, a key, an import), any other change is an edge. An
uncertain edge is an edge. The plan gate gets the graph with the plan.

## 2. Forking

A milestone forks only once **all its predecessors have landed** on the task branch (§5):

    git -C <task branch checkout> worktree add \
      __HOME__/projects/.worktrees/<repo>-<ID>-m<N> -b <task-branch>-m<N> <task-branch>

The sub-branch stays local, never pushed. Log the fork SHA (`git rev-parse <task-branch>`): every reviewer's `diff_base` for this milestone.

## 3. Delegation

One `implementer` per worktree, the ordinary `delegate` template, except: project path = the worktree,
`paths` = that worktree only. tdd-guard and verify count from the worktree root, so each milestone has
its own RED. State in `extra_context`: only targeted tests and lint of its own files; anything on a shared
resource (docker stack, database, fixed port, device, serial port, flashed board, full firmware build,
twister) is deferred to §6, which you run one at a time.

## 4. No barrier

While a milestone builds: evidence only (`git status --short` and `git diff <fork SHA> --stat` in its
worktree, plus the logs its report names). When it reports done: review, fix round and end test run per
`review`, on its worktree, every reviewer with `diff_base` = the fork SHA; the milestone commit and its
fixups go on its sub-branch; shared-resource runs stay deferred to §6. Then autosquash, land it at once
(§5), and launch what got unblocked without waiting for its peers.

## 5. Landing, in dependency order

    git -C <worktree> rebase <task-branch>
    git -C <task branch checkout> merge --ff-only <task-branch>-m<N>

Linear history, one commit per milestone, message unchanged. On a rebase conflict:

- **an append in a shared file** — merge it yourself;
- **anything else** — a missing edge: log it, leave the markers, SendMessage the files to that
  milestone's implementer (gone → a fresh spawn with the file list).

Either way, before it lands: the milestone's tests through verify, `git -C <worktree> add <files>`, then
`git -C <worktree> commit --no-edit` (the standards gate checks the resolved state), only then
`git -C <worktree> rebase --continue`. Never a bare `rebase --continue` after a conflict.

- Literal paths in git commands (hooks do not expand `$W`).
- `git add` and `git commit` in separate Bash calls (a rejected commit cancels the call).

Clean up after landing: `git -C <checkout> worktree remove <worktree>` (dirty → check `status --short`,
remove only test/build products such as `__pycache__`, never `--force`), then
`git -C <checkout> branch -d <task-branch>-m<N>`.

## 6. Integration — after the last landing

CLAUDE.md step 8 on the task branch, plus every shared-resource run deferred in §3, one at a time, and the
acceptance scenario on the landed branch. No review of the whole; a delta trio only on code conflict
resolutions from landing. A regression here: the implementer fixes it in the task branch's checkout
(SendMessage with the new path, or a fresh spawn), sequentially, with a regression test.

## 7. Log

One progress log per task branch (not per sub-branch), a section per milestone. Beyond the usual entries
(`review`): fork SHA, worktree path, SHA after landing, edges added after a conflict and who found them.
