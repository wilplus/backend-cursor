# BE handoff — Admin Tab 1: snippet list re-rank + transcript hiding

Status: **NOT STARTED — blocked on two clarifications from FE.**
Once both questions are answered, BE work is small (~30 LOC).

---

## What was asked

> Re-rank: sort by `classifier_stress_probability` desc, surface top-1 stress + top-1 charisma at the top, then the rest. Stop sending `transcript_excerpt`.

## The endpoint

`GET /v2/admin/users/<user_id>/snippets` — `v2_admin_get_user_snippets` in `routes/v2_routes.py:13386`.
Backing DB call: `db.get_snippets_by_user(user_id, limit, offset)` in `services/db.py:5401`.

**Current behaviour:**
- Queries `charisma_snippets` table only (`SELECT *`)
- Orders by `created_at DESC`
- Paginated via `limit` + `offset` (default 100, max 500)
- Returns `{ status, snippets: [...], limit, offset, count }` — each snippet is the full row

---

## Blocker #1 — `classifier_stress_probability` is on the WRONG table

The brief says: *"sort by `classifier_stress_probability` desc"*.

That column **does not exist on `charisma_snippets`** (the table this endpoint queries). It lives on the separate `stress_snippets` table — populated by the (dormant) stress classifier when one runs.

`charisma_snippets` does have a `snippet_type` column with values `"charisma"` / `"stress"` / `"unlabeled"` — that's the admin's manual label, not a model output.

**Possible interpretations — FE needs to pick:**

| Option | What it means | Cost |
|---|---|---|
| **A** | "Sort by `snippet_type` proxy": pick top-1 row where `snippet_type='stress'` + top-1 where `snippet_type='charisma'` by some quality signal (`created_at`? `kpi_score`? a different existing field?). Tell me which signal. | ~10 LOC, no schema change |
| **B** | "Merge stress_snippets into this endpoint's response": LEFT JOIN stress_snippets onto charisma_snippets via `recording_id`, hoist the `classifier_stress_probability` into the response, sort by it. Acoustic-classifier-driven ranking. | ~40 LOC. Caveat: classifier is dormant — most rows will have `NULL`, so ranking falls back to a secondary key. |
| **C** | "Backfill the classifier first": run the stress classifier over historical snippets so the field is populated, then do B. | Out of scope for this commit — gate on the rec-engine-v1 work. |

**Default recommendation if you don't answer:** Option A using `snippet_type` + `created_at desc` as the tiebreaker. Cheapest, no schema change, works today.

---

## Blocker #2 — Which "transcript" field do you mean?

The brief says: *"Stop sending `transcript_excerpt` on this view."*

There are TWO transcript fields on the relevant tables:

| Field | Where it lives | What it is | Current behaviour on this endpoint |
|---|---|---|---|
| `transcript_excerpt` | `stress_snippets` only | A 300-char preview cut from the source recording's transcription. | NOT sent today (this endpoint queries `charisma_snippets`, not `stress_snippets`). The field never appears. |
| `transcript` | `charisma_snippets` | The full transcription of the snippet's audio. **This is almost certainly what the admin actually sees rendered "below the snippet".** | Sent today via `SELECT *`. |

**FE confirm:** the field you want hidden is `transcript` on `charisma_snippets`, not `transcript_excerpt`. If that's right, the BE work is changing `SELECT *` to an explicit column list that omits `transcript`.

---

## The strip-vs-hide decision (raised in the brief itself)

> Brief: *"Cons: Transcripts may still be useful for coach hover-tooltips — consider keeping the data but hiding the default render rather than stripping at the API."*

Two options, with mirror trade-offs:

| Approach | Pro | Con |
|---|---|---|
| **Strip at API** — server omits `transcript` from response | Smaller payloads. No risk of FE accidentally rendering it. Enforces the hide. | Hover tooltip needs a second fetch (`/v2/admin/snippets/<id>` returns full row) — extra round-trip per hover. |
| **Keep in API, hide in FE** — FE just stops rendering it | Tooltip is free (data already loaded). No second round-trip. | Snippet list payload stays larger. Future FE work could accidentally re-render. |

**Default recommendation if you don't answer:** Keep in API, hide in FE. Hover tooltips are a near-term ask per the brief; the payload size delta is tiny (charisma snippets are short).

If FE confirms tooltips are NOT planned, I'll strip at API. Cleaner.

---

## Proposed final response shape (Option A + keep-in-API)

If FE picks the defaults above, the response stays mostly the same — only the ranking changes:

```jsonc
{
  "status": "ok",
  "snippets": [
    // Re-ranked: top-1 snippet_type='stress' first (by created_at desc),
    // then top-1 snippet_type='charisma' (by created_at desc),
    // then the rest in created_at desc order. Duplicates suppressed
    // (the top picks are not repeated in the tail).
    { id, transcript, snippet_type, admin_comment, follow_up_question,
      follow_up_outcome, created_at, ... all existing fields ... }
  ],
  "limit": 100,
  "offset": 0,
  "count": 100,
  // New, optional — helps FE highlight the pinned rows:
  "pinned": {
    "top_stress_id":   "uuid|null",   // null if no stress snippet exists
    "top_charisma_id": "uuid|null"
  }
}
```

The `pinned` block is optional — if FE doesn't need to style the pinned rows differently, I can drop it.

---

## FE deliverables (parallel PR after BE ships)

- Stop rendering `transcript` below each snippet card (assuming "keep in API + hide in FE")
- Optional: wire `pinned.top_stress_id` / `top_charisma_id` to a visual treatment (badge, divider, etc.)
- Hover tooltip — if planned — reads `snippet.transcript` directly off the payload (no new fetch)

If FE confirms "strip at API instead": skip the FE render change (the field just won't be there), wire a `/v2/admin/snippets/<id>` fetch on hover instead.

---

## Two questions in one message — please answer both

1. **Ranking signal**: A (snippet_type + tiebreaker — name the tiebreaker), B (join stress_snippets), or C (defer)?
2. **Transcript handling**: keep in API + hide in FE, or strip at API + fetch on hover?

Once answered I ship the BE change in one commit (~30 LOC) and hand back the deployed shape so the FE PR can be opened against it.
