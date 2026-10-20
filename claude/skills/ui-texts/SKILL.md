---
name: ui-texts
description: UI texts and translations through Gemini Flash (agy-worker). Load when you write or translate UI texts, labels, messages, i18n keys or locale files (en/pl etc.), also when Sebastian asks only to "translate" a new key.
---

## Steps

1. Find the repo's locale files (`locales/`, `i18n/`, `*.json` with language keys) and the `i18n:check`
   script in `package.json` (remember the directory that holds that `package.json`).
2. Collect the keys to write or translate: new and changed ones from the diff or a list from Sebastian.
   UI parameters stay as `{{param}}` (habit H001) — the text gets a placeholder, not a number.
   Plural forms: the target language has its own CLDR categories (pl: `_one`, `_few`, `_many`, `_other`;
   the list is in the `i18n:check` configuration, e.g. `plurals` in `i18n-check.config.json`). In `entries`
   put the target keys of every category with the source `_one`/`_other`, and in `context` describe in
   words which number each form concerns, without number ranges (e.g. "keys _one/_few/_many/_other are
   the Polish plural categories of the same sentence") — numbers in `context` make Flash try to run
   commands, and then the tool returns `AGY-UNAVAILABLE`.
3. Glossary: the project's dictionary file, if there is one (look for `glossary`, `slownik`, `terminology`,
   `nomenklatura`); otherwise collect the existing source→target pairs from the locale files of the same
   namespace (at most ~200) and pass them as the glossary text.
4. Call `mcp__agy-worker__agy_translate` (`project_path`, `entries`, `source_lang`, `target_lang`,
   `glossary`, `context`) with the model `gemini-3.8-flash-medium`. Never the Argon model — the tool rejects it.
5. A response starting with `AGY-UNAVAILABLE` → stop and tell Sebastian the reason
   (a repo outside the allowlist → he can add it to `~/.claude/mcp/agy-worker/allowed-remotes.txt`). Do not
   translate yourself as a silent substitute.
6. Resolve every entry in `problems`: request those keys again or fix the placeholders.
7. Write the translations into the locale files, keeping the key order and the file's formatting.
8. Run the repo's `i18n:check`:
   `~/.claude/bin/verify --repo <repo> -- 'cd <directory with package.json> && <bun|npm> run i18n:check'`
   (package manager per the lockfile: `bun.lock` → bun).

## Optional nomenclature review (redakcja.py + ui-writer `terms`)

At Sebastian's request or for Polish texts that reach customers:

1. Read `~/claude-skills/_shared/references/jezyk-acme.md` (in slices).
2. Save the translated texts to a file in the scratchpad, each as a separate paragraph (a blank line
   between texts — otherwise `redakcja.py` counts adjacent lines as one paragraph).
3. Run `python3 ~/claude-skills/_shared/redakcja.py --lang pl <file>` (`--lang en` for English);
   exit code 0 = clean, 1 = warnings, one per line: `file: problem`.
4. Spawn `ui-writer` in `terms` mode (Sonnet) with the strings, the glossary, the guide path and the
   `redakcja.py` warnings: it checks the nomenclature against the glossary and the guide and returns
   corrected strings with one reason each. Apply its corrections, then repeat `i18n:check`.

`~/claude-skills` is a colleague's repo — read-only, never edit it.
