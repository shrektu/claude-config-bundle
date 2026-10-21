---
name: ui-texts
description: UI texts (ui-writer) and translations (Gemini Flash via agy-worker). Load when you write or translate UI texts, labels, messages, i18n keys or locale files, also when Sebastian asks only to "translate" a new key.
---

1. Find the locale files (`locales/`, `i18n/`, `*.json` with language keys) and the `i18n:check` script
   in `package.json` (note that directory).
2. Glossary: the project's dictionary file (`glossary`, `slownik`, `terminology`, `nomenklatura`), else up
   to ~200 existing source→target pairs from the same namespace's locale files, as text.
3. New source text: spawn `ui-writer` mode `publish` (kind `ui_message`) once for all new strings, with the
   repo path, the facts and the glossary; its output is the source text.
4. Keys to translate: new and changed ones from the diff or Sebastian's list. Parameters stay `{{param}}`,
   never a number. Plurals: send the target key of every CLDR category of the target language (pl: `_one`,
   `_few`, `_many`, `_other`; the list is in the `i18n:check` config, e.g. `plurals`) with the source
   `_one`/`_other` text; describe the forms in `context` in words, never with numbers (they make Flash run
   commands → `AGY-UNAVAILABLE`).
5. Call `mcp__agy-worker__agy_translate` (`project_path`, `entries`, `source_lang`, `target_lang`,
   `glossary`, `context`) with its default model.
6. `AGY-UNAVAILABLE` → stop and tell Sebastian why (repo off the allowlist → he can add it to
   `~/.claude/mcp/agy-worker/allowed-remotes.txt`); never translate yourself instead.
7. Resolve every `problems` entry: re-request those keys or fix the placeholders.
8. Nomenclature review of Polish texts (others on Sebastian's request): spawn `ui-writer` mode `terms`
   with the strings and the glossary; apply its corrections.
9. Write the texts into the locale files, keeping key order and formatting, then run
   `~/.claude/bin/verify --repo <repo> -- 'cd <package.json dir> && <bun|npm> run i18n:check'` (bun when
   `bun.lock` exists).

`~/claude-skills` is a colleague's repo: read-only.
