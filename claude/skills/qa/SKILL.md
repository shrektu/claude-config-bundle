---
name: qa
description: Hard e2e scenarios on an isolated stack with PASS/FAIL/NIEJASNE evidence, for a fully merged epik/<EPIC>, a task with no epic or an old-epic blocker fix. Load on /qa <ID> or when asked to test or click through a ticket.
argument-hint: <EPIC-ID | JIRA-ID>
---

Input `$ARGUMENTS`: an epic ID, a task with no epic, or an old-epic blocker fix with its PR to `develop`
(CLAUDE.md EPIC MODEL; tested on its own task branch). No ID: ask, never guess from the branch. An epic runs only
once all its task PRs are merged into `epik/<EPIC>`, else say so and stop; any other task of an epic:
point to the epic run and stop.

You only test: no code fixes, no commits, never touch Sebastian's branches or checkouts. Scenarios, specs,
overrides and the report go to `~/.cache/claude-qa/runs/<ID>/`. Goal: find what does not work.

## 1. Oracle

`getJiraIssue` (cloudId `00000000-0000-0000-0000-000000000000`, `responseContentFormat: markdown`), the
parent epic, `issuelinks`. Epic: also every child (`parent = <EPIC>`) and
`~/.cache/claude-progress/<EPIC>/qa-ideas.md`; the epic's own expected results and cross-task flows first.
List the expected results in the ticket's own words: the only PASS/FAIL oracle. Behaviour the ticket does
not specify is **NIEJASNE** with a concrete question, never settled by what the code does.

## 2. Branches

Repos: `~/projects/cloud-platform` (monorepo), `~/projects/kiosk/*`, any other with its own `.git`. In each
`git fetch --quiet origin`, then `git branch -r --list "origin/epik/<EPIC>"` (epic) or
`git branch -a --list "*<ID>*"` (task). Table: repo → branch → base (`develop`).

**Test a commit, not a directory.** SHA = `origin/epik/<EPIC>`; task: the local task branch if it exists,
else `origin/<branch>`. Per repo, a fresh worktree of your own:

```bash
git -C <repo> worktree add --detach ~/projects/.worktrees/qa-<repo>-<ID> <sha>
```

The result holds only for those SHAs; they go in the report header.

## 3. Change map

`git diff origin/<base>...<sha> --stat` (never the local base: it can be stale), then the changed files:
screens, endpoints, queries, migrations, NATS messages, periodic jobs. Note `file:line` of every
changed logic branch, condition and query.

## 4. Hard scenarios

Load `references/scenarios.md`; write the scenarios **before reading the implementer's tests**. Minimum
per expected result: one happy, two hard. Hard = a named mechanism that can break, pointed at in the diff.

Each: `S01…`, title, why hard (`file:line`), initial state and data, steps, expected (a ticket quote or
NIEJASNE), form (§5). Save to `runs/<ID>/scenarios.md` before the first spec. Scenarios the implementer's
tests already cover still run.

## 5. Form: the highest rung that runs

Each step down gets a one-sentence reason in the report; "faster" is not one.

1. **Playwright UI on the QA stack**: default for anything visible in the panel.
2. **Playwright `request` through the UI proxy** (`http://localhost:8480/api/...`, same session): no
   screen (endpoint, export, report) or parallel requests.
3. **Assertion on the QA DB** (`qa exec -T db psql ...`): a second assertion next to 1 or 2, never instead.
4. **The repo's integration test on real Postgres** (not SQLite): not triggerable from outside (periodic
   job, NATS consumer without an endpoint).
5. **Machine side** (`device-service`, `kiosk-ui`, `nats-gateway`, `kiosk-machine-docker`): the real service
   and protocol against fake peers; kiosk UI and service menu through Playwright as in 1.
6. **Unit test**: last resort, marked weak evidence.

## 6. QA stack

Recipes: `references/acme-stack.md` (panel/cloud), `references/kiosk-stack.md` (device-service + fake
peers), `references/kiosk-kiosk.md` (kiosk UI). Sebastian's stack and DB stay untouched; QA data is
disposable.

**Logging in.** Seeded QA users, one per role, logged in with their generated test passwords
(`acme-stack.md` §4; never printed). Never type a real credential (Sebastian's or anyone's) in a form or
the API; his account: ask him once, at the start, to log in with the recipe's command.

