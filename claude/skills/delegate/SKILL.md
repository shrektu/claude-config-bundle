---
name: delegate
description: Szablony promptów do spawnowania agentów — implementer (M), implementer-hard (L/XL), implementer-opus (długa, wieloplikowa praca L/XL albo po nieudanej rundzie Sonneta) oraz codex-runner (review z mode plan/code/final-audit). Załaduj tuż przed każdym wywołaniem Agent(...) z tymi typami: hook delegation-guard odrzuca prompt bez acceptance_criteria, bez `verify --`, bez ścieżki absolutnej, bez linii o zakazie revertu i bez granicy repozytoriów. Zawiera też review_focus per klasa zadania i zasadę, kiedy wysłać najpierw Explore.
---

## Implementer prompts

`implementer` (M, Sonnet high) · `implementer-hard` (L/XL, Sonnet xhigh) · `implementer-opus` (L/XL long
multi-file autonomous work, or after one failed Sonnet round). Never a bare `model:` Agent call — that
loses the effort setting. Fill every section; delegation-guard denies a spawn that misses one.

```
task
<what to build, in two or three sentences>

architecture
<exact files, functions, signatures; what to change and what not to; the data shapes;
 no architecture decisions left to the agent>

acceptance_criteria
<checkable statements, one per line>

paths
/absolute/path/to/repo — the repo root
/absolute/path/to/repo/src/module.py — the file to change

test_command
~/.claude/bin/verify -- 'cd /absolute/path/to/repo && <the real test/lint/build command>'

extra_context
<constraints, pinned versions, things that must not regress, links to the plan or log files>

rules
- run `~/.claude/bin/repo-facts` as your first command and match the pinned versions it prints
- for a bug fix: write the reproducing test first, confirm it fails, then fix
- comment policy: as few comments as possible, ideally zero; if unavoidable, one line of a few words
- do not create branches, commit, or push (the orchestrator commits after review)
- repos: you may only write under <repo list>; you may not touch <everything else, named>
- Never revert or discard changes you did not make (checkout/restore/stash/reset/clean are blocked by a hook); if you think a revert is needed, stop and report.

report
Under 60 lines: changed files (path — what), acceptance criteria met/not met with evidence pointers,
verify summary lines only (VERIFY PASS/FAIL, exit code, log path), checks NOT run and why,
versions/idioms verified against (from repo-facts), blocked/questions/deviations or "none".
Never paste full logs, diffs or file contents.
```

Fix-task round: prefer SendMessage to the implementer that did the work (its context is intact) with the
verified findings of the round; keep the same sections, replace `task` with the finding list.

## Codex review prompt (`codex-runner`)

Hand exactly these fields; the runner calls `codex_review_changes` once and returns the output verbatim:
`what_changed`, `review_focus`, `acceptance_criteria`, `project_path` (absolute), `extra_context`,
`mode` ∈ plan | code | final-audit. `reasoning_effort="xhigh"` only for an XL plan review or an XL final
audit; never override `model` or `service_tier` (gpt-6-astra, high, service_tier default are the server
defaults). Spawn the runner in the SAME tool batch as your verify run and review in parallel.

| mode | when | what_changed | review_focus |
|---|---|---|---|
| plan | XL always, L with an open architectural question | the plan text | contradictions, missed dependencies, rollout order, data/protocol risks, missing acceptance criteria |
| code | M above the gate, L/XL every round | round 1 the full diff; later rounds `review-checkpoint diff <SHA>` plus the findings it was meant to fix | correctness, regressions, contract mismatches, missing tests, idioms deprecated for the pinned versions (put the repo-facts output in `extra_context`); later rounds: is each finding really fixed, did anything regress |
| final-audit | XL after the last fix | the full diff plus the list of findings already handled | what the earlier reviews missed; no redesign |

## Explore first?

Send `Explore` before the implementer when the repo is unfamiliar or the plan cannot name the files yet
(locating a symbol, a convention, a config across many files) — it returns the conclusion, not the dumps.
Skip it when the plan already names the files: the implementer opens them itself.
