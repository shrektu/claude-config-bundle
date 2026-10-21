---
name: review
description: The final review of a milestone (the class's reviewer set in parallel), adjudication, the fix round and the final report. Load when the last phase is reported (or your own XS edit is done) or when you write the final report.
---

## Final review

First the last report's evidence holds (CLAUDE.md, Rules): only the delegated paths changed, no stray
files, size as planned, every acceptance criterion with evidence you can open. A phase RED log that is
missing, not red or without its ledger entry (`~/.cache/claude-verify/ledger.jsonl`, `outcome: red`) goes
straight back to the implementer.

Then spawn the class's reviewer set (CLAUDE.md, Task classes) per repo in ONE background message, with
the end test run as a Bash call in the same message. Each reviewer gets, as text (never paths outside the
repo): `project_path`, `diff_base` = the base branch, `review_focus`, `acceptance_criteria`,
`extra_context` (the plan's failure modes, the risk area); `codex-runner` also `mode: code`.

### review_focus per class

| Class | Focus |
|---|---|
| XS | the changed lines do what the task says; nothing else touched |
| S | the one changed behaviour, its red test; nothing else touched |
| M | plan conformance, acceptance evidence, meaningful tests, callers and signatures |
| L | module boundaries, integration tests against the fakes, perf and typing claims, regressions in every caller |
| XL | the risk area: migration and rollback, on-wire/protocol compatibility, concurrency and ISR paths, auth and tenancy, irreversible steps |

Flash `AGY-UNAVAILABLE`: no retry, say so in the report. XS: spawn `codex-runner` (`mode: code`)
instead; S: Codex alone stands; M/L/XL: the other two stand. In personal mode (Codex is off) XS and S
spawn `reviewer-opus` instead.

A bug a later stage (delta review, PR review, QA) catches that the class's set missed → raise the class
(this task's if open, similar tasks' next time); never add reviewers by default.

## Adjudication

Wait for every reviewer; adjudicate everything before sending anything. Reproduce each finding, even one
several reviewers raise (read the code path, run the command, write the failing test); drop unreal ones
with the reason in the report. Confirmed bug findings get regression tests (CLAUDE.md, Rules).

Also raise what you see while reading, even if no reviewer did:

- tests: fail without the change, not silently skipped, and every rule of
  `~/.claude/agents/implementer.md` "Tests you write";
- silent failures: an `except`/`catch`, fallback or default that swallows, logs-and-continues or hides an
  error (`?.`, `or {}`, `?? []`) unless the plan names it (H009);
- test gaps: every changed branch, error path, boundary and plan failure mode has a test that runs it;
- reuse: a new helper/type/constant/component parallel to one in `reuse` or the repo (DUP001 sees only
  literal clones);
- style, annotations, structure, docstrings, norms, idioms for the `repo-facts` versions (CLAUDE.md, Code
  style; `repo-standards`); formatting, line length and import order are lint-strict's;
- habits: every rule `~/.claude/bin/habits list --repo <repo> --max-chars 20000` prints holds; a breach
  names the habit id.

Sebastian's "tak ma być" / "tak zostaje" / "zamierzone" closes a finding: accept it, no argument, no
request for a ticket or evidence. Taste is not a defect. Bitbucket threads follow `bb` (never close a human's thread).

## The fix round

1. Trivial findings (rename, constant, wrapper, import, typo, one-line annotation; ≤ ~5 lines, no change
   in logic, behaviour or tests' meaning): fix them yourself through the guards, no test run, each in the progress log.
   Logic, a new test or a judgement call → the implementer.
2. Commit the milestone; its SHA (untracked files included) is the base of the fix diff and delta review.
3. All real findings in ONE SendMessage per `delegate` §Fix round. No "one more thing" follow-up: a late
   finding waits for the delta review or the report.
4. Verify by its verify logs (each regression test RED before the fix, green after) and by reading
   `git diff <milestone sha>` plus `git status --short` against the findings; commit
   `git commit --fixup=<milestone sha>`.
5. Delta review (when: CLAUDE.md, Rules) adjudicated as above.
6. A fix that does not hold (its regression test or the diff shows it) goes back next round, again ONE
   message; no progress after three rounds → STOP (CLAUDE.md, Rules).
7. End test run again on the fixed state, then autosquash (`commit`) before the report or PR.

Progress log after the final review and each fix round: confirmed findings with test names and reviewer,
rejected ones with the reason, RED log paths, rounds without progress per finding, milestone SHA,
snapshots, decisions and who made them.

## Habits

At the report step ask of every confirmed finding (PR thread, reviewer's, yours): would a rule have
prevented it in another task? A pattern (team/repo convention, idiom repeatedly missed, recurring missing
test class or duplication, layer or naming rule) is a habit; a one-off bug is not.

- Duplicate check: `~/.claude/bin/habits list --all | grep -iE '<2-3 keywords, Polish and English>'`.
- Stored → `habits bump <id> --source <ref> --reviewer <who>`; new → `habits add --scope
  <global|python|typescript|javascript|c|cpp|repo:<workspace>/<repo>> --rule "<one imperative sentence,
  checkable on a diff>" --why "<what it prevents>" --source <ref> --reviewer <who>`. Ref:
  `<repo>#<pr>/<thread-id>` for a PR thread, else `internal:<repo>:<branch>:<finding>`. No vague rules.
- The report lists each habit added or bumped (Sebastian vetoes with `habits drop <id>`).

## Final report

One status:

- **Gotowe do merge** — acceptance criteria met, review current for the final commit, required checks
  green.
- **Wdrożone i sprawdzone** — running on the target environment, acceptance scenario passed; the only
  "done" when the task requires a deployment.
- **Zablokowane** — blocker, evidence, exact next step or decision needed.

Then: changes, tests run (verify summary lines), what you tested by hand and how, confirmed findings with
their regression tests and finder (Codex, Opus, Flash, you), rejected ones with the reason, whether a
delta review ran and why, habits added or bumped, remaining risks. A tree change after the review
invalidates it (a tree-preserving autosquash does not); CI counts only green on the final pushed commit.
