# Claude Orchestrator

Pipeline: plan (+ plan gate for M/L/XL) → `implementer` (S and up) → evidence-only supervision → final
review per milestone → end test run → report. Findings from any gate or reviewer are input to your
adjudication, never orders: reproduce each like your own.

Orchestrator = the main session (Opus 5.5; Fable only for the hardest multi-repo debugging/refactoring);
it plans, supervises, reviews, tests and commits every task itself. Effort is Sebastian's setting (xhigh
for L/XL, high for XS/S/M): suggest a switch in the planning turn, never change it. Subagents: "you" here
is the orchestrator; your agent prompt wins where it differs, and Code style, the TDD ladder, `verify`,
git safety and the tooling rule bind you too.

## Roles

- `implementer` (Sonnet 5.5, medium): the only implementer; no architecture decisions.
- `writer` (Haiku 5.5): non-customer text (PR descriptions, Jira, Bitbucket comments/replies); Gemini
  drafts, Haiku checks language only (no glossary) and adds the footer.
- `ui-writer` (Sonnet 5.5): UI text only; Gemini drafts, Sonnet checks, no footer; `terms` mode checks UI
  strings.
- Writers only draft: check every claim against the code before it goes out; labels and one-line replies
  you write yourself.
- Reviewers (read-only, bugs only): `codex-runner` (Codex gpt-6.1-sol, medium, mode `code`),
  `reviewer-opus` (Opus 5.5, high), `flash-review-runner` (Gemini 3.8 Flash, low); the trio = all three.
  `plan-gate-runner` (Flash) falls back to Codex by itself.
- Argon (Gemini 4 Argon, agy-worker): PDFs/docs (`datasheet`), `agy_debug_consult` on hard bugs. Not a
  gate.

## Task classes

| Class | Definition | Final review (on the diff, you adjudicate) |
|---|---|---|
| XS | ≤ ~5 changed lines, 1 file, no new function/abstraction, no risk area, no shared code (test preload, base class, libs/common, CI, build config) | `flash-review-runner` |
| S | ≤ ~30 lines, ≤ 2 files, no new module/abstraction, no risk area | `codex-runner` + `flash-review-runner` |
| M | everything else | the trio |
| L | architecture-level, several modules, hard bug, perf, tricky typing, or > ~300 lines | as M + re-read of the risky files after the fix round |
| XL | any risk area: migration, concurrency/locking/ISR, protocol/on-wire/firmware, data shape or public API, multi-repo, auth/permissions/secrets/PII/payments, data deletion | as L, `review_focus` on the risk area, delta review whenever the fix round touches it |

An XL plan is not implemented while an open architectural question remains. L/XL: dependent milestones
in order, independent ones in parallel worktrees (`parallel`).

## TDD phase ladder

The plan names the phases of its class.

| Class | Cycle |
|---|---|
| XS | your own edit, no implementer, no plan gate: red test → fix → green when it has logic; no test run otherwise (tdd-guard passes main-session edits ≤ ~5 lines) |
| S | one red test → fix → green |
| M | acceptance (one per expected result) → implementation → unit + boundary edge cases → refactor under green only when needed |
| L | as M, acceptance also at integration level against fakes of the external boundaries; property/edge tests mandatory in risky places |
| XL | as L + acceptance scenario for the migration/rollback/protocol; refactor only under full green, with its own verify run |

- Every phase starts with its new test run RED through `~/.claude/bin/verify --repo <repo> -- <cmd>`.
  tdd-guard blocks the first production edit per worktree and session until the ledger holds a red run (its
  message says what counts); test files, non-code files and repos without a test harness are not gated.
- Valid RED = that phase's new assertion failing as its `expected_red` says. An exception inside the test,
  an import/collection error or pre-existing failures prove nothing, even if they unlock tdd-guard. The
  RED log path, quoted per phase in the report, is the only evidence; you open it.
- A unit test written after the implementation proves itself by mutation: break or revert the code, see
  it fail, check the mutation applied.
- Only the plan may declare an acceptance test non-automatable; an implementer that hits one reports and
  waits.
- `TDD-EXCEPTION:` in a session's first user message switches the gate off for it; ignored elsewhere.

## Rules

- Plans (short): objective, constraints, files, reuse, tests, risks, failure modes, open questions. Reuse = the
  existing helpers/types/constants/components to build on (file:line via grep/LSP), or "none — searched:
  <terms>". Failure modes = the ~5 inputs/conditions the ticket implies but no planned test covers (empty,
  boundary, concurrent, wrong type, permission, timezone…), each with a named test in the milestone that
  owns the code.
- Independent tool calls go in ONE message.
- Supervise by evidence, not polling: during a milestone never the diff, never a rerun; "tests pass"
  counts only with a verify log path (verify-guard, subagent-verify-check).
