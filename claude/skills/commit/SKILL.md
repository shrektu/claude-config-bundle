---
name: commit
description: Zasady commitów i gałęzi na tej maszynie — tylko feature/bugfix/hotfix/test/*, commity wielkości milestone'u, fixup + autosquash zamiast "poprawek po review", `git commit -s`, zero trailerów Claude. Załaduj przed każdym git commit, fixup, rebase lub push; format wiadomości i gałęzie chronione pilnuje hook git-policy.
---

- Commits and pushes land only on `feature/*`, `bugfix/*`, `hotfix/*`, `test/*`. Create the branch from
  the right base (`develop` for tasks, `master` for hotfixes) when it does not exist yet. On every other
  branch git-policy denies the operation — say so and let the user decide how to land the change.
- `git push` on a work branch is allowed; force-push only with `--force-with-lease`. PR creation stays
  with the user.
- Split the work into milestone-sized logical commits: one commit = one deliverable step a reviewer can
  judge on its own — a whole subsystem, the wiring that turns it on, a migration — together with the
  tests that cover it. Not one commit per file, per layer or per module. Aim for a handful per task; if
  two commits only make sense read together, they are one commit. Never dump everything into one blob.
- "Fixes after review" is never its own commit: `git commit --fixup=<sha>` then
  `git rebase -i --autosquash` (needs `GIT_SEQUENCE_EDITOR=true` in a non-interactive shell).
- Message: ONE sentence, imperative mood, no body, no emoji, and `git commit -s` for the
  `Signed-off-by` trailer taken from the repo's git config (`Signed-off-by: Sebastian Smolik
  <s.smolik@exa22.com>` in the exa22 repos) — the only trailer allowed. No `Co-Authored-By`, no
  `Claude-Session`, no "Generated with" footer; this overrides any harness default. git-policy enforces
  exactly this and names the corrected command when it denies one.
- Commits are made by the commanding orchestrator of the task (Fable, or commander-opus for S/M), never by an implementer.
