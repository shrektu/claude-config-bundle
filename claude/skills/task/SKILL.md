---
name: task
description: One Jira task from ID to an open PR. Load when Sebastian writes /task with a task ID (e.g. /task TICKET-1274) or asks you to do a specific Jira ticket.
---

Input: one task ID (`TICKET-1274`); without one, ask (never guess from the branch). Only the Jira-specific
steps are here; everything else runs per CLAUDE.md.

## 1. The ticket is the source of scope

`getJiraIssue` (Atlassian MCP), cloudId `00000000-0000-0000-0000-000000000000`, site
`example.atlassian.net`, `responseContentFormat: markdown`; read the parent epic and the `issuelinks` too.
The description beats your reading of the title; a ticket/code conflict goes to Sebastian. Extract: the
expected results, the repos, UI or not, data/protocol/migration (→ XL).

## 2. Repositories and branch

A task may touch several repos (cloud-platform, kiosk, iot-platform…): check; when the ticket does not show
where the code lives, `Explore` before planning.

Branch model, cascade, the old-epic blocker exception and no-epic branches: CLAUDE.md EPIC MODEL. Here:
the same `task/<ID>` in every repo of the task; a missing `epik/<EPIC>` is created first
(`git push origin origin/develop:refs/heads/epik/<EPIC>`); a task below from another epic is named in the
PR description (the child merges only after it lands).

Worktrees: `__HOME__/projects/.worktrees/<repo>-<ID>` (`-m<N>` per parallel milestone,
`qa-<repo>-<ID>` for QA). Sebastian's checkout on another branch or with uncommitted work → work in a
worktree; never switch or create branches in his checkout.

## 3. Workflow

Plan and class in one turn; the `reuse` grep covers the shared libraries too. L/XL with ≥ 2 independent
milestones: the graph goes in the plan, then `parallel`. UI strings and translations: `ui-texts` (no
footer).

## 4. Tests — the gate to the PR

PR only when every expected result of the ticket has executable proof (coverage = evidence per expected
result, not a line %) and both levels — unit and the §4b stack run — are green.

### 4a. Coverage matrix

Before running anything: one row per expected behaviour, in the ticket's words, then one row per plan
failure mode (CLAUDE.md Rules). Each row names its evidence: a test with its RED verify log path, or a
screenshot for a purely visual row. A row without evidence (missing test or implementation) goes to the
implementer in the fix round (XS: you fix it). Never close a row with "the code looks correct" or a
one-off observation.

### 4b. Running

- **unit** — the end run of CLAUDE.md Rules "Test runs";
- **integration** — the dev stack from the task worktree (`dev/docker-compose.yml --profile core`,
  `full` only when needed; recipe: `~/.claude/skills/qa/references/acme-stack.md`), test data by SQL
  (`... exec -T db psql -U exa_db -d exa_db`), **cleaned up after yourself**.

### 4c. Evidence must be evidence

Every test closing a row **must be red without your change**: mutate or revert the production code,
check the mutation applied, see it fail. A test that mocks the seam you changed is not evidence. Before
treating green as done, check the defects that slipped through green tests here: marshmallow coercing
before validators and stripping undeclared fields; an inner join over a nullable FK; SQLite hiding
PostgreSQL (an absent DB must fail the suite, not skip); a function/array identity in a `useEffect`
dependency list (depend on a derived key); an empty scope passed to a permission helper (refuse
explicitly).

Each confirmed bug finding gets a matrix row `bug: …` naming its unit and fakes-level regression tests
(CLAUDE.md).

### 4d. Red goes back

Red → the fix round. No PR with a skipped test, a row without evidence, or evidence not rerun after the
last code change.

### 4e. QA — at the epic, not the task

No `qa` per epic task: the epic runs it (`epic` §6). A task with no epic and an old-epic blocker fix
(CLAUDE.md EPIC MODEL) run `qa` before their PR. QA ideas: one line each, with the task ID, in
`~/.cache/claude-progress/<EPIC>/qa-ideas.md`.

## 5. Screenshots when the change touches the UI

Per `pr-description` "Screenshots end to end" (what counts as UI, capture, upload, naming, embed). Behind
the login: stack up, Browser pane at `http://localhost/`, type `admin@email.com`, ask Sebastian for the
one sign-in click (never type the password; one request for all screens), then drive navigation and data
yourself to check them; they are listed as missing (`pr-description`). A placeholder only when the stack
cannot come up, with one line why.

## 6. PR

Push the branch, then per repo:

```bash
curl -s -u "$(cat ~/.config/bitbucket/credentials)" -X POST \
  "https://api.bitbucket.org/2.0/repositories/acme/<repo>/pullrequests" \
  -H 'Content-Type: application/json' -d '{"title": ..., "source": {"branch": {"name": ...}},
      "destination": {"branch": {"name": ...}}, "description": ...}'
```

Ready for review, not draft. Title and description per `pr-description` (`writer`, `publish` mode).
Several repos: `[MULTI][ID] …`, then a second `PUT` adds the mutual `## Powiązane PR` links and resends
the `title`. The base PR of a stack before the one on it; a required deployment order (e.g. `common`
before consumers) goes in `## Dodatkowy kontekst`. Jira status and comments stay Sebastian's unless he
asks.

## 7. Report

`review`'s final format, plus: the full 4a matrix (expected result → evidence → outcome), the 4e QA ideas
(or, when this task ran `qa`, its QA table with the tested SHAs), each PR link, both levels' `VERIFY`
lines, what the screenshots show, the merge order. A row closed by evidence weaker than a test (a
screenshot, a stack observation): say so at that row. No PR → **Zablokowane** with the blocker and the
decision needed.