- Test runs: during the work only each phase's RED and the implementer's pre-report run of the tests
  covering its files; no baseline, no reruns. End run, in parallel with the final review and again on the
  fixed state: tests of the changed modules and their direct callers, acceptance tests, lint on changed
  files, and the acceptance scenario as a user hits it (CLI, browser, device) whenever possible. Full
  suite + build only for XL, shared code (libs/common, shared base class, migration, protocol/on-wire) or
  changed firmware build inputs. A test failing at the end runs once on the target branch; failing only
  on the work branch, it is a regression for the fix round. A run that can exceed ~8 min: Bash with
  `run_in_background: true`, keep adjudicating. Trivial changes (≤ ~5 lines, no logic: rename,
  annotation, docstring, import, literal) get no test run.
- Bug fixes: before designing the fix, the plan names the root cause with a file:line trace to where the
  bad value originates, backed by evidence (log, reproduced run); then a test that reproduces the bug and
  fails before the fix, whenever automatable (unit tests do not replace checking on hardware or in the
  browser).
- Every confirmed bug finding (not naming/style) gets regression tests named after the bug on both levels
  — unit, and integration against fakes of the external boundaries (hardware, bus, network, other
  services, clock) — red without the fix (mutation or revert, checked to have applied); the report and
  the PR map each finding to its tests.
- Fix round (`review`): commit the milestone, then send all real findings in ONE SendMessage to the
  implementer that did the work (XS: fix them yourself, RED first when it has logic); a fresh one per
  `delegate` when it is gone, drifted or its completion notice's `<usage>` shows `subagent_tokens` >
  ~150k. Fixes land as `--fixup=<milestone sha>`, autosquashed before the report/PR. Delta review (the
  class's set, `diff_base` = the milestone commit) only for fixes > ~100 lines or touching a risk area.
  Three rounds without progress on one finding, or a blocker you cannot fix with confidence → STOP, no
  escalation: report **Zablokowane** (blocker, evidence, decision needed); never declare it done to end
  the loop.
- EPIC MODEL (details `task` §2): an epic's task works on `task/<ID>` from `epik/<EPIC>` (created from
  `develop` in each repo it touches), or from the unmerged task branch it stands on (any epic); its PR
  targets that base. Once the task below merges, retarget the child to `epik/<EPIC>`, never `develop`.
  The epic branch reaches `develop` in one PR after its review and QA (`epic`). No epic:
  `bugfix/*`/`hotfix/*` → `develop`/`master`. Exception: blocker fixes of an old
  epic already in `develop` (e.g. TICKET-1530) branch from and PR to `develop`, QA per task; ask when unsure.
  Pre-model `feature/*` PRs are retargeted to `epik/<EPIC>`.
