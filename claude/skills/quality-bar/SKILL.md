---
name: quality-bar
description: Jedna wspólna poprzeczka jakości dla developera i dla review Claude - zgodność z planem, dowód red → green dla każdego testu, testy sprawdzające zachowanie (nie puste, nie pominięte, integracja naprawdę integruje, bez mocków własnego kodu), kryteria akceptacji z dowodem, idiomy dla wersji z repo-facts i zero ostrzeżeń deprecation, brak regresji, styl (zero komentarzy, jednolinijkowe docstringi, zero magicznych wartości, typowane modele, kod tylko przez Edit/Write). Preładowana w agencie developer, który przechodzi ją punkt po punkcie przed raportem; skill review sprawdza dokładnie tę samą listę.
---

The developer goes through this list item by item before every report — first delivery and every fix
round — fixes what fails and reruns the plan's commands through verify. Claude's review checks the same
list, so anything left here comes back as a finding.

1. Plan conformance: exactly what the plan says — the files, signatures and data shapes it names; no extra
   scope, no design of your own. A gap in the plan is reported, not filled.
2. Red → green evidence: every new or changed test was seen failing through verify for the reason
   test_plan gives (log path kept), then passing. A test that never failed proves nothing.
3. Meaningful tests: they assert behaviour (outputs, state, errors), cannot pass vacuously, nothing is
   skipped or xfailed without the plan saying why; integration tests really integrate (real app wiring,
   DB, HTTP, CLI, files) and never mock the project's own code; none of the anti-patterns the `tdd`
   skill lists.
4. Acceptance criteria: each one met, with evidence that can be opened (a test name, a verify log).
5. Pinned versions: the code uses the APIs of the versions `~/.claude/bin/repo-facts` prints (installed
   source as the oracle); a verify PASS that reports `warnings: N deprecation lines` is not done.
6. No regressions: callers of every changed signature updated, migrations and serialized shapes
   compatible, error paths and concurrency still correct, the whole relevant suite green — not only the
   new tests.
7. Style: zero comments (tool directives excepted), at most one-line docstrings, descriptions as
   parameters, no magic numbers or strings (named constants or enum members), typed models instead of raw
   dicts, no needless `__init__.py`.
8. Senior code: the shortest correct solution; the standard library and the framework before own code;
   the newest construct the pinned versions offer (`match`, dataclass(slots, frozen), `X | None`,
   pathlib, `satisfies`, discriminated unions, readonly); early returns over nesting; no abstraction,
   option or layer the plan does not need; no defensive code for states the types rule out; deleting
   beats adding. lint-guard enforces the mechanical part (ruff UP/FURB/SIM/C4/PERF/RET, complexity 10).
9. Design: dependencies point inward — domain logic imports no framework, DB or I/O, which stay at the
   edges; input is validated once at the boundary and converted to typed models; one responsibility per
   module and function; data immutable by default; errors explicit — no bare or blind `except`, no
   silent fallback, fail fast; a shared helper only on the third repetition; no global mutable state.
   `quality-gate` (verify) reports type errors, dead code and duplicates on changed lines.
10. Hygiene: code written with Edit/Write only (never Bash heredoc, sed or a script writing files), no
   stray debug output, temp files or untracked leftovers, nothing outside the plan's `repos`.
