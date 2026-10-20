# FE handoff — wins → proposed principles (piece 6, 2026-08-03)

**From:** Backend
**Program:** founder-agreed 2026-08-02 — piece 6: *the Wins wall proposes
principles*
**Branch:** `claude/life-panel-doc-dock-be-m6e8rc`

```
FILTER: JUSTIFIED-SCAFFOLDING — cat {SCAFFOLDING} — fences {clear} — locks {clear}
        redirect: tighten word→slide bucketing at the two-clocks boundary
```

**One migration to run.** `migrations/add_life_items_origin_wins.sql` — one
nullable column on `life_items` (`origin_win_ids jsonb`), no new table, no
RLS change. Deploy order does not matter: with the column absent the
derivation still lands its proposals and only their grounding chips are
missing. **No flag to flip** — the endpoint sits behind the existing
three-tier gate.

---

## 1. What this is

The case engine's positive mirror. `#mistake` already works a proposed
principle out of something that went wrong; this reads the **Wins wall** —
things that went right, in the founder's own words — and proposes the
principles they teach. Same discipline end to end:

- **Founder-initiated, always.** One button on the Wins wall fires it.
  Nothing schedules it, no capture path triggers it, `#win` still saves
  instantly with no model call (L-4: dormant until opened).
- **Propose, never commit (N5).** Every proposal lands as a
  `status='proposed'` principle item. It is not part of the archive — and
  not retrievable as one — until the founder approves it.
- **Grounded or dropped.** Every proposal carries `origin_win_ids`: the
  wins it was read out of. A lesson the model could not point at a win
  never comes back at all.
- **Never re-proposed.** A line the archive already holds — active,
  already-proposed, **dismissed or retired** — is skipped (accent- and
  case-insensitive match). Saying no once is enough.

## 2. The derive call

`POST /v2/life/wins/derive` (no body) →

```json
{
  "outcome": "ok",              // "ok" | "no_wins" | "no_derivation"
  "proposed": [ { …item, "status": "proposed",
                  "origin_win_ids": ["<win id>", …] } ],
  "wins_read": 20,              // the window it actually read…
  "wins_total": 34,             // …out of how many wins exist
  "already_held": 1             // proposals skipped as already in the archive
}
```

- The engine reads the **20 most recent wins** (chronological), retrieves
  the ~10 most relevant existing principles as context, and proposes **at
  most 3** one-liners per run. When `wins_read < wins_total`, say so —
  "read your last 20 wins" — a partial read must never look like a full
  one.
- `outcome` values: `no_wins` (the wall is empty — don't show an error),
  `no_derivation` (the model call failed — "try again", never "your wins
  teach nothing"), `ok` with an empty `proposed` list (the honest common
  case: these wins teach nothing the archive doesn't hold).
- `proposed` is 0–3 items; render them as cards awaiting a decision, each
  with its grounding wins (resolve `origin_win_ids` against the wall you
  already have). Rows written before the migration carry `[]`.

## 3. Approve / dismiss — existing endpoints, one new field

- **Approve** = `PATCH /v2/life/items/<id>` `{"status": "active"}` — the
  same PATCH the panel already uses. The response now carries one
  **additive** field:

```json
{ "item": { … }, "retire_prompt": null }
```

  `retire_prompt` is non-null only when a principle just went
  `proposed → active` **and** it looks like it supersedes an existing one:

```json
{ "question": "…does this retire #12?",   // BE-7 copy, already signed off
  "retires": { …the existing principle… },
  "number": 12 }
```

  Show the question; the answer goes to the **existing** retire endpoint:
  `POST /v2/life/principles/<new_id>/retire` with
  `{"retires_id": "<old id>", "decision": "yes" | "no"}`. The veto is
  absolute, a "no" is remembered, and the pair is never asked about again.
  The PATCH itself retires nothing.

- **Dismiss** = `PATCH /v2/life/items/<id>` `{"status": "dismissed"}`. A
  dismissed line is never proposed again from any future run.

## 4. Fences that shaped this (unchanged, for the reviewer)

- **AC-9 / CONSTRUCT:** nothing here is a score. `wins_read` /
  `wins_total` / `already_held` are window-honesty counts (the
  `queued_held_back` class); render them as prose if at all, never as a
  meter.
- **N5 / L-1:** the model writes ONE line per proposal and grounds it; it
  never rewrites a win, never summarises the wall back, never touches
  reflections.
- **L-2b untouched:** these are item proposals (the class the case flow
  already ships), not strategy-document proposals — the daily strategy
  budget does not apply and was not changed.

## 5. SIGN-OFF — user-facing copy needed (founder words, not ours)

Nothing user-readable ships from the backend here. Needed before the FE
piece goes live:

1. The **button label** on the Wins wall (working name: "what do these
   wins teach?").
2. The **proposal card** framing (a proposed principle awaiting a
   decision, with its grounding wins).
3. The three **outcome lines**: empty wall / derivation failed / read the
   wins, nothing new to propose.
4. The **partial-window line** ("read your last 20 wins of 34").
5. The **already-held line**, if shown at all ("1 lesson your archive
   already holds").

(The retire question itself is existing BE-7 copy and needs no new
sign-off.)
