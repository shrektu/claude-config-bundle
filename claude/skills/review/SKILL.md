---
name: review
description: Twoja runda review i testów po raporcie implementera oraz raport końcowy. Załaduj, gdy implementer skończył rundę albo piszesz raport końcowy.
---

## Your own review (every round)

Read `git status --short` + `git diff HEAD --stat` first, then the patch per file. Untracked files never
appear in a diff — list them and read them. Check, in this order:

- plan conformance: what the plan said, no extra scope, no architecture invented by the implementer;
- acceptance criteria: each one actually checkable and actually checked, with evidence you can open;
- tests: present, meaningful (they fail without the change — for a bug fix the reproducing test existed
  first), not silently skipped, not asserting the implementation instead of the behaviour;
- test quality: literals as expected values (no mirror assertions), behaviour over pinned constants,
  fakes that mirror the full real data shape, assertions on behaviour rather than on the mock, no mock of
  the very thing under test, no production code that exists only for tests, condition waits over fixed
  sleeps — each break is a finding;
- TDD phases: each phase of the class ladder has a RED verify log path in the report, and you open it —
  the ledger entry (`~/.cache/claude-verify/ledger.jsonl`, `outcome: red`) plus the log it points at. A
  declaration that a test was red first is not evidence; a run that errored out is not red, and the
  failure in the log must be the phase's `expected_red` — the new assertion failing for the missing
  behaviour, not an exception inside the test. A missing or
  non-red log path is a finding and goes back in this round's fix task;
- modern idioms: the code matches the versions `~/.claude/bin/repo-facts` prints for this repo; a
  deprecated-for-this-version API, or a `warnings: N deprecation lines` line on a verify PASS, is a
  finding (details in the `repo-standards` skill);
- regressions: callers, signatures, migrations, serialized shapes, error paths, concurrency;
- silent failures: every `except`/`catch`, fallback and default on the diff — an error swallowed,
  logged-and-continued, replaced by an empty or default value, hidden behind `?.`/`or {}`/`?? []`, or a
  retry with no final failure — is a finding unless the plan names that fallback; the failure must reach
  the caller or the user (habit H009);
- test gaps: map every changed branch, error path, boundary and plan failure mode to the test that runs
  it; one with no test is a finding that names the missing test;
- reuse: the delegation's `reuse` list was used; a new helper, type, constant or component parallel to a
  listed or existing one is a finding (`lint-strict` DUP001 catches literal clones, the semantic ones are
  yours);
- code style: no narrating comments, no magic strings (magic numbers only as `lint-strict` reports them —
  never by hand), no `dict[str, Any]` where a typed model
  belongs, no needless `__init__.py`;
- type annotations: every new or changed signature (parameters, return, model fields) is annotated;
  no `Any`/`object`/`unknown` where the type is known, no annotation that lies, no `cast`/`as`/
  `type: ignore` covering a wrong type;
- architecture and structure of the added code: consistent with how the repo already does it (layers —
  business logic in services/hooks, not in endpoints/components; the repo's patterns and conventions;
  where files and modules live), no abstraction parallel to an existing one, no dependency pointing the
  wrong way;
- simplification: anything that can clearly be shorter, simpler or better structured — needless
  indirection or wrappers, repeated blocks to extract, nesting to flatten with early returns, a manual
  loop where the language idiom exists, a function or component to split — is a finding with the
  concrete change named;
- norms: the commit gate (`standards-gate` → `lint-strict`) enforces the linters, type checkers and
  complexity limits at `git commit`, and the advisory `ai-review-gate` you start in the background looks
  at architecture, duplication, habits and test quality; in your round you still read for what they
  miss —
  names that lie, non-idiomatic constructs, swallowed exceptions, mutable default arguments, PEP 8
  naming, `is None` comparisons, a new suppression (noqa, NOLINT, eslint-disable, type: ignore) without
  a reason. Formatting, line length and import order are not findings;
- docstrings: every Python class and function (private, nested and magic included; tests exempt) has
  a docstring, one line, one sentence, at most 72 characters, as short as possible — a missing, long or
  narrating one, or any module docstring, is a finding;
- habits: every rule `~/.claude/bin/habits list --repo <repo> --max-chars 20000` prints is checked on the diff; breaking
  one is a finding that names the habit id;
- claims: open the verify logs the report names — "tests pass" without a log path is not evidence; do
  not rerun them yourself during the rounds;
