# Speaker memory: how Will learns about each speaker

Founder, 2026-10-20 (WIL-74): "a permanent part of our application,
compartmentalized". No model is retrained. Each speaker has one short
private note that the AI rewrites from what happened, and Will reads it.

```
what happens                 kept for good              rewritten              read by
──────────────────────       ─────────────────────      ──────────────────     ─────────────────────────
answer to "Did this help?" ─► speaker_memory_events ──► speaker_memory.note ─► Will in the chat (librarian)
a Take's outcome           ─►  (raw inputs, the asset)    (≤ 5 lines, plain)  ─► the summary after a Take
                                                          ▲
                                       the founder reads / corrects it in admin
```

## The one module

Everything lives in `services/speaker_memory.py`. Other code only calls its
public functions:

| Function | Who calls it | What it does |
|---|---|---|
| `record(db, user_id, kind, payload, take)` | `feedback_check._save` (every answer), `take_summary.summary_message` (every Take) | keeps the event, rewrites the note in the background |
| `note_for(db, user_id)` | `chat_query._librarian`, `take_summary.memory_facts` | the current note, `''` when none |
| `prompt_block(note)` | `chat_query._librarian` (as `app_context["memory"]`) | the note as Will's private prompt block |
| `set_note(db, user_id, note)` | `GET/PUT /v2/admin/people/<id>/speaker-memory` (founder only) | the founder's correction |
| `rebuild(db, user_id, take)` | by hand, after a model change | the note from every stored event |

A new source of learning (for example what speakers ask Will about) is a new
`kind` in `KINDS`, the migration's CHECK, and one line in `_event_line`.
Nothing else changes.

## Storage (migration 0480)

- `speaker_memory_events`: the raw inputs, kept for good. They are the asset:
  a better or different model (Mistral, a newer GPT) rebuilds every note from
  them with `rebuild`.
- `speaker_memory`: one row per speaker: the note, who wrote it last (`ai` or
  `founder`), the model, when.
- Both are plain rows in our own Supabase database, export as CSV or SQL like
  any table, and are deleted with the account (`data_purge_registry`).

## Rules that hold

- Nobody but the founder sees the note. Will never quotes it, never repeats a
  speaker's answer back, never says it keeps one.
- No numbers, scores or verdicts in it (CLAUDE.md, Never 1): a rewrite with a
  digit is refused and the old note stays (`clean_note`).
- Every AI call goes through the processing-authorization path, in the
  protected scope of the Take the event came from.
- The speaker's flow never waits on it: recording an event never raises, and
  the rewrite runs off the request.
- The prompt is drift-locked (`services/prompts/pending.py`,
  `speaker_memory.system`).

## The guard

`tests/test_speaker_memory.py` fails if an answer stops being kept, if the
note stops reaching Will in the chat or in the summary, if a number gets
through, or if the note survives an account deletion. CLAUDE.md lists it
under "Promises that must never break".
