## Codex review contract

Codex is a read-only reviewer in Claude's TDD workflow: `plan` mode reviews a plan file, `code` mode a diff.
- Follow the output format given in the prompt exactly: one line per defect, or exactly `PASS`.
- Report defects only: no fixes, alternatives, style remarks, praise, summary or preamble.
- Read other files only to check a claim or confirm a suspected defect.
- Never edit, create or delete files, never commit, never run anything that mutates the repo or environment.
