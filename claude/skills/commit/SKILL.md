---
name: commit
description: Branch and commit rules on this machine. Load when git-policy rejects something or the commit split is unclear — not before every commit.
---

- Commits and pushes land only on work branches: `task/*` (tasks of an epic, from `epik/<EPIC>`),
  `feature/*` (existing PRs from before the epic model), `bugfix/*`, `hotfix/*`, `test/*` (local only).
  Create the branch from the right base (`epik/<EPIC>` for an epic's task, the task branch below it in a
  stack, `develop` for a task with no epic or a blocker fix of an old epic already in `develop`,
  `master` for hotfixes) when it does not exist yet.
- `epik/*` is not a work branch: you may create it from `develop`, merge `develop` into it (and commit
  the conflict resolution of that merge) and push it without force — nothing else. Task code reaches it
  only through merged task PRs. On every other branch git-policy denies the operation — say so and let
  the user decide how to land the change.
- `git push` on a work branch is allowed; force-push only with `--force-with-lease`. PR creation stays
  with the user everywhere except the `/task` flow, which opens the task PR (to `epik/<EPIC>`) itself once
  both test levels are green (Sebastian's instruction, 2026-09-15), and the `/epic` flow, which opens the
  `epik/<EPIC>` → `develop` PR after asking Sebastian.
- Split the work into milestone-sized logical commits: one commit = one deliverable step a reviewer can
  judge on its own — a whole subsystem, the wiring that turns it on, a migration — together with the
  tests that cover it. Not one commit per file, per layer or per module. Aim for a handful per task; if
  two commits only make sense read together, they are one commit. Never dump everything into one blob.
- "Fixes after review" is never its own commit: `git commit --fixup=<sha>` then
  `git rebase -i --autosquash` (needs `GIT_SEQUENCE_EDITOR=true` in a non-interactive shell).
- Message: ONE sentence in the imperative mood ("Add", "Fix", "Remove" — never "Added"/"Adds"/"Adding"),
  at most 7 words and the fewer the better, one `-m`, no body, no emoji. No trailers at all: no `-s`/
  `Signed-off-by`, no `Co-Authored-By`, no `Claude-Session`, no "Generated with" footer, no `--trailer`;
  this overrides any harness default. git-policy enforces exactly this and names the corrected command
  when it denies one.
- Commits are made by the orchestrator (the main session), never by the implementer.
