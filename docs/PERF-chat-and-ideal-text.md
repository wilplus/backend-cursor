# Load-time finding — chat + Ideal Text (ticket 7, 2026-07-26; audit refreshed 2026-11-16)

> **Label: Reference** · how something works today; where it differs from the In force docs, they win. Every doc and its label: [`README.md`](../README.md) (N106).

## Chat integration, 18 November 2026

Under N663 and N665, the existing authorized `POST /v2/chat/query` remains
the single transport, including its durable claim, terminal receipt,
replay and charging. An explicit `arc_id` selects `services/project_chat.py`:
owner-checked, currently authorized Takes, transcript, qualitative vocal/verbal
cues, published feedback, deck, current Ideal Text and bounded conversation
rows from that project. Both persisted rows keep the project identity.
The shared history transport is retained; Speaking Coach filters project
rows before rendering or using them as conversational context.

Project Chat keeps the post-Take audience and desired-impact capture and
answers subsequent project questions without closing the composer. Its
state skips known audience/goal fields and varies language and tone from
the actual conversation. The normal path makes one contextual generation;
a short acknowledgement after setup has a deterministic fast path.

In Speaking Coach (`place=speaking`), ordinary conversation uses deterministic
routing and one `SPEC_SPEAKING_COACH` generation. Questions scoped to a Take
use one `SPEC_SPEAKING_COACH_TAKE` generation to ground the reflection in its
words and delivery. Product questions keep their existing app-aware path.
Project setup cannot consume a Speaking Coach turn.
The service defaults on; `SPEAKING_COACH_ENABLED=0` restores its previous
answer path. Retrieval is bounded to sixteen source reads, four projects
and four Takes per project, with a sixty-second derived cache and current
authorization checked again before reuse. Small greetings and joke requests
avoid evidence reads. The model specs use a fifteen-second provider timeout
and the shared language helper. Logs expose timings and call counts without
conversation words; no production latency improvement has been measured yet.

The frontend stores unfinished turns in the current tab, with their original
owner, project, history and UUID. Retry reuses the server receipt instead of
regenerating or charging again. A failed terminal response stays recoverable.
The existing feedback, transcript, Ideal Text, practice and recording doors
remain in the project.

## 2026-11-16 backend/API performance audit

Filter stamp: `JUSTIFIED-SCAFFOLDING` — category `F1-surface` — fences clear,
locks clear — redirect: reduce latency/query load on existing feedback, Ideal
Text, chat, queue and strengths surfaces without changing contracts.

This pass measured the request shapes in code and added only bounded,
read-only performance changes. Production traffic and production database
access were not available from this worktree, so the query counts below are
structural measurements, not claims about production wall-clock latency.
The existing `Server-Timing` header remains the production measurement path:
it reports total app time, DB-call count, summed DB wait and the slowest DB
call. Use it on the named routes before/after release; no deployment was
performed here.

### Implemented changes and before/after measurements

| Surface | Before | After | Contract/risk boundary |
|---|---:|---:|---|
| `GET /v2/explore/arc/<arc>/feedback` | `5T + 3R + 1` DB reads for `T` spoken Takes and `R` re-reads | 5 batched reads for up to 20 sessions/page, plus pagination for larger sets | Same per-Take payload; coach-only confidence labels still pass through `key_snippet_ids`; edits remain display-only |
| `GET /v2/chats/<thread>/messages` | authors, words, answer slides and join attribution read serially | Same 4 reads overlapped after identical ownership/filtering | No writes or filtering moved into worker threads; results are collected in submission order |
| `GET /v2/models/queue` | examples and private/exam access read serially | Same reads overlapped after the teaching/model scope is resolved | Model visibility, exam sealing, pause state and queue ordering remain in the rules layer |
| `POST /v2/strengths/today` | consent, talk dates and open plan read serially after gates | Same 3 reads overlapped after the existing ring/onboarding early exits | No new read happens when the feature is off, onboarding is active, or no date matches |

For the feedback path, a representative 3-Take arc with one re-read drops from
19 structural reads to 5 (14 fewer); a 10-Take arc with 10 re-reads drops from
81 to 5 before batch pagination. A fixed-delay 4-way, 25 ms synthetic
independent-read harness measured 128.9 ms serial versus 36.9 ms overlapped
(3.5×); this is a concurrency sanity check, not a production benchmark.

The new transcript-edit query uses the existing `idx_user_transcript_edits_session`
index. The existing migrations already index the other batch predicates:
snippet session, coach draft session, confidence-label snippet, chat member /
message thread, model teacher / example / answer, and strengths / notes. No
new migration is needed or included. This matters because `MIGRATE_ON_BOOT`
means merging a migration also runs it in production at the next release.

### Remaining bottlenecks and measurement plan

