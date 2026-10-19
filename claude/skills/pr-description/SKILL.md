---
name: pr-description
description: Gotowy do wklejenia opis PR na Bitbucket dla skończonego zadania. Użyj, gdy Sebastian prosi o opis PR, „przygotuj PR” albo pull request description.
---

Trigger: the task is finished and the user asks for a PR description. Return a ready-to-paste,
Bitbucket-flavoured Markdown block — title first, then description — with no commentary around it
other than the target-branch line. A request for the PR description means the work is already
verified — do not re-check, re-review or re-test the code. Read the diff only to describe it accurately.

## Title

Format: `[ID-TASKA] Krótki opis zmian` — ID from Jira (project prefix + number), short description in Polish.
Multi PR (a set of related PRs realizing one common task): `[MULTI][ID-TASKA] Krótki opis zmian`.
Take the Jira ID from the branch name when the user did not give it; if it cannot be derived, ask for it.
Right under the title state the target branch: `develop` for normal tasks, `master` for hotfixes.
The PR is opened as Draft right after the first push and stays Draft until the work is functionally
complete — except in the `/task` flow, where the PR is created only after both test levels are green,
so it goes straight to ready-for-review.

## Description

The orchestrator does not write it itself: spawn `writer` with the diff range, the repo path, the Jira
ID, the confirmed findings with their test names and this skill as the template; check every claim in
the draft against the code, then publish. Write it in Polish, in full sentences, concrete and concise. Bitbucket renders Markdown — use `##`
headings. The description always opens with the line `🤖 Wygenerowane przez Claude` and a blank line, before the first
section, so readers know it was written by AI. Include only the sections that apply; drop the optional ones instead of writing "N/A" or
leaving them empty. Sections, in this order:

- `## Powiązane PR` — Multi PR only: links to all the other PRs in the group.
- `## Co zostało zmienione` — the real change in the code and the effect it introduces. Not a list of
  commits, not a list of changed files.
- `## Dlaczego` — the business or technical goal; the reviewer must understand why this change is needed.
- `## Jak` — key implementation decisions, approach, libraries, migrations, trade-offs or non-standard
  solutions, and the places that need the reviewer's attention.
- `## Scope zmian` — optional: only when the PR goes beyond the ticket's scope. Defines what QA retests.
- `## Screenshots` — required when the change touches the UI. **Capture AND attach them yourself; a
  placeholder is a last resort, not the default.** The whole loop is automatable — see "Screenshots end
  to end" below. Before/after whenever the change alters something that already existed. "The change
  does not touch the visual layer" is a claim to verify by looking, not an excuse to skip the section:
  a new field, a changed control state (enabled/disabled) or a different rendered value all count as UI.
- `## Scenariusze QA` — when the `qa` skill ran: the summary line, the tested SHAs and the scenario table
  from `~/.cache/claude-qa/runs/<ID>/report.md` (scenario, why it is hard, test form, result). Every FAIL
  in it is either fixed and re-run or marked "zastany" with a pointer to `## Dodatkowy kontekst`.
- `## Dodatkowy kontekst` — known limitations, tech debt, alternatives, risks, decisions needing
  conscious acceptance, topics for outside this PR, actions required for the change to work (e.g. migration).

## Screenshots end to end

Capture to disk, upload to the repo, embed in the description — no step needs the user, for any screen
reachable without signing in.

**1. Capture.** Bring the app up (`bun run dev --port 3100`, detached with `setsid nohup ... &`) and
shoot each route with the playwright chromium headless shell already on the machine:

    ~/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell \
      --headless --disable-gpu --no-sandbox --hide-scrollbars \
      --window-size=1440,900 --virtual-time-budget=8000 \
      --screenshot=$HOME/Downloads/<ticket>/<nn>-<name>.png http://localhost:3100<route>

`--virtual-time-budget` is not optional: without it the shot lands before React mounts and you get a
blank rectangle. Restart the dev server after any bulk file rename or Vite keeps serving the old module
graph. **Read every PNG back before using it** — identical file sizes across shots mean several routes
resolved to the same page, which is how a wrong URL hides (take routes from the route tree, not from
`paths.ts`, which can be stale).

**2. Upload.** The repo Downloads endpoint takes a local file and is reachable with the same credentials
as every other Bitbucket call:

    curl -u "$(cat ~/.config/bitbucket/credentials)" \
      -X POST "https://api.bitbucket.org/2.0/repositories/acme/<repo>/downloads" \
      -F "files=@/path/to/sw<NNNN>-<name>.png"

Expect HTTP 201. Name files `sw<NNNN>-<name>.png` so they are identifiable among the repo's downloads.
Verify each upload by fetching it back from `api.bitbucket.org/.../downloads/<file>` and checking the
byte size and `file -b` output; the `bitbucket.org/...` web URL returns 401 to app-password auth, so it
proves nothing either way.

**3. Embed.** In the description, reference the web URL:

    ![sw<NNNN>-<name>.png](https://bitbucket.org/acme/<repo>/downloads/sw<NNNN>-<name>.png)

Give each image a one-line caption saying what it demonstrates, and point at the screenshot that shows
a fix wherever one does. Back the old description up before a `PUT`, and send the title with it.

**Behind the login is still the user's step.** The JWT is an HttpOnly cookie, so a session cannot be
carried into the headless shell, and there is no headed Chrome on this machine to share a profile with
it (snap Firefox is no substitute — its `--screenshot` has no `--virtual-time-budget` and fires before
the SPA renders). For dashboard screens, ask for the single sign-in from the `browser-check-login-rule`
memory, drive the Browser pane, and say in the section itself which screens are missing and why.

Template to emit:

```
[ABC-123] Krótki opis zmian
Target branch: develop

🤖 Wygenerowane przez Claude

## Co zostało zmienione
...

## Dlaczego
...

## Jak
...
```
