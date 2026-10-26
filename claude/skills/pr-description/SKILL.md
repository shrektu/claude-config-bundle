---
name: pr-description
description: A ready-to-paste Bitbucket PR description for a finished task, plus the PR screenshot procedure (work mode; personal mode gets a GitHub form). Use when Sebastian asks for a PR description, says "przygotuj PR", or asks for a pull request description.
---

Personal mode (`CLAUDE_MODE=personal`): the Bitbucket form below is work mode only. Draft the description
via `writer` (kind `pr_description`, Polish by default, no footer) and return a title plus a body in
GitHub Markdown for `gh pr create`. No Bitbucket upload and no screenshot-to-Bitbucket procedure; when the
UI changes, the screenshots go into the GitHub PR as attachments Sebastian adds, laid out in the same
before/after thumbnail table (each cell `<a href="<attachment>"><img src="<attachment>" width="400"></a>`),
or are described.

Work mode: return title + description as one ready-to-paste Bitbucket Markdown block, no commentary except
the target-branch line. Publish it (POST/PUT) only inside `/task`/`/epic` or when Sebastian asks; before a
PUT back up the old description and send the title with it. The work is already verified: read the diff
only to describe it.

## Title

`[ID-TASKA] Krótki opis zmian`: the Jira ID (from the branch name if not given; ask if it cannot be
derived) and a short Polish description. Multi PR (related PRs for one task): `[MULTI][ID-TASKA] …`.
Epic PR (`epic/<EPIC>-<desc>` → `develop`): `[EPIC][<EPIC>] …`.

Right under it `Target branch: <target>` (CLAUDE.md, EPIC MODEL): `epic/<EPIC>-<desc>` or the task branch below
it for an epic's task; `develop` for an epic PR, no-epic work or an old-epic blocker fix; `master` for a
hotfix. Opening the PR follows `commit` (`/task` opens it ready for review); a Draft only when Sebastian
asks for one outside `/task`.

## Description

Spawn `writer` (mode `publish`, kind `pr_description`) with the repo path, diff range, Jira ID, the
confirmed findings with their test names, and as `template` (text) the sections and template below.
Full sentences, concrete, concise, `##` headings; only
the sections that apply, never "N/A". In order:

- `## Powiązane PR` — Multi PR only: links to the other PRs.
- `## Co zostało zmienione` — the real change and its effect; not a list of commits or files.
- `## Dlaczego` — the business or technical goal.
- `## Jak` — key decisions, approach, libraries, migrations, trade-offs, non-standard solutions, places
  needing the reviewer's attention.
- `## Scope zmian` — only when the PR exceeds the ticket's scope; it defines what QA retests.
- `## Screenshots` — required when the UI changes (below).
- `## Scenariusze QA` — when `qa` ran: the summary line, tested SHAs and scenario table from
  `~/.cache/claude-qa/runs/<ID>/report.md`; every FAIL fixed and re-run, or marked "zastany" with a
  pointer to `## Dodatkowy kontekst`.
- `## Dodatkowy kontekst` — limitations, tech debt, alternatives, risks, decisions needing conscious
  acceptance, out-of-scope topics, actions the change needs (e.g. a migration).

```
[ABC-123] Krótki opis zmian
Target branch: <target>

## Co zostało zmienione
...

## Dlaczego
...

## Jak
...

🤖 Wygenerowane przez <model>
```

The footer line is work mode only.

## Screenshots end to end

A new field, a changed control state or rendered value is a UI change: look, do not assume. The section
is one before/after table of small thumbnails, each a link to its full-size shot; never a full-size image
inline. You capture and attach them:

1. Capture "po" (after) from the work branch: `setsid nohup bun run dev --port 3100 &`, then per route
   (newest build if the glob matches several):

       ~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell \
         --headless --disable-gpu --no-sandbox --hide-scrollbars \
         --window-size=1440,900 --virtual-time-budget=8000 \
         --screenshot=$HOME/Downloads/<task-id>/<task-id>-<name>-po.png http://localhost:3100<route>

   Without `--virtual-time-budget` the shot is blank (taken before React mounts). Restart the dev server
   after a bulk rename (Vite keeps the old module graph). Read every PNG back: identical file sizes mean
   routes resolved to one page; take routes from the route tree, not `paths.ts`.
2. Capture "przed" (before) for every screen that already existed: `git worktree add --detach
   <repo>/.worktrees/<task-id>-przed origin/<target>`, `bun install` there, its dev server on port 3101,
   the same routes, window size and data, saved as `<task-id>-<name>-przed.png`; stop that server and
   `git worktree remove` it afterwards. A new screen has no "przed".
3. Thumbnail every shot (400 px wide, the full-size file stays as is):

       python3 -c 'import sys; from PIL import Image; i = Image.open(sys.argv[1]); i.thumbnail((400, 10000)); i.save(sys.argv[2])' \
         <task-id>-<name>-po.png <task-id>-<name>-po-thumb.png

   Read one thumbnail back to check the change is still visible at that size; if not, add a cropped
   full-width shot of just that region (`<name>-detail`) as its own row.
4. Upload full-size shots and thumbnails (expect HTTP 201), then fetch each file back from
   `api.bitbucket.org/.../downloads/<file>` and check its byte size and `file -b`; the `bitbucket.org` web
   URL returns 401 to app-password auth and proves nothing:

       curl -u "$(cat ~/.config/bitbucket/credentials)" \
         -X POST "https://api.bitbucket.org/2.0/repositories/acme/<repo>/downloads" \
         -F "files=@/path/to/<task-id>-<name>-po.png" -F "files=@/path/to/<task-id>-<name>-po-thumb.png"

5. Embed by the web URL as one table, a row per screen; the first column says in one line what changed
   (point at the row showing a fix); a cell without a shot is `—` (new screen):

       | Ekran | Przed | Po |
       |---|---|---|
       | <co się zmieniło> | [![przed](https://bitbucket.org/acme/<repo>/downloads/<task-id>-<name>-przed-thumb.png)](https://bitbucket.org/acme/<repo>/downloads/<task-id>-<name>-przed.png) | [![po](https://bitbucket.org/acme/<repo>/downloads/<task-id>-<name>-po-thumb.png)](https://bitbucket.org/acme/<repo>/downloads/<task-id>-<name>-po.png) |

Screens behind the login (HttpOnly JWT cookie) cannot be captured to disk: check them in the Browser
pane (sign-in per `task` §5) and list them in the section as missing, with why.