| Area | Remaining issue | Evidence/status | Next safe step |
|---|---|---|---|
| App boot | Import-time route registration plus provenance/snippet reachability checks still run on every web process | Code inspection only; this worktree cannot import `app.py` because its CI dependencies are not installed | Capture process-start timing around the existing boot checks in Railway; do not defer checks without an explicit live-loop review |
| Feedback | Large arcs can cross the 20-session or 1,000-row batch boundaries; signed playback and JSONB snippet payloads remain costly | Bounded batch code in `services/db.py`; no production row cardinalities available | Use `Server-Timing` and DB slowest-call data on the largest arc before narrowing projections |
| Ideal Text | Optional enrichment remains intentionally uncached and generation-fenced; the core snapshot is already one read model | Existing route uses parallel ownership/core reads and stale fence checks | Measure section-level timings; cache only immutable, actor-scoped payloads after freshness/tenant review |
| Conversational chat | LLM/provider latency and push side effects are outside the list/read changes | Route/service inspection; no upstream timing available here | Keep provider timing separate from DB timing before changing sequencing |
| Model queue | Clip URL signing and answer filtering still happen after the batched reads | Existing `with_clips` and `_waiting_for` paths | Measure queue sizes and `Server-Timing` before considering clip-url caching |
| Strengths/today | Ring and onboarding gates remain required reads and intentionally fail closed | Existing behavior preserved | Add a request-level timing sample if this surface is observed as slow; do not cache private freshness-sensitive state without a TTL decision |

No safe cache was added: these surfaces contain private, freshness-sensitive,
or authorization-dependent data, and the current evidence supports batching /
overlap more strongly than a cache policy.

## Prior measurement (2026-07-26)

**Measurement only, as instructed. No optimisation code in that pass.**

## What I could and could not measure

I have no access to production or to a database with real data, so **there are
no wall-clock numbers here.** What I did instead is a static call-graph profile
of both read paths (three levels deep through `routes/v2_routes.py` helpers),
counting DB round-trips and heavy service calls. That finds *structural* cost —
N+1 patterns, duplicate reads, work on the read path that belongs at write time
— which is where a 2-second budget is usually won or lost.

To get real numbers, someone with prod access should add per-request timing
around these two handlers. See "How to get real numbers" below.

## `GET /v2/explore/arc/<arc_id>/ideal-text` — this is the slow one

**17 DB round-trips**, 13 loops, 15 helper functions traversed.

Notable:

| Calls | Method | Note |
|---|---|---|
| 2× | `db.get_moment_suggestions_by_arc` | **same data fetched twice** in one request |
| 2× | `db.get_arc_sessions` | **same data fetched twice** |
| 1× per session | `db.get_coach_snippet_drafts` | inside `_moment_explanations_map`, which loops over sessions → **N round-trips for N takes** |
| 1× per session | (playback lookups) | `_moment_playback_map`, same per-session loop |
| 1× | `build_key_points` | on the read path, behind `KEY_POINTS_ENABLED` |

### The three things worth fixing, in order

1. **The two per-session loops.** `_moment_explanations_map` and
   `_moment_playback_map` each issue one query per take. An arc with many takes
   pays linearly on every single ideal-text load. A batched
   "drafts for these session ids" query would collapse each loop to one call.
   This is almost certainly the largest win and the least risky.

2. **The duplicated reads.** `get_moment_suggestions_by_arc` and
   `get_arc_sessions` are each called twice per request. Fetch once, pass the
   result down. Pure saving, no behaviour change.

3. **`build_key_points` on the read path.** It's flag-gated and off in prod
   today, so it isn't costing anything *yet* — but when `KEY_POINTS_ENABLED`
   flips it becomes per-request work. Worth precomputing at write time (it only
   changes when the text changes) before that flag goes on, rather than after
   someone notices.

## `POST /v2/chat/query` — not the problem

The historical measurement in this section predates retirement of the Strong
Sides collection. The active handler no longer loads that collection; rerun the
request trace before using the old round-trip count for capacity decisions.

Structurally this is already cheap. If chat *feels* slow, the cost is very
unlikely to be in this handler — look at the FE (bundle, waterfall, whether the
request is even fired eagerly) or at the LLM call if one happens on a path the
static walk didn't reach. **Do not optimise this endpoint on a hunch.**

## One N+1 this exercise caught, already fixed

Ticket 6 (the coach reference link) originally resolved the attached blog post
inside the per-moment decorator — one extra post lookup **per verified moment**,
on every ideal-text load. That's the exact pattern this ticket is about, and it
would have shipped in the same wave as the complaint about it. Now batched by
distinct slug (`_moment_reference_map`), with a test that pins the call count.

Worth naming because it's the general lesson: the read path grows an N+1 every
time a feature resolves something per item. The two per-session loops above are
older instances of the same habit.

## How to get real numbers

Whoever has prod access:

1. Time the two handlers end to end, and separately time the DB layer, so the
   split between query time and Python time is visible.
2. Do it on the arc with the **most takes**, not a median one — the per-session
   loops are invisible on a 1-take arc and dominate on a 10-take arc.
3. Report: total, DB total, number of queries, slowest single query.

If DB time dominates → fix items 1 and 2 above and re-measure. If Python time
dominates → the 13 loops over moments/snippets are the place to look. Either way
the answer should come from the measurement, not from this document.
