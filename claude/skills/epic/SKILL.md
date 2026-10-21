---
name: epic
description: A whole Jira epic — its epik/<EPIC> branch, its task/* PRs in parallel, QA and the final review of the epic branch before it goes to develop. Load when Sebastian writes /epic with an epic ID (e.g. /epic TICKET-1273) or asks for a whole epic to be done.
---

Input: the epic ID (`TICKET-1273`). This skill **executes** the epic, it does not only plan it: after the
analysis it starts at once, without asking for consent, and keeps adding tasks until the epic is finished
or only blocked ones are left. Every single task follows the procedure of the `task` skill — load it once,
at the start.

## 1. Collect the epic

`searchJiraIssuesUsingJql` (cloudId `00000000-0000-0000-0000-000000000000`): `parent = <EPIC>` — and when
the project uses the old field, `"Epic Link" = <EPIC>`. Read each child with `getJiraIssue`
(`responseContentFormat: markdown`) together with `issuelinks` and the status. Tasks already done or in
progress drop out of the plan but stay in the graph as satisfied dependencies.

## 1a. The epic branch

The company's model: every epic has a branch `epik/<EPIC>`; each task works on `task/<ID>` and its PR
targets `epik/<EPIC>` (a stacked task — of this or another epic — targets the task branch below it, so diffs never duplicate; when that task is merged, the child is retargeted to `epik/<EPIC>`); the team reviews and merges the
task PRs into the epic branch; at the end the epic branch gets a final review and one PR
`epik/<EPIC>` → `develop`. The one exception (Sebastian, 2026-10-21): a fix of blockers of an old epic
whose tasks already went to `develop` before this model (e.g. TICKET-1530 for TICKET-1273) gets its PR straight
to `develop` and its own `qa` run (the `task` skill, section 1).

At the start, per repository the epic touches, create `epik/<EPIC>` from the current `develop` (from
`master` in a repo whose main line is `master`, e.g. cloud-platform-kubernetes) if it does not exist:
`git push origin origin/develop:refs/heads/epik/<EPIC>` or `POST /repositories/acme/<repo>/refs/branches`.
On `epik/*` you only ever create it, merge `develop` into it (to pick up develop and resolve conflicts
before the final PR) and push without force — git-policy enforces this. Task code lands on it only
through merged task PRs.

## 2. Build the dependency graph

Jira shows only part of the truth. Four sources of edges, all mandatory:

- **Explicit from Jira** — `blocks` / `is blocked by`, subtasks, sentences in the description saying
  "after SW-…".
- **Shared code** — two tasks touching the same module in the same repository conflict; if one changes a
  contract the other uses, that is an edge, not parallelism.
- **Branch stack** — a task whose PR targets another task's branch can start only once that branch exists
  and is pushed (not: merged). A base that receives a fix round invalidates the descendant's worktree —
  rebase before the descendant goes further.
- **Deployment order** — the producer of a model before the consumer (`common`/`liquibase` before the
  services, data before the screen that shows it). That is an edge even when the code compiles without it.

An uncertain edge is an edge: false parallelism costs a round of conflicts, a false dependency costs a
little time.

## 3. Compute the schedule

Topological sort, then: the **critical path** (the longest dependency chain — the lower bound of the
epic's time) and, for each task, its class S/M/L/XL per CLAUDE.md as a rough cost. Tasks on the critical
path start before everything else that is equally ready — a delay on them delays the whole epic, a delay
off it does not.

Do not work in waves with a barrier: a task starts the moment its dependencies are satisfied, not when
the whole previous wave finishes. After each finished task recompute what got unblocked and add it.

## 4. Resource constraints — they, not the number of agents, set the ceiling

- **No limit on parallel tasks or implementers.** Every task gets its own `implementer` (Sonnet 5.5,
  medium); the only things that cap parallelism are the shared resources below.
- **One repository, several tasks at once → separate worktrees**
  (`__HOME__/projects/cloud/.worktrees/<repo>-<ID>`). Never two tasks in the same checkout; never
  a `checkout` in Sebastian's directory.
- **There is one shared minimal docker stack.** Integration tests and screenshots go through it one at a
  time — two tasks inserting test data into the same database at once give a result that cannot be
  defended. Serialise the integration phase, do the rest of each task in parallel.
- **The login click** for screenshots stays with Sebastian. Collect these requests and raise one when
  several tasks wait for the panel, instead of interrupting him separately for each.

## 5. Drive

Supervise as in CLAUDE.md — you react when a task reports. Each task gets its one final review by the
trio (see the `task` skill) when its implementation is done; no task is reviewed while it is being built.
After adjudication each task's milestone is committed, its fix round lands as `git commit
--fixup=<milestone sha>` (delta trio `diff_base` = that commit), and it is autosquashed before the task's
report and PR.
A blocked task **does not stop the epic**: cut off its descendants in the graph, carry on with what is
left, and list it in the report. The CLAUDE.md rule — three fix rounds without progress on the same
finding means **Zablokowane** with the evidence — applies in each task separately. The epic's integration
run also has regression tests for every bug found in the tasks, on mocks of the external boundaries.

When two tasks start fighting over the same file despite the graph, an edge was missing — add it, stop
the one that is further from completion, and write the reason in the report.

## 6. Verify the whole epic — on `epik/<EPIC>`, before it goes to develop

Green tasks do not mean a green epic: each one tested its own slice on its own branch, and the epic's
defects live exactly where those slices meet. The epic is verified **once all its task PRs are merged
into `epik/<EPIC>`** — earlier QA has no point, the parts do not meet yet.

**Early assembly (optional).** While task PRs are still open you may check how they fit: in a worktree,
per repository, a throwaway branch `test/<EPIC>-integration` = `epik/<EPIC>` plus the open task branches
in merge order. It is **never the source of a PR and never goes to the remote**. A conflict here is a
finding about the graph or the order.

**Sync with develop.** Before the run, merge the current `develop` into `epik/<EPIC>` (allowed on epik/*)
and resolve conflicts, so what you test is what will land.

**The run** on `epik/<EPIC>` (stack brought up from it):

- **unit** — the full suites of all repositories touched by the epic, not only those of the last task;
- **integration** — the epic's own scenarios: flows that cross several tasks at once and that, by
  definition, no single task checked;
- **UI** — a walk through the final user path the epic promises, with screenshots;
- **QA** — load the `qa` skill with the epic ID: hard e2e scenarios on the epic branch's final SHAs,
  including the ideas the tasks left in `~/.cache/claude-progress/<EPIC>/qa-ideas.md`. FAIL goes back as a
  fix, NIEJASNE waits for Sebastian, NIE URUCHOMIONY is a blocker.

**The epic coverage matrix.** From the description and acceptance criteria of the **epic** in Jira (not
from the sum of the task descriptions) you spell out the expected results and assign each one a proof, on
the same rules as in the `task` skill: executable proof, red without the epic's changes. A row that no
task implements is an **epic scope gap** — report it and name where it should go (which task is missing),
instead of quietly adding it to some PR.

**When something fails.** The fix goes through a PR into `epik/<EPIC>`: into the owning task's branch if
its PR is still open, otherwise a new `task/<ID>-fix` branch from `epik/<EPIC>` with its own PR to it —
never a direct commit on the epic branch. After the fix is merged you run the whole again: a new commit
on `epik/<EPIC>` invalidates the previous run and QA, just as it invalidates a review.

**Final.** With the run and QA green on the epic branch's final SHAs: the final review — the trio
(`codex-runner` mode `code`, `reviewer-opus`, `flash-review-runner`) on `epik/<EPIC>` against `develop`,
per repository, `review_focus` on where the tasks meet — then one PR per repository `epik/<EPIC>` →
`develop` (title `[EPIC][<EPIC>] …`, description from `pr-description` with the epic matrix, the QA
table with SHAs and links to every merged task PR). Ask Sebastian before opening these PRs.

If a task was blocked, you verify the epic as it stands, and the report states explicitly which matrix
rows could not be checked because of that hole.

## 7. Report

A table: task, class, PRs (links), status (open / merged into `epik/<EPIC>`), what it rested on. Plus:
**the epic coverage matrix from point 6** (expected epic result → proof → outcome) together with the
result of the run and QA on `epik/<EPIC>`,
scope gaps and missing tasks, the critical path and what actually determined the epic's duration, the
merge order of the PRs, blocked tasks with the blocker and the decision needed, and the dependency edges
that were not in Jira — worth adding to the tickets so the next epic starts with a better graph.

The status **Gotowe do merge** for an epic requires every task PR merged into `epik/<EPIC>`, a green run
and QA on its final SHAs, a current final review and the `epik/<EPIC>` → `develop` PR(s) open — not the
sum of green tasks.
