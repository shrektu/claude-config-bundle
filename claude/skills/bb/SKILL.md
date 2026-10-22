---
name: bb
description: Work mode only (skip where CLAUDE_MODE=personal). Bitbucket sweep — threads and fixes on Sebastian's PRs, review and vote on others' PRs. Load on /bb or when asked to go through Bitbucket PRs or comments, or to review someone else's PR.
---

## 0. Scope

- Only OPEN PRs. Drafts are untouched (no comments, votes, replies, resolves; a bug seen there goes to
  the report; `bb-sweep` hides them unless `--include-drafts`), unless Sebastian names one: then a full
  § 2 review with comments, and a vote only if he asks.
- Whose PRs you may change: CLAUDE.md PR OWNERSHIP. Every other PR gets only the § 2 review; a ping
  or fix request there goes to the report.
- `~/.claude/bin/bb-sweep`: read-only scan, ~2 min; `--repos a,b`, `--json`. Sections `mine`, `review`,
  `replies`, `approve`; `[bot]` = CodeRabbit (posts as Jenkins). It writes only through `resolve <repo>
  <pr> <id...>` (`resolve --answered`: answered bot threads on Sebastian's PRs, in bulk). A closing line
  **UWAGA … nie dało się w pełni sprawdzić** → rerun those repos with `--repos` before any vote or resolve.
- In parallel: `bb-sweep harvest` (others' threads on Sebastian's open and merged PRs not yet made into
  habits). Assess each per § 1 "Habit" and mark every shown thread, including those handled in § 1:
  `bb-sweep harvest-mark <repo> <pr> <thread-id...>`, one call per PR. `bb-sweep harvest-done` (moves the
  cutoff) only once every shown thread is marked.
- Cloud routines "Morning/Evening bitbucket sweep" (RemoteTrigger): both prompts hold a `NAWYKI` block;
  Evening also holds the image lists and the PR-description comments (§ 2). After `habits add`/`drop`
  (`python3 ~/.claude/bin/bb-routine-habits` prints the block) or a change to those, `RemoteTrigger update` each affected routine with the full prompt, then `get` it to confirm.

## Writing (everything you publish)

- Footer: CLAUDE.md, AI footer; no header. Labels and one-sentence replies you write yourself; longer
  text → `writer` mode `publish` (kind `review_comment` for comments and replies, `pr_description`).
- Short, a hard rule:
  - clean-code remark: a ~5-word label ("magic string", "zduplikowana logika — jest `X`", "surowy dict —
    użyj modelu", "martwy kod", "`Any` — typ jest znany", "da się prościej: early return", "niespójne z
    repo — logika w serwisie"); no norm names, rule numbers or links;
  - bug: one or two sentences, what breaks and when; one resting on external semantics cites file:line
    or the doc link (§ 2 Method 3);
  - no preamble, restating, praise or quoting the adjacent code; evidence (file:line, test result, SHA),
    not argument; what does not fit belongs in a conversation or the task description;
  - reply to an author's counter-argument: ≤ 3 sentences, § 2 Tone.
- Exception: when the author asks, or the blockers come from misreading the mechanism the task stands on,
  one longer inline explanation (why the task exists, how it should work, the main problem) at the main
  problem's line.

## 1. Sebastian's PRs (`mine`)

Every thread without his reply: reproduce first (open file:line, run the test or command), then decide.

- **valid** → fix it per its class in CLAUDE.md (XS yourself, otherwise `implementer`; that class's TDD
  ladder and review set before the push). The fix goes to the owner branch: in a PR stack, a remark on an
  inherited file is fixed in the lowest PR that changes it, then merged up the stack. Land it as `git
  commit --fixup` + autosquash + `--force-with-lease`; the reply gives the post-autosquash SHA and branch.
- **invalid or a deliberate trade-off** → no code change; reply with evidence (file:line, test result,
  a doc quote).
- Product, contract and architecture decisions are Sebastian's: never settle or ask about them in the
  thread; list them in the report (repo, PR, thread link, what is to decide).
- One reply per thread.
- Resolve a `[bot]` thread only after the fix is pushed or a reasoned rejection is posted. Never resolve a
  human's thread.

**Habit.** Each remark judged valid goes through the `review` skill's "Habits" step (ref
`<repo>#<pr>/<thread-id>`, reviewer = its author); an invalid one never does.

## 2. Others' PRs

**`review`**: every open PR of someone else without your vote, assigned or not (`--deep` asks all repos).
Review the whole diff by this section (not the `review` skill); vote `approve` or `request-changes`,
never neither.

**Scope source.** `getJiraIssue` on the ID in the title (`[TICKET-1274] …`) and on its epic (content,
acceptance criteria), plus the PR `description` (`GET …/pullrequests/<id>`). Compare the code with both:
- **missing**: an item of the task or criteria not in the code;
- **excess**: a change the task did not ask for (other modules or endpoints, replaced defaults, a side
  refactor).

**Scope reminder, not a blocker.**
- The description mentions the omission or the extra → no comment.
- Otherwise one short inline reminder: what is extra or missing and that the description does not say
  so, no demands; at the change for an excess, at the closest diff line for a missing item (no such
  line → report only).
- Closed per the table, silently; never press or ask where the decision came from.
- A bug in excess code is still a bug.

**Reading.** In a scratchpad worktree (`git fetch` the PR branch), with `~/.claude/bin/habits list --repo
<worktree> --max-chars 20000`. No typecheck, no lint-strict: judge correctness by reading the code on
both sides of the diff. Tests and CI are out of scope: no runs, no CI reads, no remarks.

**Static analysis** (every review), directly, not through verify:
`~/.claude/bin/bb-sweep static --repo <worktree> --base origin/<target branch> --json`. Candidates come
only from added lines of non-test files: magic numbers (comparison, repeated, sleep/delay without a
constant or comment), commented-out code, copied code (jscpd), getattr/setattr/hasattr/delattr with a
literal name, bare or swallowed exceptions and empty `catch`, mutable defaults, `==` None/True, PEP 8
naming, unused variables. Take these categories ONLY from the result. Each candidate is one inline
comment: category `magic-number` → label `magic number`, any other → its `label` verbatim; images per
"Images"; a commented-out block gets one comment at its first line. Skip a candidate only when a thread
already sits on that line (closed or answered) or it is plainly false (one sentence why in the report).
Files in `not_checked`, or the whole PR when the command fails: check these categories by reading and
say so in the report.

**What you flag yourself** (never the static categories):
- wrong types: `Any`/`object` where the type is known, a lying annotation, `cast`/`as`/`type: ignore`
  instead of the right type;
- architecture inconsistent with the repo (layers, e.g. business logic in an endpoint or component instead
  of a service or hook; patterns; file and module placement and naming), a parallel abstraction,
  dependencies pointing the wrong way;
- clear simplifications (needless layers or wrappers, repeated blocks, nesting → early return, manual loop
  → idiom, a function or component to split), with one sentence on what to change it to;
- magic strings and repeated string literals, duplication of an existing helper, a raw dict for a known
  shape, error paths ending in success, names that lie, functions doing several things, dead code;
- real bugs and team habits (including getattr/hasattr/setattr on a known field with a non-literal name).

Never flag formatting, line length, import order, docstrings, quote or comma style or missing type
annotations, nor habits about them (e.g. H004). In test files only real bugs (a test that checks nothing,
checks the wrong thing or passes regardless of the code); no style remarks, no style habits.

**What blocks and what closes a thread.** The vote is `request-changes` while one of your blocking threads
is open; non-blocking ones never hold back `approve`.

| Remark | Blocks | Closed by |
|---|---|---|
| Bug, logic, architecture, edge case (wrong value, data loss, exception, regression against `origin/<target branch>`, validation hole) | yes | a fix, or the author's argument that you verified in the code. "Tak ma być", "zamierzone", "działa od lat", "jest dobrze", a meme: no |
| Behaviour change the author confirms in a comment as intended (a product or contract decision, not a bug) | yes | that confirmation, silent resolve. "Intended" on a shown bug is not a decision |
| Style and clean code, any weight (including style habits) | yes | a fix or a substantive argument verified in the code ("taka konwencja w projekcie" → grep the repo). "Tak ma być", "jest dobrze", "lepiej żeby została", "nie trzeba", a meme: no |
| A number in `sleep`/`delay_ms`/`k_sleep`/`setTimeout`… without a constant or a "why" comment | yes | a constant or an explanatory comment |
| Scope reminder | no | a fix, or the author confirming the deviation |
| PR-description comment | no | see "PR-description comments" |

Give each style remark an internal weight (low/medium/high/critical, by real harm: a magic number in a
business threshold or a swallowed exception on a payment path → high; `Any`/`cast`/a lying annotation →
low) for the report only. Never publish it; it does not change blocking.

**Method** (no vote before step 5 is done):
1. Ticket context: when the PR delivers part of a bigger ticket, judge that part's requirements; `git log
   origin/<target branch> --grep <ID>` shows what earlier PRs delivered, so do not demand it again.
2. Read the code on both sides of the diff: the producer of its input and the consumer of its output
   (worker, contract, configuration).
3. A remark resting on an external tool, library or protocol you cannot run here: check its source or
   official docs and cite file:line or a link; never from memory, never unchecked.
4. When the tests only mock a dependency and check argument lists while the bug lies in its semantics,
   say so and propose one test against the real dependency.
5. Every habit in the list loaded above, one by one: does not apply / OK / broken (file:line);
   static-category habits are settled from its result. Broken → an inline label without the habit id;
   a logic or architecture habit is handled like a bug, a style habit like style. Report line per PR: "nawyki: N sprawdzonych, złamane: H0xx (plik:linia), …".

**Comments.** One problem, scope reminder or § 3 question per inline thread, at the exact line. No general
comment except the two PR-description comments, no review summary (report only), no collective reply.

**Images** (others' PRs only), for three categories: magic number, getattr/hasattr/setattr on a known
field (label `getattr na znanym polu`, or hasattr/setattr), commented-out code. One image per category
per PR, on its first comment; later comments of that category get the label only; a category your
earlier review of this PR already illustrated gets none. Pick with `shuf -i 1-<N> -n 1` over that
category's list in `references/images.md` (read it before the first such comment) and take exactly that
item. Paste the URL verbatim; never upload or download images. Exactly:

    <label>

    ![](<URL>){: data-layout='center' }

    🤖 Wygenerowane przez <model>

**PR-description comments** (general, no `inline`): each kind at most once per PR (skip it when anyone
already posted one); they never block. Both use the image
`https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2207092381-image.png`.
- Description empty or perfunctory (a few words, a placeholder, only links) or not saying what changed
  and why → `brak opisu PR` in the image format above. Close silently once the description is completed.
- Description claims what the code does not do (a change not in the diff; a different behaviour, value,
  name, endpoint or scope) → `opis PR niezgodny z kodem`, one line per inconsistency, no demands. Not
  for a PR without a description, nor for a deviation the description is silent about (scope reminder).
  Close silently once the description is fixed or the author says the code is right. Exactly:

      opis PR niezgodny z kodem

      - opis: „<co mówi opis>”; kod: <co robi kod> (<plik>:<linia>)

      ![](<the image above>){: data-layout='center' }

      🤖 Wygenerowane przez <model>

**`replies`**: judge each reply by the table. Resolve is silent (`bb-sweep resolve <repo> <pr> <id>`, no
reply), except when conceding: one sentence "Racja — <evidence>" first.
- Fixed, verified in the code ("Done" is not evidence) → resolve; if the vote hung only on those blockers,
  switch to `approve`.
- The author confirms a scope deviation or an intended behaviour change → resolve; do not dig into the
  decision's source.
- Counter-argument (bug, logic, style) → verify it first: behaviour on the target (`git show
  origin/<target branch>:<file>`), history (`git log`, `git show <sha>`), library source, a repo grep for
  "that's the convention". It holds → "Racja — <file:line or commit>" and resolve; conceding is mandatory,
  never keep a thread on principle. It does not → reply with evidence (file:line, commit, comparison with
  the target branch), thread open, vote `request-changes`.
- No argument against a bug or style remark ("tak ma być", "jest dobrze", "lepiej żeby została", "nie
  trzeba", "działa od lat", just an image) → thread stays open; reply ≤ 3 sentences: why it is not an
  argument, the evidence, what you expect (a reason or a fix).
- A claimed fix the code does not show → one sentence where it is missing (file:line), thread open.

**Tone: assertive, with a light jab.** Evidence closes a thread, not the number of rounds, and the tone
does not soften after a refusal. A short jab is allowed („„Dobrze” według czego?”, „Obrazek to nie
uzasadnienie.”, „„Done” — a w `plik:linia` dalej jest …”), always next to evidence and about the code or
argument, never the person: no irony about competence, no exclamation marks, no caps. Concede just as
plainly when the evidence favours the author.

**Collective replies.** `replies` also lists the author's comments in any thread, and pushes, after your
last entry; it does not list other people's comments outside your threads, such as a mention. On each
listed PR read every comment since your last entry and compare `source.commit.hash` with the commit you
reviewed.
- Split a collective comment into points, map each to your thread and handle it as if answered there:
  verify in the code → silent resolve, or one sentence IN THAT thread on what is missing.
- Points matching none of your remarks (new changes, workarounds of your decisions) → review them like
  any code change.
- Your remark in neither the collective comment nor the code stays open, with no reply under the
  collective comment; report only.

**Others' threads.** Close only threads you opened; one of yours that someone else closed you never
reopen or comment on. If the author left one unfixed, you may
reply in it with file:line; if that reviewer is wrong, reply in it with evidence that the author's
original code is right.

**`approve`** → change the vote to `approve`. While handling `replies`, also approve a PR whose only open
threads of yours are non-blocking (table); `approve` does not list those.

## 3. Decisions — the author is asked

The PR author settles decisions: ask in the thread, tag nobody. A scope reminder (§ 2) is not a decision.
Ask when:
- the remark is right but the fix is big: it touches a contract (API, data format, DB schema,
  migration), redesigns a flow, spans several modules or repos, or changes behaviour visible to a user or
  another service → fix now or a separate task?
- a product or contract decision within the scope (API, data format, policy) that the ticket does not
  settle.

Behaviour or contract makes a change big, not its line count. A mechanical refactor inside the PR (raw
dict → Pydantic or dataclass, magic number → named constant, extracting a function, names, types, a
missing test) is an ordinary remark to the author (fix it yourself only where § 0 allows), however many
places it touches. Ask for a decision, not for work.

One or two sentences: the problem and the options. One question per thread. "It stays" closes a
decision question silently; it never closes a bug (table). A question thread stays open until the author
answers. It blocks (`request-changes`) when it concerns a bug or an unsettled product or contract
decision; a "fix now or a separate ticket" question about a non-bug does not block.

## 4. Technical

- REST API v2.0, credentials in `~/.config/bitbucket/credentials`.
- Empty POSTs (`/approve`, `/request-changes`) go **without** `Content-Type`.
- A reply carries `parent.id`; on an inline thread copy the parent's `inline`.
- The comment listing omits `resolution`: GET each comment.
- Fixes on Sebastian's PRs go in a scratchpad worktree when his checkout is on another branch or dirty;
  never switch branches in his checkout.

## 5. Report

Per PR with a pushed fix: a `review`-skill status. Then one list: fixes (SHA + branch); rejected remarks
and why; votes (where, which); closed threads; what you wait for from people; drafts skipped; decisions
you asked authors about (repo, PR, thread link, what you asked); scope reminders left and those closed
after "intended"; each style remark's internal weight; authors' counter-arguments you verified and the
result (held → "Racja" and resolve, with evidence; did not → your reply with evidence, thread open);
decisions on Sebastian's PRs waiting for him (§ 1); the habits line per reviewed PR; new and bumped
habits (id, rule, source), so he can `habits drop <id>`.
