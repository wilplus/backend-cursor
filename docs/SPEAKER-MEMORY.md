# Speaker memory: how Will learns about each speaker

> **Label: Reference** · how something works today; where it differs from the In force docs, they win. Every doc and its label: [`README.md`](../README.md) (N106).

> **2026-10-21 (N102):** the whole picture of what the app learns from is [`docs/LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md). This file keeps the detail of Will's memory.

Founder, 2026-10-20 (WIL-74): "a permanent part of our application,
compartmentalized". No model is retrained. Each speaker has one short
private note that the AI rewrites from what happened, and Will reads it.

```
what happens                 kept for good              rewritten              read by
──────────────────────       ─────────────────────      ──────────────────     ─────────────────────────
answer to "Did this help?" ─► speaker_memory_events ──► speaker_memory.note ─► Will in the chat (librarian)
answer to Will's question  ─►  (kind "answer", N82)
a Take's outcome           ─►  (raw inputs, the asset)    (≤ 5 lines, plain)  ─► the summary after a Take
                                                          ▲
                                       the founder reads / corrects it in admin
```

## The one module

Everything lives in `services/speaker_memory.py`. Other code only calls its
public functions:

| Function | Who calls it | What it does |
|---|---|---|
| `record(db, user_id, kind, payload, take)` | `feedback_check._save` (every answer), `take_summary.summary_message` (every Take), `tempo_stretch.keep_tries` (each tempo game, kind `take` with a `tempo` part: the stretch's reading, each try, how it ended, and the dot's paths; N166) | keeps the event, rewrites the note in the background |
| `note_for(db, user_id)` | `chat_query._librarian`, `take_summary.memory_facts` | the current note, `''` when none |
| `prompt_block(note)` | `chat_query._librarian` (as `app_context["memory"]`) | the note as Will's private prompt block |
| `history_for(db, user_id, question)` | `chat_query._librarian` (added to `app_context["memory"]`) | the pieces of the speaker's own history that match the question, as Will's private block (see Lookup) |
| `set_note(db, user_id, note)` | `GET/PUT /v2/admin/people/<id>/speaker-memory` (founder only) | the founder's correction |
| `rebuild(db, user_id, take)` | by hand, after a model change | the note from every stored event |

A new source of learning (for example what speakers ask Will about) is a new
`kind` in `KINDS`, the migration's CHECK, and one line in `_event_line`.
Nothing else changes.

## Lookup (step 1, founder 2026-10-20)

Before Will answers in the chat he looks up the speaker's own history:
`services/speaker_lookup.py`, reached through `history_for`. A simple
lookup, no vector search, no embeddings, no AI call, no migration.

| Source | Where | Ownership | Bound |
|---|---|---|---|
| Their Takes' transcripts | `v2_sessions.slide_transcripts`, one piece per slide | `user_id` = the speaker; finished spoken Takes only; erased or archived projects left out | newest 6 Takes |
| What their coach sent | `coach_take_words` with `shared_at` (`text`, and the video's `transcript`); `exercise_coach_requests` with `shared_at` and a written answer (`answer_text`) | only on the Takes above; moment answers also `owner_user_id` = the speaker. Never `draft_text` | 12 of each |
| What they told Will | `lounge_messages`, role `user`, kind `text` | `user_id` = the speaker. Never Will's replies, never an answer to "Did this help?", not the newest 24 rows (Will already reads them) | 120 rows |

Each piece is ranked by the words it shares with the question (lowercased,
stopwords out, light stemming), times a small weight (coach 1.2, Take 1.0,
chat 0.9); ties go to the newest. The top 5 reach Will, each cut to about
200 characters, with a plain label ("Take 2 transcript, slide 3", "your
coach's word on Take 2", "you asked earlier"). The block tells Will it is
private, to steer by, and that he may quote at most a few of the speaker's
own words, never their answers to "Did this help?", never a number, score
or verdict. Its wording is drift-locked (`speaker_memory.lookup_block`).

**Permission (founder 2026-10-20).** Only a Take whose processing
authorization is in force for this speaker gives excerpts, and the coach's
words and moment answers on a Take follow their Take. `_takes_in_force`
resolves each Take's acquisition principal as the recording pipeline does
(`ProcessingAuthorizationService.resolve_acquisition_principal`, from the
Take's owner, account and recording) and asks `require_current(principal,
operation="ai_conversation")`, the chat's own operation: in force means an
accepted, current receipt, not withdrawn, not waiting for a re-acceptance,
not blocked. A refused principal leaves its Takes out. If the check cannot
be made, no Take-based excerpt goes (fails closed). The speaker's own chat
messages belong to no Take: they ride the chat's own call, which
`routes.v2.processing_authorization.phase1_provider_route` already binds to
the caller's current authority (`ai_conversation`), the strictest rule that
exists for chat content. While the gate is off every Take passes, as on
every other surface.

**Chat history (founder confirmed, 2026-10-20).** Reading the speaker's own
earlier messages is fine because nothing is stored and it only answers the
same speaker. This is not the "thread never feeds profile" rule of the
`lounge_messages` migration being relaxed: step 2, feeding the private note
from chat history, needs the founder's OK again.

The reads run side by side (`services.parallel`): Takes and chat first,
then the project check, the authorization check and the coach's words; the
note is read alongside.
Any failed read leaves its source out; nothing raises, and with no block
Will answers as before. Guarded by `tests/test_will_looks_up_history.py`.

## The summary looks back too (step 3, founder 2026-10-20)

The summary after a Take (`services/take_summary.py`) can point back to an
earlier Take ("in Take 2 the pricing line rushed; this time it landed").
It has no question, so its query is the current Take's key words: the
helper words, the talk's title and slides and what they said this Take,
the 24 most frequent content words (`speaker_lookup.key_terms`).
`speaker_lookup.earlier_takes` then ranks only the transcripts of the
speaker's **older** Takes: the arc's Takes before this one, or another
project's Take recorded before it; never this Take (already in the prompt),
never a later one, never coach words or chat. The same project comes
first. The same project and authorization checks as the chat apply, and a
failed check lets no Take through. At most 3 pieces reach the prompt as one
private fact (drift-locked, `take_summary.earlier_facts`):

> What they said in earlier Takes (private, to steer by; you may point back
> to one moment in a few of their own words, never more): Take 2: "…"

The reply still passes `_clean`: a number (outside a Take number), drift
from the signed lines or a closing question still gives the signed copy.
The lookup starts off the request right after the moments are read and
runs beside the other reads; the summary waits at most 1 second for it
(`_EARLIER_BUDGET`). Too slow, failed, or nothing found: no fact, and the
summary is written exactly as before. Guarded by `tests/test_take_summary.py`
(O6).

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
