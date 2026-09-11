---
name: orchestrate
description: Claude+Codex execution loop. The orchestrator (you) analyzes the user's task and writes a spec, the sonnet-worker subagent (Sonnet 5, effort medium) implements it, you verify the work independently (never trust the worker's word), then claude-reviewer and Codex (gpt-5.6-sol, reasoning effort max, fast mode, via MCP) review in parallel, you reconcile their findings into a shared verdict, blocking findings go back to the worker for rework, and finally you return the answer to the user's original prompt. Use when the user runs /orchestrate <task> or explicitly asks for the claude+codex loop / "pętla claude+codex".
argument-hint: <task prompt>
---

# /orchestrate — Claude + Codex execution loop

**User task:**

$ARGUMENTS

You are the **ORCHESTRATOR**. You do not implement; you analyze, specify, verify, and adjudicate. Roles:

| Role | Who | How |
|---|---|---|
| Analysis, spec, verification, consensus, final answer | **you** | inline |
| Implementation | `sonnet-worker` subagent (Claude Sonnet 5, effort medium) | `Agent` tool, `subagent_type: "sonnet-worker"` |
| Review A (Claude side, fresh context, your model) | `claude-reviewer` subagent | `Agent` tool, `subagent_type: "claude-reviewer"` |
| Review B (Codex side) | Codex `gpt-5.6-sol`, effort `max`, fast mode (`service_tier: fast`) | MCP tools `mcp__codex__codex` / `mcp__codex__codex-reply` |

Hard rules, valid for the whole loop:
- **Trust nothing you did not verify yourself.** Every worker claim gets re-run; every reviewer finding gets confirmed or refuted by you with evidence.
- **Do not implement yourself.** Exception: trivial fix-ups (≤ 5 lines) after the loop has converged — and then say so explicitly in the final report. Never silently take over a stuck task; stop and report instead.
- **Never commit, push, or rewrite git history** unless the user's task explicitly asks for it.
- **Keep a journal.** Create `RUN=<your scratchpad dir>/orchestrate/<short-slug>/` and write every artifact there (`spec.md`, `worker-report-N.md`, `verify-N.md`, `review-claude-N.md`, `review-codex-N.md`, `consensus-N.md`). Context may be compacted mid-loop; the journal is your state.
- Talk to the user in the user's language; internal artifacts and prompts to agents in English.
- Caps: max **3 worker rounds per verification phase**, max **3 full review cycles**, max **2 consensus exchange rounds**. When a cap is hit, stop and report the exact state to the user.

---

## Phase 0 — Preconditions

1. Load the Codex MCP tool schemas: `ToolSearch` with query `select:mcp__codex__codex,mcp__codex__codex-reply`. If they are not available, tell the user: "Codex MCP server is not loaded in this session — run `claude mcp list` (should show `codex ✔`) and restart Claude Code", then **stop**. (Fallback only if the user explicitly accepts it: run `codex exec --skip-git-repo-check --sandbox read-only -C <ROOT> -m gpt-5.6-sol -c model_reasoning_effort="max" -c service_tier="fast" --json "<prompt>"` via Bash `run_in_background: true` and read its final `agent_message`; mark the deviation in the final report.)
2. Determine `ROOT` = the project root (absolute). `git rev-parse --show-toplevel` if it is a git repo.
3. Record the baseline in `$RUN/baseline.md`:
   - git repo: `git rev-parse HEAD`, `git status --porcelain` (if already dirty, note the pre-existing paths — later diffs must be restricted to files the worker touched).
   - not a git repo: `rsync -a --exclude .git --exclude node_modules --exclude target --exclude .venv --exclude __pycache__ ROOT/ $RUN/baseline/` so you can `diff -ruN` later.

## Phase 1 — Analyze and write the spec (you, not the worker)

Read the relevant code yourself (Explore subagents are fine for broad searches) until you can write an unambiguous spec. Write `$RUN/spec.md`:

```
# Spec: <title>
## Goal            — what the user wants, in one paragraph; user's original prompt quoted verbatim below it
## Context         — files/functions involved, conventions observed (test runner, style, patterns to follow), relevant constraints
## Exact changes   — per file: what to add/change/remove (precise enough that a junior dev can do it without asking)
## Out of scope    — what NOT to touch
## Acceptance criteria — AC1..ACn, each testable/observable
## Verification commands — exact commands from ROOT and the expected outcome of each
## Constraints     — no commits; no new deps unless listed here; follow existing style; no debug output; etc.
## Assumptions     — decisions you made on ambiguous points
```

If an ambiguity would lead to materially different deliverables, ask the user with `AskUserQuestion` **before** dispatching. Otherwise decide, and record it under Assumptions.

For large tasks split the spec into sequential chunks (each chunk: dispatch → verify), never parallel workers on overlapping files.

## Phase 2 — Dispatch to the worker

Call `Agent` with `subagent_type: "sonnet-worker"`. The prompt must contain, inline (not only by path): the full `spec.md`, `ROOT`, the instruction to work only inside `ROOT`, and a reminder that the report must follow the worker's mandatory report format. Save the worker's report verbatim to `$RUN/worker-report-N.md`.

Keep the worker's agent id. For rework, prefer `SendMessage` to the **same** agent (it keeps context); start a fresh `sonnet-worker` only if the old one is clearly confused or has failed twice on the same item.

## Phase 3 — Verify the worker (trust nothing)

Do all of this yourself and write `$RUN/verify-N.md`:

