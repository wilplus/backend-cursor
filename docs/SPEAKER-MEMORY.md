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
| `record(db, user_id, kind, payload, take)` | `feedback_check._save` (every answer), `take_summary.summary_message` (every Take), `tempo_stretch.keep_tries` (each tempo game, kind `take` with a `tempo` part: the stretch's reading, each try, how it ended or that they skipped it, and the dot's paths; N166) | keeps the event, rewrites the note in the background |
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

**Broad speaking view (N663).** A focused question still uses word overlap.
An explicit request for an overall view of the speaker's skills, strengths,
patterns, progress or approach instead receives a bounded, source-diverse
sample from the same authorised history (at most eight pieces, with repeated
slides from one Take prevented from crowding out other evidence). This is the
smallest useful retrieval change: it keeps one lookup path and one privacy
gate instead of adding a second memory system. The answer combines that
private evidence with the curated speaking-science Master Document. It must
separate direct observation from tentative interpretation and may not infer a
stable personality trait, diagnose anxiety, or label challenge versus threat
from voice alone. A short greeting such as `hej` is routed as conversation
before the model classifier, so an old project answer cannot replace the
latest social turn; the immediate typed language still controls the reply.

The chat also sends the recent visible turns and a bounded current-project
context with the question. These are conversational context, not new
evidence: Will may use them to resolve a follow-up or name the project, but
must not invent a metric, pattern or claim that is absent from the supplied
history and project data.

| Source | Where | Ownership | Bound |
|---|---|---|---|
| Their Takes' transcripts | `v2_sessions.slide_transcripts`, one piece per slide | `user_id` = the speaker; finished spoken Takes only; erased or archived projects left out | newest 6 Takes |
| What their coach sent | `coach_take_words` with `shared_at` (`text`, and the video's `transcript`); `exercise_coach_requests` with `shared_at` and a written answer (`answer_text`) | only on the Takes above; moment answers also `owner_user_id` = the speaker. Never `draft_text` | 12 of each |
| What they told Will | `lounge_messages`, role `user`, kind `text` | `user_id` = the speaker. Never Will's replies, never an answer to "Did this help?", not the newest 24 rows (Will already reads them) | 120 rows |

For a focused question, each piece is ranked by the words it shares with the
question (lowercased, stopwords out, light stemming), times a small weight
(coach 1.2, Take 1.0, chat 0.9); ties go to the newest. The top 5 reach Will.
For N663's broad view, the most recent distinct source-and-Take groups go
first and then fill to eight. In both cases each excerpt is cut to about 200
characters, with a plain label ("Take 2 transcript, slide 3", "your coach's
word on Take 2", "you asked earlier"). The block tells Will it is private,
to steer by, and that he may quote at most a few of the speaker's own words,
never their answers to "Did this help?", never a number, score or verdict,
and never turn an interpretation into a personality or stress-state claim.
Its wording is drift-locked (`speaker_memory.lookup_block`).

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

A completed Take closing (`metadata.next_take`, including the existing
"Good job. See you next time." copy) is walk state, not prior dialogue. It is
left out of the bounded chat context before Will answers a later typed turn;
the closing can therefore never be mistaken for an answer to that new turn.

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

## Speaking Coach context, 18 November 2026

Under N663 and N665, `services/speaking_coach.py` reads the existing private
speaker note alongside owner-scoped, finished Takes across active projects,
spoken transcripts, uploaded slide text, current Ideal Text, qualitative
delivery cues and coach words shared with the speaker. Source labels keep
speaker reports, observations and interpretations distinct. Sparse evidence
still produces the best supported answer, with uncertainty stated.

The note continues to shape replies privately and is never quoted or
serialized in a response. Private admin notes and coach drafts stay out.
Project questions and answers stay in Project Chat; they are not replayed
as Speaking Coach conversation. This is a bounded derived packet rather
than a new profile store. Its source fingerprint, explicit invalidation and
short TTL refresh it. Archive/deletion and processing authority fail closed.
The retrieval, model and retry bounds are documented in
[`PERF-chat-and-ideal-text.md`](PERF-chat-and-ideal-text.md).

Talk-specific requests find the project and Take in the speaker's index
before reading their words. This reaches older named projects and keeps the
recording on a follow-up. The coach uses the talk's saved audience and call
to action, compares matching slides or deckless openings and endings, and
asks for clarification when a talk is ambiguous.

The scoped lookup ranks transcript passages, delivery observations, current
Ideal Text and shared coach feedback by keywords and by meaning. It uses one
authorized batch of up to 48 passages with a two-second timeout and falls
back to keyword ranking.
Coach references resolve to the cited Take transcript, Ideal Text or shared
feedback. A practice request may add one matching exercise from the reviewed
catalogue. Private speaker memory guides coaching preferences and stays out
of search and source links.

When a speaker asks what a Take shows about them, the coach gives a direct
listener impression in everyday language. A short cue from the same passage
ties that impression to what the speaker said and how they said it. When
the speaker shows resolve or names a next step, the follow-up asks what
helps them draw on that strength. A practice request can connect the moment
to one reviewed exercise. The coach can reflect a value the speaker has
stated, including faith, and ask about an action the speaker can choose.

The approved example combines the cue, the takeaway, and the follow-up in
the speaker's everyday language.

> Mocniejsze drugie „Nie chcę” oraz szybsze podkreślenie „że się nie uda” brzmią, jakbyś miał już dość tego wewnętrznego głosu. Chwilę później mówisz „Jutro powiem wprost, czego potrzebuję”. Słyszę, że coś pomaga ci się temu głosowi przeciwstawić. Skąd bierzesz tę wewnętrzną siłę?

One batch reads the saved snippets for the selected, authorized Takes.
Existing qualitative delivery descriptions and plain-language readings of
saved pace, pauses, pitch and volume stay with the words of their original
passage. Measurements for a whole passage support observations at that
scope. With words alone, the coach says its reflection comes from the words.
A passage receives a slide reference only when its spoken words match one
saved slide in that Take.

The [Speaking Coach golden cases](../tests/evals/golden/speaking_coach.jsonl)
exercise questions about what a Take reveals about the speaker's communication.
They grade observations about specific words and delivery, tentative readings
the speaker can confirm, and a follow-up that helps understand the speaker.
The same transcript has firmer, measured, and missing delivery evidence.
A second pair uses different recorded pace and pause measurements for the
same words and exercises the app's delivery conversion.
Other cases cover choosing a fitting exercise and reflecting faith in the
speaker's own terms when they bring it up. The synthetic Takes run through
the production coach reply path. The live run calls the configured model and
the separate semantic grader.

```sh
python tests/evals/run_prompt_evals.py --surface speaking_coach
```

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
  In the walk this is checked in code (`walk_voice.check`, N565 item 2): a
  draft that shares four words in a row with the note, quoted or not, is
  refused, unless the speaker also said those words in the Take.
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
