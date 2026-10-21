---
name: repo-standards
description: Idioms for the versions pinned in the repo (per-stack tables in references/) and the language norms lint-strict checks. Preloaded in implementer; load when reviewing idioms or on deprecation warnings.
---

## 1. Versions and the API oracle

`~/.claude/bin/repo-facts` runs first. An entry with `installed == locked` (Rust: listed under
`cargo locked+fetched`) makes the installed source the API oracle: JS/TS `node_modules/<pkg>`
(`package.json`, `dist/*.d.ts`, `types/`), Python the venv's `site-packages/<pkg>`, Rust
`~/.cargo/registry/src/<registry-dir>/<crate>-<version>`, a Rust `path=<dir>` dependency at `<dir>`.
A `FLAG:` entry is no oracle: `MISMATCH`, `not installed`, `not fetched` → sync (`uv sync`, `npm ci`,
`cargo fetch`) and re-run repo-facts; `git-source`, `unverified`, `ambiguous`, `not in Cargo.lock` →
read the source the build actually uses, never the registry cache. Grep signatures, exports and
deprecation notes there; never code an API from memory.

## 2. Idioms

Before the first edit read the table for your stack:
`~/.claude/skills/repo-standards/references/python.md`, `ts-react.md`, or `native.md` (C/CMake,
PlatformIO, Rust, Go).

- Use a newer idiom in new or changed code when the repo's floor allows it, never above it. Raising a
  floor (`requires-python`, tsconfig `lib`/`target`, `engines`, `react`) is the orchestrator's call.
  Do not rewrite existing code outside the task.
- Floors. Python: the lower bound of `requires-python`, else `.python-version` (lint-strict passes it
  to ruff as `--target-version`). TS/JS: the feature type-checks under the app's tsconfig `lib`
  (tsconfig.app.json) and exists in the oldest runtime (Node in `engines`/`.nvmrc`; frontend:
  browserslist or the target device browser); `lib` polyfills nothing; Baseline "newly available" is
  not "widely available". React: the lower bound of `react` in package.json.

## 3. Who checks what

- Hook-checked by lint-strict at the floor (fix what it reports, do not re-review by hand): ruff
  UP040/046/047/043/035/017/041, B012, B911/B912, DTZ003; mypy `explicit-override` (≥ 3.12); VER002
  `get_event_loop()` in `async def`; VER003 deprecated asyncio APIs (≥ 3.14); VER007 `re.match`
  (≥ 3.15); ESLint `prefer-object-has-own` (ES ≥ 2022); VER201–204 `forwardRef` /
  `<XContext.Provider>` / `useFormState` from react-dom / `propTypes` (React ≥ 19).
- Everything else in the tables is not hook-checked: apply it while writing (review raises it) and
  judge each case, since a rewrite can change behaviour (Set vs array, custom `__replace__`,
  `TYPE_CHECKING` imports, live `MappingProxyType` views, index-sensitive `find` callbacks).

## 4. Deprecations

Configure warnings-as-errors where the project allows it (pytest `-W error::DeprecationWarning`,
eslint deprecation rules, `-Werror=deprecated`). Elsewhere `warnings: N deprecation lines` with N > 0
on a verify PASS is a finding: fix the deprecations in code you touched, report the rest.

## 5. Norms

`~/.claude/bin/lint-strict --repo <repo>` shows standards-gate's findings early.

| Language | Norm | lint-strict runs |
|---|---|---|
| Python | PEP 8, 257, 484, 585, 604 | ruff --select ALL (off: formatter conflicts, D100/D104/D203/D213, INP001, print, S603/S607, CPY001, FAST001) + ruff format, mypy --strict, complexity limits; docstrings per CLAUDE.md; lines ≤ 79, or the repo's configured length up to 99 |
| TS / JS | ECMAScript + typescript-eslint strict | the package's ESLint config + typescript-eslint strict-type-checked and stylistic-type-checked, complexity limits, explicit return types, tsc --noEmit, Prettier (the repo's config, else defaults with the file's quote and semicolon style) |
| C | the ISO standard the build compiles with (`-std` from compile_commands.json) | clang-tidy -Wall -Wextra -Wpedantic, CERT, bugprone, analyzer, readability, misc, performance, portability, cognitive-complexity and function-size limits; Zephyr repos also checkpatch without its indentation rules; clang-format only with the repo's own .clang-format |
| C++ | the build's standard + C++ Core Guidelines | as C, plus cppcoreguidelines and modernize |

- Only what the norm leaves to the team is configurable (line length up to 99, quote style); no repo
  config switches a rule off.
- A suppression is not a fix: report the line when the norm truly cannot be met (a framework-imposed
  signature, generated code); the orchestrator decides.
- `Not checked` = the tool could not run (no compile_commands.json, no node_modules): build or install
  what it needs and rerun, or check that file by hand.

## 6. Project rules win

A repo's `.claude/rules/standards.md` overrides this skill, except § 5 (template:
`~/.claude/templates/rules-standards.md`).