1. **Diff vs. report.** `git status --porcelain` + `git diff --stat` (or `diff -ruN $RUN/baseline ROOT`). Every path must match the report's "Changed files" list. Unreported changes, or reported-but-absent changes, are a failure.
2. **Read the full diff.** `git diff` plus `git diff --no-index /dev/null <file>` for new files. Check each item of "Exact changes" and "Out of scope".
3. **Re-run every verification command** from the spec yourself and compare with the output the worker pasted. A "pass" from the worker that fails for you = failure, and note the false claim.
4. **Walk AC1..ACn**; each gets PASS/FAIL with evidence (file:line or command output).
5. **Hygiene:** unrelated edits, deleted code, new dependencies, debug prints, TODOs, formatting churn.

If anything fails → back to Phase 2 with a precise delta list (`AC3 FAIL: expected X, got Y (see cmd ...). Fix: ...`). Count the round. After 3 failed rounds: stop and report to the user.

## Phase 4 — Parallel review (Claude + Codex)

Issue **both calls in the same message** so they run concurrently:

**(a)** `Agent`, `subagent_type: "claude-reviewer"`, prompt = the REVIEW PROMPT below.

**(b)** `mcp__codex__codex` with:
```
prompt:           <the same REVIEW PROMPT>
model:            "gpt-5.6-sol"
config:           {"model_reasoning_effort": "max", "service_tier": "fast"}   # fast = Codex /fast (API tier "priority", ~1.5x speed, higher plan usage)
sandbox:          "read-only"
approval-policy:  "never"
cwd:              "<ROOT absolute>"
```
The result's `structuredContent.threadId` is the Codex thread — save it in `$RUN/codex-thread.txt`; you need it for `mcp__codex__codex-reply`. The call can take many minutes at effort max; Claude Code may move it to the background and notify you when done — do **not** re-issue it. Meanwhile you may read the diff yourself, but do not start Phase 5 before both reports are in. Save both reports verbatim to `$RUN/review-codex-N.md` / `$RUN/review-claude-N.md`.

**REVIEW PROMPT** (fill in; identical for both reviewers, so their findings are comparable):
```
You are reviewing a change set implemented by another agent against a spec. Be skeptical and evidence-driven; an independent reviewer is reviewing the same change in parallel and an orchestrator will verify every finding.

Repo root: <ROOT>
Diff scope: <e.g. "uncommitted changes vs HEAD — run `git status --porcelain` and `git diff`; untracked files are new files" | "files: a, b, c">
Previous-round findings that were supposed to be fixed (verify each): <list or "none">

SPEC:
<full contents of spec.md>

Review for, in this order: spec compliance (every acceptance criterion), correctness bugs, edge cases and error handling, regressions at call sites, security where the diff touches such surfaces, tests (present, meaningful, actually passing), scope creep and hygiene. Read the full changed files and their call sites, not only the hunks. You may run the verification commands if they are read-only-safe; do not modify the working tree.

Report in EXACTLY this format:
## Verdict
APPROVE | REQUEST_CHANGES
## Findings
### F1 — <title>
- severity: blocker | major | minor
- confidence: high | medium | low
- location: <path>:<line>
- claim: ...
- evidence / repro: ...
- suggested fix: ...
(or "none")
## Acceptance criteria check
- AC1: PASS | FAIL | UNVERIFIED — evidence
## Verified OK
- ...
## Not checked / uncertain
- ...
Only report findings you can back with file:line evidence. No style nits unless they hide a bug.
```

## Phase 5 — Consensus

1. **Merge.** In `$RUN/consensus-N.md` build one table: `id | source (claude / codex / both) | severity | location | claim | your verdict | evidence`. For **every** finding (from either side) you personally establish `CONFIRMED` / `REFUTED` / `UNCERTAIN` by reading the code or running a repro. Never accept or dismiss on authority, and never let the two reports' agreement substitute for your own check.
2. **Exchange with Codex** (`mcp__codex__codex-reply`, `threadId` from Phase 4): send the Claude-side findings plus your verdicts on Codex's own findings. Ask it to (a) confirm or refute each Claude-side finding with evidence, (b) answer your refutations, (c) output a final list it agrees with. If a real disagreement remains that needs the Claude side, `SendMessage` the same `claude-reviewer` agent with Codex's position and ask for a reasoned reply. Max 2 exchange rounds; then you decide, by evidence, and write down why.
3. **Output of this phase:** `AGREED BLOCKING` (must fix: spec not met, real bug/regression, unsafe), `AGREED NON-BLOCKING` (fix if cheap, otherwise report), `DISMISSED` (with the reason each was refuted).

## Phase 6 — Rework loop

If `AGREED BLOCKING` is non-empty (or you decide to fix non-blocking items): send the exact findings — location, what is wrong, required fix, and "re-run all verification commands" — to `sonnet-worker` (`SendMessage`, same agent). Then Phase 3 again (full verification), then Phase 4 again: both reviewers get the new diff **and** the previous findings list so they check the fixes and hunt for regressions; reuse the Codex thread via `codex-reply` so it keeps context. Increment the cycle counter; after 3 cycles stop and report.

Exit the loop when: Phase 3 passes and both reviewers report no blocker/major that you confirmed.

## Phase 7 — Final output to the user

Respond in the user's language, standalone (the user has not seen the intermediate steps):

1. **Answer to the original prompt** — what was delivered.
2. **Changes** — files and a short summary of each.
3. **Verification** — the commands *you* ran and their results.
4. **Review** — cycles run; findings agreed and fixed; non-blocking findings left open; dismissed findings with the reason; any Claude/Codex disagreement and how you resolved it.
5. **Deviations, assumptions, residual risks** — including anything you fixed yourself, any cap that was hit, any fallback used.
6. Path to `$RUN`.

State only what you verified. If the loop did not converge, say so plainly and describe the exact state of the working tree.
