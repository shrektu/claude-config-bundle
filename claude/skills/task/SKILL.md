---
name: task
description: One Jira task from ID to an open PR. Load when Sebastian writes /task with a task ID (e.g. /task TICKET-1274) or asks you to do a specific Jira ticket.
---

Input: one task ID (`TICKET-1274`). Without an ID, ask — do not guess from the branch.

This skill is a procedure, not a second set of rules: task classes, delegation, review and commits work
exactly as `~/.claude/CLAUDE.md` describes. Here is only what is specific to a Jira task: where the scope
comes from, how to test, and how to open the PR.

## 1. The ticket is the source of scope

`getJiraIssue` (Atlassian MCP), cloudId `00000000-0000-0000-0000-000000000000`, site `example.atlassian.net`,
`responseContentFormat: markdown`. Read the parent epic and the linked tasks (`issuelinks`) too — they
say what this task builds on and what comes after it. The Jira description wins over your interpretation
of the title; a conflict between the ticket and the code is a question for Sebastian, not room for your
own decision.

From the ticket extract: what must work after the change, which repositories it touches, whether it
touches the UI, whether it touches data/protocol/migrations (that raises the class to XL per the table in
CLAUDE.md).

## 2. Repositories and branch

Tasks in this project regularly touch several repositories at once — do not assume one. When the ticket
does not show where the code lives, send `Explore` before you plan anything.

Branch: `task/<ID>` from the epic branch `epik/<EPIC>` (the task's Jira parent), the same name in every
repo of the task. The PR targets `epik/<EPIC>` — not `develop` (except a blocker fix of an old epic, below); the epic branch goes to `develop`,
after its final review (the `epic` skill). If `epik/<EPIC>` does not exist yet in a repo the task
touches, create it from the current `develop` (`git push origin origin/develop:refs/heads/epik/<EPIC>`)
before the task branch. When the task stands on another unmerged task — of this epic or of another one —
the base is that task's branch and the PR targets that branch (team decision: cascade, so a PR's diff
shows only its own changes, never the tasks below it). Only the bottom of a chain targets
`epik/<EPIC>`. When the task below is merged, retarget the child to its own `epik/<EPIC>` — merged work
stays on the epic branch and never goes to `develop` on its own. When the task below belongs to another
epic, say so in the PR description: the child merges into its epic only after that dependency is there.
Every task that belongs to an epic in Jira goes to `epik/<EPIC>` (or the task below it), always — also
when nothing stands on it or under it. The one exception (Sebastian, 2026-10-21): a fix of blockers of
an old epic whose tasks already went to `develop` before the epic model (e.g. TICKET-1530, blockers of
TICKET-1273) — `task/<ID>` from `develop`, PR to `develop`, `qa` before its PR (4e). When unsure whether
the epic is old, ask Sebastian.
A task with no epic (a hotfix, a standalone bug)
keeps the old model: `bugfix/<ID>-<slug>` or `hotfix/<ID>-<slug>` from `develop`/`master`, PR to the
same. Open PRs created before this model keep their `feature/*` source branches; only their target moved
to `epik/<EPIC>`. If Sebastian's checkout is on another branch or has uncommitted work, work in a
worktree (`__HOME__/projects/cloud/.worktrees/<repo>-<ID>`), never by `checkout` in his
directory.

## 3. Workflow

