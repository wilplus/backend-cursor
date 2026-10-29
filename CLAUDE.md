# CLAUDE.md — WillpowerLab (one page)

## What we are building

A speaker records a Take. The app turns it into a transcript, one paragraph
per slide, the **Ideal Text**, and gives evidence-backed feedback after every
Take. Then they record the next Take. That loop is the product.

Second priority: coach review, Confident Voice and practice. These never
slow the loop down. The plan (diagnosis, practice days, calls) chooses what
each walk practises; when it competes with the loop, the loop wins (N129,
N178).

This repo: **backend** (Flask, Railway, Supabase). The frontend is
`wilplus/frontend-cursor` (Next.js, Vercel).

## Never

1. **No scores, numbers or verdicts shown to speakers.** Feedback is in words. A processing-progress percentage and a token price are not about the speaker and are allowed (founder, 2026-10-19), and so is a count of where the speaker is in their plan ("Practice 2 of 9"); their own 1 to 10 answers are never shown back (N178).
2. **No coach sees the machine's guess before answering.** Coach judgements stay blind.
3. **Never break record → process → Ideal Text → next Take.** Coaches and exercises are never in the way; the plan's questions come once, before the first Take, and never stop the speaker from recording it; before any other Take, only the feelings check, one tap (N136, N140, N178, N262, N271).
4. **No new words on screen without the founder's OK.**
5. **The Ideal Text is only what the speaker said in their latest Take.** Their helper words stay until they pick new ones. Every old version stays in the history.

## Screens that are locked

Ideal Text and the Feedback walk, the coach panel, the recording screens and
the consent screens are finished designs. Build them exactly as their
prototypes show. To change one, ask the founder first. The prototypes and
lock files are listed in [`docs/LOCKS.md`](docs/LOCKS.md). The earlier, longer
version of this page is [`docs/history/CLAUDE-2026-10-11.md`](docs/history/CLAUDE-2026-10-11.md).

The Feedback walk and the chat have one page, in the frontend repo:
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) (the rules as they stand, what is in
flight, what is open, one line per change). A backend change to a rule of
that flow is a line on that page, never a new file: the backend PR names the
frontend PR that updates it. Its entry here in [`docs/SPEC-DECISIONS-LOG.md`](docs/SPEC-DECISIONS-LOG.md)
is two lines and a link. Every other locked screen has a page of the same
shape in the frontend's `docs/flows/`: the recording screens, the consent
screens, the Ideal Text page and the AI voice in practice (N107). The plan
has one too, [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md):
a rules page, locked once its first part is built (N160, N178).

## One source of truth

The single source of truth is this backend repo's `main`, read in this order:
[`docs/SPEC-DECISIONS-LOG.md`](docs/SPEC-DECISIONS-LOG.md) (the founder's dated decisions), then
[`docs/CANONICAL_PRODUCT_CONTRACT.md`](docs/CANONICAL_PRODUCT_CONTRACT.md) (the numbered clauses), then
[`docs/LOCKS.md`](docs/LOCKS.md) and the `FOUNDER-LOCK-*.md` files with their prototypes.
Nothing is in force until it is written there and merged: not a decision said
only in chat, a PR description, an open branch, or the frontend's own docs.
Write every founder decision made in chat into the decisions log right away,
in its own small docs PR, never bundled with code that waits for review.
Where the code on main disagrees with these docs, the docs win and the code
is a bug to fix (founder, 2026-10-21, N95). The frontend's flow pages
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) and [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md) also
count for their flows, because the frontend design-lock guard requires them
to change together with the code. Every doc in both repos, with its label
(In force, Reference, History or Archive) and a link, is listed in
[`README.md`](README.md) (N106).

## Docs

Every doc is listed in [`README.md`](README.md) with its label (N106), and
every part of the code has one home doc, in the table
[Home docs for the code](README.md#6-home-docs-for-the-code). Don't start a
new doc: write what changed into the code's home doc, or into the pull
request. Handoffs and prompts for coding agents go in the pull request
description, not in a file. New code that no row covers gets a row in the
same pull request. A new doc needs the founder's OK, written as
`Founder-Approved:` on its line in `README.md`. `scripts/doc_guard.py` checks
all of this in CI (N107, N111). It also checks the decisions log: numbers are
unique and go up, every N a rules page cites is an entry, and every new entry
ends by naming where it landed ("The rules:" or "No rules page").

## How to ship

- Branch from `main` → PR → checks green → squash-merge. "Merge when green" is standing permission.
- Check locally before pushing: backend `bash scripts/local_ci.sh`, frontend `bash scripts/local_ci.sh`.
- **Merging a migration runs it in production.** Make it idempotent (`IF NOT EXISTS`) and never drop anything. Set any environment variable it needs on every Railway service *before* merging.
- New migrations get an outside review (GPT or Grok) before merging.
- Every speaker's recording and every provider call goes through the processing-authorization path. No shortcuts.

## Before you start a task, ask one question

**Does this make the transcript, the Ideal Text or the feedback better, or
does a task in progress need it?** If not, say so and ask before building it.

## Replacing a feature

Before replacing or redesigning anything, list everything the old one does,
including every backend call and side effect, and keep each one in the new
version. "One in, one out" moves the old tests' promises into the new tests
before the old tests go. Before merging, say what stops happening.

Promises that must never break:

- Every moment a speaker meets reaches a coach (alarm:
  `coach_moments_queue.reach_alarm`, backend).
- The coach's link opens the coach's feedback, whatever else is processing.
- Will learns about each speaker: every answer and every Take's outcome is
  kept, and Will reads the speaker's private note in the chat and in the
  summary (`services/speaker_memory.py`, [`docs/SPEAKER-MEMORY.md`](docs/SPEAKER-MEMORY.md), guarded by
  `tests/test_speaker_memory.py`).

## How to test (founder, 2026-10-12)

Test business behaviour and contracts, not lines of code. Before writing a
test, ask:

- **Does it map to something a speaker, coach or the founder cares about?**
  Test public routes, service contracts and user outcomes, not private
  helpers. A refactor that keeps the output right must not break a test.
- **Is it a duplicate?** If another test already covers it, don't add one.
- **Is it testing someone else's code?** Don't test libraries, the database
  driver or the framework. Test only our own logic.
- **Is it a style or layout check?** No snapshot or CSS tests unless a
  break would stop the app working.
- **Is it an unlikely edge case?** Handle it with defensive code (a
  fallback, a try/except), not with many test variations.
- **ML behaviour:** a strange model result becomes a new row in the one
  golden evaluation set, never a new test script. Bad input data is caught
  by validation in production code, not by mock datasets.
- **One in, one out:** a feature that replaces an old one deletes the old
  one's tests.
- **Time budget:** a test that takes more than a few seconds or mocks
  several services is the wrong test. Make it a small integration check.
- **No coverage target.** Cover the critical path (record → Ideal Text →
  feedback → next Take, consent, deletion, payments), not boilerplate.

## Security

Never ask for or reuse passwords, tokens or keys in chat. Keys go into
environment settings.
