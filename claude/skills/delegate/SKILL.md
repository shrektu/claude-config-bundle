---
name: delegate
description: Spawn prompt template for `implementer` and the fix-round message. Load when you spawn an implementer and cannot write the prompt from memory, or when delegation-guard rejects a spawn.
---

Class S and above. Fill every section; delegation-guard names a required one you leave out.

```
task
<what to build, 2-3 sentences>

plan
<exact files, functions, signatures, data shapes; what to change and what not; no architecture left open>

class
<S, M, L or XL>

plan_gate
<`pending` for M while plan-gate-runner runs (acceptance phase only, then report); omit otherwise>

acceptance_criteria
<checkable statements, one per line>

paths
/absolute/path/to/repo — repo root
/absolute/path/to/repo/src/module.py — file to change
you may only touch these paths; you may not touch <everything else, named>

reuse
<helpers, types, constants, components, test fixtures to build on, each file:line; or `none — searched: <terms>`>

tdd_phases
<the class's ladder phase by phase: acceptance tests one per expected result, the boundaries that get
 fakes, any acceptance test the plan declares non-automatable, one named test per plan failure mode; per
 phase `expected_red:` the assertion that must fail and why ("FAIL: total() returns 0.0 for [] — empty
 case missing")>

test_command
~/.claude/bin/verify --repo /absolute/path/to/repo -- 'cd /absolute/path/to/repo && <the real test/lint/build command>'

extra_context
<constraints, pinned versions, what must not regress>

rules
- full suite or build only if this delegation asks for it
- <task-specific deviations from your agent prompt, or none>
Never revert or discard changes you did not make (checkout/restore/stash/reset/clean are blocked by a hook); if you think a revert is needed, stop and report.
```

## Fix round

SendMessage the implementer that did the work (fix round or next milestone); when CLAUDE.md Fix round
says spawn fresh, use `findings` in place of `tdd_phases` (no `reuse`).

The message: every verified finding (defect, file:line, how you reproduced it) and, explicitly, that each
bug finding needs its own regression test named after the bug, unit AND integration against fakes of
the external boundaries, red without the fix. The changes stay uncommitted.