Plan and class in one turn. The plan has a `reuse` section: before you design anything, grep the repo and
the shared libraries (or ask the LSP for references) and list the existing helpers, types, constants,
components and fixtures, with file:line, that the milestone must build on. Then everything as in
CLAUDE.md: the `implementer` (Sonnet 5.5, effort medium) does the implementation; during a milestone you
check evidence only (git status, RED and verify logs), never the diff; the plan gate
(`plan-gate-runner`: Gemini 3.8 Flash, Codex as fallback — before implementation for L/XL, and for M in
parallel with the implementer's acceptance-test phase; S has none); the final review once per milestone —
`codex-runner` (mode code), `reviewer-opus` and `flash-review-runner` in one message, with your end test
run in parallel (`review_focus` and `acceptance_criteria` as text, never as paths outside the repo);
every finding reproduced, then the milestone is committed and all real findings go back in ONE fix round
via SendMessage; a finding whose fix does not hold goes back in the next round, three rounds without
progress mean Zablokowane. The fix round lands as `git commit --fixup=<milestone sha>`, a delta trio
(`diff_base` = the milestone commit) only under the conditions in the `review` skill, the end test run
repeats on the fixed state, and you autosquash before the report and the PR. Milestone commits, message: one sentence in the
imperative, at most 7 words, no trailers. Nothing here is an exception to those rules. A task of class
L/XL with at least two independent milestones: the graph goes in the plan and the milestones run in
parallel worktrees per the `parallel` skill, with no limit on the number of implementers.

Everything you publish (PR description, Jira text, Bitbucket comments, UI texts) is Polish by default and
ends with the footer `🤖 Wygenerowane przez <model>` per CLAUDE.md; UI strings and translations go
through the `ui-texts` skill.

## 4. Tests — this is the gate to the PR

The PR is created only when **every expected result from the ticket has executable proof** and both test
levels are green. Not "the tests passed", but "the functionality does what the ticket promised".

### 4a. Coverage matrix

Before you run anything, list the expected behaviours from the Jira description and acceptance
criteria — one row per behaviour, in the ticket's words, not your paraphrase. Below them, separate rows
for the error scenarios of the plan (empty, boundary, concurrency, permissions, timezone…) — each with a
named test; a scenario the ticket does not settle goes straight to Sebastian as NIEJASNE, not as your
decision. Next to every row you write concrete evidence: the name of a unit test, an integration scenario
or (for purely visual rows) a screenshot — **and the path of the red run's log**, the one in which this
test failed before the change (`~/.claude/bin/verify --repo <repo> -- '<command>'`, a `red` entry in
`~/.cache/claude-verify/ledger.jsonl`). A row without a RED log path is a declaration, not evidence; a
run that errored out (import error, collection error, a typo in the command) is not red. A row without
evidence has two possible causes and both have an action: a test is missing — write it; the
implementation is missing — it goes back to the fix round. **You never close a row with "the code looks
correct"** or with a one-off observation that cannot be repeated.

"100% covered" means here: every expected result has evidence — not a line-coverage percentage. The two
can diverge in both directions, and confusing them is exactly what lets defects through.

### 4b. Running

Both commands through `~/.claude/bin/verify`:

- **unit** — the tests of the modules you touched (their test files and the tests of their direct
  callers), once, at the end; the full repo suite only for XL or changes to shared code (CLAUDE.md, Rules
  "Test runs");
- **integration** — on a minimal stack brought up: `docker compose -f docker-compose.minimal.yml
  up -d --build <service>` in `__HOME__/projects/cloud/cloud-platform-dev`, test data inserted with
  SQL through `... exec -T db psql -U exa_db -d exa_db` and **cleaned up after yourself**.

### 4c. Evidence must be evidence

Every test that closes a matrix row **must be red without your change** — mutate the production code or
revert the change and see the test fail. And check that the mutation actually applied: in this project a
mutation twice failed to match the code and a green run meant nothing. A test that passes because it mocks
exactly the seam you changed is not evidence.

The memory `reports-epic-progress` lists the classes of defects that went through green tests in this
project — validation order in marshmallow, an inner join over a nullable FK, SQLite hiding PostgreSQL,
mock fixtures replacing exactly the seam under test. Walk that list before you treat green as the end.

**Every bug found in the final review gets its own regression test on both levels:** a unit test and an
integration test on mocks/fakes of the external boundaries (hardware, bus, network, other services,
clock), named after the bug and red without the fix. In the coverage matrix each such bug has its own row
("bug: …") with the names of both tests. Without a second human reviewer, those tests — not more review
rounds — are the proof that the bug will not return.

### 4d. Red goes back

Every red item and every uncovered row goes back to the fix round (the limits from CLAUDE.md apply: 3
fix rounds without progress on the same finding → **Zablokowane**). There is no PR with a skipped test,
a row without evidence, or evidence you did not run after the last code change. The matrix goes into the
final report in full.

### 4e. QA — at the epic, not the task

A blocker fix of an old epic (section 1) goes to `develop` on its own, so it runs `qa` before its PR
like a task with no epic. Otherwise no `qa` run per task: hard e2e scenarios run only once the whole epic is merged into `epik/<EPIC>`,
before the epic branch goes to `develop` (the `epic` skill, step "Final"). A task is ready for its PR
when the matrix from 4a is green. Scenarios you think of while working on the task go to
`~/.cache/claude-progress/<EPIC>/qa-ideas.md` (one line each, with the task ID), so the epic's QA run
picks them up. A task with no epic still runs `qa` before its PR, as before.

## 5. Screenshots when the change touches the UI

"A new field, a changed control state, a different displayed value" is UI too. The procedure is in the
memories `pr-screenshots-required` and `browser-check-login-rule`:

1. minimal stack up, Browser pane on `http://localhost/`;
2. type the e-mail (`admin@email.com`) and **ask Sebastian for one click to log in** — you never type
   the password, that is a hard rule, not a preference. This is the only moment this skill stops and
   waits for a human; collect all such requests into one;
3. from there you drive yourself: navigation, data, screenshots. Before/after whenever you change
   something that already existed.

Putting a screenshot into the PR (Bitbucket has no PR attachments — it goes through the repository's
downloads):

```bash
curl -s -u "$(cat ~/.config/bitbucket/credentials)" -X POST \
  "https://api.bitbucket.org/2.0/repositories/acme/<repo>/downloads" \
  -F files=@<task-id>-<what-is-visible>.png
```

The file name starts with the task ID — `downloads` is a flat namespace for the whole repository. In the
description you link `https://bitbucket.org/acme/<repo>/downloads/<file>.png`. A placeholder only when
the stack truly cannot be brought up, and then one line says why.

## 6. PR

Push the branch, then for each repository:

```bash
curl -s -u "$(cat ~/.config/bitbucket/credentials)" -X POST \
  "https://api.bitbucket.org/2.0/repositories/acme/<repo>/pullrequests" \
  -H 'Content-Type: application/json' -d '{"title": ..., "source": {"branch": {"name": ...}},
      "destination": {"branch": {"name": ...}}, "description": ...}'
```

The PR is created **ready for review**, not as a draft — the tests passed, so the work is functionally
finished, and `/bb` skips drafts anyway. Title and description from `pr-description` (`[ID] Short
description`, sections in Polish, `## Screenshots` with the links from point 5), written by the `writer`
agent in `publish` mode and ending with the footer `🤖 Wygenerowane przez <model>`. With several
repositories: title `[MULTI][ID] …`, and the mutual links in `## Powiązane PR` go in with a **second**
`PUT` request, because you only know the PR numbers after all of them are created — send the `title` in
the `PUT` too, or Bitbucket drops it.

The bottom PR of a stack targets `epik/<EPIC>`, the ones above target the task branch below them; only a
blocker fix of an old epic (section 1) targets `develop`.
Order matters: the base PR of a stack before the one standing on it; when the task requires a deployment
order (e.g. `common` before consumers), write it in `## Dodatkowy kontekst`.

You do not touch the status in Jira and you comment nothing there — that stays with Sebastian unless he
asks.

## 7. Report

The final format from the `review` skill, plus: **the coverage matrix from point 4a in full** (expected
result → evidence → outcome), the QA ideas added in point 4e (or, for a task with no epic, the QA table with the tested SHAs), a
link to each PR, the `VERIFY` lines of both test levels, what the screenshots show, and the agreed merge order. If
you closed a row with evidence weaker than a test (a screenshot, an observation on the stack), say so
explicitly at that row — it is information for the human who will merge it. Without a PR the status is
**Zablokowane** with the blocker and the decision you need — never "done" just to close the loop.
