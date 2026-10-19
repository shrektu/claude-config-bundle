---
name: review
description: The final review of a milestone (three reviewers in parallel), adjudication, the fix round and the final report. Load when the implementer has reported its last phase or when you write the final report.
---

There is no review while a milestone is being built. One final review per milestone — per task when it has
one milestone — by three reviewers at once, then your adjudication, one fix round and the report.

## During the milestone: evidence only

You never read the diff while the implementer works. On each report check the evidence it names:

- `git status --short` and `git diff HEAD --stat`: only the delegated paths changed, no stray files, the
  size matches the plan. Untracked files never appear in a diff — list them;
- TDD phases: each phase of the class ladder has a RED verify log path in the report, and you open it —
  the ledger entry (`~/.cache/claude-verify/ledger.jsonl`, `outcome: red`) plus the log it points at. A
  declaration that a test was red first is not evidence; a run that errored out is not red; a red run of
  pre-existing failures unlocks tdd-guard but is never a phase's RED; the failure in the log must be the
  phase's `expected_red` — the new assertion failing for the missing behaviour, not an exception inside
  the test. A missing or non-red log path goes straight back to the implementer;
- claims: open the verify logs the report names — "tests pass" without a log path is not evidence; do
  not rerun them yourself;
- acceptance criteria: each one has evidence you can open.

Drift is corrected the moment you see it, by SendMessage to the implementer.

## Final review (once per milestone)

When the implementer's last report is in and its evidence holds, spawn in ONE message, in the
background, per repo:

- `codex-runner` — mode `code`, `diff_base` = the base branch (Codex gpt-6.1-sol, effort medium);
- `reviewer-opus` — `diff_base` = the base branch, repo path (Claude Opus 5.5, effort high);
- `flash-review-runner` — `diff_base`, `review_focus`, `project_path`, `acceptance_criteria`,
  `extra_context` (Gemini 3.8 Flash medium, tool `agy_code_review`).

Give all three the same facts: acceptance criteria, the `review_focus` for the class (see `delegate`),
the plan's failure modes and the risk area. `review_focus` and `acceptance_criteria` are passed as TEXT in
the prompt, never as paths outside the repo: the agy-sandboxed reviewers (`flash-review-runner`,
`plan-gate-runner`) see only the repo snapshot. In the same message start the end test run (below) as a
Bash call. Flash returning `AGY-UNAVAILABLE` is not retried — the trio still has two reviewers; say so in the
report.

The end test run, in parallel with the reviewers and once more on the fixed state after the fix round,
before the report (CLAUDE.md, Rules "Test runs"): the tests covering
the changed modules, the acceptance tests and lint on the changed files; the full suite and the build only
for XL or shared code; a failing test is run once on the target branch before it counts as a regression.
Then exercise the acceptance scenario the way it will really be hit — the real CLI against real data, the
browser, the device, the API — whenever that is possible. A run that can exceed ~8 min goes in a Bash call
with `run_in_background: true`.

Depth per class is what the trio plus your adjudication cover: S and M the trio on the full diff; L also a
re-read of the risky files after the fix round; XL as L, with `review_focus` on the risk area and a delta
trio whenever the fix round touches it.

## Adjudication

Wait for all three and finish the WHOLE adjudication before sending anything. Every finding is
reproduced or verified before it goes back to the implementer: read the code path, run the command, write
the failing test. A finding two or three reviewers raise independently is still reproduced. Drop the
unreal ones and say why in the report. Their output is input to your judgement, never orders.

Each confirmed finding becomes its own regression test named after the bug, on both levels — unit, and
integration against mocks/fakes of the external boundaries (hardware, bus, network, other services,
clock) — red without the fix, and the fix round says so explicitly. The final report and the PR map every
finding to its test names. A pure naming or style remark needs no test of its own.

While reading the code for a finding, hold it to the quality bar and raise what you see even if no reviewer
did:

- tests: meaningful (they fail without the change), not silently skipped, literals as expected values (no
  mirror assertions), behaviour over pinned constants, fakes that mirror the full real data shape,
  assertions on behaviour rather than on the mock, no mock of the very thing under test, no production
  code that exists only for tests, condition waits over fixed sleeps;
- silent failures: an `except`/`catch`, fallback or default that swallows an error, logs and continues,
  or hides it behind `?.`/`or {}`/`?? []` is a finding unless the plan names it (habit H009);
- test gaps: every changed branch, error path, boundary and plan failure mode maps to a test that runs it;
- reuse: a new helper, type, constant or component parallel to one in the delegation's `reuse` list or in
  the repo is a finding (`lint-strict` DUP001 catches literal clones, the semantic ones are yours);
