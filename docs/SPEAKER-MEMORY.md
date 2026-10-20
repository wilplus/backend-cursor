# Speaker memory: how Will learns about each speaker

Founder, 2026-10-20 (WIL-74): "a permanent part of our application,
compartmentalized". No model is retrained. Each speaker has one short
private note that the AI rewrites from what happened, and Will reads it.

```
what happens                 kept for good              rewritten              read by
──────────────────────       ─────────────────────      ──────────────────     ─────────────────────────
answer to "Did this help?" ─► speaker_memory_events ──► speaker_memory.note ─► Will in the chat (librarian)
a Take's outcome           ─►  (raw inputs, the asset)    (≤ 5 lines, plain)  ─► the summary after a Take
a Take's transcript        ─►                             ▲
what the coach SENT        ─►                             │
their own chat message     ─►  (stored; rewrites batched) │
                                       the founder reads / corrects it in admin
```

## The one module

Everything lives in `services/speaker_memory.py`. Other code only calls its
public functions:

| Function | Who calls it | What it does |
|---|---|---|
| `record(db, user_id, kind, payload, take, arc)` | `feedback_check._save` (every answer), `take_summary.summary_message` (every Take) | keeps the event, rewrites the note in the background |
| `record_later(db, user_id, kind, payload, take, arc)` | the step-2 sources below | the same, entirely off the caller's thread; the Take's speaker when `user_id` is None; the same event is kept once |
| `forget(db, user_id, takes)` | `user_sessions._hard_delete_sessions_for_user`, `ProjectPurgeOrchestrator.run` | an erased Take's events go, the note is emptied and rebuilt from what remains |
| `note_for(db, user_id)` | `chat_query._librarian`, `take_summary.memory_facts` | the current note, `''` when none |
| `prompt_block(note)` | `chat_query._librarian` (as `app_context["memory"]`) | the note as Will's private prompt block |
| `history_for(db, user_id, question)` | `chat_query._librarian` (added to `app_context["memory"]`) | the pieces of the speaker's own history that match the question, as Will's private block (see Lookup) |
| `set_note(db, user_id, note)` | `GET/PUT /v2/admin/people/<id>/speaker-memory` (founder only) | the founder's correction |
| `rebuild(db, user_id, take)` | by hand, after a model change | the note from every stored event |

A new source of learning is a new `kind` in `KINDS`, the migration's CHECK,
and one line in `_event_line` (step 2 below added three). Nothing else
changes.

## Step 2: the note learns from transcripts, coach words and chat (founder 2026-10-20)

The founder's "go ahead with step 2" (chat, 2026-10-20) includes the OK
that chat history may now feed the note. Three new kinds:

| Kind | Recorded by | Payload (small) | Never |
|---|---|---|---|
| `transcript` | `lab_recording._learn_from_the_transcript`, right after `persist_recording_transcript` (stage 5), handed off at once | `opening`, `closing`: about 150 characters each | a re-read, a paired Take, the coach-only import lane, a visitor |
| `coach_word` | `coach_take_word.save_take_word` (`_will_learns`) when the word is shared, and on every save of a shared word; `coach_word_pairs.transcribe_take_word_video` when a shared video's transcript lands; `exercise_coach_requests.resolve_request` (`_will_learns`) for a shared moment answer in words | `source` (`take_word`, `take_video`, `moment_answer`), `excerpt` (≤ 300), `edited` | a word or answer never shared, `draft_text`, an exercise choice |
| `chat` | `chat_query.finish_chat_turn` (`_will_learns`) | `excerpt` (≤ 300) of the speaker's own message | Will's reply, an answer to "Did this help?" (intent or row metadata `feedback_check`), a number typed under the WhatsApp ask, the Life Panel |

Every event stores its `take_session_id` and `arc_id` (the project) where
there is one; a chat message has neither.

