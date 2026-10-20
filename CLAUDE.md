# CLAUDE.md — WillpowerLab (one page)

## What we are building

A speaker records a Take. The app turns it into a transcript, one paragraph
per slide, the **Ideal Text**, and gives evidence-backed feedback after every
Take. Then they record the next Take. That loop is the product.

Second priority: coach review, Confident Voice and practice. These never
slow the loop down.

This repo: **backend** (Flask, Railway, Supabase). The frontend is
`wilplus/frontend-cursor` (Next.js, Vercel).

## Never

1. **No scores, numbers or verdicts shown to speakers.** Feedback is in words. A processing-progress percentage and a token price are not about the speaker and are allowed (founder, 2026-10-19).
2. **No coach sees the machine's guess before answering.** Coach judgements stay blind.
3. **Never break record → process → Ideal Text → next Take.** Coaches and exercises are never in the way.
4. **No new words on screen without the founder's OK.**
5. **The Ideal Text is only what the speaker said in their latest Take.** Their helper words stay until they pick new ones. Every old version stays in the history.

## Screens that are locked

Ideal Text and the Feedback walk, the coach panel, the recording screens and
the consent screens are finished designs. Build them exactly as their
prototypes show. To change one, ask the founder first. The prototypes and
lock files are listed in `docs/LOCKS.md`. The earlier, longer
version of this page is `docs/history/CLAUDE-2026-10-11.md`.

The Feedback walk and the chat have one page, in the frontend repo:
`docs/flows/feedback-walk-and-chat.md` (the rules as they stand, what is in
flight, what is open, one line per change). A backend change to a rule of
that flow is a line on that page, never a new file: the backend PR names the
frontend PR that updates it. Its entry here in `docs/SPEC-DECISIONS-LOG.md`
is two lines and a link. The other locked screens get a page of the same
shape the next time one of them is changed.

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
  summary (`services/speaker_memory.py`, `docs/SPEAKER-MEMORY.md`, guarded by
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
