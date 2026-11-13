---
name: pr-description
description: A ready-to-paste Bitbucket PR description for a finished task, plus the PR screenshot procedure (work mode; personal mode gets a GitHub form). Use when Sebastian asks for a PR description, says "przygotuj PR", or asks for a pull request description.
---

Personal mode (`CLAUDE_MODE=personal`): the Bitbucket form below is work mode only. Draft the description
via `writer` (kind `pr_description`, Polish by default, no footer) and return a title plus a body in
GitHub Markdown for `gh pr create`. No Bitbucket upload and no screenshot-to-Bitbucket procedure; when the
UI changes, the screenshots go into the GitHub PR as attachments Sebastian adds, laid out in the same
`| przed | po | co się zmieniło |` table of full-size images (each cell `![<alt>](<attachment>)`), or are
described.

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
- `## Schematy` — when a diagram explains the change better than prose (architecture, sequence, flow, CI;
  mux-sim#1, fleet-management-service#20): exported PNGs hosted like screenshots, one caption sentence
  above each. Non-UI evidence (DB tables, Grafana, simulator console, test output) goes in only when the
  result is the point, under the section it proves.
- `## Scenariusze QA` — when `qa` ran: the summary line, tested SHAs and scenario table from
  `~/.cache/claude-qa/runs/<ID>/report.md`; every FAIL fixed and re-run, or marked "zastany" with a
  pointer to `## Dodatkowy kontekst`.
- `## Dodatkowy kontekst` — limitations, tech debt, alternatives, risks, decisions needing conscious
  acceptance, out-of-scope topics, actions the change needs (e.g. a migration).
- `## Wdrożenie (DevOps)` — task and epic PRs, whenever the change needs anything on the Kubernetes side
  (new or changed env var, secret, ConfigMap, service/image, port, ingress, CronJob, resources, a
  migration or rollout order). We never open a PR to Kubernetes; DevOps does it. First the disclaimer,
  then numbered steps, one action per line: what, where (service, environment), the exact name and
  value (secrets: name and source only, never the value), the order, and how to check it worked.
  Simple words, no background (that belongs in `## Jak`).

```
## Wdrożenie (DevOps)
> ⚠️ Ta zmiana wymaga zmian w Kubernetes. Celowo nie ma PR-a do repozytorium Kubernetes — wdrożenie
> po stronie DevOps.

1. `<serwis>`: dodać zmienną `<NAZWA>=<wartość>` (wszystkie środowiska).
2. ...
3. Sprawdzenie: `<co powinno się pokazać / komenda>`.
```

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
is one before/after table of full-size images shown inline, with the markup of cloud-platform#96 (table,
alt texts, columns) but the hosting of step 4; never thumbnails, never a link to a file instead of the
image. Reviewers ask for large, legible shots (cloud-platform#217). You capture and attach them:

1. Capture "po" (after) from the work branch: `setsid nohup bun run dev --port 3100 &`, then per route
   (newest build if the glob matches several):

       ~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell \
         --headless --disable-gpu --no-sandbox --hide-scrollbars \
         --window-size=1440,900 --virtual-time-budget=8000 \
         --screenshot=$HOME/Downloads/<task-id>/<task-id>-<name>-po.png http://localhost:3100<route>

   Window size per repo: panel (cloud-platform, web-ui) `1440,900`; kiosk (kiosk-ui,
   service-menu-ui) the full portrait screen `1080,1920`, plus `720,2560` when the change
   touches DEVBOARD layout; the device goes into the file name and alt (`<name>-devboard-720x2560-po.png`).
   Without `--virtual-time-budget` the shot is blank (taken before React mounts). Restart the dev server
   after a bulk rename (Vite keeps the old module graph). Read every PNG back: identical file sizes mean
   routes resolved to one page; take routes from the route tree, not `paths.ts`.
2. Capture "przed" (before) for every screen that already existed: `git worktree add --detach
   <repo>/.worktrees/<task-id>-przed origin/<target>`, `bun install` there, its dev server on port 3101,
   the same routes, window size and data, saved as `<task-id>-<name>-przed.png`; stop that server and
   `git worktree remove` it afterwards. A new screen has no "przed".
3. Read each full-size shot back: the change must be legible in it. When it sits in a small part of the
   window (a side panel, one control), crop that region at full resolution (`<name>-detail`) and give it
   its own row; never downscale. An interaction a still cannot show (a flow, an animation, a simulator
   run) gets a GIF hosted the same way, under ~5 MB, one line above it saying what to watch.
4. Upload the full-size shots (expect HTTP 201), then fetch each file back from
   `api.bitbucket.org/.../downloads/<file>` and check its byte size and `file -b`; the `bitbucket.org` web
   URL returns 401 to app-password auth and proves nothing. PR attachments (what #96 uses) go through
   Bitbucket's internal API, which refuses app-password auth (403), so the repo downloads host the files:

       curl -u "$(cat ~/.config/bitbucket/credentials)" \
         -X POST "https://api.bitbucket.org/2.0/repositories/acme/<repo>/downloads" \
         -F "files=@/path/to/<task-id>-<name>-przed.png" -F "files=@/path/to/<task-id>-<name>-po.png"

5. Embed the images directly by the web URL as one table under `Zrzuty przed / po:`, a row per change;
   the last column says in one line what changed (point at the row showing a fix), each alt text is
   that line plus ` — przed` / ` — po`, and a cell without a shot is `—` (new screen). When a whole
   column is `—`, one sentence above the table says why (new screen, state not reproducible). The final
   description holds no `null`, local-path or `/tmp` image URL:

       | przed | po | co się zmieniło |
       | --- | --- | --- |
       | ![<co się zmieniło> — przed](https://bitbucket.org/acme/<repo>/downloads/<task-id>-<name>-przed.png) | ![<co się zmieniło> — po](https://bitbucket.org/acme/<repo>/downloads/<task-id>-<name>-po.png) | <co się zmieniło> |

Screens behind the login (HttpOnly JWT cookie) cannot be captured to disk: check them in the Browser
pane (sign-in per `task` §5) and list them in the section as missing, with why.
