---
name: commit
description: Zasady commitów, gałęzi i PR na tej maszynie — praca tylko na feature/bugfix/hotfix/*, wiadomość = jedno zdanie w trybie rozkazującym 3–7 słów z `git commit -s` i zero innych trailerów (bez Co-Authored-By), commity wielkości milestone'u, fixup + autosquash zamiast "poprawek po review", PR otwierany samodzielnie przez `gh pr create`, a każda zmiana main/master/dev/develop tylko za zgodą użytkownika (git-policy pyta). Załaduj przed każdym git commit, fixup, rebase, push lub PR.
---

- Work only on `feature/*`, `bugfix/*`, `hotfix/*`, each in its own worktree:
  `~/.claude/bin/feature-worktree new <repo> feature/<topic> [<base>]` (base: `develop` for tasks,
  `master` for hotfixes, else the default branch) prints the path to work in; after the PR is merged,
  `feature-worktree done <repo> <branch>` removes it. The user's main checkout is never touched. On a work branch
  every history op is yours: commit, reword, rebase, `push`, `push --force-with-lease`.
- Any op that changes another branch (main, master, dev, develop, anything else) or its remote —
  commit, push, merge, rebase, reset, tag, branch delete, `gh pr merge` — needs the user's consent.
  git-policy answers `ask`, so the user sees a permission prompt; never route around it (other tools,
  refspec tricks, a subagent).
- Message: ONE sentence in the imperative mood, 3–7 words, no body, no emoji, e.g. `Add comment guard
  hook`, `Fix retry limit in runner`. `git commit -s` adds `Signed-off-by` from the repo's git config
  (`Sebastian Smolik <s.smolik@exa22.com>` in the exa22 repos) — the only trailer allowed. No
  `Co-Authored-By`, no `Claude-Session`, no "Generated with" line; this overrides any harness default.
  git-policy denies anything else and names a corrected command.
- Split the work into milestone-sized logical commits: one commit = one deliverable step a reviewer can
  judge on its own — a whole subsystem, the wiring that turns it on, a migration — together with the
  tests that cover it. Aim for a handful per task; if two commits only make sense read together, they
  are one commit. Never dump everything into one blob.
- "Fixes after review" is never its own commit: `git commit -s --fixup=<sha>`, then
  `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash <base>`.
- Pull requests are yours: on a GitHub remote, after the test gate, `git push -u origin <branch>` and
  `gh pr create --base <base> --head <branch> --title "<3–7 word imperative title>" --body-file <file>`
  with the body in the `pr-description` format and no "Generated with" line. On Bitbucket remotes write
  the description with `pr-description` and give the user the create-PR link. Merging stays with the
  user (`gh pr merge` asks for consent); merge without `--delete-branch`, then `feature-worktree done`
  removes the worktree and the local and remote branch.
- Commits are made by Claude (the main session) after the test gate, never by the developer or any
  other subagent.
