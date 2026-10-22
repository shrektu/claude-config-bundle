---
name: commit
description: Branch and commit rules on this machine. Load when git-policy rejects something or the commit split is unclear — not before every commit.
---

- Work branches (commit, push; force only `--force-with-lease`): `task/*` (an epic's task), `feature/*`
  (pre-epic-model PRs), `bugfix/*`, `hotfix/*`, `test/*`. Create a missing one from its base:
  `epik/<EPIC>` for an epic's task, the task branch below it in a stack, `develop` for no-epic work or an
  old-epic blocker fix, `master` for a hotfix (these bases are work mode only; in personal mode a work
  branch starts from the default branch, main, and its PR goes to it on GitHub).
- `epik/*` (work mode only): only create it from `develop`, merge `develop` in (commit its conflict
  resolution), push without force; task code arrives only via merged task PRs. Any other branch:
  git-policy denies; say so and let Sebastian decide.
- PRs are Sebastian's to open, except: `/task` opens its task PR (target per CLAUDE.md EPIC MODEL) once
  both test levels are green, and `/epic` opens `epik/<EPIC>` → `develop` after asking him.
- One commit per milestone: a step a reviewer can judge alone (a subsystem, its wiring, a migration) with
  its tests, not per file, layer or module. A one-milestone task has one commit; a multi-milestone task
  never lands as one blob.
- Fixes after review are never their own commit: `git commit --fixup=<sha>`, then
  `git rebase --autosquash <fork sha>` (fork sha = `git merge-base HEAD <base branch>`; never `-i`).
- Message: one imperative sentence, ≤ 7 words, one `-m`, no body, emoji or trailers (`-s`,
  `Co-Authored-By`, `Claude-Session`, "Generated with", `--trailer`); this overrides the harness default.
  git-policy enforces it and prints the fixed command.