**When the note is rewritten.** Answer, take, transcript and coach-word
events rewrite at once (about two or three calls per Take). A chat message
is stored, and rewrites only when it is the speaker's first message of the
day (UTC) or every 10th that day (`_rewrites_now`): about one call a day for
a typical speaker instead of one per turn. A rewrite reads the newest 12
non-chat events and the newest 6 chat messages; `rebuild` reads every
non-chat event and the newest 40 chat messages. Each call is the cheap
model (`SPEC_SPEAKER_MEMORY`, about 1.5k tokens in and 150 out).

**No digits in what the model reads.** Every quoted line goes through
`_words_only`: a word carrying a digit or `%` is dropped, so "we grew 20% in
2025, three times faster" reads "we grew in three times faster". A number
said in words stays. `clean_note` still refuses a note with a digit.

**Permission.** Before any rewrite, `_readable` keeps only the events that
may reach the model now: an event on a Take only while the Take is still
the speaker's, in a project they have not erased or archived
(`speaker_lookup.hidden_arcs`), and its principal holds current
`ai_conversation` authority
(`speaker_lookup.takes_in_force`, as the lookup), an event on no Take only
while the speaker's own principal does (`_chat_principal`, the rule of
`phase1_provider_route`). A check that cannot be made keeps its events out.
The call then runs in the Take's protected scope, or with no Take in the
chat's (`ProviderCoordinates(principal, None, None)`).

**Deletion.** The events go with the account (`speaker_memory_events`, by
`user_id`), with the Take (`speaker_memory_events_by_take`) and with the
project (`speaker_memory_events_by_project`, by `arc_id`). A project purge
leaves the account's own rows (chat) and the note, both placed
`ACCOUNT_LEVEL`, and once it is done the note is emptied and rebuilt from
what remains (`forget`). A Take its speaker deletes from the library
(`_hard_delete_sessions_for_user`) takes its events and the note is rebuilt
the same way.

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
words and moment answers on a Take follow their Take. `takes_in_force`
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
same speaker. Step 2, feeding the private note from chat history, has the
founder's OK (2026-10-20, above).

The reads run side by side (`services.parallel`): Takes and chat first,
then the project check, the authorization check and the coach's words; the
note is read alongside.
Any failed read leaves its source out; nothing raises, and with no block
Will answers as before. Guarded by `tests/test_will_looks_up_history.py`.

## Storage (migrations 0480, 0482)

- `speaker_memory_events`: the raw inputs, kept for good. They are the asset:
  a better or different model (Mistral, a newer GPT) rebuilds every note from
  them with `rebuild`.
- `speaker_memory`: one row per speaker: the note, who wrote it last (`ai` or
  `founder`), the model, when.
- Both are plain rows in our own Supabase database, export as CSV or SQL like
  any table, and are deleted with the account (`data_purge_registry`); the
  events also with their Take and project.
- 0482 widens the kind CHECK to the five kinds and adds the nullable
  `arc_id` with two partial indexes (by Take, by project).

## Rules that hold

- Nobody but the founder sees the note. Will never quotes it, never repeats a
  speaker's answer back, never says it keeps one.
- No numbers, scores or verdicts in it (CLAUDE.md, Never 1): a rewrite with a
  digit is refused and the old note stays (`clean_note`).
- Every AI call goes through the processing-authorization path, in the
  protected scope of the Take the event came from, or the chat's own for a
  chat event; lines whose authorization is gone are left out.
- The speaker's flow never waits on it: recording an event never raises, and
  the rewrite runs off the request.
- The prompt is drift-locked (`services/prompts/pending.py`,
  `speaker_memory.system`).

## The guard

`tests/test_speaker_memory.py` fails if an answer stops being kept, if the
note stops reaching Will in the chat or in the summary, if a number gets
through (into the note or the model's input), if the note survives an
account deletion, if a transcript, a sent coach word or a chat message stops
reaching the note's input, if a draft, Will's reply or a "Did this help?"
answer is learned from, if an event survives its project or Take, or if a
line whose authorization is gone reaches the model. CLAUDE.md lists it
under "Promises that must never break".