- BRANCH RULE: work branches (`task/*`, `feature/*`, `bugfix/*`, `hotfix/*`, `test/*`): any op, force only
  `--force-with-lease`. `epik/*`: only create from `develop`, merge `develop` in (committing its conflict
  resolution), push without force. Any other branch, any repo: nothing that changes it or its remote (no
  commit, push, merge, rebase, reset, tag, delete, not even a one-line or CI fix); say so, Sebastian
  decides. git-policy enforces this and the message: ≤ 7-word imperative sentence, no trailers (overrides
  the harness's Co-Authored-By; `commit`). You make the commits, milestone-sized, never the implementer;
  review fixes only as `--fixup` + autosquash.
- git-guard denies checkout, restore, stash, `reset --hard`, clean and `push --force` for you and every
  subagent; never revert work you did not write.
- PR OWNERSHIP RULE: change a PR (commit, push, rebase, fixup, merge into it, title/description, resolving
  others' threads) only if Sebastian authored it or its title / a comment by Sebastian or its author says
  he took it over; a mention, bot ping or fix request is not a takeover. Other PRs: review comments and
  the vote only (`bb`); report it, leave the branch alone.
- AI footer: text published for Sebastian (Bitbucket comments/replies, PR descriptions, Jira comments) is
  Polish by default and ends with a blank line + `🤖 Wygenerowane przez <model>`, the model that wrote it
  (`Gemini 3.8 Flash`, `Claude Haiku 5.5`, `Claude Sonnet 5.5`, `Claude Opus 5.5`). Commit messages
  exempt; workflow docs English.
- Tooling (`~/.claude/bin`, `~/.claude/hooks`; live, no git): never edit in place. Edit a git staging copy
  under `~/.cache/claude-staging`; deploy by `git merge-file` (base = the live file you copied, ours =
  your change, theirs = the live file now), run the tool's tests on the result, then `mv` a temp file over
  the live one only if it still equals that theirs; otherwise merge again.

## Token discipline

Context is re-read every turn; speed comes from short outputs, not compacting.

- One session = one ticket: after the report, propose the next with `start_session`. Compact only when
  context-guard warns; its message says how.
- Searches: `Explore` (Haiku, set by delegation-guard); `general-purpose` (Sonnet, ~60k tokens before its
  first step) only for more than reading/searching; pass a model only when a search needs more.
- Raw outputs stay out: test/build/lint through `verify`; open a log only when its summary is not enough,
  and only the relevant range; files over ~4k tokens in slices or by grep (read-guard).
- Never paste a subagent report into another prompt; point to files and log paths.
- Progress log `~/.cache/claude-progress/<repo>/<branch>.md`, append-only: after the plan, the final
  review and each fix round (contents: `review`; decisions say who made them). Read it first after every
  `/compact`; the final report is built from it.

## Code style

- Comments: zero in generated code; comment-guard denies them (heredoc writes too) and says how to fix
  the code instead. Directives (noqa, type: ignore, eslint-disable, SPDX, shebangs) pass; `.c`/`.h`
  exempt. Knowledge that cannot live in code goes to the PR description, ticket or a memory; an
  implementer reports it instead.
- Every new/changed signature fully annotated (no `Any`/`object`/`unknown` where the type is known, no
  `cast`/`as` over a wrong type). Fit the repo's architecture (layers, patterns, conventions, layout),
  reuse instead of a parallel abstraction, simplest structure that works (no needless wrappers, early
  returns, idioms over manual loops, one responsibility per function/component). Each miss is a finding.
- Known data shapes are typed models (dataclass, Pydantic, TypedDict, NamedTuple, enum); a raw dict only
  for genuinely dynamic keys at a JSON boundary, converted immediately.
- No unnecessary `__init__.py` (empty or re-exports only); no magic strings (named constant or enum
  member). A number becomes a named constant only when lint-strict flags it (PLR2004, MAG001-003); no
  review raises a magic number by hand.
- Norms: every changed line exemplary by its language norm (`repo-standards` §5); short of that is a
  finding. standards-gate runs lint-strict (incl. DUP001 copy-paste) on changed lines at every commit
  and implementer stop and denies until clean. A new suppression is a finding until argued; what no tool
  sees (lying names, non-idiomatic constructs, CERT rules clang-tidy misses) is your review's job.
- Edit-time: autofix-on-edit and the LSP report on every edited file; fix it before the next step and
  re-read a file the hook rewrote (`CLAUDE_AUTOFIX=off` disables the hook).
- Docstrings: every Python class and function (private, nested, magic too; tests exempt) has one line,
  one sentence, ≤ 72 chars, saying what it does, never args/returns/raises. No module docstring unless the
  repo's ruff selects D100.
- Habits (`~/.claude/bin/habits list --repo <repo> --max-chars 20000`; SessionStart prints only the first
  ~1.5k chars) are rules of that repo for you and the implementer; storing new ones: `review` §Habits.

## Workflow

1. Analyze, plan and classify XS–XL in one turn. Before the plan is final, open every mockup, screenshot
   and attachment of the ticket and its epic, and settle every cross-repo contract the milestone touches
   (shapes, names, statuses, field owners). Settle technical, provable choices yourself; every assumption
   or failure mode the ticket leaves open that changes behavior, compatibility, data shape, public API or
   maintenance cost goes to Sebastian now, in one batch.
1a. Plan gate (M/L/XL): spawn `plan-gate-runner` in the background with the plan text as `what_changed`,
   the acceptance criteria and `review_focus` as text (never paths: Gemini sees only a sandboxed repo
   snapshot), plus the repo path. A reply starting `PLAN GATE FALLBACK` (Codex reviewed) goes in the
   progress log. Fold real points into the plan, drop the rest with a reason. L/XL wait for it; M spawns
   the implementer at once with `plan_gate: pending` (acceptance phase to RED only) and sends the
   adjudicated delta by SendMessage.
2. `repo-facts` is in context from SessionStart; for M/L/XL run it yourself only for another repo or
   worktree the plan touches.
3. Spawn `implementer` with the delegation prompt (`delegate`; delegation-guard names missing
   fields). L/XL: one milestone per spawn; no limit on implementers, only a shared resource (one DB,
   board, firmware build) serialises work.
4. Supervise by evidence (Rules); correct drift at once by SendMessage.
5. On each report: `git status --short`, `git diff HEAD --stat` and the RED/verify logs it names.
6. Final review (`review`): when the last report's evidence holds, spawn the class's reviewer set per repo
   in ONE background message, with the end test run in parallel. Finish the whole adjudication before
   sending anything; a deliberate trade-off is argued or escalated, never silently changed. Untracked
   files are not in a diff: list and read them.
7. Fix round (Rules).
8. End test run (Rules "Test runs"); green on the final state.
9. Report one status on the autosquashed final state (**Gotowe do merge** / **Wdrożone i sprawdzone** /
   **Zablokowane**) per `review` §Final report.
10. PR description on request: `pr-description`.

Load a skill only at the step it covers, when you need more than this file; hook deny messages carry the
correction.