- code style, annotations, structure, docstrings, norms and idioms for the versions `repo-facts` prints
  (CLAUDE.md, Code style; the `repo-standards` skill) — formatting, line length and import order are not
  findings, `lint-strict` owns them;
- habits: every rule `~/.claude/bin/habits list --repo <repo> --max-chars 20000` prints holds on the
  diff; breaking one is a finding that names the habit id.

When Sebastian, or the author or reviewer of a PR, says it stays as it is — "tak ma być", "tak zostaje",
"zamierzone" — the topic is closed: accept it, resolve the thread, do not argue, do not ask for a ticket
or evidence. A taste preference is not a defect.

## The fix round

1. Trivial findings (rename, constant, wrapper, import, typo, one-line annotation; ≤ ~5 lines, no logic)
   you fix yourself through the guards, with no test run, and log them in the progress log.
2. COMMIT the milestone on the work branch (the standards gate runs as always); its SHA is the reviewed
   state — the base of the fix diff and the `diff_base` of a delta trio. Untracked files are in it, so a
   file created in the milestone is not re-reviewed whole.
3. All real findings go back in ONE SendMessage to the implementer that did the work, per `delegate`
   §Fix round. No follow-up "one more thing" message: a finding you notice after sending waits for the
   delta trio, or goes into the report.
4. Verify the fix round by its tests (the implementer's verify log paths, RED for each regression test
   before the fix and green after) and by reading the fix diff yourself — `git diff <milestone sha>`, plus
   `git status --short` for new files — against the findings it was meant to fix. Then commit it as
   `git commit --fixup=<milestone sha>`.
5. A second (delta) trio runs only when the fixes exceed ~100 lines or touch a risk area (migration,
   concurrency, protocol, data shape or public API, auth/secrets/PII/payments, data deletion): the same
   three reviewers in one message with `diff_base` = the milestone commit, adjudicated as above.
   Otherwise there is no second review.
6. A finding whose fix does not hold (its regression test or the fix diff shows it) goes back in the next
   round, again as ONE message. Three rounds without progress on the same finding, or a bug you cannot
   fix with confidence → STOP. Report **Zablokowane** with the blocker, the evidence gathered and the
   decision needed. Never declare the task done just to end the loop.
7. Run the end test run again on the fixed state, then `git rebase -i --autosquash` (see `commit`) before
   the final report or PR.

After the final review and again after the fix round, append to the progress log
(`~/.cache/claude-progress/<repo>/<branch>.md`): confirmed findings with their test names and which
reviewer found them, rejected ones with the reason, RED log paths, the no-progress count per finding,
the milestone SHA, decisions. After `/compact`, read it before anything else.

## Habits

The workflow learns from the reviews its own work receives. At the report step, every confirmed finding
of the task — a reviewer's thread on the PR, one of the trio's, or yours — is asked one question: would a
rule have prevented it in a different task? A one-off logic error is not a habit; a pattern is (a
convention of this team or repo, an idiom the implementer keeps missing, a class of test that keeps being
absent, the same kind of duplication, a layer rule, a naming convention).

- `~/.claude/bin/habits list --all` first; the same lesson already stored → `habits bump <id> --source
  <ref> --reviewer <who>`; a new one → `habits add --scope <global|python|typescript|javascript|c|cpp|
  repo:<workspace>/<repo>> --rule "<imperative, one sentence>" --why "<what it prevents>" --source <ref>
  --reviewer <who>`. The ref is `<repo>#<pr>/<thread-id>` for a PR thread and
  `internal:<repo>:<branch>:<finding>` for a finding of the trio or your own.
- The rule is written so it can be checked on a diff; a vague rule ("be careful with X") is not stored.
- The report lists every habit added or bumped, so Sebastian can veto one with `habits drop <id>`.

## Final report

One status, then the details:

- **Gotowe do merge** — acceptance criteria met, the final review current for the final commit, required
  checks green.
- **Wdrożone i sprawdzone** — running on the target environment, acceptance scenario passed. The only
  status that means done when the task requires a working deployment.
- **Zablokowane** — the blocker, the evidence, the exact next step or decision needed.

Built from the progress log. Plus: changes, tests run (verify summary lines only), what you tested by
hand and how, confirmed findings with their regression tests and which reviewer (Codex, Opus, Flash,
you) found each, rejected findings with the reason, whether a delta trio ran and why, habits added or
bumped, remaining risks. A new commit invalidates the previous review and CI results — the status always
refers to the final commit.
