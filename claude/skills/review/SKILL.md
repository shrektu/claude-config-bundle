---
name: review
description: Jak przeprowadzić rundę review w workflow TDD - własna checklista Claude (zgodność z planem, dowody red → green dla każdego testu, sensowne testy jednostkowe i integracyjne, idiomy dla wersji z repo-facts, regresje, pliki untracked, styl), adjudykacja linii od astry i sol (reprodukcja, zanim cokolwiek wróci do developera), bramka testów (unit + integracja przez verify + realne uruchomienie), mechanika rund z review-checkpoint i re-review sol tylko na diffie poprawek, limit 3 rund oraz raport z trzema statusami. Załaduj, gdy developer skończył albo gdy wracają findingi.
---

## Your own review (every round)

`git status --short` + `git diff <START> --stat` first (later rounds: `review-checkpoint diff <SHA>`),
then the patch per file. Untracked files never appear in a diff — list them and read them. Check:

- plan conformance: what the plan says, no extra scope, no architecture invented by the developer;
- TDD evidence: every new or changed test has a red verify log from before the production change (the
  developer's report lists them). For a test that carries a criterion, confirm it really fails without
  the change: `git worktree add <tmp> <START>`, copy the test in, run it through verify — it must fail;
  remove the worktree afterwards;
- tests are meaningful: behaviour asserted, cannot pass vacuously, nothing skipped, the integration
  tests really integrate (real app wiring, DB, HTTP, CLI), no mocks of the project's own code;
- acceptance criteria: each one checked, with evidence you can open;
- idioms match the versions `~/.claude/bin/repo-facts` prints; a deprecated-for-this-version API or a
  `warnings: N deprecation lines` line on a verify PASS is a finding (`repo-standards` skill);
- regressions: callers, signatures, migrations, serialized shapes, error paths, concurrency;
- code style: no narrating comments, no magic numbers or strings, typed models instead of raw dicts,
  no needless `__init__.py`.

## Astra (plan) and sol (code) lines

Both answer `PASS` or one defect per line. Every line is adjudicated before anything is acted on:

- reproduce it — a failing test, a command, or the code path read until certain;
- real → into the plan fix (astra) or the round's fix list (sol);
- unreal → dropped, with the reason kept for the report;
- a deliberate trade-off → argued on the merits or escalated to the user, never silently changed.

Astra reviews the plan once; your fixes close the plan phase. Record the token header of every Codex
call for the report.

## Test gate (yours, after the review is clean)

1. Rerun the plan's unit and integration commands yourself through verify on the final tree.
2. Run the repo's whole relevant suite and its lint/typecheck.
3. Real run: use the feature the way it is used — start the app (`run` skill), drive the UI in the
   browser pane, call the API, run the CLI, simulate or flash firmware. Note what you did and what you
   saw. Unit tests never replace this.

A failure anywhere is a finding: it goes into the next fix round with a reproducing test.

## Round mechanics

1. START SHA saved before the developer was spawned — base of round 1.
2. Developer reports → `review-checkpoint save` → R1; sol `base=<START>`; your review of the full diff.
3. Real findings → ONE SendMessage (`delegate` skill). Developer reports → sol `base=<R1>` with
   `recheck=<findings>`; your review of `review-checkpoint diff <R1>`; save R2 before the next round.
4. Done when sol says PASS on the last round, your review is clean and the test gate is green.
5. 3 rounds without progress on the same finding → STOP. Report **Zablokowane** with the blocker, the
   evidence and the decision needed. Never declare the task done to end the loop.

## Final report

One status, then the details:

- **Gotowe do merge** — acceptance criteria met, review current for the final commit, test gate green.
- **Wdrożone i sprawdzone** — running on the target, acceptance scenario passed. The only status that
  means done when the task requires a working deployment.
- **Zablokowane** — the blocker, the evidence, the exact next step or decision needed.

Plus: changes, verify summary lines (unit, integration) and the real run, astra and sol outcome with
their token headers, confirmed findings, rejected findings with the reason, remaining risks. A new
commit invalidates the previous review — the status always refers to the final commit.
