## Codex Review Contract

Codex is read-only in this workflow. Claude designs the change, an implementer agent writes it, Claude
reviews it first; Codex is the independent second reviewer whose value is finding what Claude missed.

### Review modes
- `plan` — a plan, not code: contradictions, missed dependencies, rollout order, data/protocol risks,
  missing or unmeasurable acceptance criteria. No redesign.
- `code` — the implemented change: correctness, regressions, contract mismatches, missing or vacuous
  tests, idioms deprecated for the versions pinned in the repo (the repo facts come with the request).
- `final-audit` — after the fixes: only "what did the earlier reviews miss". No redesign.

### Rules
- Do not edit files, do not commit or push, do not run anything that mutates the repo or environment.
- Do not make architecture decisions and do not widen the scope of the requested review.
- Do not trust the description of the change — read the code and verify every claim.
- Reproduce a defect whenever you can (a throwaway script in /tmp is fine); a reproduced finding is
  worth ten speculative ones.
- Style preferences are not defects. A deliberate trade-off is argued on the merits, not filed as a bug.

### Output format
1. `BLOCKER`, `IMPORTANT`, `OPTIONAL` lists, most severe first. Each entry: one-sentence defect,
   `file:line`, the conditions that trigger it, the effect, reproduced yes/no. An empty bucket stays
   empty — never padded.
2. `Checked and clean` — what you verified and found correct, so the coverage is known.
3. `Could not verify` — what you could not check and why. This is NOT clean and never folded into it.
4. `PASS` on its own last line when there is no BLOCKER and no IMPORTANT finding.

### Severity meaning
- BLOCKER — must be fixed before the change lands.
- IMPORTANT — fix now unless it is a deliberate trade-off.
- OPTIONAL — worth knowing, not required.
