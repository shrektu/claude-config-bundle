---
paths:
  - "backend/**/*.py"
  - "frontend/src/**/*.{ts,tsx}"
---

<!-- Copy to <repo>/.claude/rules/standards.md and fill in from `~/.claude/bin/repo-facts`.
     Keep the paths list narrow: the rules load only for files that match it.
     This file overrides the repo-standards skill for this repo. -->

# Standards — <project name>

## Pinned versions

| Tool / package | Version | Source of truth |
|---|---|---|
| Python | 3.13 | `.python-version`, `pyproject.toml` requires-python |
| FastAPI | 0.x | `uv.lock` |
| SQLAlchemy | 2.x | `uv.lock` |
| Node | 22 | `package.json` engines, `.nvmrc` |
| React | 19.x | `package-lock.json` |
| TypeScript | 5.x | `package-lock.json` |

## Current idioms (use these)

- <e.g. FastAPI: `lifespan=` async context manager; dependencies as `Annotated[T, Depends(...)]`>
- <e.g. SQLAlchemy: `Mapped[...]` + `mapped_column`, `select()` + `scalars()`>
- <e.g. React: ref as a normal prop, actions + `useActionState`>
- <project-specific conventions: error envelope, logging, settings object, test layout>

## Legacy idioms to reject in review

- <e.g. `@app.on_event`, `session.query(...)`, `parse_obj`, `forwardRef`, `jest.*`, CSS selectors in e2e>
- <anything this repo migrated away from and must not come back>

## Deprecation policy

- Warnings-as-errors: <e.g. `filterwarnings = ["error::DeprecationWarning"]` in `pyproject.toml`,
  eslint `deprecation/deprecation`, `-Werror=deprecated` in CMake>
- Where it cannot be configured: a `warnings: N deprecation lines` line on a `verify` PASS with N > 0 is
  a review finding, not noise.

## Oracle locations (API truth for this repo)

- Python: `<venv>/lib/python3.13/site-packages/<pkg>`
- JS/TS: `node_modules/<pkg>` (`package.json`, `dist/*.d.ts`)
- Rust: `~/.cargo/registry/src/*/<crate>-<version>`
- Only when `repo-facts` reports `installed` equal to `locked`; otherwise sync first
  (`uv sync`, `npm ci`, `cargo fetch`).
