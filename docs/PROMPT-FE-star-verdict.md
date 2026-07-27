# FE prompt — Coach Star Verdict

**Repo:** `frontend-cursor` · **BE branch:** `feat/coach-star-verdict` (commit `ed57690`)
**Date:** 2026-07-27 · **Status:** BE complete, migration pending (`migrations/add_star_verdicts.sql`)
**Surface:** the coach panel only. Nothing in this document is ever visible to a student.

---

## What this is, in one paragraph

The system fires "stars" on a student's take — delivery nudges (emphasis / pace / pause /
congruence), structural spots (contrast / list-of-three), and text suggestions (emphasize /
replace). Until now the coach could edit what a star *says* but had no way to say a star was
*wrong*. This surface adds that judgment: for every fired star the coach answers **Keep** /
**Wrong kind** / **Shouldn't have fired**. The verdicts are the training corpus that teaches
the system when to speak and when to stay quiet. The coach is doing a review, not moderation —
a verdict changes nothing the student sees.

---

## 0. Non-negotiables

| # | Rule | Why |
|---|---|---|
| N1 | **This surface never appears near the confidence-labeling surface.** Do not embed the verdict controls in, or link them from, the blind labeling flow (the challenge/threat — soon confidence/weakness — labeler). Separate screen, separate navigation entry. | BLIND COACH. This surface *shows the machine's guess*; the labeling surface must never. Putting them side by side anchors the blind label. The BE enforces payload separation; the FE must enforce visual/navigational separation. |
| N2 | **A verdict is silent toward the student.** No student-facing state changes when a verdict is saved — the star still renders for the student exactly as before, including on a `should_not_fire`. | A verdict is coach→machine training signal (AC-9). Suppressing the star on rejection would make the coach's judgment visible to the student by inference. |
| N3 | **`wrong_kind` requires a correction.** The UI must not allow submitting "wrong kind" without picking what it should have been. The BE 400s without `corrected_device`; don't let the coach hit that wall — make the picker part of the same gesture. | The labeled confusion pair (`pace_fast → pace_slow`) is the actual signal; a bare rejection is nearly worthless. |
| N4 | **Render `device_options` from the payload, never a hard-coded list.** The device vocabulary lives in the BE and will grow. | An FE-side list drifts the day a new star family ships. |
| N5 | Verdicts are re-editable. Re-judging replaces (upsert) — render the saved verdict as the current state, not as a locked answer. | The corpus wants the coach's current view. |

---

## The two endpoints

### FE-1 — Review list

```
GET /v2/coach/arc/<arc_id>/stars          (auth: coach or admin JWT, same as all /coach/*)
```

```jsonc
200 {
  "arc_id": "…",
  "total": 7,            // stars fired on this arc
  "judged": 3,           // how many already have a verdict
  "stars": [
    {
      "snippet_id": "uuid",
      "star_kind": "delivery",          // emphasize | replace | structure | delivery
      "star_device": "pace_fast",       // delivery only; null for other kinds
      "trigger": "pace_fast",           // raw trigger (delivery: the device; replace: threat|profanity|stickiness)
      "why": "…",                       // the machine's stated reason, when it has one
      "replacement_text": "…",          // replace stars only, else null
      "verdict": null,                  // null = unjudged · keep | wrong_kind | should_not_fire
      "corrected_device": null,         // set when verdict = wrong_kind
      "note": null,                     // the coach's own note, if they left one
      "judged": false,
      "device_options": ["emphasis","pace_fast","pace_slow","pause","congruence"]
                                        // what "wrong kind" may be corrected TO (N4).
                                        // [] for single-device kinds (emphasize/replace)
    }
  ],
  "summary": { "total": 3, "by_verdict": {…}, "by_kind": {…},
               "confusions": {"pace_fast->pace_slow": 1},
               "false_negatives_captured": false }   // internal bookkeeping — do not render
}
404 { "code": "NOT_FOUND" }      // arc unknown
500 { "code": "SERVER_ERROR" }
```

Ordering is server-side: **unjudged first**, then by family. Render in payload order.

`summary` is for a small coach-side progress readout at most ("3 of 7 reviewed") — do not
build charts from it, and never render `confusions` or `false_negatives_captured`.

### FE-2 — Save one verdict

```
PUT /v2/coach/snippets/<snippet_id>/star-verdict
```

```jsonc
// body — keep
{ "star_kind": "delivery", "star_device": "pace_fast", "verdict": "keep" }

// body — wrong kind (corrected_device REQUIRED; may be another family's device
// or a family name itself, e.g. "contrast" or "structure")
{ "star_kind": "delivery", "star_device": "pace_fast",
  "verdict": "wrong_kind", "corrected_device": "pace_slow",
  "note": "she always talks this fast — this is her normal" }   // note optional, ≤1000 chars

// body — shouldn't have fired
{ "star_kind": "structure", "star_device": "contrast", "verdict": "should_not_fire" }
```

```jsonc
200 { "saved": true, "snippet_id": "…", "verdict": "keep" }
400 { "code": "INVALID_INPUT", "error": "<verbatim reason — safe to toast>" }
404 { "code": "NOT_FOUND" }      // snippet unknown
500 { "code": "SERVER_ERROR", "error": "…(run migrations/add_star_verdicts.sql)" }
```

Echo `star_kind`/`star_device` from the GET row verbatim — don't reconstruct them.
`star_version` may be passed through if present on the row; omit otherwise.

---

## FE-3 — Suggested interaction (not locked; copy needs founder sign-off)

One list per arc, reachable from the coach's arc review screen (near review-state /
ideal-text, **not** near the labeler — N1). Each row: the star's kind+device as a chip, the
`why` / `replacement_text` as the body, and a three-way control:

```
[ ✓ Keep ]   [ ⇄ Wrong kind… ]   [ ✕ Shouldn't fire ]
```

- **Keep** and **Shouldn't fire** save on tap (one PUT).
- **Wrong kind** expands an inline picker built from `device_options` (plus the other family
  names when `device_options` is `[]`), and saves on pick — never a two-step submit (N3).
- An optional free-text note field behind a "add note" affordance; sent with the same PUT.
- Saved state: the chosen control stays selected; tapping another replaces (N5).

Empty state (`total: 0`): "No stars fired on this arc." — nothing to review is a valid state,
not an error.

---

## Gotchas

- **Migration gate:** until `add_star_verdicts.sql` runs in prod, PUT returns 500 with a
  message naming the migration, and GET returns every star as unjudged. Degrade gracefully.
- A star may exist on a snippet whose session the coach opened from either the per-take view
  or the arc view — the GET is arc-scoped; there is no per-session variant.
- `star_kind: "replace"` rows carry `replacement_text`; `"structure"` rows carry the verbatim
  quote in `why`. Render whichever is present; both may be present.
- Don't cache verdicts across arcs in client state keyed by snippet only — snippet ids are
  globally unique, but the review context is the arc.