- RED evidence: each phase's RED log must show that phase's own new test failing; a red run of
  pre-existing failures unlocks tdd-guard but is never a phase's RED;
- the end run, once, right before the commit (CLAUDE.md, Rules "Test runs"): the tests covering the
  changed modules, the acceptance tests and lint on the changed files; the full suite and the build only
  for XL or shared code; a failing test is run once on the target branch before it counts as a
  regression. Then exercise the acceptance scenario the way it will really be hit — the real CLI against
  real data, the browser, the device, the API — whenever that is possible.

## Adjudication

Every finding is reproduced or verified before it goes back to the implementer: read the code path, run
the command, write the failing test. Drop the unreal ones and say why in the report. Each confirmed
finding becomes its own regression test named after the bug, on both levels — unit, and integration
against mocks/fakes of the external boundaries (hardware, bus, network, other services, clock) — red
without the fix, and the fix round says so explicitly. The final report and the PR map every finding to
its test names. A pure naming or style remark needs no test of its own.

When Sebastian, or the author or reviewer of a PR, says it stays as it is — "tak ma być", "tak zostaje",
"zamierzone" — the topic is closed: accept it, resolve the thread, do not argue, do not ask for a ticket
or evidence. A taste preference is not a defect.

## Habits

The workflow learns from the reviews its own work receives. At the report step, every confirmed finding
of the task — a reviewer's thread on the PR or yours — is asked one question: would a rule have
prevented it in a different task? A one-off logic error is not a habit; a pattern is (a convention of
this team or repo, an idiom the implementer keeps missing, a class of test that keeps being absent).
Findings of `ai-review-gate` count too: an accepted gate finding that is a pattern of the repo (the same
kind of duplication, a layer rule, a naming convention) becomes a habit, so the implementer meets it
before the gate does. Gate findings are adjudicated in your round like any finding — sent back, or
rejected with a reason (recorded with `waive` so later rounds do not re-raise them).

- `~/.claude/bin/habits list --all` first; the same lesson already stored → `habits bump <id> --source
  <ref> --reviewer <who>`; a new one → `habits add --scope <global|python|typescript|javascript|c|cpp|
  repo:<workspace>/<repo>> --rule "<imperative, one sentence>" --why "<what it prevents>" --source <ref>
  --reviewer <who>`. The ref is `<repo>#<pr>/<thread-id>` for a PR thread and
  `internal:<repo>:<branch>:<finding>` for your own finding.
- The rule is written so it can be checked on a diff; a vague rule ("be careful with X") is not stored.
- The report lists every habit added or bumped, so Sebastian can veto one with `habits drop <id>`.

## Round mechanics

1. `~/.claude/bin/review-checkpoint save` → SHA before each round goes to review.
2. Your round 1 reads the full diff; later rounds read `review-checkpoint diff <SHA>` plus the findings
   they were meant to fix.
3. Start the Codex code gate (`codex-runner`, mode code) in the background as round 1 begins, so its
   findings join that round. Finish the whole round — diff, logs, Codex —
   before sending anything. Trivial findings (rename, constant, wrapper, import, typo, one-line
   annotation; ≤ ~5 lines, no logic) you fix yourself through the guards, with no test run, and
   log in the progress log. All other real findings go back in ONE SendMessage to the implementer that
   did the work — never a follow-up message adding to a round already sent.
4. After each round append to the progress log (`~/.cache/claude-progress/<repo>/<branch>.md`): round
   number, confirmed findings with their test names, rejected ones with the reason, waivers, RED log
   paths, the no-progress count per finding. After `/compact`, read it before anything else.
5. Three fix rounds without progress on the same finding → one `implementer-strong` attempt (`delegate`
   §Escalation), reviewed in full. Still no progress, or a bug you cannot fix with confidence → STOP.
   Report **Zablokowane** with the blocker, the evidence gathered and the decision needed. Never
   declare the task done just to end the loop.

## Final report

One status, then the details:

- **Gotowe do merge** — acceptance criteria met, your review is current for the final commit, required
  checks green.
- **Wdrożone i sprawdzone** — running on the target environment, acceptance scenario passed. The only
  status that means done when the task requires a working deployment.
- **Zablokowane** — the blocker, the evidence, the exact next step or decision needed.

Built from the progress log. Plus: changes, tests run (verify summary lines only), what you tested by hand and how, confirmed
findings with their regression tests, rejected findings with the reason, habits added or bumped,
remaining risks. A new commit invalidates the previous review and CI results — the status always
refers to the final commit.
