---
name: tdd
description: Doktryna TDD tego workflow - jak zaprojektować test_plan w pliku planu (testy jednostkowe i integracyjne jak najbliżej realnego działania, e2e), cykl red → green → refactor z dowodem VERIFY FAIL przed kodem produkcyjnym, co liczy się jako poprawny red, kiedy wolno mockować, testy reprodukujące bugi i findingi z review, kiedy dopuszczalny jest `tdd_exempt:` i jak działa hook tdd-guard. Załaduj przy pisaniu planu i na szybkiej ścieżce; preładowana w agencie developer.
---

## The loop

1. Red — write the test first and run it through `~/.claude/bin/verify -- <command>`. Read the failure:
   it must fail for the reason the plan expects. Valid red: an assertion on the missing behaviour, or
   the missing symbol of an API the plan defines. Not red: a typo or syntax error in the test, a missing
   fixture, a broken environment — fix the test and run it again.
2. Green — the minimum production code that makes the red tests pass. Nothing the tests do not demand.
3. Refactor — names and structure, with the suite green after every step.

A test that has never been seen failing proves nothing: every new test has a red verify log on record.

## test_plan in the plan file

At least one test per acceptance criterion. One line per test:
`<unit | integ | e2e> — <test name> — <what it asserts> — <why it fails today>`

```
- unit  — test_parse_rejects_empty — parse("") raises ParseError — parse accepts "" today
- integ — test_create_program_persists — POST /programs on the real app + test DB → 201 and the row
          exists — the route does not exist
- e2e   — editor saves a program — Playwright on the dev server: build, save, reload, blocks still
          there — the save button is not wired
```

The `commands` section of the plan gives the verify command for each level.

## Levels

- Unit: one module, fast and deterministic; a fake only for what it talks to across a boundary.
- Integration, as close to real operation as possible: the real application wiring (router,
  validation, persistence, serialization), a real database (docker compose or testcontainers; SQLite
  only if production runs SQLite), the real CLI as a subprocess, real files in a tmp dir, real HTTP
  against the running server, the simulator or the attached device for firmware and robot code.
- e2e: the user-visible scenario; the final test gate runs it, or Claude does it by hand in the real app.
- Mock only what cannot run locally or is non-deterministic: third-party remote or paid APIs, wall-clock
  time, randomness, hardware that is not attached. Never mock the code under test or its own modules.

## Rules

- Bug fix: a test that reproduces the bug and fails, then the fix. A verified behavioural review
  finding is treated the same way.
- Never weaken, skip or delete a failing test to get green. A wrong test is fixed and seen red again.
- No skip/xfail without the plan saying why.
- Assert behaviour — outputs, state, errors — not implementation details (private calls, mock call
  counts) unless that call is the contract.
- Deterministic: fixed seeds, frozen time, no sleeps for synchronisation — poll with a timeout.
- Before reporting, run the whole relevant suite, not only the new tests; it stays green.

## tdd-guard

Applies to the `developer` agent only. An Edit/Write on a production source file is denied until the
agent's own transcript shows a test-file edit followed by a verify run that printed `VERIFY FAIL`.
Test files (`tests/`, `test_*.py`, `*_test.go`, `*.test.ts`, `*.spec.ts`, `conftest.py`, `__tests__/`,
`e2e/` …) and non-code files are always editable; a Rust edit adding `#[test]` or `#[cfg(test)]` counts
as a test edit. Fix rounds are not gated mechanically — the rule above still holds.

`tdd_exempt: <reason>` in the spawn prompt disables the gate. Allowed only for a pure refactor under
existing coverage (suite green before and after), docs or config, or generated code.

## Fast path (Claude, main session)

The same loop without a developer: reproducing test red through verify → fix → green → the
integration check that covers the change.
