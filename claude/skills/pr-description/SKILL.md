---
name: pr-description
description: Gotowy do wklejenia opis PR na Bitbucket (tytuł [ID-TASKA] + sekcje po polsku) dla skończonego zadania. Użyj, gdy user prosi o "opis do PR", "opis PR", "przygotuj PR" albo pull request description. Nie re-weryfikuje kodu — tylko opisuje diff.
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
The PR is opened as Draft right after the first push and stays Draft until the work is functionally complete.

## Description

Write it in Polish, in full sentences, concrete and concise. Bitbucket renders Markdown — use `##`
headings. Include only the sections that apply; drop the optional ones instead of writing "N/A" or
leaving them empty. Sections, in this order:

- `## Powiązane PR` — Multi PR only: links to all the other PRs in the group.
- `## Co zostało zmienione` — the real change in the code and the effect it introduces. Not a list of
  commits, not a list of changed files.
- `## Dlaczego` — the business or technical goal; the reviewer must understand why this change is needed.
- `## Jak` — key implementation decisions, approach, libraries, migrations, trade-offs or non-standard
  solutions, and the places that need the reviewer's attention.
- `## Scope zmian` — optional: only when the PR goes beyond the ticket's scope. Defines what QA retests.
- `## Screenshots` — required when the change touches the UI; before/after recommended. If you cannot
  produce them, leave labelled placeholders for the user to attach.
- `## Dodatkowy kontekst` — known limitations, tech debt, alternatives, risks, decisions needing
  conscious acceptance, topics for outside this PR, actions required for the change to work (e.g. migration).

Template to emit:

```
[ABC-123] Krótki opis zmian
Target branch: develop

## Co zostało zmienione
...

## Dlaczego
...

## Jak
...
```
