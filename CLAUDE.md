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

1. **No scores, numbers or verdicts shown to speakers.** Feedback is in words.
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

## How to ship

- Branch from `main` → PR → checks green → squash-merge. "Merge when green" is standing permission.
- Check locally before pushing: backend `bash scripts/local_ci.sh`, frontend `bash scripts/local_ci.sh`.
- **Merging a migration runs it in production.** Make it idempotent (`IF NOT EXISTS`) and never drop anything. Set any environment variable it needs on every Railway service *before* merging.
- New migrations get an outside review (GPT or Grok) before merging.
- Every speaker's recording and every provider call goes through the processing-authorization path. No shortcuts.

## Before you start a task, ask one question

**Does this make the transcript, the Ideal Text or the feedback better, or
does a task in progress need it?** If not, say so and ask before building it.

## Security

Never ask for or reuse passwords, tokens or keys in chat. Keys go into
environment settings.
