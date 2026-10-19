---
name: qa
description: Hard e2e scenarios for a Jira task on an isolated stack, with a PASS / FAIL / NIEJASNE result and evidence. Load when Sebastian writes /qa with a task ID or asks to test or click through a task, and always in step 4e of the task skill.
argument-hint: <JIRA-ID>
---

Input: `$ARGUMENTS` — one task ID (`TICKET-1274`). Without an ID, ask; do not guess from the branch.

You are a tester, not an implementer. You do not fix code, do not commit, do not touch Sebastian's
branches or checkouts. Everything you write — scenarios, specs, the compose override, the report — lands in
`~/.cache/claude-qa/runs/<ID>/`. The goal is to find what does not work: a scenario that passes is not a
failure, but a list of only happy paths is.

## 1. The oracle from Jira

`getJiraIssue` (cloudId `00000000-0000-0000-0000-000000000000`, `responseContentFormat: markdown`), the
parent epic and `issuelinks`. List the expected results in the ticket's own words — that is the only
PASS/FAIL oracle. Behaviour the ticket does not specify is neither PASS nor FAIL: it is **NIEJASNE** with
a concrete question. You do not settle it by what the code happens to do — then the test would check the
code against itself.

## 2. The task's branches

Repositories: `~/projects/cloud/cloud-common`, `~/projects/cloud/cloud-platform-dev/repos/*` and
`~/projects/kiosk/*` with their own `.git`. In each, `git fetch --quiet origin` and
`git branch -a --list "*<ID>*"`. The result is a table: repo → branch → base (`develop`; `common` and
`content-management` → `master`; a task standing on another unmerged task → that task's branch).

**You test a commit, not a directory.** SHA = the local task branch if it exists, otherwise
`origin/<branch>`. For each repo you create a fresh worktree of your own:

```bash
git -C <repo> worktree add --detach ~/projects/cloud/.worktrees/qa-<repo>-<ID> <sha>
git -C ~/projects/cloud/.worktrees/qa-<repo>-<ID> submodule update --init
```

You never build from a worktree where an implementer or another session is working — uncommitted changes
may be lying there. If the `common` submodule on a service's branch points to a different commit than the
head of the task branch in `cloud-common`, that is a finding (a service built from an old
`common`), not something to quietly fix. The QA result is valid only for those SHAs — write them in the
report header.

## 3. The change map

`git diff <base>...<sha> --stat` and reading the changed files (in slices): which screens, endpoints,
queries, migrations, NATS messages and periodic jobs. For every changed branch of logic, condition and
query note `file:line` — the hard scenarios come from them.

## 4. Hard scenarios

Load `references/scenarios.md` and write the scenarios **before you look at the implementer's tests** —
otherwise you will repeat its assumptions. The minimum: every expected result from the ticket has one
happy scenario and at least two hard ones. Hard means: it has a named mechanism that can break, pointed
out in the diff.

Each scenario: `S01…`, a title, why it is hard (`file:line`), the initial state and data, the steps, the
expected result with a quote from the ticket or NIEJASNE, and the test form (point 5). Save them to
`runs/<ID>/scenarios.md` before the first spec exists. Only now look through the implementer's tests: a
scenario they already cover you run anyway — QA is independent evidence.

## 5. Test form — the ladder

You take the highest rung that can be run. Every step down has a one-sentence reason in the report;
"it was faster" is not a reason.

1. **Playwright UI on the QA stack** — the default for everything visible in the panel.
2. **Playwright `request` through the UI proxy** (`http://localhost:8480/api/...`, the same session) —
   when there is no screen (an endpoint, an export, a report) or the scenario needs parallel requests.
3. **An assertion on the QA database** (`qa exec -T db psql ...`) — as a second assertion next to 1 or 2,
   never instead of them.
4. **The repo's integration test on a real Postgres** (not SQLite) — when the scenario cannot be
   triggered from outside: a periodic job, a NATS consumer without an endpoint.
5. **The machine side** (`device-service`, `kiosk-ui`, `nats-gateway`, `kiosk-machine-docker`): the machine
   stack from `kiosk-machine-docker` (`docker-compose.mock.yml`, `wiremock/`) and the real protocol with
   a fake peer; the kiosk UI and service menu — Playwright as in 1. Write the first recipe that works
   into `references/kiosk-stack.md`, so the next run does not rediscover it.
6. **A unit test** — the last resort, marked in the report as weak evidence.

## 6. The QA stack

A recipe with verified commands: `references/acme-stack.md`. In short: a clone of the database in the
volume `acme-qa_pgdata`, the compose project `acme-qa`, services changed in the task built from the QA
worktrees, the rest from the `cloud-platform-*` images, liquibase from the task branch (or `origin/develop`)
on the clone, the UI on `:8480`. Sebastian's stack and database stay untouched, and the scenarios may
destroy data with impunity.

**Logging in.** You never type the password — neither into a form nor through the API (memory
`browser-check-login-rule`, a hard rule). The session lives in `~/.cache/claude-qa/auth/acme-qa.json`;
when it is missing or expired, you ask Sebastian for one login using the command from the recipe. You
make that request once, at the start, before you begin writing specs — afterwards you work without
interruption.

## 7. Specs

Files in `~/.cache/claude-qa/runs/<ID>/`, a test title starts with the scenario ID (`S07 …`) — the result
returns to the table by it. Every spec starts with:

```ts
import { test, expect } from '@playwright/test';

test.use({
  baseURL: 'http://localhost:8480',
  storageState: `${process.env.HOME}/.cache/claude-qa/auth/acme-qa.json`,
  screenshot: 'on',
});
```

- assertions on what the user sees (roles, text, values), not on CSS classes;
- no `waitForTimeout` — you wait for state (`expect(...).toBeVisible()`, `waitForResponse`);
- every scenario on its own data (SQL in the QA database or through the UI), independent of order;
- mutating API requests with the `X-CSRF-TOKEN` header from the `csrf_access_token` cookie;
- zero comments — the name of the test and of its steps says what you check.

Running and reading the results:

```bash
cd ~/.cache/claude-qa && PLAYWRIGHT_JSON_OUTPUT_NAME=runs/<ID>/results.json \
  ~/.claude/bin/verify -n qa-<ID> -- npx playwright test runs/<ID> \
  --workers=1 --trace=on --output=runs/<ID>/artifacts --reporter=list,json
jq -r '.. | objects | select(has("specs")) | .specs[] | [.title, .tests[0].results[-1].status] | @tsv' \
  ~/.cache/claude-qa/runs/<ID>/results.json
```

Forms 4–6 also go through `verify`, and the scenario gets the log path as its evidence.

## 8. Whether a FAIL is real

Before you write a FAIL:

1. look at the screenshot and `error-context.md` from `artifacts/`;
2. tell an application error from a test error — a wrong selector, missing data, an expired session, a
   service that did not come up (`qa logs <service>`). A test error you fix and rerun the scenario; it is
   not a result;
3. confirm with a second, independent method when possible: an SQL query, an API request, a service log;
4. a scenario that passes once and fails once (`--repeat-each=3`) is a FAIL with the note "niestabilny" —
   instability is usually a race, that is, a bug;
5. a FAIL outside the ticket's promises (a neighbouring feature) you check on the base: rebuild that
   service from the base's worktree and run the scenario again. It fails there too → **FAIL (zastany)**:
   you report it, it does not block.

## 9. Cleanup

Always, also after a FAIL and after an interruption: `qa down`, `docker volume rm acme-qa_pgdata`,
`git -C <repo> worktree remove --force <QA worktree>` — only the `qa-*` worktrees you created yourself.
The `acme-qa-*` images stay as a build cache. The `runs/<ID>/` directory stays — it is the evidence.

## 10. Report

Save it to `runs/<ID>/report.md` and return it in the reply:

```
QA TICKET-1234 — 14 scenarios: 9 PASS, 3 FAIL, 1 NIEJASNE, 1 NIE URUCHOMIONY
Tested SHAs: cloud-platform-reports abc1234, web-ui def5678; the rest from cloud-platform-* images (<date>)

| #   | Scenario | Why hard | Form | Result | Evidence |
|-----|----------|----------|------|--------|----------|
| S01 | ...      | ...      | UI   | PASS   | runs/TICKET-1234/ui.spec.ts, screenshot |
```

Below the table:

- **FAIL** — steps, expected (a quote from the ticket), actual, screenshot, the suspect place
  `file:line`. Every FAIL must be a ready finding that can be handed to the implementer without further
  questions;
- **NIEJASNE** — questions for Sebastian, in one batch;
- **NIE URUCHOMIONY** — the blocker and what is needed for it to run;
- **Steps down the ladder** — scenario → form → reason.

## 11. Invocation from `task` (step 4e)

This is the gate to the PR. A FAIL goes back into the fix loop as a finding — with a regression test on
both levels per CLAUDE.md; you point to the spec and screenshot path, you do not paste them. After a fix
round you repeat the FAILs and the scenarios from the same area, and before the PR — a full run on the
final SHAs, because a new commit invalidates the previous result. NIEJASNE waits for Sebastian's answer,
NIE URUCHOMIONY is a blocker — the PR is not created until Sebastian decides otherwise. FAIL (zastany)
goes into the PR's `## Dodatkowy kontekst` section and does not block. The table goes into the `task`
report and into the PR description's section with the QA scenarios.
