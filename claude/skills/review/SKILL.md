---
name: review
description: Jak przeprowadzić review rundy w tym workflow: własna checklista orchestratora (zgodność z planem, acceptance criteria, sensowne testy, aktualne idiomy dla wersji z repo-facts, regresje, pliki untracked, styl kodu), adjudykacja findingów (najpierw reprodukcja, bug vs świadomy trade-off), tryby i kubełki Codexa (BLOCKER/IMPORTANT/OPTIONAL/PASS), mechanika rund z review-checkpoint i limitem 3, oraz format raportu końcowego z trzema statusami. Załaduj, gdy implementer skończył pracę albo gdy wracają findingi z Codexa.
---

## Your own review (always, Codex or not)

Read `git status --short` + `git diff HEAD --stat` first, then the patch per file. Untracked files never
appear in a diff — list them and read them. Check, in this order:

- plan conformance: what the plan said, no extra scope, no architecture invented by the implementer;
- acceptance criteria: each one actually checkable and actually checked, with evidence you can open;
- tests: present, meaningful (they fail without the change — for a bug fix the reproducing test existed
  first), not silently skipped, not asserting the implementation instead of the behaviour;
- modern idioms: the code matches the versions `~/.claude/bin/repo-facts` prints for this repo; a
  deprecated-for-this-version API, or a `warnings: N deprecation lines` line on a verify PASS, is a finding
  (details in the `repo-standards` skill);
- regressions: callers, signatures, migrations, serialized shapes, error paths, concurrency;
- code style: no narrating comments, no magic numbers or strings, no `dict[str, Any]` where a typed model
  belongs, no needless `__init__.py`;
- claims: rerun the relevant checks yourself through `~/.claude/bin/verify` — a report saying "tests pass"
  is not evidence.

## Codex as second reviewer

Gate and modes: see the class table in CLAUDE.md and the `delegate` skill. Code changes in a product repo
always go through this loop; config, doc or text edits outside a product repo never need Codex, whatever
the diff size. Codex answers in buckets:

- BLOCKER — must be fixed before the commit; goes into the fix task of this round.
- IMPORTANT — fix in this task unless you can argue it is wrong or a deliberate trade-off; if you reject
  it, say why in the final report.
- OPTIONAL — record it in the report; implement only when it is cheap and in scope, otherwise leave it.
- "Checked and clean" — coverage information, tells you what you do not have to re-verify.
- "Could not verify" — NOT clean: either verify it yourself or list it as a remaining risk.
- `PASS` — no BLOCKER and no IMPORTANT. Only then is the Codex half of the review clean.

## Adjudication

Every finding — yours or Codex's — is reproduced or verified before it goes back to the implementer: read
the code path, run the command, write the failing test. Drop the unreal ones and say why in the report.
When a finding is really a trade-off or a deliberate design choice, argue it on the merits or escalate it
to the user — never silently change the design. Findings about style preferences are not defects.

## Round mechanics

1. `~/.claude/bin/review-checkpoint save` → SHA before the round goes to review; `review-checkpoint size`
   decides the M gate (≥ 200 lines or > 3 files).
2. Round 1 reviews the full diff; every later round reviews `~/.claude/bin/review-checkpoint diff <SHA>`
   plus the findings it was meant to fix.
3. All real findings of a round go back in ONE fix task, via SendMessage to the implementer that did the
   work; spawn a fresh agent only when it is gone or has drifted.
4. 3 rounds without progress on the same finding → STOP. Report **Zablokowane** with the blocker, the
   evidence gathered and the decision needed. Never declare the task done just to end the loop.

## Command handoff (S/M)

When a task was handed to `commander-opus`, it runs this whole skill itself — its own checklist, the
Codex gate, adjudication, round mechanics, the commit, the final report. Fable relays that report to the
user verbatim and does not add a second review on top of it.

## Final report

One status, then the details:

- **Gotowe do merge** — acceptance criteria met, the review is current for the final commit, required
  checks green.
- **Wdrożone i sprawdzone** — running on the target environment, acceptance scenario passed. The only
  status that means done when the task requires a working deployment.
- **Zablokowane** — the blocker, the evidence, the exact next step or decision needed.

Plus: changes, tests run (verify summary lines only), whether Codex reviewed and why (gate outcome),
confirmed findings, rejected findings with the reason, remaining risks. A new commit invalidates the
previous review and CI results — the status always refers to the final commit.
For an XL task end the report with: switch back: `/effort high`.
