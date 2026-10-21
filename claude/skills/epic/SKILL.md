---
name: epic
description: Work mode only (skip where CLAUDE_MODE=personal). A whole Jira epic — its epik/<EPIC> branch, its tasks in parallel sessions, QA and the final review of the epic branch before it goes to develop. Load when Sebastian writes /epic with an epic ID (e.g. /epic TICKET-1273) or asks for a whole epic to be done.
---

Input: the epic ID (`TICKET-1273`). Execute, do not only plan: after the analysis start at once without
asking, and keep starting tasks until the epic is done or only blocked ones remain. Each task runs in its
own session (`start_session`, `/task <ID>`); this session owns the graph, the epic run, QA and the
`epik/<EPIC>` → `develop` PR. Load `task` once at the start.

## 1. Collect the epic

`searchJiraIssuesUsingJql` (cloudId as in `task` §1): `parent = <EPIC>` (old field: `"Epic Link" =
<EPIC>`). Read each child with `getJiraIssue` (markdown), its `issuelinks` and status. Done or
in-progress tasks leave the plan but stay in the graph as satisfied dependencies.

## 1a. The epic branch

Model: CLAUDE.md EPIC MODEL. At the start create `epik/<EPIC>` from `develop` in every repo the epic
touches if missing (`task` §2, or `POST /repositories/acme/<repo>/refs/branches`). Task code lands on
it only through merged task PRs.

## 2. Build the dependency graph

Four edge sources, all mandatory:

- **Jira** — `blocks` / `is blocked by`, subtasks, "after SW-…" in a description.
- **Shared code** — two tasks in the same module of one repo conflict; changing a contract the other
  uses is an edge.
- **Branch stack** — a task whose PR targets another task's branch starts once that branch is pushed
  (not merged); a fix round on the base → rebase the descendant before it goes further.
- **Deployment order** — producer before consumer (`common`/`liquibase` before the services, data
  before the screen showing it), even when it compiles without.

An uncertain edge is an edge.

## 3. Compute the schedule

Topological sort; the critical path (longest chain) and each task's class (CLAUDE.md) as a rough cost.
Among equally ready tasks, critical-path ones start first. No waves: a task starts once its dependencies
are satisfied; after each finished task, start what got unblocked.

## 4. Resources — the only cap on parallel tasks

- One repo, several tasks → a worktree each (`task` §2); never two tasks in one checkout.
- One shared dev stack (`task` §4b): integration tests and screenshots use it one task at a time.
- Login clicks (`task` §5): one request for all tasks waiting on the panel.

## 5. Drive

React when a task session reports. A blocked task does not stop the epic: cut its descendants from the
graph, carry on, list it in the report. Two tasks fighting over one file → a missing edge: add it, stop
the one further from completion, give the reason in the report.

## 6. Verify the whole epic — on `epik/<EPIC>`, before it goes to develop

Only once every task PR is merged into `epik/<EPIC>`: the epic's defects live where the tasks meet.

**Early assembly (optional).** While task PRs are open: per repo, in a worktree, a throwaway
`test/<EPIC>-integration` = `epik/<EPIC>` + the open task branches in merge order — never a PR source,
never pushed. A conflict is a finding about the graph or the order.

**Sync with develop.** Before the run merge the current `develop` into `epik/<EPIC>` and resolve
conflicts.

**The run** on `epik/<EPIC>` (stack from it):

- **unit** — the full suites of every repo the epic touched (they carry every task's regression tests);
- **integration** — the epic's own flows that cross tasks, which no single task checked;
- **UI** — the epic's final user path, with screenshots;
- **QA** — `qa` with the epic ID on the final SHAs (it reads `qa-ideas.md` and handles each result).

**The epic coverage matrix.** From the **epic's** Jira description and acceptance criteria (not the sum
of the tasks): each expected result with proof per `task` §4 (executable, red without the epic's
changes). A row no task implements is an **epic scope gap**: report it and name the missing task; never
slip it into some PR.

**When something fails.** The fix goes through a PR into `epik/<EPIC>`: the owning task's branch if its
PR is open, else a new `task/<ID>-fix` from `epik/<EPIC>` with its own PR; never a direct commit on the
epic branch. After the merge, run the whole again.

**Final.** Run and QA green on the final SHAs → the trio on `epik/<EPIC>` against `develop`, per repo,
`review_focus` on where the tasks meet; then, after asking Sebastian, one PR per repo `epik/<EPIC>` →
`develop` (title `[EPIC][<EPIC>] …`, description per `pr-description` with the epic matrix, the QA table
with SHAs and links to every merged task PR).

With a blocked task, verify the epic as it stands; the report names the matrix rows left unchecked.

## 7. Report

A table: task, class, PRs (links), status (open / merged into `epik/<EPIC>`), what it rested on. Plus:
the epic matrix (expected result → proof → outcome) with the run and QA result, scope gaps and missing
tasks, the critical path and what really set the duration, the PR merge order, blocked tasks with the
blocker and the decision needed, and dependency edges missing from Jira (worth adding to the tickets).

**Gotowe do merge** for an epic: every task PR merged into `epik/<EPIC>`, run and QA green on its final
SHAs, a current final review, and the `epik/<EPIC>` → `develop` PR(s) open.