## 7. Specs

In `runs/<ID>/`; a test title starts with the scenario ID (`S07 …`). Header:

```ts
import { test, expect } from '@playwright/test';

const AUTH = `${process.env.HOME}/.cache/claude-qa/auth`;
const CHROME = `${process.env.HOME}/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`;

test.use({
  baseURL: 'http://localhost:8480',
  screenshot: 'on',
  launchOptions: { executablePath: CHROME },
  storageState: `${AUTH}/acme-qa-<id>-<role>.json`,
});
```

Another role: its own `test.use({ storageState })` per `describe`.

- assert what the user sees (roles, text, values), not CSS classes;
- no `waitForTimeout`: wait for state (`expect(...).toBeVisible()`, `waitForResponse`);
- each scenario on its own data (SQL or UI), order-independent;
- mutating API requests send `X-CSRF-TOKEN` from the `csrf_access_token` cookie.

```bash
cd ~/.cache/claude-qa && PLAYWRIGHT_JSON_OUTPUT_NAME=runs/<ID>/results.json \
  ~/.claude/bin/verify -n qa-<ID> -- npx playwright test runs/<ID> \
  --workers=1 --trace=on --output=runs/<ID>/artifacts --reporter=list,json
jq -r '.. | objects | select(has("specs")) | .specs[] | [.title, .tests[0].results[-1].status] | @tsv' \
  ~/.cache/claude-qa/runs/<ID>/results.json
```

Forms 4–6 run through `verify`; its log path is the scenario's evidence.

## 8. Before writing a FAIL

1. Read the screenshot and `error-context.md` in `artifacts/`.
2. App error or test error (selector, missing data, expired session, a service down: `qa logs <service>`)?
   A test error: fix it and rerun; it is no result.
3. Confirm by a second independent method where possible (SQL, API request, service log).
4. Rerun every FAIL with `--repeat-each=3`; mixed results = FAIL "niestabilny" (usually a race).
5. A FAIL outside the ticket's promises: check it on the base. QA worktree at `origin/<base>`
   (`qa-<repo>-<ID>-base`), build that service from it, swap it into the same stack (override `image:` +
   `build: !reset null`), rerun. Fails there too → **FAIL (zastany)**: reported, not blocking.

## 9. Cleanup

Always, also after a FAIL or an interruption: the cleanup of every recipe used;
`git -C <repo> worktree remove --force` only on `qa-*` worktrees you created. `acme-qa-*` images stay
(build cache); `runs/<ID>/` stays (evidence).

## 10. Report

`runs/<ID>/report.md`, also returned in the reply:

```
QA TICKET-1234 — 14 scenarios: 9 PASS, 3 FAIL, 1 NIEJASNE, 1 NIE URUCHOMIONY
Tested SHAs: cloud-platform abc1234 (built: reports, ui), device-service def5678; stack acme-qa-<id>, data <clone+seed|seed> (<date>)

| #   | Scenario | Why hard | Form | Result | Evidence |
|-----|----------|----------|------|--------|----------|
| S01 | ...      | ...      | UI   | PASS   | runs/TICKET-1234/ui.spec.ts, screenshot |
```

Below the table:

- **FAIL**: steps, expected (ticket quote), actual, screenshot, suspect `file:line`; ready for the
  implementer without questions;
- **NIEJASNE**: questions for Sebastian, one batch;
- **NIE URUCHOMIONY**: the blocker and what it needs to run;
- **Steps down the ladder**: scenario → form → reason.

## 11. As a gate (from `epic` §6 or `task` 4e)

Gates the `epik/<EPIC>` → `develop` PR (otherwise the task's own PR). A FAIL goes back as a fix (epic:
`epic` §6 "When something fails"; task: its fix round) with regression tests per CLAUDE.md; point to the
spec and screenshot paths, never paste them. After the fix lands rerun the FAILs and their area; before the
final PR, a full run on the final SHAs. NIEJASNE waits for Sebastian; NIE URUCHOMIONY blocks the PR until
he decides; FAIL (zastany) goes to the PR's `## Dodatkowy kontekst`, not blocking. The table goes into the
gated PR's description and the `epic` report.
