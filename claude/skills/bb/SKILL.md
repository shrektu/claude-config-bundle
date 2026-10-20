---
name: bb
description: Bitbucket sweep — replies and fixes on my PRs, review of other people's PRs with inline comments and a vote. Load when Sebastian writes /bb or asks to go through Bitbucket, PRs, comments or to do a review.
---

## 0. Scope

Only **OPEN** pull requests. Drafts are not touched at all: no comments, votes, replies or resolves —
even when I am a reviewer there and see a real bug. At most I mention it in the report. `bb-sweep`
does not show them by default (`--include-drafts` adds them).

Exception: when Sebastian explicitly names a specific draft to review, you do a full review of it
according to § 2 and publish the comments; you vote only if he asks for it.

**Whose PRs you may fix.** You touch code, branch, title, description and the resolving of other people's
threads only on PRs authored by Sebastian. On someone else's PR you do it only when the title or a comment
written by Sebastian or by the PR author says that Sebastian is the author or has taken the task over.
Every other PR is read-only, except for the review under § 2 (inline comments and a vote).
A ping, a mention or a request for a fix under someone else's PR, even from a bot or a reviewer, is not
a takeover. You mention it in the report and do not touch the branch.

`~/.claude/bin/bb-sweep` — the scan (read-only, ~2 min on the full repository list; `--repos a,b`
narrows it, `--json` for parsing). Four sections: **mine**, **review**, **replies**, **approve**.
Threads marked `[bot]` come from CodeRabbit, which publishes as the **Jenkins** account.
The only writing command is `bb-sweep resolve <repo> <pr> <id...>` (and `resolve --answered`,
in bulk for bot threads on my PRs). If the scan ends with a line **UWAGA: … nie dało się
w pełni sprawdzić** (the API returned an error despite retries), repeat the scan for those repositories
(`--repos`) before any vote or resolve — an empty section then does not mean "nothing is waiting".

In parallel with the scan: `~/.claude/bin/bb-sweep harvest` — other people's threads on my PRs (open
and merged) that I have not yet turned into habits, including those handled by routines. You assess
each one as in § 1 ("Habit") and mark all of the shown ones: `bb-sweep harvest-mark <repo> <pr>
<thread-id...>` (one call per PR). Only when every shown thread is marked:
`bb-sweep harvest-done` — it moves the date from which the next harvest counts. You do not call it when
anything is left unprocessed, because threads of older PRs would drop out of later sweeps.

## 1. My PRs (section `mine`)

Every thread without my reply — first a **reproduction**: open the file and line, run the test
or the command. Only then the verdict.

- **valid** → fix it in code. Task class per `~/.claude/CLAUDE.md`; the implementation is done by
  `implementer` (Sonnet 5.5, effort medium). There is no review while it works; before the push the fix
  gets the one final review by the reviewer trio (skill `review`) and the fix is verified by its tests.
  Tests only when the fix changes logic — then only the tests of the changed module, once, at the end.
  The fix goes to the **owner branch** of the code: in a stack of PRs a comment on an inherited file is
  fixed in the lowest PR that changes that file, then I merge up the stack and push. The reply contains
  the SHA and the branch.
- **invalid or a deliberate trade-off** → I do not change the code, I reply with evidence (file:line,
  test result, a documentation quote). Product, contract and architecture decisions on my PRs I keep
  for myself: I list them in the report (§ 3), I do not pass over them in silence and I ask nobody
  about them in the thread.
