---
name: delegate
description: Szablon pliku planu (task, architecture, test_plan, acceptance_criteria, commands, repos, risks) i prompty workflow TDD - spawn agenta developer (Sonnet 5.5 medium, implementuje test-first z plan_file), runda poprawek przez SendMessage oraz codex-runner (review planu i kodu przez gpt-6-sol/high; przekazujesz tylko ścieżki i SHA, nigdy treść planu ani diff). Załaduj przed napisaniem planu i przed każdym Agent(...) z tymi typami - delegation-guard odrzuca spawn bez plan_file albo z planem bez test_plan, acceptance_criteria, `verify --`, ścieżki absolutnej lub granicy repo.
---

## Plan file

Path: `~/.claude/plans/<repo>-<slug>.md`. One file is the single source for sol's plan review, the developer and
sol's code review — nobody gets the plan pasted into a prompt.

```
# Plan: <title>

## task
<what and why, two to four sentences>

## architecture
<exact files, functions, signatures, data shapes; what must not change; no decision left open>

## test_plan
<per acceptance criterion at least one line: unit | integ | e2e — test name — asserts — fails today because>

## acceptance_criteria
<checkable statements, one per line>

## commands
Unit: ~/.claude/bin/verify -- 'cd /absolute/path/to/repo && <unit test command>'
Integration: ~/.claude/bin/verify -- 'cd /absolute/path/to/repo && <integration test command>'

## repos
You may only touch /absolute/path/to/repo; you may not touch <everything else, named>.

## risks
<what can bite; the user's answers to open questions>
```

## developer spawn prompt

The plan holds the contract, so the prompt stays short:

```
plan_file: <absolute path of the plan file, ~ expanded>
repo: /absolute/path/to/repo — branch <work branch>; do not commit
tdd_exempt: <reason>          (only when the tdd skill allows it; otherwise leave the line out)
<at most a few lines the plan does not hold, e.g. a plan-review line you rejected and why>
Report per your agent contract.
```

Save `~/.claude/bin/review-checkpoint save` → START SHA before the spawn; it is the base of the first
code review.

## Fix round (SendMessage to the same developer)

Only the verified findings of the round, one per line:
`path:line — defect — test to add first` (or `— non-behavioural, no test`). Nothing else: the
developer still has the plan and its own context. Spawn a fresh developer only when the old one is gone
or has drifted.

## codex-runner prompts

The MCP server fixes model and effort (plan and code → gpt-6-sol/high), builds the
prompt, inlines the diff and the plan's acceptance_criteria itself. Run the runner in the background, in
the same batch as your own verify run.

Plan review:
```
mode: plan
plan_file: <absolute plan path>
project_path: /absolute/path/to/repo
```

Code review, round 1:
```
mode: code
plan_file: <absolute plan path>
project_path: /absolute/path/to/repo
base: <START SHA>
```

Re-review after a fix round — only the fix diff:
```
mode: code
plan_file: <absolute plan path>
project_path: /absolute/path/to/repo
base: <round SHA saved before the fix round>
recheck: <the findings sent to the developer, one per line>
```

The answer is a header `codex <mode> <model>/<effort> tokens in=… cached=… out=…` followed by `PASS` or one
line per defect (`<section>: …` for a plan, `<path>:<line>: …` for code).

## Explore first?

Send `Explore` before planning when the repo is unfamiliar or the plan cannot name the files yet — it
returns the conclusion, not the dumps. Skip it when you already know the files.
