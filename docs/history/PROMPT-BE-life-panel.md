# BE prompt — The Life Panel

**Repo:** `backend-cursor` · **Spec of record:** [PROMPT-life-panel.md](PROMPT-life-panel.md)
**Pair:** [PROMPT-FE-life-panel.md](PROMPT-FE-life-panel.md)
**Date:** 2026-07-26 · **Status:** not started

Read the spec first. This document is *how to build it*; the spec is *what and why*, and where
the locked rules L-1…L-6 live. Where they disagree, the spec wins.

```
VERDICT:  JUSTIFIED-SCAFFOLDING (founder-directed), public-facing
CATEGORY: SCAFFOLDING
GUARD:    Isolation is the price of admission. Nothing here modifies an F1 path
          (record → transcribe → coach → read). Two permitted contact points:
          (1) the chat router, guarded by a byte-identical-response test;
          (2) the PER-USER block of master_doc_rag, guarded by the probe eval.
```

---

## 0. Non-negotiables — every one is a test, not a note

| # | Rule | Enforced by |
|---|---|---|
| N1 | RLS enabled on every `life_*` table **in its creating migration** | migration review + a test that queries with the anon key and gets zero rows |
| N2 | No product-side module imports the life module; the **shared** master body is never written to | isolation test (pattern: Journal PR #254) |
| N3 | Non-consented / non-allowlisted chat responses are **byte-identical to `main`** | full existing chat suite re-run under a non-participating user |
| N4 | The per-user master-doc injection never drops the probe baseline | `tests/evals/master_doc_probe.py` run with injection ON |
| N5 | The system never authors reflective prose (L-1) | prompt-level; test asserts the `reflections` field is only ever written from request input |
| N6 | Nothing writes to the strategy doc without an approved proposal (L-2); the immutable core is never proposed against (L-2a) | test: propose against Section I → returns report-only |
| N7 | At most one strategy proposal surfaced per day (L-2b) | test with 5 qualifying notes in one day → 1 surfaced, 4 queued |
| N8 | Zero scheduled outbound anything (L-4) | no email/push/notification call in the module; grep-fenced |
| N9 | Hard delete actually deletes; export returns everything | round-trip test |

---

## BE-0 — Export button on the OLD principles app (different repo)

**Do this first. It is not in this repo and it is not optional.**

`/Users/arturwillonski/Documents/principles-app` has no export. Its data lives in localStorage
mirrored to an unauthenticated Firestore doc. Until an export exists, one cleared browser
profile loses a four-year corpus.

Add a button that downloads `{principles, wins, prayer}` from `loadAll()` as JSON. ~10 lines in
`app/SyncControls.tsx` or the footer nav. No willab code touched. Ship, export on the device
with the most data, keep the file.

---

## BE-1 — Schema, RLS, flags

**Migration:** one idempotent file for the Supabase SQL Editor (founder has no psql/Docker).

```
migrations/add_life_panel.sql
  life_notes · life_cases · life_items · life_strategy
  life_days · life_weeks · life_consent · life_proposals · life_applications
  + RLS policies + indexes, all IF NOT EXISTS
```

Tables beyond the spec's six, and why:

- `life_consent` — `user_id · consent_version · accepted_at · ip`. L-6 requires consent before
  any life row is written; the record has to be auditable.
- `life_proposals` — `user_id · kind · target · current · proposed · warrant_principle_id ·
  status ('queued'|'surfaced'|'approved'|'dismissed'|'expired') · surfaced_on · expires_at`.
  This table *is* L-2b: the budget is a query over it, not a counter in code.
- `life_applications` — `user_id · principle_id · context ('case'|'diff'|'conflict'|'board') ·
  ref_id · created_at`. L-5's log. Append-only.

`life_items.kind ∈ { principle, win, phrase, bet, goal, task, habit, distraction, event }`.
`life_cases.category` is an **array** — multi-category cases exist in the corpus.

**Flags:** `LIFE_PANEL_ENABLED` (default `0`, global kill) · `LIFE_PANEL_ALLOWLIST` (comma-separated
user ids — prayer + founder-only surfaces only, NOT the principles engine).

**Acceptance:** migration runs twice cleanly. Anon-key select on every table returns zero rows.
Flag off → every `/v2/life/*` 404s and the menu payload is byte-identical to today.

---

## BE-2 — Core API

All under `routes/life_routes.py`, registered as its own blueprint. No edits to `v2_routes.py`
beyond blueprint registration.

```
GET    /v2/life/state                     consent + setup status, menu entries, flags
POST   /v2/life/consent                   {version} → records acceptance
GET    /v2/life/setup                     partial answers (save-and-resume)
PUT    /v2/life/setup                     upsert partial answers
POST   /v2/life/setup/complete            → generates docs, replays queued notes

GET    /v2/life/strategy                  all horizons, current version
GET    /v2/life/strategy/download         one assembled document
POST   /v2/life/strategy/upload           returns a DIFF — never writes
POST   /v2/life/proposals/<id>/approve    applies + bumps life_strategy.version
POST   /v2/life/proposals/<id>/dismiss    remembered, not re-proposed

GET    /v2/life/principles                ?q= for retrieval, ?limit=
GET    /v2/life/principles/<id>           principle + its case + application log
POST   /v2/life/principles/<id>/retire    {retires_id, decision} — veto is absolute
GET    /v2/life/cases  ·  /v2/life/cases/<id>

GET    /v2/life/items?kind=               wins · phrases · distractions · goals · events
POST   /v2/life/items  ·  PATCH  ·  DELETE
GET    /v2/life/timeline                  events + goals with due_at, for the canvas

GET    /v2/life/day?date=                 the daily card
PATCH  /v2/life/day/<id>                  checkbox ticks, #edit target
GET/POST /v2/life/week

GET    /v2/life/notes  ·  POST /v2/life/notes
POST   /v2/life/export                    everything, JSON
DELETE /v2/life/data                      hard delete, irreversible, confirmed
```

**Gate behaviour:** flag off → 404. Consented=false → **409** with a pointer to the Principles
tab (except `/consent` and `/setup`). Allowlisted surfaces to a non-allowlisted user → **404**,
never 403.

---

## BE-3 — Importers

Against the three JSON files from BE-0 / the timeline export / the transcribed strategy docs.
Idempotent, re-runnable, dry-run mode that reports counts without writing.

Must preserve, and each is a test:

- `createdAt` — corpus spans 2022→2026; the dates carry meaning.
- Category strings mapped to the fixed six; **anything unmapped goes to a review queue**, never
  silently coerced.
- Multi-principle and multi-category cases.
- Polish text **verbatim** — no translation, no normalisation, no cleanup pass. Several
  reflections are code-switched mid-paragraph and that is the record.
- Drag-to-reorder order → `order_key`.
- The `prayer.v1` blob split into `phrase` rows on quote boundaries; **anything unsplittable
  stays as one note** so nothing is lost.

**Acceptance:** row counts match the export; ten spot-checked reflections are byte-identical.

---

## BE-4 — Setup → document generation

`POST /v2/life/setup/complete` takes the eight-horizon answers and generates the document set
(daily / weekly / monthly / quarterly / yearly / 5y / 10y / 20y) into `life_strategy` v1.

This is generation **from the user's own answers** — structuring their input, not inventing
goals. The bets and their rank come from the answers; the model formats and cross-references.

On completion, replay any notes the user typed before setup (§6.2 of the spec) through the
engine, oldest first, and return the results.

---

## BE-5 — Hashtag router + principles engine

Deterministic tag match first. **No classifier.** Unknown tag or no tag → capture only.

| Tags | Route |
|---|---|
| `#principle` `#sin` `#mistake` `#error` `#problem` | principles engine |
| `#data` `#observation` `#reflection` `#idea` `#finding` | strategy comparison → BE-6 |
| `#win` `#wins` `#wygrane` `#liftmeup` | Wins |
| `#add` | append to the phrase wall |
| `#edit` | daily card edit → BE-8 |

Parsing: tag is the first token, matched case-insensitively, terminated by whitespace. `#lift
me up` correctly parses as `#lift` (unknown) + prose → capture only. That is the desired
failure mode.

**Principles engine.** Input: case text + the user's own reflections. Output, all proposals:

1. 👾 category from the fixed six (array — may be more than one).
2. **Retrieval** of which existing principles bore on this case → this is slot 3, and it is the
   thing that turns the archive into a machine. Retrieve ~10, never the whole corpus.
3. ⚜️ a one-line phrasing for the new principle.

It does **not** write `reflections` (N5). Nothing is committed until approved.

**Phrase attach:** every `#` note's response carries the single best-fitting wall phrase, with a
**relevance floor** (below it, attach nothing) and **no repeat inside a rolling window**.

---

## BE-6 — Strategy comparison, proposals, budget

On a `#observation`-class note: compare against the whole document set, detect direct
inconsistencies, and write a row to `life_proposals` carrying:

- what it contradicts (section + quoted line),
- the proposed edit,
- **`warrant_principle_id`** — one of the user's own principles justifying the change. A
  proposal without a warrant is not created.

**Budget (L-2b):** at most one proposal moves to `surfaced` per day; the rest stay `queued` and
arrive as a ranked batch of three at the weekly review. `queued` older than 14 days → `expired`.

**Immutable core (L-2a):** proposals whose target is Section I (The Anchor) or the *rank* of the
bets are never created. Those produce a report-only response and stop.

Every proposal creation and every approval writes a `life_applications` row for its warrant
principle (L-5).

---

## BE-7 — Conflict, retire, board, lookup

- **conflict** — when retrieval returns principles that pull opposite ways, return **both** as a
  pair. The system never picks (L-3). Detection can be simple: precomputed opposition pairs
  plus an LLM check on the retrieved set.
- **retire** — a new principle that looks like it supersedes an old one returns a
  *"does this retire #12?"* prompt. On `no`, both stay active and **the question is not
  re-asked** (persist the decision).
- **board** — routes to one of the five advisors by domain and answers in that lens; states
  which and why. Never presents itself as replacing prayer.
- **lookup** — top-10 retrieval over principles + phrases. Never a corpus dump.

---

## BE-8 — Daily card + `#edit`

Card **generated at 05:00** local, stored in `life_days`, and **waits**. No email, no push, no
notification (N8). Generation is scheduled; delivery is not.

`#edit <text>` targets **the most recent daily-card row only**. Any other target → refuse.

Frame fixed, content editable: the existence of a ONE THING is not editable; what it is, is.
The "why" is captured as a candidate correction so tomorrow's card is already right. If it also
bears on a longer horizon it becomes a normal BE-6 proposal — inside the daily budget, warrant
required. **A `#edit` never silently reaches the 5- or 10-year document.**

---

## BE-9 — Per-user master-doc injection

Inject the user's principles / phrases / strategy into the **per-user** block of
`services/master_doc_rag.py`, alongside the strong-sides library — so untagged chat is smarter
for participating users.

**Bound it exactly like the library does.** That file caps the library at 20 entries and trims
each excerpt, and RULE K states the answer is never a dump of it. That cap is not cosmetic: the
Lounge prompt already ran over its attention ceiling once (PRs #81–#89 — rules moved out of the
prompt into code, −22 lines of prompt, RULE-K hardening). Sixty principles plus eight strategy
documents would re-open exactly that failure.

Therefore: **top-N by relevance, hard cap, trim, never the whole corpus.** Retrieved at request
time from the requesting user's own rows; the shared master body is never written to.

**Gate (N4):** re-run `tests/evals/master_doc_probe.py` with injection ON. If the baseline
drops, the injection shrinks. The injection yields; the probe never does.

---

## BE-10 — Consent, retention, export, delete

Launch blockers, not follow-ups — the founder chose no staged rollout, so there is no soft
launch in which to add these later.

- Consent recorded with a version, before any life row is written.
- Retention statement, and the retention actually implemented.
- `POST /v2/life/export` — everything the user owns, one JSON.
- `DELETE /v2/life/data` — hard delete, irreversible, explicit confirmation.
- **LLM calls:** no-training-retention API path; log derivation *outputs*, never raw note
  bodies; never send a corpus dump as context.

---

## Build order

```
BE-0  export the old corpus            ← do today, unblocks nothing but risks everything
BE-1  schema + RLS + flags
BE-3  importers                        ← corpus safe in Supabase = P1 exit
BE-2  core API
BE-10 consent / export / delete        ← must land before FE ships the public tab
BE-4  setup → doc generation
BE-5  router + principles engine
BE-6  proposals + budget
BE-8  daily card + #edit
BE-7  conflict / retire / board / lookup
BE-9  master-doc injection             ← last: it is the only F1-adjacent change
```

BE-9 last on purpose. It is the one change that can degrade the shipped product, and it should
land when everything else is stable and the probe has a clean baseline to compare against.

---

## Open (do not guess)

1. **Spendings** — in or out? Money is the one shape that does not fit `life_items`.
2. **Bet 3 daily tasks** — may the router propose a daily task against 🟣 The Dream, or is it
   display-only? The weekly doc says it "does not drive daily execution."
3. **Undated cases** — import at `createdAt`, or a separate undated bucket?
4. **Seventh category** — may GPT suggest one for approval, or is the list closed?
5. **`mvp.willpowerlab.com`** — add the hostname alias or not? ~10 lines, no fork.