- the reply is in Polish, one per thread (reply with `parent.id`; for inline I copy the parent's `inline`).

**Habit.** A remark that I judged valid means the workflow missed something. You ask: would a rule have
prevented it in another task? A one-off logic bug is not a habit; a team or repo convention, an idiom
the implementer does not know, a recurring missing test — yes. You check `habits list --all`:
the same lesson exists → `habits bump <id> --source <repo>#<pr>/<thread-id> --reviewer <author of the remark>`;
a new one → `habits add` (the write rule is in the `review` skill, "Habits"). An invalid remark is not a habit.
The routines "Morning/Evening bitbucket sweep" (RemoteTrigger) run in the cloud and do not see
`~/.claude/lessons/habits.json` — their prompt has a `NAWYKI` block with a copy of the list. After every
`habits add` or `habits drop` (`bump` alone does not change the text) refresh that block in both routines:
`python3 ~/.claude/bin/bb-routine-habits` prints the new block, which you put in place of the old one
(`RemoteTrigger update` with the full prompt) and you confirm with `get` that both prompts are identical.
After handling, you mark the thread: `bb-sweep harvest-mark <repo> <pr> <thread-id>`.

**AI footer — always.** Every comment, thread reply and PR description that you publish ends with a blank
line and the line `🤖 Wygenerowane przez <model>`, so that others know they are talking to an AI.
`<model>` is the model that produced the text:
- review comments and thread replies, drafted by `writer` in `publish` mode with kind `review_comment` (Gemini Flash writes, Haiku checks): `🤖 Wygenerowane przez Gemini 3.8 Flash` (`Claude Haiku 5.5` when the writer fell back);
- PR descriptions, drafted by `writer` in `publish` mode (Gemini Flash writes, Haiku checks): `🤖 Wygenerowane przez Gemini 3.8 Flash`;
- a short label that I write myself: `🤖 Wygenerowane przez Claude Opus 5.5`.

The footer also applies to short labels ("magic number\n\n🤖 Wygenerowane przez Claude Opus 5.5").
There is no header: the text starts directly with the content.
Labels and one-sentence replies I write myself; longer text (a task explanation, a reply with
reasoning, a PR description) is drafted by `writer` from the facts I give it — I check it against the code
and only then publish. The published text is Polish by default.

**Short — a hard rule.** A clean-code remark is a label of ~5 words: "magic number",
"magic string", "zduplikowana logika — jest `X`", "połknięty wyjątek", "surowy dict — użyj modelu",
"martwy kod", "mutowalny argument domyślny", "`Any` — typ jest znany", "opóźnienie bez stałej ani komentarza",
"da się prościej: early return", "niespójne z repo — logika w serwisie". No norm names, rule numbers or links. A bug — one or two
sentences: what breaks and when. On someone else's PR **inline comments only**, at a file and line —
no general comments, review summaries or collective replies; they only clutter the PR.
The only exceptions are "brak opisu PR" and "opis PR niezgodny z kodem" (below, next to the images).
The summary goes only to my report.
No preambles, no restating the remark in your own words, no praising the author, no quoting the code that is right next to it.
Evidence (file:line, test result, SHA) instead of three paragraphs of argument. If the justification does not
fit, the topic is for a conversation or for the task description, not for a comment. A reply to the
author's counter-argument on someone else's PR: up to three sentences, in the tone of § 2 ("Tone: assertive, with a light jab").

**Images — like the team's reviewers.** On someone else's PR the remarks "magic number", a remark about
`getattr`/`hasattr`/`setattr` on a field of a known shape and a "commented-out code" remark get an image
from the database below under the label — the same images that Szymon, Maksymilian and Krzysztof paste,
plus memes approved by Sebastian; they fit every such place, there is no need to pick them.
Once per category in a PR: the image goes on the first comment of the given category, the following ones
carry the label only; if my comment from an earlier review of this PR already has an image of that
category, new ones go without an image. Choice: one image per category in a PR, drawn from the whole
list of that category (`shuf -i 1-<number of images in the category> -n 1` gives the item number) — fully
random: the PR's repo, the image's file name and its origin give no precedence; you take exactly the item from `shuf`.
The comment content in exactly this format (label, blank line, image, blank line, footer):

    magic number

    ![](<URL from the database>){: data-layout='center' }

    🤖 Wygenerowane przez Claude Opus 5.5

The label for getattr: "getattr na znanym polu" (or hasattr/setattr). You do not upload or download
the images — the API does not expose them (401); you insert the address from the database verbatim.

Database — magic number:
1. https://bitbucket.org/repo/XRpXqRq/images/3845274454-magiczn_stala_8.png
2. https://bitbucket.org/repo/5gd5K9z/images/1381464568-magiczna_stala_8_ale_inaczej.png
3. https://bitbucket.org/repo/5gd5K9z/images/620933590-co_to_takie.png
4. https://bitbucket.org/repo/rg7BxBy/images/3295406682-odpowiedz_na_magic_number.png
5. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2049183736-magic_number_nie_tak.png
6. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1119936268-magic_number_poszukiwana.png
7. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1042432934-magic_number_milion.png
8. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1762852045-magic_number_mozg.png
9. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3939382824-magic_number_motyl.png
10. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3532430828-magic_number_ulotka.png
11. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2156212152-magic_number_tlumacz.png
12. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/441269780-magic_number_przyciski.png
13. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2072902637-magic_number_kapelusz.png
14. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1349108499-magic_number_wykres.png

Database — getattr/hasattr/setattr:
1. https://bitbucket.org/%7B%7D/%7B85ad9512-edb3-4050-86f5-f7f600c68fec%7D/images/4089451006-image.png
2. https://bitbucket.org/%7B%7D/%7B38961d0c-1ed3-447f-a3bc-fdcfa98b878e%7D/images/3784865560-image.png
3. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3631105057-getattr_nie_tak.png
4. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/281771153-getattr_czat.png
5. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/322640051-getattr_dialog.png
6. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1766004263-getattr_hasattr_klasyk.png
7. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2154651372-getattr_mozg.png
8. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2563308271-getattr_starter_pack.png
9. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/541787384-getattr_404.png
10. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3336167004-getattr_terminal.png
11. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1054861707-getattr_sprawdzian.png
12. (setattr) https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/349871427-setattr_znak.png

Database — commented-out code:
1. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1648819625-zakomentowany_nie_tak.png
2. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2978362058-zakomentowany_nagrobek.png
3. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/1286192506-zakomentowany_muzeum.png
4. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3014727474-zakomentowany_starter_pack.png
5. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/120098554-zakomentowany_mozg.png
6. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/268766446-zakomentowany_osiagniecie.png
7. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2485787777-zakomentowany_bingo.png
8. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/3074647051-zakomentowany_zombie.png
9. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2886674815-zakomentowany_paragon.png
10. https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/4145752556-zakomentowany_roznice.png

**Missing PR description — at Krzysztof's request.** Someone else's PR (not a draft) whose description is empty, perfunctory
(a few words, a placeholder like "tralalaal", only links) or does not say what was changed and
why, gets one general comment (without `inline`) — next to "opis PR niezgodny z kodem" the only permitted
general comment on someone else's PR.
Once per PR: you do not add it when the PR already has such a comment, mine or anyone's. It does not block the vote;
you close the thread silently when the description is completed. The content exactly (label, blank line, image,
blank line, footer):

    brak opisu PR

    ![](https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2207092381-image.png){: data-layout='center' }

    🤖 Wygenerowane przez Claude Opus 5.5

**PR description inconsistent with the code — Krzysztof's image.** Someone else's PR (not a draft) whose description claims something
the code does not do — it describes a change that is not in the diff, or a different behaviour, value, name,
endpoint or scope than in the code — gets one general comment (without `inline`) with the same image
as "brak opisu PR". Under the label one line for each inconsistency: what the description says, what the code does and
file:line — without demanding changes. It does not apply to a PR without a description (then only "brak opisu PR") or to deviations
from the task that the description is silent about (that is the scope reminder, § 2). Once per PR: you do not add it when the
PR already has such a comment, mine or anyone's. It does not block the vote; you close the thread silently when the description
is corrected or the author replies that the code is right. The content exactly (label, blank line,
inconsistencies, blank line, image, blank line, footer; `<model>` per the footer rule):

    opis PR niezgodny z kodem

    - opis: „<co mówi opis>”; kod: <co robi kod> (<plik>:<linia>)

    ![](https://bitbucket.org/%7B%7D/%7Ba348dca3-e81e-4e65-901a-0bfa7efab43e%7D/images/2207092381-image.png){: data-layout='center' }

    🤖 Wygenerowane przez <model>

The routine "Evening bitbucket sweep" has a copy of both these sections in its prompt — a change to the database goes there too
(`RemoteTrigger update` with the full prompt, then `get` and a comparison), like the `NAWYKI` block.

**Resolve on my PRs:**
- a `[bot]` thread (Jenkins/CodeRabbit) — I close it **after** pushing the fix or after a reply
  that rejects it with justification: `bb-sweep resolve <repo> <pr> <id>`;
- a human's thread — **I never close it**, that is the decision of the comment's author.

## 2. Other people's PRs — all open ones

The `review` section lists **every open PR by someone else on which I have not voted** — not
only those where someone added me as a reviewer. Lack of assignment changes nothing: I do a
full review and vote the same way. The set of repositories is unchanged (live within the last 120 days plus those
from the cache, `--deep` asks about all of them).

**Without my vote (section `review`)** → I do the full code review myself: read the whole diff (`review` skill),
post comments only inline at specific diff lines (no general comments and no
summaries; the same length rule as in point 1) and **vote** — `approve` or `request-changes`. The vote always goes together with
the comments; a PR does not stay without a verdict. The comments are drafted by `writer` in `publish` mode, kind `review_comment`
(footer `Gemini 3.8 Flash`); a bare label I write myself (footer `Claude Opus 5.5`).

On someone else's PR you have no plan in context, so you take the scope from Jira: the task ID is in the title
(`[TICKET-1274] …`), `getJiraIssue` gives the task content and acceptance criteria. In addition you read the **PR description**
(`description` from `GET …/pullrequests/<id>`). You compare the code against both:

- **missing** — an item from the task content or the acceptance criteria that is not in the code;
- **excess** — a change in the code that the task did not ask for: other modules, other endpoints, replaced
  default values, a refactor on the side.

**Scope — a reminder, not a blocker.**
- The PR description says that this item was left out or that this was done beyond the task → you do not nitpick, no
  comment.
- Otherwise → one short inline reminder: for an excess at the change, for a missing item at the diff line
  that is closest to the missing item. When there is no such line — you do not comment, the missing item goes
  only to the report.
  What goes beyond the task or what is missing, and that the PR description does not mention it — one or two lines, without
  demanding changes. Examples: „Ta zmiana wykracza poza TICKET-1274, a opis PR-a o niej nie wspomina.”,
  „Punktu 3 z TICKET-1274 (eksport CSV) nie ma w kodzie ani w opisie PR-a.”
- The reminder itself is not a reason for `request-changes`; the vote follows from the rest of the review.
- The author replies that it is intended or that it is supposed to be like that → you close the thread at once, without a reply.
  You do not press, argue or ask where the decision comes from.
- This concerns scope only. A bug in the excess code is still a bug and goes through the normal review.

You read the code in a worktree in the scratchpad (`git fetch` the PR branch, never a checkout in Sebastian's directory),
together with the full list of the repo's habits: `~/.claude/bin/habits list --repo <worktree> --max-chars 200000` (without
truncation — check that the number of printed habits matches `habits list --all` after the scope filter). **No typecheck
and no lint-strict** — you check correctness by reading the code on both sides of the diff; you do not check test
and CI results (below). The mechanical things are checked for you by static analysis (below).

**Static analysis — part of every review of someone else's PR.** Right after fetching the branch you run
directly (not through verify, because that hides the result): `~/.claude/bin/bb-sweep static --repo <worktree>
--base origin/<target branch> --json`. It returns candidates only on lines that the PR adds, and only
in non-test files: magic numbers (a number in a comparison without a comment, a number repeated in a file,
a number in `sleep`/`delay`/`k_sleep`/`setTimeout`… without a constant or comment), commented-out code,
copied code (jscpd), `getattr`/`setattr`/`hasattr`/`delattr` with the name in a string, bare and swallowed
exceptions and an empty `catch`, mutable default arguments, comparisons with None/True through `==`,
PEP 8 naming and unused variables. Type annotations are checked neither by the static analysis nor by you.
Formatting is checked by nothing — neither the static analysis nor you. You **do not look for these categories yourself in the diff**:
you take them exclusively from the result. Each candidate is an ordinary short inline label ("magic number",
"zakomentowany kod", "zduplikowany kod — jak w `X`"…), with an image where the Images section
says so; subsequent lines of one commented-out block are one comment at the first line.
You skip a candidate only when there is already a thread at that line (closed or with the author's reply) or
when it is obviously false — then one sentence why in the report. Files from `not_checked` you check
in these categories yourself, by reading; likewise the whole PR when the command does not run at all — and you write
that in the report. What stays yours is everything the tool will not judge: magic strings,
duplication of an existing helper, architecture, a raw dict, names that lie, `Any`/`cast`/lying
annotations, error paths that end in success, real bugs and team habits (including `getattr` on a
known field, when the name is not a string).

**You do not assess tests stylistically.** In test files no remarks about clean code, names,
magic numbers, duplication or simplifications — only real bugs (a test that checks nothing,
checks the wrong thing or passes regardless of the code).

**Clean code and norms — only what matters.** You do not flag formatting, line length, import order,
docstrings, quote or comma style or the lack of type annotations. You flag:
- **wrong types** — `Any`/`object` where the type is known, an annotation that lies,
  `cast`/`as`/`type: ignore` instead of the correct type;
- **architecture and structure of the added code** — inconsistency with how the repo already does it (layers, e.g.
  business logic in an endpoint or component instead of in a service or hook; repo patterns and conventions;
  placement of files and modules; module naming), a new abstraction parallel to an existing one,
  dependencies pointing the wrong way;
- **simplifications** — code that can clearly be shortened, simplified or better structured: needless
  intermediate layers and wrappers, repeated blocks to extract, nesting to flatten (early
  return), a manual loop instead of a language idiom, a function or component to split. You say what to change it to,
  in one sentence;
- and what really harms: magic numbers and repeated literals instead of a named constant; duplicated logic where
  the repo already has a helper; a raw dict where the shape of the data is known (dataclass, model, enum);
  swallowed exceptions, bare excepts and error paths that end in success; names that lie; functions doing
  several things at once; dead and commented-out code; mutable default arguments. From PEP 8 only naming
  (snake_case for functions and variables, PascalCase for classes, UPPER_CASE for constants) and comparisons with None
  through is.

**What blocks and what closes a thread.** The vote is `request-changes` as long as at least one of my blocker threads is open;
open non-blocking threads do not hold back `approve`. The kind of remark decides what closes it:

| Kind of remark | Blocks? | What closes the thread |
|---|---|---|
| Logic, architecture, a possible bug, an edge case — something breaks (wrong value, data loss, exception, regression against develop, a validation hole) | yes | a fix or the author's argument that **you checked in the code yourself** and that held up. "Tak ma być", "zamierzone", "działa od lat", "jest dobrze", a meme — do NOT close |
| A change of behaviour that the author **confirms in a comment** as intended (a product or contract decision, not a bug) | yes | that author's confirmation — a silent resolve. Does not apply to the remark in the row above: the reply "intended" to a shown bug does not make it a decision |
| Style and clean code — any weight (norms, style habits, wrong types, names, magic numbers and strings, duplication, dead and commented-out code, raw dict, swallowed exceptions) | yes | only a fix or a substantive argument that you checked in the code (e.g. "taka konwencja w projekcie" → grep whether that convention really exists in the repo). "Tak ma być", "jest dobrze", "lepiej żeby została", "nie trzeba", a meme — do NOT close |
| A number in `sleep`/`delay_ms`/`k_sleep`/`setTimeout`… without a constant or a "why" comment | yes | a fix: a constant or an explanatory comment |
| Scope: a deviation from the PR description or the task content (reminder) | no | a fix or a comment from the author confirming the deviation — that is enough |
| PR description inconsistent with the code (general comment with an image) | no | a corrected description or the author's reply that the code is right |

You let through on the author's word **only two things**: a deviation from the PR description or the task and an intended
change of behaviour — both confirmed by the author's comment. Sloppy code you do not let through: a bug and style are
closed only by a fix or an argument that passed your verification in the code.

**The style weight is internal.** You assign every style remark a low / medium / high /
critical in your head — by how much it grates and how much it really harms (e.g. a magic number in a business threshold or
a swallowed exception on a payment path → high; `Any` where the type is known, `cast`, a lying
annotation → low). The weight does not decide blocking — every style remark blocks; it serves only the report.
You **never publish the weights** — neither in a comment nor in a reply; they go only to my report
next to that thread.

**Test results — outside the review.** On other people's PRs you do not check whether tests (including newly added ones)
pass: you do not read CI statuses, you do not run tests on the PR branch or on the target, and you do not
leave remarks or blockers about it — we do not nitpick that in PRs. For fixes on my PRs
you do not run tests unless the fix changes logic — then only the tests of the changed module.

**Team habits.** The rules from `habits list` came from reviewers' remarks on my PRs — they are the conventions
of this team and repo. Breaking a habit on someone else's PR is an ordinary inline remark: a label saying what is wrong (e.g.
"enumy do models.py"), without the habit number — there are no H0xx in comments. Walking through the habits
is mandatory in EVERY review, also a quick one (step 5 of the method below). A broken habit you treat like
a remark of its kind from the table "What blocks and what closes a thread": a habit about logic or architecture — like a bug,
a style habit — like style (it blocks). Habits about missing type annotations (e.g. H004) you do not apply on other people's
PRs, and in test files you do not apply style habits.

**Method for reviewing someone else's PR** — this is what distinguishes a review from skimming a diff:

1. **The ticket's context, not only the diff.** When the PR delivers a piece of a bigger ticket, you assess the
   requirements that this piece concerns. `git log origin/develop --grep <ID>` shows what
   earlier PRs of this ticket have already delivered, so as not to demand things already done.
2. **Code on both sides of the diff.** You read the code that produces the PR's input and the code that consumes its
   output (worker, contract, configuration). The heaviest bugs sit at the seam: a flag hard-coded at the producer, a retry limit at the consumer.
3. **First-hand semantics of tools.** When a remark depends on the behaviour of an external tool,
   library or protocol that cannot be run here, you check it in the source or the official
   documentation and cite file:line or a link — never from memory. What you have not checked you do not
   publish as a fact.
4. **Do the tests catch this class of bugs.** When the tests only mock a dependency and check argument lists, and the bug
   lies in the dependency's semantics, you say so plainly and propose one test against the real dependency.
5. **All habits, one by one.** You take the full list from `habits list --repo <worktree>` (global,
   the repo's languages, `repo:acme/<repo>`) and for EVERY habit you decide on the diff: does not apply / OK /
   broken (file:line). Habits about static-analysis categories (magic numbers)
   you settle from its result, without reading the diff a second time. Broken → inline remark without the habit number. In the report per PR: "nawyki: N
   sprawdzonych, złamane: H0xx (plik:linia), …". A review without this step is not finished — you
   do not vote until you have done it.

**The set of comments:** only inline at the exact line — every problem, scope reminder and
question to the author (§ 3) separately, one per thread. No general comment (an image, deployment, tests
also go inline at the line they concern, or only to the report) and no summary — except
"brak opisu PR" from the Images section.
**Explanation in human terms:** when the author asks for an explanation of the task or the blockers result from a misunderstanding of
the mechanism the task stands on, the explanation (why the task exists, how it should work, what
the main problem is) goes inline at the line with the main problem. Only it is not subject to the length limit.

**Replies to my comments (section `replies`)** → read and assess them according to the table "What blocks and what
closes a thread". **Resolve is silent:** when a thread closes, you give only `bb-sweep resolve <repo> <pr>
<id>` — no reply, confirmation or congratulations; you do not clutter the PR.
- fixed — checked in the code, not on trust ("Done" is not evidence) → silent resolve; if the vote
  hung only on the blockers you have just closed — you change it to `approve`;
- the author confirms in a comment a deviation from the PR description or the task, or an intended change of behaviour
  (a decision, not a bug) → silent resolve. Here you do not dig into the source of the decision;
- the author counter-argues (bug, logic, style) → **before you reply, you check their argument in the code**:
  behaviour on `develop` (`git show origin/develop:<file>`), history (`git log`, `git show <sha>`),
  library source, a grep over the repo for "that's the convention". The argument held up → one sentence
  "Racja — <evidence file:line or commit>" and resolve. Conceding is mandatory — you do not keep
  a thread on principle and do not publish a remark whose evidence has just collapsed. It did not hold up → a reply
  with evidence (file:line, commit, comparison with develop), the thread stays open, the vote `request-changes`;
- a reply with no argument against a bug or style remark ("tak ma być", "jest dobrze", "lepiej żeby została",
  "nie trzeba", "działa od lat", just an image) → the thread does NOT close. You reply: why this is not an
  argument, evidence from the code and what you expect (a concrete reason or a fix) — up to three sentences;
- the author claims to have fixed it and the code does not show it → one short sentence where it is missing
  (file:line), the thread stays open.

**Tone: assertive, with a light jab.** You do not let go, and your voice does not soften after the author's second refusal —
evidence decides the closing, not the number of rounds. A little sharpness is allowed: a short, apt opening
such as „„Dobrze” według czego?”, „Obrazek to nie uzasadnienie.”, „„Lepiej żeby została” to nie
argument.”, „„Done” — a w `plik:linia` dalej jest …”. The jab always stands next to evidence and always concerns
the code or the argument, never the person: no irony about competence, no exclamation marks, no capital letters.
A jab without evidence is spite — you do not publish that. In the same factual way you concede
when the evidence is on the author's side.

**Collective replies and replies outside my threads.** A PR on which I voted needs a look
when, after my last entry, any comment from the author or a new commit appeared — regardless of
which thread. The author does not always reply under every remark: sometimes they write one main comment
("fixes in commit X: …") or reply in another thread. Therefore on every PR of someone else with my vote
you read ALL comments added after my last entry — new main threads, replies in other people's
threads, mentions of me — and compare `source.commit.hash` with the commit I reviewed; a new
commit without a comment is also a signal to check my remarks. The `replies` section of `bb-sweep` shows
only threads in which I spoke, so it will not catch this by itself — do not treat its emptiness as
"nothing is waiting".
- You break a collective comment into points and assign each to my thread. You handle each thread
  as if the author had replied in it: you check in the code and do a silent resolve or, in one sentence IN THAT
  thread, point out what is missing.
- Points of the collective comment that do not correspond to any remark of mine (new changes, workarounds of my
  decisions from the PR description) you assess like an ordinary change in the code.
- My remark that is neither in the collective comment nor in the code stays open — without a
  reply under the collective comment; it goes only to the report.

I close only threads I opened myself — I do not touch other people's on someone else's PR. A thread of mine
closed by someone else I do not reopen or comment on.
I glance at other reviewers' remarks and check whether the author fixed what they reported. If not, you may leave a comment.
If a reviewer is wrong and gives an unjustified remark, I comment that it should not be done that way and the author's original intention was correct.
For Jira tasks I check the task and the epic, whether the change follows the plan.

**All my threads closed (section `approve`)** → change the vote to `approve`. This section lists
exactly those PRs: my vote is `changes_requested` and none of my threads is open any more. You change the vote
to `approve` also when only my non-blocking threads remained open (a scope reminder, a PR
description inconsistent with the code) — the `approve` section will not show those, so you check that yourself while handling
`replies`. An open style thread blocks, regardless of weight.

## 3. Decisions — the author is asked

Decisions and architectural changes are settled by the **PR author**. You ask them directly in the thread. Scope alone
(excess and missing items against the task) does not belong here — it is the reminder from § 2, closed when the author says that
it is intended. You tag nobody: the author gets a notification for every comment on their PR.

You ask the author when:

- the remark is accurate, but the fix is a **really big change**: it touches a contract (API, data format,
  database schema, migration), requires redesigning a flow or changes in several modules or
  repositories, or changes behaviour visible to a user or another service — the question is:
  do we fix it now or do we create a separate task;
- within the task's scope a product or contract decision is made (a change of API, data format,
  policy) that the ticket does not settle.

**Threshold.** The number of lines does not make a change big — what counts is whether it changes behaviour or a contract.
A mechanical refactor inside the PR (raw dict → Pydantic or dataclass, magic number → named constant,
extracting a function, names, types, a missing test) is an ordinary review remark: you write it to the author
or fix it yourself, even when it touches a dozen places. You ask the author for a decision, not for work.

Form: one or two sentences — what the problem is and the options to choose from. One question per thread, in Polish.
When the author replies that it stays as it is, you close the thread without further questions — this applies to questions about a decision
(fix now or a separate ticket, a product or contract choice). When the thread shows a bug,
"it stays" does not close it: the table and the reply rules of § 2 apply.

A thread with a question to the author **stays open** until their reply: you do not close it and do not count it as
closed. When the question concerns a real bug, the vote on that PR is `request-changes` until
it is settled; when it concerns scope only (a separate ticket), you may vote `approve` and leave the
thread with the question open.

**On my PRs I am the author.** You do not settle such a decision and do not ask anyone about it in the
thread — you leave it to me and list it in the report: repo, PR, link to the thread, what the decision is about.

Every question to the author lands in the report: repo, PR, link to the thread, what I asked.

## 4. Technical

REST API v2.0, credentials from `~/.config/bitbucket/credentials`. Empty POSTs (`/approve`,
`/request-changes`, `/comments/<id>/resolve`) must go **without** `Content-Type`. The comment listing
does not return `resolution` — a single GET per comment. When my checkout of the repository is on another
branch or has uncommitted work, I make fixes in a worktree in the scratchpad, never through a
checkout in Sebastian's directory. Commit: one sentence in the imperative mood, max 7 words, without `-s` and without any trailers (Signed-off-by, Co-Authored-By).

## 5. Report

One status per the `review` skill plus: what was fixed (SHA + branch), what was rejected and why, where
and how I voted, what was closed, what I am waiting for from people, what was skipped as a draft, which decisions beyond the
ticket I asked the authors about (repo, PR, thread link), which scope reminders I left and which I
closed after the reply "intended", for every style remark its internal weight
(low/medium/high/critical), which counter-arguments of the authors I verified in the code and with what result
(held up → "Racja" and resolve, with evidence; did not hold up → my reply with evidence, thread open), which decisions on my PRs
are waiting for me, and new and bumped
habits (id, rule, source) —
so that I can reject one through `habits drop <id>`.
