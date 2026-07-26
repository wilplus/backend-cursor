# Load-time finding — chat + ideal text (ticket 7, 2026-07-26)

**Measurement only, as instructed. No optimisation code in this pass.**

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

**3 DB round-trips**, 1 loop, no LLM call on the traversed path
(`get_user_settings`, `get_strong_sides_library`, `insert_lounge_messages`).

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
